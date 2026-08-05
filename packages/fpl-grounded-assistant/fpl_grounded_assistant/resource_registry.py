"""
fpl_grounded_assistant.resource_registry
=========================================
Phase M1 (MCP_architecture): Resource registry for the six M1 @resources.

All six resources share a uniform `ResourceResult` shape:

    title      — display title (English, UI may localize)
    columns    — ordered tuple of column keys (UI never branches per resource)
    rows       — tuple of dicts; each dict has the column keys plus optional
                 extras (e.g. "extra" for the sort field). All values are
                 JSON-safe primitives.
    data_age   — string label describing freshness ("current_bootstrap").
    resource   — canonical resource key (echoed for caller convenience).

Rules
-----
* Deterministic, read-only, argument-free, LLM-free.
* Reuses existing helpers where present (`injury_list.get_injury_list`).
* For ranking resources (top_form/xg/points/minutes/popular) we read
  bootstrap.elements directly — there is no existing rank-form helper
  that matches this thin-wrapper shape.

Live-bootstrap verification result (Lead Action 1, 2026-05-11)
---------------------------------------------------------------
A live `bootstrap-static` payload was inspected against this design:
299 of 299 elements with status != "a" had `news_added` populated
(100%). `chance_of_playing_this_round` was populated on 298/299.
DECISION: `@injuries` sorts by `news_added` DESC (newest first) as
PRIMARY; ties / nulls fall back to `chance_of_playing_this_round`
ASC (lowest playing chance first); last-resort tie-break is
bootstrap input order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from fpl_tool_contract import tool_resolve_player

from .injury_list import get_injury_list, _POSITION_LABEL, _STATUS_LABEL


# ---------------------------------------------------------------------------
# Uniform result shape
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResourceSpec:
    """Static metadata about a registered resource."""
    name: str                 # canonical key, e.g. "injuries"
    title: str
    description: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class ResourceResult:
    """The uniform per-resource result shape."""
    resource: str
    title: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    data_age: str = "current_bootstrap"

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "title": self.title,
            "columns": list(self.columns),
            "rows": [dict(r) for r in self.rows],
            "data_age": self.data_age,
        }


@dataclass(frozen=True)
class PlayerResourceResult:
    """Immutable FI-7f player-resource envelope."""
    resource: str
    title: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    data_age: str = "current_bootstrap"
    status: str = "ok"
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "title": self.title,
            "columns": list(self.columns),
            "rows": [dict(row) for row in self.rows],
            "data_age": self.data_age,
            "status": self.status,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_TOP_N = 10


def _teams_map(bootstrap: dict[str, Any]) -> dict[int, str]:
    return {
        t["id"]: t.get("short_name", "?")
        for t in bootstrap.get("teams", [])
        if "id" in t
    }


def _pos_label(et: int | None) -> str:
    return _POSITION_LABEL.get(int(et) if et is not None else 0, "?")


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Resource implementations
# ---------------------------------------------------------------------------

def _resource_injuries(bootstrap: dict[str, Any]) -> ResourceResult:
    """Players with status != 'a', sorted by news_added DESC.

    Reuses `injury_list.get_injury_list()` for the grouping logic, then
    re-flattens to a single rows list and applies the recency sort
    documented in the module header.
    """
    # We bypass get_injury_list() because it does not surface news_added.
    # Instead we re-scan bootstrap directly, mirroring its filter logic.
    teams_map = _teams_map(bootstrap)
    raw_rows: list[dict[str, Any]] = []
    for idx, el in enumerate(bootstrap.get("elements", [])):
        status = el.get("status", "a")
        if status == "a":
            continue
        row: dict[str, Any] = {
            "web_name":     el.get("web_name", "?"),
            "team_short":   teams_map.get(el.get("team", -1), "?"),
            "position":     _pos_label(el.get("element_type")),
            "status_label": _STATUS_LABEL.get(status, status.upper()),
            "chance_of_playing": (
                int(el["chance_of_playing_this_round"])
                if el.get("chance_of_playing_this_round") is not None
                else None
            ),
            "news":         el.get("news") or "",
            "news_added":   el.get("news_added") or "",
            "_idx":         idx,  # preserves bootstrap input order
        }
        raw_rows.append(row)

    # Sort key: news_added DESC (lexicographic on ISO-8601), then
    # chance_of_playing ASC (None treated as -1 = top), then _idx ASC.
    def _key(r: dict[str, Any]) -> tuple:
        na = r.get("news_added") or ""
        cop = r.get("chance_of_playing")
        cop_sort = 1000 if cop is None else cop
        return (
            # negative sort by news_added — use reverse=True via tuple trick:
            # we sort with reverse=False on a key whose order matches "newest
            # first when reversed". Easiest: return (news_added,) and use
            # reverse=True at sort site.
            na,
            -cop_sort if cop is not None else 0,
            -r["_idx"],
        )

    raw_rows.sort(key=_key, reverse=True)

    cols = ("web_name", "team_short", "position", "status_label",
            "chance_of_playing", "news", "news_added")
    rows = tuple({k: r.get(k) for k in cols} for r in raw_rows)
    return ResourceResult(
        resource="injuries",
        title="Injuries & Availability",
        columns=cols,
        rows=rows,
    )


def _rank_by(
    bootstrap: dict[str, Any],
    *,
    field_name: str,
    title: str,
    canonical: str,
    cast: Callable[[Any], float] = _as_float,
    extra_columns: tuple[str, ...] = (),
    top_n: int = _DEFAULT_TOP_N,
) -> ResourceResult:
    """Generic 'top-N by bootstrap field' ranking, descending.

    Includes only available players (`status == 'a'`). Each row carries
    a `value` key holding the sort field value (display-friendly).
    """
    teams_map = _teams_map(bootstrap)
    raw: list[tuple[float, dict[str, Any]]] = []
    for el in bootstrap.get("elements", []):
        if el.get("status") != "a":
            continue
        v = cast(el.get(field_name))
        row: dict[str, Any] = {
            "web_name":   el.get("web_name", "?"),
            "team_short": teams_map.get(el.get("team", -1), "?"),
            "position":   _pos_label(el.get("element_type")),
            "value":      v,
        }
        for ec in extra_columns:
            row[ec] = el.get(ec)
        raw.append((v, row))

    raw.sort(key=lambda t: t[0], reverse=True)
    rows = tuple(r for _, r in raw[:top_n])
    cols: tuple[str, ...] = ("web_name", "team_short", "position", "value") + extra_columns
    return ResourceResult(
        resource=canonical,
        title=title,
        columns=cols,
        rows=rows,
    )


def _resource_top_form(bootstrap: dict[str, Any]) -> ResourceResult:
    return _rank_by(
        bootstrap, field_name="form",
        title="Top Form", canonical="top_form",
    )


def _resource_top_xg(bootstrap: dict[str, Any]) -> ResourceResult:
    return _rank_by(
        bootstrap, field_name="expected_goal_involvements",
        title="Top Expected Goal Involvements", canonical="top_xg",
    )


def _resource_top_points(bootstrap: dict[str, Any]) -> ResourceResult:
    # total_points may not be in test fixtures — _as_float handles None.
    return _rank_by(
        bootstrap, field_name="total_points",
        title="Top Points", canonical="top_points",
        cast=lambda v: float(_as_int(v)),
    )


def _resource_top_minutes(bootstrap: dict[str, Any]) -> ResourceResult:
    return _rank_by(
        bootstrap, field_name="minutes",
        title="Top Minutes", canonical="top_minutes",
        cast=lambda v: float(_as_int(v)),
    )


def _resource_popular(bootstrap: dict[str, Any]) -> ResourceResult:
    return _rank_by(
        bootstrap, field_name="selected_by_percent",
        title="Most Selected", canonical="popular",
    )


_PLAYER_MINUTES_COLUMNS = (
    "web_name", "team_short", "position", "value", "unit", "scope", "provenance",
)
_PLAYER_ROLE_COLUMNS = (
    "web_name", "team_short", "role", "role_kind", "provenance",
)
_POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _unavailable_player_resource(
    canonical: str,
    reason: str,
) -> PlayerResourceResult:
    is_minutes = canonical == "player_minutes"
    return PlayerResourceResult(
        resource=canonical,
        title="Player Minutes" if is_minutes else "Player Role",
        columns=_PLAYER_MINUTES_COLUMNS if is_minutes else _PLAYER_ROLE_COLUMNS,
        rows=(),
        status="unavailable",
        reason=reason,
    )


def _player_resource(
    canonical: str,
    bootstrap: dict[str, Any],
    argument: str | None,
    shape_reason: str | None,
) -> PlayerResourceResult:
    """Resolve and serialize one deterministic FI-7f bootstrap fact."""
    if shape_reason is not None:
        return _unavailable_player_resource(canonical, shape_reason)

    # This fallback is defensive for direct registry callers.  Normalized
    # command traffic supplies the governed missing-argument reason above.
    if argument is None or not argument:
        return _unavailable_player_resource(canonical, "missing_player_argument")

    if not isinstance(bootstrap, dict):
        return _unavailable_player_resource(canonical, "resource_data_unavailable")
    elements = bootstrap.get("elements")
    teams = bootstrap.get("teams")
    if not isinstance(elements, list) or not elements or not isinstance(teams, list):
        return _unavailable_player_resource(canonical, "resource_data_unavailable")
    if any(not isinstance(element, dict) for element in elements):
        return _unavailable_player_resource(canonical, "resource_data_unavailable")

    try:
        resolved = tool_resolve_player(argument, bootstrap)
    except (AttributeError, KeyError, TypeError, ValueError):
        return _unavailable_player_resource(canonical, "resource_data_unavailable")
    if not isinstance(resolved, dict):
        return _unavailable_player_resource(canonical, "resource_data_unavailable")

    status = resolved.get("status")
    if status == "ambiguous":
        return _unavailable_player_resource(canonical, "ambiguous_player")
    if status == "not_found":
        return _unavailable_player_resource(canonical, "unresolved_player")
    if status != "ok":
        return _unavailable_player_resource(canonical, "resource_data_unavailable")

    player_id = resolved.get("player_id")
    if isinstance(player_id, bool) or not isinstance(player_id, int):
        return _unavailable_player_resource(canonical, "resource_data_unavailable")
    matches = [
        element for element in elements
        if isinstance(element.get("id"), int)
        and not isinstance(element.get("id"), bool)
        and element.get("id") == player_id
    ]
    if len(matches) != 1:
        return _unavailable_player_resource(canonical, "resource_data_unavailable")

    web_name = resolved.get("web_name")
    team_short = resolved.get("team_short")
    position = resolved.get("position")
    if (
        not isinstance(web_name, str) or not web_name
        or not isinstance(team_short, str) or not team_short
    ):
        return _unavailable_player_resource(canonical, "resource_data_unavailable")

    element = matches[0]
    if canonical == "player_minutes":
        if position not in _POSITIONS.values():
            return _unavailable_player_resource(canonical, "resource_data_unavailable")
        minutes = element.get("minutes")
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
            return _unavailable_player_resource(canonical, "minutes_unavailable")
        row = {
            "web_name": web_name,
            "team_short": team_short,
            "position": position,
            "value": minutes,
            "unit": "minutes",
            "scope": "current_season_to_bootstrap",
            "provenance": "fpl_bootstrap.elements.minutes",
        }
        return PlayerResourceResult(
            resource=canonical,
            title="Player Minutes",
            columns=_PLAYER_MINUTES_COLUMNS,
            rows=(row,),
        )

    element_type = element.get("element_type")
    if isinstance(element_type, bool) or element_type not in _POSITIONS:
        return _unavailable_player_resource(canonical, "role_unavailable")
    row = {
        "web_name": web_name,
        "team_short": team_short,
        "role": _POSITIONS[element_type],
        "role_kind": "nominal_fpl_position",
        "provenance": "fpl_bootstrap.elements.element_type",
    }
    return PlayerResourceResult(
        resource=canonical,
        title="Player Role",
        columns=_PLAYER_ROLE_COLUMNS,
        rows=(row,),
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

RESOURCE_SPECS: tuple[ResourceSpec, ...] = (
    ResourceSpec(
        name="injuries",
        title="Injuries & Availability",
        description="Players currently unavailable, sorted by most recent status change.",
        columns=("web_name", "team_short", "position", "status_label",
                 "chance_of_playing", "news", "news_added"),
    ),
    ResourceSpec(
        name="top_form",
        title="Top Form",
        description="Available players ranked by FPL form (descending).",
        columns=("web_name", "team_short", "position", "value"),
    ),
    ResourceSpec(
        name="top_xg",
        title="Top Expected Goal Involvements",
        description="Available players ranked by expected_goal_involvements (descending).",
        columns=("web_name", "team_short", "position", "value"),
    ),
    ResourceSpec(
        name="top_points",
        title="Top Points",
        description="Available players ranked by total_points (descending).",
        columns=("web_name", "team_short", "position", "value"),
    ),
    ResourceSpec(
        name="top_minutes",
        title="Top Minutes",
        description="Available players ranked by minutes played (descending).",
        columns=("web_name", "team_short", "position", "value"),
    ),
    ResourceSpec(
        name="popular",
        title="Most Selected",
        description="Available players ranked by selected_by_percent (descending).",
        columns=("web_name", "team_short", "position", "value"),
    ),
    ResourceSpec(
        name="player_minutes",
        title="Player Minutes",
        description="Use @minutes <player> for accumulated current-season FPL minutes.",
        columns=_PLAYER_MINUTES_COLUMNS,
    ),
    ResourceSpec(
        name="player_role",
        title="Player Role",
        description="Use @role <player> for nominal FPL position.",
        columns=_PLAYER_ROLE_COLUMNS,
    ),
)


_RESOURCE_HANDLERS: dict[str, Callable[[dict[str, Any]], ResourceResult]] = {
    "injuries":    _resource_injuries,
    "top_form":    _resource_top_form,
    "top_xg":      _resource_top_xg,
    "top_points":  _resource_top_points,
    "top_minutes": _resource_top_minutes,
    "popular":     _resource_popular,
}


def list_resource_specs() -> tuple[ResourceSpec, ...]:
    """Return the eight ResourceSpec entries in stable registration order."""
    return RESOURCE_SPECS


def has_resource(canonical: str) -> bool:
    return canonical in _RESOURCE_HANDLERS or canonical in {
        "player_minutes", "player_role",
    }


def run_resource(
    canonical: str,
    bootstrap: dict[str, Any],
    *,
    argument: str | None = None,
    shape_reason: str | None = None,
) -> ResourceResult | PlayerResourceResult:
    """Dispatch to the resource handler for *canonical*.

    Raises `KeyError` if the resource is not registered — callers MUST
    check `has_resource()` first or catch the error.
    """
    if canonical in {"player_minutes", "player_role"}:
        return _player_resource(canonical, bootstrap, argument, shape_reason)
    handler = _RESOURCE_HANDLERS[canonical]
    return handler(bootstrap)

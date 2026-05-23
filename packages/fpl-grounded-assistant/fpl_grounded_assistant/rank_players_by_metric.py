"""
fpl_grounded_assistant.rank_players_by_metric
=============================================
P2.8 (Gap A fix): Atomic rank_players_by_metric tool — top N players ranked
by any numeric bootstrap metric.

Closes the "dame el top 10 de jugadores por xgi" class of queries that
previously returned branch=unsupported / outcome=no_tool.

Reuse
-----
*  ``_build_match_dict`` from ``find_players`` — single source of truth for
   the 21-field grounding payload.
*  ``_safe_float`` from ``find_players`` — numeric coercion with safe default.
*  ``_POSITION_MAP`` / ``_normalize`` from ``find_players`` — position labels
   and accent-strip utility.

Metric aliases
--------------
The public API accepts common aliases (xgi, xg, xa, ict, popularity).
All aliases are resolved to the canonical bootstrap field name before lookup.

Filters
-------
*  ``position``: optional filter (GKP/DEF/MID/FWD, case-insensitive).
*  ``min_minutes``: exclude players with fewer minutes than this threshold.

Both filters are applied BEFORE sorting.

Registration
------------
Registers ``rank_players_by_metric`` in ``TOOL_REGISTRY`` as a side-effect
of import.  ``__init__.py`` must import this module so
``run_tool("rank_players_by_metric", ...)`` works.
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from fpl_grounded_assistant.find_players import (
    _build_match_dict,
    _safe_float,
    _safe_int,
    _normalize,
    _position_label,
)


# ---------------------------------------------------------------------------
# Metric alias map: public name (or alias) -> bootstrap element field name
# ---------------------------------------------------------------------------

_METRIC_ALIASES: dict[str, str] = {
    # Form & points
    "form":                           "form",
    "total_points":                   "total_points",
    "points":                         "total_points",
    "points_per_game":                "points_per_game",
    "ppg":                            "points_per_game",
    # xG stats
    "expected_goals":                 "expected_goals",
    "xg":                             "expected_goals",
    "expected_assists":               "expected_assists",
    "xa":                             "expected_assists",
    "expected_goal_involvements":     "expected_goal_involvements",
    "xgi":                            "expected_goal_involvements",
    # Other metrics
    "ict_index":                      "ict_index",
    "ict":                            "ict_index",
    "selected_by_percent":            "selected_by_percent",
    "popularity":                     "selected_by_percent",
    "ownership":                      "selected_by_percent",
    "minutes":                        "minutes",
    "goals_scored":                   "goals_scored",
    "goals":                          "goals_scored",
    "assists":                        "assists",
    "clean_sheets":                   "clean_sheets",
    "bonus":                          "bonus",
    "bps":                            "bps",
}

#: Sorted list of canonical metric names exposed to users.
_VALID_METRICS: list[str] = sorted(set(_METRIC_ALIASES.keys()))

#: Position filter map: normalized input -> canonical label
_POSITION_FILTER_MAP: dict[str, str] = {
    "gkp": "GKP",
    "goalkeeper": "GKP",
    "portero": "GKP",
    "def": "DEF",
    "defender": "DEF",
    "defensa": "DEF",
    "mid": "MID",
    "midfielder": "MID",
    "centrocampista": "MID",
    "medio": "MID",
    "fwd": "FWD",
    "forward": "FWD",
    "delantero": "FWD",
}

_TOP_N_CAP: int = 50


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def rank_players_by_metric(
    metric: str,
    top_n: int = 10,
    position: "str | None" = None,
    min_minutes: int = 0,
    bootstrap: "dict[str, Any] | None" = None,
) -> dict[str, Any]:
    """Rank players by a numeric bootstrap metric.

    Args:
        metric: metric name or alias (case-insensitive).
            Accepted: form, total_points, points_per_game, expected_goals/xg,
            expected_assists/xa, expected_goal_involvements/xgi, ict_index/ict,
            selected_by_percent/popularity/ownership, minutes, goals_scored,
            assists, clean_sheets, bonus, bps.
        top_n: max results (1-50, default 10). Silently capped at 50.
        position: optional position filter (GKP/DEF/MID/FWD, case-insensitive).
            Also accepts Spanish names (portero/defensa/centrocampista/delantero).
        min_minutes: exclude players with fewer minutes (default 0).
        bootstrap: live FPL bootstrap; fetched if None.

    Returns:
        # Success:
        {
            "status": "ok",
            "metric": <canonical field name>,
            "top_n": <int>,
            "position_filter": <str | None>,
            "min_minutes_filter": <int>,
            "ranked": [
                {
                    # Full 21-field grounding payload (including match_rank=0)
                    # PLUS:
                    "metric_value": <float>,
                    "rank": <int>   # 1-based
                },
                ...
            ]
        }
        # Invalid metric:
        {
            "status": "invalid_argument",
            "code": "unknown_metric",
            "message": "Metric '<m>' not recognized. Try: <list>.",
            "valid_metrics": [<str>, ...]
        }
        # No players match filters:
        {
            "status": "ok",
            "metric": <str>,
            "top_n": 0,
            "position_filter": <str | None>,
            "min_minutes_filter": <int>,
            "ranked": []
        }
    """
    # ------------------------------------------------------------------
    # 0. Validate inputs
    # ------------------------------------------------------------------
    if not isinstance(metric, str) or not metric.strip():
        return {
            "status":        "invalid_argument",
            "code":          "unknown_metric",
            "message":       "Metric must be a non-empty string.",
            "valid_metrics": _VALID_METRICS,
        }

    normalized_metric = metric.strip().lower()
    field_name = _METRIC_ALIASES.get(normalized_metric)

    if field_name is None:
        # Try partial: if input is a prefix of exactly one metric, resolve.
        partial_matches = [k for k in _METRIC_ALIASES if k.startswith(normalized_metric)]
        if len(partial_matches) == 1:
            field_name = _METRIC_ALIASES[partial_matches[0]]
            normalized_metric = partial_matches[0]
        else:
            return {
                "status":        "invalid_argument",
                "code":          "unknown_metric",
                "message":       (
                    f"Metric '{metric}' not recognized. "
                    f"Try: {', '.join(_VALID_METRICS[:15])} ..."
                ),
                "valid_metrics": _VALID_METRICS,
            }

    # Silent cap on top_n
    try:
        top_n = max(1, min(int(top_n), _TOP_N_CAP))
    except (ValueError, TypeError):
        top_n = 10

    # Silent floor on min_minutes
    try:
        min_minutes = max(0, int(min_minutes))
    except (ValueError, TypeError):
        min_minutes = 0

    # Resolve position filter
    canonical_position: "str | None" = None
    if position is not None and isinstance(position, str) and position.strip():
        pos_key = _normalize(position.strip())
        canonical_position = _POSITION_FILTER_MAP.get(pos_key)
        if canonical_position is None:
            # Accept direct canonical forms: GKP/DEF/MID/FWD
            pos_upper = position.strip().upper()
            if pos_upper in ("GKP", "DEF", "MID", "FWD"):
                canonical_position = pos_upper

    # ------------------------------------------------------------------
    # 1. Guard: bootstrap required
    # ------------------------------------------------------------------
    if bootstrap is None:
        return {
            "status":             "ok",
            "metric":             field_name,
            "top_n":              0,
            "position_filter":    canonical_position,
            "min_minutes_filter": min_minutes,
            "ranked":             [],
        }

    elements:      list[dict[str, Any]] = bootstrap.get("elements", []) or []
    teams:         list[dict[str, Any]] = bootstrap.get("teams", []) or []
    element_types: list[dict[str, Any]] = bootstrap.get("element_types", []) or []

    # ------------------------------------------------------------------
    # 2. Apply filters
    # ------------------------------------------------------------------
    filtered: list[dict[str, Any]] = []

    for el in elements:
        # Minutes filter
        el_minutes = _safe_int(el.get("minutes"), 0)
        if el_minutes < min_minutes:
            continue

        # Position filter
        if canonical_position is not None:
            el_position = _position_label(el, element_types)
            if el_position != canonical_position:
                continue

        filtered.append(el)

    # ------------------------------------------------------------------
    # 3. Sort by metric value descending
    # ------------------------------------------------------------------
    def _metric_value(el: dict[str, Any]) -> float:
        return _safe_float(el.get(field_name), 0.0)

    filtered.sort(key=_metric_value, reverse=True)

    # ------------------------------------------------------------------
    # 4. Build ranked list
    # ------------------------------------------------------------------
    top = filtered[:top_n]

    ranked: list[dict[str, Any]] = []
    for rank_idx, el in enumerate(top, start=1):
        payload = _build_match_dict(el, teams, element_types, match_rank=0)
        payload["metric_value"] = _metric_value(el)
        payload["rank"] = rank_idx
        ranked.append(payload)

    return {
        "status":             "ok",
        "metric":             field_name,
        "top_n":              len(ranked),
        "position_filter":    canonical_position,
        "min_minutes_filter": min_minutes,
        "ranked":             ranked,
    }


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

RANK_PLAYERS_BY_METRIC_SPEC = ToolSpec(
    name="rank_players_by_metric",
    description=(
        "Top N players by metric (xGI, form, points, xG, xA, ICT, ownership, minutes, etc.). "
        "Filter by position/min_minutes. Returns ranked list with grounding payload + metric_value. "
        "Use for top-N queries."
    ),
    parameters={
        "type": "object",
        "properties": {
            "metric": {
                "type":        "string",
                "description": (
                    "Metric to rank by. Aliases accepted: xgi, xg, xa, ict, "
                    "popularity, ppg, points. Full names: expected_goal_involvements, "
                    "form, total_points, selected_by_percent, minutes, etc."
                ),
            },
            "top_n": {
                "type":        "integer",
                "description": "Max players to return (1-50, default 10)",
                "minimum":     1,
                "maximum":     50,
            },
            "position": {
                "type":        "string",
                "description": (
                    "Optional position filter: GKP/DEF/MID/FWD (case-insensitive). "
                    "Spanish names accepted: portero/defensa/centrocampista/delantero."
                ),
            },
            "min_minutes": {
                "type":        "integer",
                "description": "Exclude players with fewer minutes (default 0)",
                "minimum":     0,
            },
        },
        "required":             ["metric"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":             {"type": "string"},
            "metric":             {"type": "string"},
            "top_n":              {"type": "integer"},
            "position_filter":    {"type": ["string", "null"]},
            "min_minutes_filter": {"type": "integer"},
            "ranked":             {"type": "array"},
        },
    },
)


def _rank_players_by_metric_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``rank_players_by_metric()``."""
    try:
        metric = args.get("metric")
        if not metric:
            return {
                "status":        "invalid_argument",
                "code":          "unknown_metric",
                "message":       "metric is required.",
                "valid_metrics": _VALID_METRICS,
            }
        return rank_players_by_metric(
            metric      = metric,
            top_n       = args.get("top_n", 10),
            position    = args.get("position"),
            min_minutes = args.get("min_minutes", 0),
            bootstrap   = bootstrap,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status":  "error",
            "code":    "tool_exception",
            "message": f"rank_players_by_metric raised an unexpected error: {exc}",
        }


# Register with the shared tool registry.
TOOL_REGISTRY.register(RANK_PLAYERS_BY_METRIC_SPEC, _rank_players_by_metric_handler)

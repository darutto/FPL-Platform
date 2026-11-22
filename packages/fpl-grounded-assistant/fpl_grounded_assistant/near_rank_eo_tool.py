"""get_near_rank_eo: the connected user's effective-ownership "neighbourhood" tool.

The managers around the user's overall rank (about 125 of them) and how heavily
they own, captain and bench each player. The compute is slow (17-35 s of FPL
calls), so this tool NEVER waits for it: the first call starts a background job
and returns ``status="computing"``; asking again after ``eta_s`` seconds returns
the result (see ``near_rank_eo.NearRankEOService``).

Behind ``FPL_NEAR_RANK_EO_ENABLED`` (default OFF): when the flag is off the tool is
not offered to the model, and a direct call returns ``status="disabled"``.

Team id: from the session (``bootstrap["_my_team_id"]``), exactly as
``get_my_squad`` does. No team, no answer (``status="no_team_connected"``).

Registers ``get_near_rank_eo`` in ``TOOL_REGISTRY`` as a side-effect of import.
Its LLM schema lives in ``tool_schema_registry.NEAR_RANK_EO_SCHEMA`` (kept OUT of
``_ALL_SCHEMAS``, like ``search_web``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fpl_player_registry import normalize_player_name
from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from . import near_rank_eo as _core
from .orch_config import is_near_rank_eo_enabled

TOP_N = 15
MAX_NAMED = 10

_SERVICE: _core.NearRankEOService | None = None


def get_service() -> _core.NearRankEOService:
    """The process-wide service (lazy, so import never builds a thread pool)."""
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = _core.NearRankEOService()
    return _SERVICE


def set_service(service: _core.NearRankEOService | None) -> None:
    """Replace the process-wide service (tests)."""
    global _SERVICE
    _SERVICE = service


def _parse(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def gw_and_valid_until(events: list[dict[str, Any]], now: datetime) -> tuple[int | None, float | None]:
    """The latest gameweek whose deadline has passed (its picks are public) and the
    next deadline as an epoch time (when a cached answer stops being current)."""
    passed: list[int] = []
    upcoming: list[float] = []
    for event in events or []:
        deadline = _parse(event.get("deadline_time"))
        if deadline is None:
            continue
        if deadline <= now:
            passed.append(event["id"])
        else:
            upcoming.append(deadline.timestamp())
    return (max(passed) if passed else None), (min(upcoming) if upcoming else None)


def _season(bootstrap: dict[str, Any]) -> str | None:
    from fpl_historical.season_guard import derive_live_season  # noqa: PLC0415  (lazy, as zonal_weakness_tool)

    return derive_live_season(bootstrap)


def _name_index(bootstrap: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[int, str]]:
    teams = {t.get("id"): t.get("short_name") or "" for t in bootstrap.get("teams") or []}
    by_id = {str(e["id"]): e for e in bootstrap.get("elements") or [] if "id" in e}
    return by_id, teams


def _row(element_id: str, stats: dict[str, float], by_id: dict[str, dict[str, Any]], teams: dict[int, str]) -> dict[str, Any]:
    element = by_id.get(element_id) or {}
    return {"player": element.get("web_name") or f"#{element_id}", "team": teams.get(element.get("team"), ""),
            "eo": stats["eo"], "owned_pct": stats["owned_pct"], "captain_pct": stats["captain_pct"]}


def shape_result(data: dict[str, Any], bootstrap: dict[str, Any], player_names: list[str]) -> dict[str, Any]:
    """The compact answer for the model: the top EO players plus any the user named."""
    by_id, teams = _name_index(bootstrap)
    players = data["players"]
    top_ids = sorted(players, key=lambda k: players[k]["eo"], reverse=True)[:TOP_N]
    named_ids: list[str] = []
    for name in player_names[:MAX_NAMED]:
        wanted = normalize_player_name(name)
        if not wanted:
            continue
        for element_id, element in by_id.items():
            if element_id in players and wanted in (normalize_player_name(element.get("web_name")),
                                                    normalize_player_name(element.get("second_name"))):
                named_ids.append(element_id)
    rows = [_row(i, players[i], by_id, teams) for i in top_ids]
    named = [_row(i, players[i], by_id, teams) for i in dict.fromkeys(named_ids)]
    return {
        "status": "ok", "tier": "near", "gw": data["gw"], "approx": True,
        "user_rank": data["user_rank"], "n_sampled": data["n_sampled"],
        "label": f"approx., n={data['n_sampled']}",
        "top_players": rows, "named_players": named,
        "note": ("EO = how many copies of the player the managers around the user's rank hold, "
                 "counting captains double; a sample, so read it as approximate."),
    }


def get_near_rank_eo(bootstrap: dict[str, Any] | None, *, player_names: list[str] | None = None,
                     now: datetime | None = None) -> dict[str, Any]:
    if not is_near_rank_eo_enabled():
        return {"status": "disabled", "code": "near_rank_eo_disabled"}
    team_id = (bootstrap or {}).get("_my_team_id")
    if not team_id:
        return {"status": "no_team_connected", "code": "no_team_connected"}
    now = now or datetime.now(timezone.utc)
    gw, valid_until = gw_and_valid_until((bootstrap or {}).get("events") or [], now)
    season = _season(bootstrap or {})
    if gw is None or season is None:
        return {"status": "unavailable", "reason": "no_gameweek"}
    try:
        result = get_service().status(season, gw, int(team_id), valid_until=valid_until)
    except Exception:  # noqa: BLE001  (a tool never raises into the turn)
        return {"status": "unavailable", "reason": "error"}
    if result["status"] == "ready":
        return shape_result(result["data"], bootstrap or {}, list(player_names or []))
    if result["status"] == "computing":
        return {"status": "computing", "eta_s": result["eta_s"],
                "message": ("Being calculated in the background (about 30 seconds). Tell the user it is "
                            "not ready yet and that they can ask again shortly; do not guess numbers.")}
    return {"status": "unavailable", "reason": result.get("reason", "error")}


NEAR_RANK_EO_SPEC = ToolSpec(
    name="get_near_rank_eo",
    description=(
        "Effective ownership (EO) among the managers around the connected user's own overall rank "
        "(about 125 sampled): top-EO players plus any named players, with ownership and captaincy %. "
        "Use for 'what do managers near me own', 'who hurts me if he hauls', 'EO of X near my rank'. "
        "It is approximate (a sample). status='computing' means the job just started: tell the user "
        "plainly it is not ready and to ask again in about 30 seconds; never invent numbers. "
        "status='no_team_connected' when no team is linked."
    ),
    parameters={
        "type": "object",
        "properties": {
            "player_names": {
                "type": "array", "items": {"type": "string"}, "maxItems": MAX_NAMED,
                "description": "Players whose EO the user asked about (web names); optional.",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "tier": {"type": "string"},
            "gw": {"type": "integer"},
            "approx": {"type": "boolean"},
            "user_rank": {"type": "integer"},
            "n_sampled": {"type": "integer"},
            "label": {"type": "string"},
            "top_players": {"type": "array"},
            "named_players": {"type": "array"},
            "eta_s": {"type": "integer"},
            "reason": {"type": "string"},
        },
    },
)


def _handler(args: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any]:
    names = args.get("player_names")
    return get_near_rank_eo(bootstrap, player_names=[n for n in names if isinstance(n, str)] if isinstance(names, list) else None)


TOOL_REGISTRY.register(NEAR_RANK_EO_SPEC, _handler)

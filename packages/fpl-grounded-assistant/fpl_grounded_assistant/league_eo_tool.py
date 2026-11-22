"""get_league_eo: the connected user's mini-league effective-ownership tool.

Who the managers in the user's own private mini-league own, captain and bench. The
compute can take up to ~20 s of FPL calls, so this tool NEVER waits for it: the
first call starts a background job and returns ``status="computing"``; asking again
returns the result (see ``league_eo.LeagueEOService``).

Behind ``FPL_LEAGUE_EO_ENABLED`` (default OFF): when the flag is off the tool is not
offered to the model, and a direct call returns ``status="disabled"``.

Inputs from the session: the team id (``bootstrap["_my_team_id"]``, as ``get_my_squad``
does) and the user's stored main league (``bootstrap["_my_league_id"]``, which the UI
sends as ``main_league_id``). A ``league_name`` argument (the user's own words) wins
over the stored id and is matched against the user's own leagues only.

Which league, in order: ``league_name``; else the stored id; else, if the user has
exactly one private league, that one; else ``status="needs_league"`` with the names
and sizes so the assistant asks. A stored id the user no longer belongs to falls back
to the same picker. The result echoes ``league_id`` so the UI can store it.

Registers ``get_league_eo`` in ``TOOL_REGISTRY`` as a side-effect of import. Its LLM
schema lives in ``tool_schema_registry.LEAGUE_EO_SCHEMA`` (kept OUT of ``_ALL_SCHEMAS``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from . import league_eo as _core
from .get_my_squad import load_linked_squad
from .near_rank_eo_tool import (  # noqa: F401  (the comparison and its thresholds live there, shared with near-rank)
    DIFFERENTIAL_MAX_OWNED_PCT,
    GROUP_SIZE,
    MAX_NAMED,
    RISK_MIN_OWNED_PCT,
    TOP_N,
    _name_index,
    _row,
    _season,
    gw_and_valid_until,
    owned_ids,
    squad_comparison,
    wording_note,
)
from .orch_config import is_league_eo_enabled
from fpl_player_registry import normalize_player_name

_SERVICE: _core.LeagueEOService | None = None


def get_service() -> _core.LeagueEOService:
    """The process-wide service (lazy, so import never builds a thread pool)."""
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = _core.LeagueEOService()
    return _SERVICE


def set_service(service: _core.LeagueEOService | None) -> None:
    """Replace the process-wide service (tests)."""
    global _SERVICE
    _SERVICE = service


def shape_result(data: dict[str, Any], bootstrap: dict[str, Any], player_names: list[str],
                 squad: dict[str, Any] | None = None) -> dict[str, Any]:
    """The compact answer for the model: the top EO players, any the user named, and the squad comparison."""
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
    own = owned_ids(squad)
    return {
        "status": "ok", "tier": "league", "gw": data["gw"],
        "league_id": data["league_id"], "league_name": data["league_name"], "league_size": data["league_size"],
        "exact": data["exact"], "approx": data["approx"], "n_sampled": data["n_sampled"], "label": data["label"],
        "top_players": [_row(i, players[i], by_id, teams, own) for i in top_ids],
        "named_players": [_row(i, players[i], by_id, teams, own) for i in dict.fromkeys(named_ids)],
        **squad_comparison(players, squad, by_id, teams),
        "note": ("EO = how many copies of the player the managers of this league hold, counting captains "
                 "double. Quote the label: 'exact' means every member was read, 'approx.' a sample. "
                 + wording_note("League has him", "La liga lo tiene")),
    }


def get_league_eo(bootstrap: dict[str, Any] | None, *, league_name: str | None = None,
                  player_names: list[str] | None = None, now: datetime | None = None) -> dict[str, Any]:
    if not is_league_eo_enabled():
        return {"status": "disabled", "code": "league_eo_disabled"}
    boot = bootstrap or {}
    team_id = boot.get("_my_team_id")
    if not team_id:
        return {"status": "no_team_connected", "code": "no_team_connected"}
    now = now or datetime.now(timezone.utc)
    gw, valid_until = gw_and_valid_until(boot.get("events") or [], now)
    season = _season(boot)
    if gw is None or season is None:
        return {"status": "unavailable", "reason": "no_gameweek"}
    stored = boot.get("_my_league_id")
    service = get_service()

    def ask(league_id: int | None, name: str | None) -> dict[str, Any]:
        return service.status(season, gw, int(team_id), league_id, league_name=name, valid_until=valid_until)

    try:
        result = ask(int(stored) if stored else None, league_name)
        if result.get("reason") == "not_a_member" and not league_name:
            result = ask(None, None)  # a stale stored league: fall back to the picker
        if result["status"] == "ready" and "leagues" in result["data"]:
            leagues = result["data"]["leagues"]
            if not leagues:
                return {"status": "no_league", "code": "no_private_league"}
            if len(leagues) > 1:
                # status "ok" + stage, like plan_to_sign's choose_moves: a question for the user, not a failure, so
                # the turn is a grounded one and the league chips can be armed on it.
                return {"status": "ok", "stage": "needs_league",
                        "message": ("Ask the user which league; the league names are shown to them as buttons. "
                                    "Then call again with league_name."),
                        "leagues": [{"league_id": lg["id"], "name": lg["name"], "size": lg["size"]} for lg in leagues]}
            result = ask(leagues[0]["id"], None)  # exactly one: it is the one
    except Exception:  # noqa: BLE001  (a tool never raises into the turn)
        return {"status": "unavailable", "reason": "error"}
    if result["status"] == "ready":
        try:
            squad = load_linked_squad(boot, gw)  # one small FPL call (the user's own picks); None if it fails
        except Exception:  # noqa: BLE001
            squad = None
        return shape_result(result["data"], boot, list(player_names or []), squad)
    if result["status"] == "computing":
        return {"status": "computing", "eta_s": result["eta_s"],
                "message": ("Being calculated in the background (up to about 30 seconds). Tell the user it is "
                            "not ready yet and that they can ask again shortly; do not guess numbers.")}
    return {"status": "unavailable", "reason": result.get("reason", "error")}


LEAGUE_EO_SPEC = ToolSpec(
    name="get_league_eo",
    description=(
        "Effective ownership (EO) inside the connected user's own private mini-league: top-EO players plus "
        "any named, with ownership and captaincy %. status='needs_league' lists the user's leagues: ask "
        "which, then call again with league_name. status='computing' means not ready: say so and ask the "
        "user to try again shortly. status='no_team_connected' when no team is linked."
    ),
    parameters={
        "type": "object",
        "properties": {
            "league_name": {"type": "string", "description": "Name of one of the user's own leagues (optional)."},
            "player_names": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_NAMED,
                             "description": "Players whose EO the user asked about (web names); optional."},
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
            "league_id": {"type": "integer"},
            "league_name": {"type": "string"},
            "league_size": {"type": "integer"},
            "exact": {"type": "boolean"},
            "approx": {"type": "boolean"},
            "n_sampled": {"type": "integer"},
            "label": {"type": "string"},
            "top_players": {"type": "array"},
            "named_players": {"type": "array"},
            "leagues": {"type": "array"},
            "eta_s": {"type": "integer"},
            "reason": {"type": "string"},
        },
    },
)


def _handler(args: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any]:
    names = args.get("player_names")
    name = args.get("league_name")
    return get_league_eo(
        bootstrap,
        league_name=name if isinstance(name, str) and name.strip() else None,
        player_names=[n for n in names if isinstance(n, str)] if isinstance(names, list) else None,
    )


TOOL_REGISTRY.register(LEAGUE_EO_SPEC, _handler)

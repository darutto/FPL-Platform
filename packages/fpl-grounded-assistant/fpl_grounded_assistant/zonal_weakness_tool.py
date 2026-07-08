"""
fpl_grounded_assistant.zonal_weakness_tool
==========================================
Tactical track (T2b / T4a reach) — orchestrator tool wrappers for the
zonal-weakness engine.

This is the **only** place ``TOOL_REGISTRY`` is touched for the tactical
track — the engine in ``zonal_weakness.py`` stays pure and side-effect-free,
mirroring the Track D ``fixture_outlook`` / ``fixture_outlook_tool`` split.
Importing this module (done by ``__init__.py``) registers
``get_zonal_weakness`` and ``get_zonal_opportunity`` so ``run_tool(...)``
works and the orchestrator can reach them from plain-text questions.

Atomic-tool pattern: the LLM-facing schemas live in
``tool_schema_registry`` (``GET_ZONAL_WEAKNESS_SCHEMA`` /
``GET_ZONAL_OPPORTUNITY_SCHEMA``, members of ``_ALL_SCHEMAS``) but the tools
are deliberately kept OUT of ``_TOOL_TO_INTENT`` / ``SUPPORTED_INTENTS`` /
the classifier — the orchestrator narrates their payloads as text; no
dedicated card in this slice.

Handlers return ``status ∈ {ok, not_found, missing_context}`` and never
raise into the orchestrator: an absent tactical store (or any unexpected
engine failure) degrades to ``missing_context``.
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .zonal_weakness import (
    get_player_zonal_outlook,
    get_zonal_opportunity,
    get_zonal_weakness,
)
# Reuse the proven team-name resolver (name / short_name / alias) and the
# current-GW helper (fixtures come from bootstrap["team_fixtures"]).
from .team_fixture_calendar import _get_current_gameweek, _resolve_team

# ---------------------------------------------------------------------------
# FPL bootstrap → Understat store team naming bridge.
# _resolve_team canonicalises free text to a bootstrap team dict, but the
# tactical store keeps Understat titles ("Manchester City", not "Man City").
# Keyed by FPL short_name (stable), values are Understat titles as stored.
# ---------------------------------------------------------------------------
_SHORT_TO_UNDERSTAT: dict[str, str] = {
    "ARS": "Arsenal",
    "AVL": "Aston Villa",
    "BOU": "Bournemouth",
    "BRE": "Brentford",
    "BHA": "Brighton",
    "BUR": "Burnley",
    "CHE": "Chelsea",
    "CRY": "Crystal Palace",
    "EVE": "Everton",
    "FUL": "Fulham",
    "LEE": "Leeds",
    "LIV": "Liverpool",
    "MCI": "Manchester City",
    "MUN": "Manchester United",
    "NEW": "Newcastle United",
    "NFO": "Nottingham Forest",
    "SUN": "Sunderland",
    "TOT": "Tottenham",
    "WHU": "West Ham",
    "WOL": "Wolverhampton Wanderers",
}


def _to_store_team(team_query: str, bootstrap: dict[str, Any]) -> str:
    """Best-effort translation of free text into a store (Understat) team name.

    Resolution: bootstrap resolver first (aliases / short names), bridged via
    short_name; falls back to the raw query — the engine matches store names
    case-insensitively, so Understat-style names pass straight through.
    """
    team = _resolve_team(team_query, bootstrap or {})
    if team is not None:
        short = str(team.get("short_name", "")).upper()
        if short in _SHORT_TO_UNDERSTAT:
            return _SHORT_TO_UNDERSTAT[short]
        name = team.get("name")
        if name:
            return str(name)
    return team_query


def _get_zonal_weakness_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to the pure engine. Never raises."""
    team_query = str(args.get("team", "") or "").strip()
    if not team_query:
        return {"status": "not_found", "team": "", "message": "No team given."}
    try:
        result = get_zonal_weakness(_to_store_team(team_query, bootstrap))
    except Exception as exc:  # noqa: BLE001 — never raise into the orchestrator
        return {"status": "missing_context", "team": team_query, "message": str(exc)}
    if result["status"] == "not_found":
        result["message"] = f"No zonal data for '{team_query}' in the tactical store."
    elif result["status"] == "missing_context":
        result["message"] = (
            "Tactical (Understat zonal) store not available on this deployment."
        )
    return result


def _get_zonal_opportunity_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to the pure engine. Never raises."""
    opponent_query = str(args.get("opponent", "") or "").strip()
    if not opponent_query:
        return {"status": "not_found", "opponent": "", "message": "No opponent given."}
    try:
        result = get_zonal_opportunity(_to_store_team(opponent_query, bootstrap))
    except Exception as exc:  # noqa: BLE001 — never raise into the orchestrator
        return {
            "status": "missing_context", "opponent": opponent_query,
            "message": str(exc),
        }
    if result["status"] == "not_found":
        result["message"] = (
            f"No zonal data for '{opponent_query}' in the tactical store."
        )
    elif result["status"] == "missing_context":
        result["message"] = (
            "Tactical (Understat zonal) store not available on this deployment."
        )
    return result


GET_ZONAL_WEAKNESS_SPEC = ToolSpec(
    name="get_zonal_weakness",
    description=(
        "Use when the user asks WHERE or HOW a team concedes (weak zones). "
        "Returns zones only — no player names (players → get_zonal_opportunity). "
        "xGA/game per zone vs league baseline, owned Understat data; penalties "
        "excluded and reported separately. Weakness read only — no buy/sell advice."
    ),
    parameters={
        "type": "object",
        "properties": {
            "team": {
                "type":        "string",
                "description": "Team name / short_name / alias (e.g. 'Crystal Palace', 'CRY').",
            },
        },
        "required":             ["team"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":          {"type": "string"},
            "team":            {"type": "string"},
            "zones":           {"type": "array"},
            "weakest_zones":   {"type": "array"},
            "penalty_context": {"type": "object"},
            "verdict":         {"type": "string"},
        },
    },
)

GET_ZONAL_OPPORTUNITY_SPEC = ToolSpec(
    name="get_zonal_opportunity",
    description=(
        "Use when the user asks WHICH PLAYERS can exploit/fit/attack a team's "
        "weak defensive zones. Returns the opponent's weak zones WITH matched "
        "player names (prefer over get_zonal_weakness when players are wanted). "
        "Opportunity signal only — no buy/sell advice."
    ),
    parameters={
        "type": "object",
        "properties": {
            "opponent": {
                "type":        "string",
                "description": "Opposing team name / short_name / alias whose defence to probe.",
            },
        },
        "required":             ["opponent"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":        {"type": "string"},
            "opponent":      {"type": "string"},
            "opportunities": {"type": "array"},
        },
    },
)


# ---------------------------------------------------------------------------
# T-player: player-centric zonal outlook over upcoming fixtures
# ---------------------------------------------------------------------------

#: GW lookahead for the player outlook (a 5-fixture report is a wall of text).
DEFAULT_OUTLOOK_HORIZON: int = 3
MAX_OUTLOOK_HORIZON: int = 5


def _team_to_store_name(team: dict[str, Any]) -> str:
    """Bridge one bootstrap team dict to its Understat store name."""
    short = str(team.get("short_name", "")).upper()
    return _SHORT_TO_UNDERSTAT.get(short) or str(team.get("name", ""))


def _get_player_zonal_outlook_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to the pure engine. Never raises.

    The engine is bootstrap-agnostic: this wrapper injects a
    ``fixtures_for_team`` callback that reads ``bootstrap["team_fixtures"]``
    and translates opponent ids to Understat store names via the short-name
    bridge.
    """
    player_query = str(args.get("player", "") or "").strip()
    if not player_query:
        return {"status": "not_found", "player": "", "message": "No player given."}
    try:
        horizon = int(args.get("horizon", DEFAULT_OUTLOOK_HORIZON))
    except (TypeError, ValueError):
        horizon = DEFAULT_OUTLOOK_HORIZON
    horizon = max(1, min(horizon, MAX_OUTLOOK_HORIZON))

    bootstrap = bootstrap or {}
    team_fixtures: dict = bootstrap.get("team_fixtures") or {}
    current_gw = _get_current_gameweek(bootstrap)
    if not team_fixtures or current_gw is None:
        return {
            "status": "missing_context",
            "player": player_query,
            "message": (
                "No team fixture schedule available "
                "(team_fixtures/current GW not in bootstrap)."
            ),
        }

    teams_by_id: dict[int, dict[str, Any]] = {
        int(t["id"]): t for t in bootstrap.get("teams", []) if t.get("id") is not None
    }

    def fixtures_for_team(store_team_name: str) -> list[dict[str, Any]]:
        team_id = next(
            (
                tid for tid, t in teams_by_id.items()
                if _team_to_store_name(t).lower() == store_team_name.lower()
            ),
            None,
        )
        if team_id is None:
            return []
        raw = team_fixtures.get(team_id) or team_fixtures.get(str(team_id)) or []
        window = sorted(
            (f for f in raw
             if current_gw <= int(f.get("gameweek", 0)) < current_gw + horizon),
            key=lambda f: int(f.get("gameweek", 0)),
        )
        out: list[dict[str, Any]] = []
        for f in window:
            opp = teams_by_id.get(int(f.get("opponent_team", 0)))
            out.append({
                "gameweek": int(f.get("gameweek", 0)),
                "opponent": _team_to_store_name(opp) if opp else str(f.get("opponent_team", "?")),
                "is_home": bool(f.get("is_home", False)),
            })
        return out

    try:
        result = get_player_zonal_outlook(
            player_query, fixtures_for_team=fixtures_for_team
        )
    except Exception as exc:  # noqa: BLE001 — never raise into the orchestrator
        return {"status": "missing_context", "player": player_query, "message": str(exc)}

    if result["status"] == "not_found":
        result["message"] = (
            f"No shot profile for '{player_query}' in the tactical store "
            f"(needs >=10 non-penalty shots this season)."
        )
    elif result["status"] == "ambiguous":
        result["message"] = (
            f"Multiple players match '{player_query}': "
            f"{', '.join(result.get('candidates', []))}."
        )
    elif result["status"] == "missing_context" and "message" not in result:
        result["message"] = (
            "Tactical store or upcoming fixtures unavailable for this player."
        )
    return result


GET_PLAYER_ZONAL_OUTLOOK_SPEC = ToolSpec(
    name="get_player_zonal_outlook",
    description=(
        "Use when the user asks whether a PLAYER's upcoming fixtures suit them "
        "zonally (do the next opponents' weak zones fit the player's shot "
        "profile). Per-GW favorable/neutral matchup read over the next 1-5 "
        "fixtures. Opportunity signal only — no buy/sell advice."
    ),
    parameters={
        "type": "object",
        "properties": {
            "player": {
                "type":        "string",
                "description": "Player name as known (e.g. 'Saka', 'Bukayo Saka').",
            },
            "horizon": {
                "type":        "integer",
                "description": "Upcoming GWs to analyse (1-5, default 3).",
            },
        },
        "required":             ["player"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":       {"type": "string"},
            "player":       {"type": "string"},
            "team":         {"type": "string"},
            "player_zones": {"type": "array"},
            "outlook":      {"type": "array"},
            "verdict":      {"type": "string"},
        },
    },
)


TOOL_REGISTRY.register(GET_ZONAL_WEAKNESS_SPEC, _get_zonal_weakness_handler)
TOOL_REGISTRY.register(GET_ZONAL_OPPORTUNITY_SPEC, _get_zonal_opportunity_handler)
TOOL_REGISTRY.register(GET_PLAYER_ZONAL_OUTLOOK_SPEC, _get_player_zonal_outlook_handler)

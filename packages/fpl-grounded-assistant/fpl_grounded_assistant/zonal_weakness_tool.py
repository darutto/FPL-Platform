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

from .zonal_weakness import get_zonal_opportunity, get_zonal_weakness
# Reuse the proven team-name resolver (name / short_name / alias).
from .team_fixture_calendar import _resolve_team

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
        "Zonal defensive weakness for one team from owned Understat shot data: "
        "xGA/game per pitch zone vs the league baseline (delta_vs_avg is the "
        "signal, penalties excluded and reported separately). Weakness/opportunity "
        "read only — no buy/sell advice."
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
        "Players whose own shot profile concentrates in an opponent's weak "
        "defensive zones (relative to league baseline, from owned Understat "
        "data). Opportunity signal only — no buy/sell advice."
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


TOOL_REGISTRY.register(GET_ZONAL_WEAKNESS_SPEC, _get_zonal_weakness_handler)
TOOL_REGISTRY.register(GET_ZONAL_OPPORTUNITY_SPEC, _get_zonal_opportunity_handler)

"""
fpl_grounded_assistant.fixture_outlook_tool
===========================================
Track D — FI2.  Orchestrator tool wrapper for the fixture-outlook engine.

This is the **only** place ``TOOL_REGISTRY`` is touched for Track D — the
engine in ``fixture_outlook.py`` stays pure and side-effect-free.  Importing
this module (done by ``__init__.py``) registers ``get_fixture_outlook`` so
``run_tool("get_fixture_outlook", args, bootstrap)`` works, and the
orchestrator can call it from plain-text questions.

Behaviour
---------
* ``team_query`` given  → single-team outlook (series + runs + verdict).
* ``team_query`` omitted → every team, ranked easiest-first (the grid data).
* ``axis`` is required (``attack`` | ``defence``) so the runner dispatches
  ``handler(args, bootstrap)`` and the model consciously chooses the
  position-relevant axis.

The LLM-facing schema lives in ``tool_schema_registry.GET_FIXTURE_OUTLOOK_SCHEMA``;
this module owns the *execution* spec + handler.
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .fixture_outlook import (
    AXES,
    DEFAULT_HORIZON,
    get_all_team_outlooks,
    get_team_outlook,
)
# Reuse the proven team-name resolver (name / short_name / alias).
from .team_fixture_calendar import _resolve_team


def _get_fixture_outlook_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to the pure engine.

    Returns ``status`` ∈ {ok, not_found, missing_context}.
    """
    axis = str(args.get("axis", "attack")).lower()
    if axis not in AXES:
        axis = "attack"
    horizon = int(args.get("horizon", DEFAULT_HORIZON))
    team_query = str(args.get("team_query", "") or "").strip()

    team_fixtures: dict = bootstrap.get("team_fixtures", {})
    if not team_fixtures:
        return {
            "status": "missing_context",
            "message": "No team fixture schedule available (team_fixtures not in bootstrap).",
        }

    if not team_query:
        # All teams — the grid data (status set by the engine).
        return get_all_team_outlooks(bootstrap, axis, horizon)

    team = _resolve_team(team_query, bootstrap)
    if team is None:
        return {
            "status":     "not_found",
            "team_query": team_query,
            "message":    f"No team found matching '{team_query}'.",
        }

    outlook = get_team_outlook(bootstrap, int(team["id"]), axis, horizon)
    if outlook.get("series"):
        outlook["status"] = "ok"
    else:
        outlook["status"] = "missing_context"
        outlook["message"] = (
            f"No upcoming fixtures for {outlook.get('team_name')} "
            f"in the next {horizon} GWs."
        )
    return outlook


FIXTURE_OUTLOOK_SPEC = ToolSpec(
    name="get_fixture_outlook",
    description=(
        "Two-axis fixture outlook (attack = scoring ease, defence = clean-sheet "
        "ease) over N GWs with run/tendency detection. One team via team_query, "
        "or all teams (easiest-first) when omitted. Schedule-only; no buy/sell."
    ),
    parameters={
        "type": "object",
        "properties": {
            "axis": {
                "type":        "string",
                "enum":        ["attack", "defence"],
                "description": "Difficulty axis: 'attack' or 'defence'.",
            },
            "team_query": {
                "type":        "string",
                "description": "Optional team name / short_name / alias. Omit for all teams.",
            },
            "horizon": {
                "type":        "integer",
                "description": "GW lookahead window (default 10, max 15).",
            },
        },
        # 'axis' required → runner passes (args, bootstrap) to the handler.
        "required": ["axis"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":           {"type": "string"},
            "axis":             {"type": "string"},
            "horizon":          {"type": "integer"},
            "current_gameweek": {"type": ["integer", "null"]},
            "teams":            {"type": "array"},
            "series":           {"type": "array"},
            "runs":             {"type": "array"},
            "verdict":          {"type": "string"},
        },
    },
)


TOOL_REGISTRY.register(FIXTURE_OUTLOOK_SPEC, _get_fixture_outlook_handler)

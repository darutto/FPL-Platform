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
* **Short horizon (i78-A).** A run needs ``_MIN_RUN_LEN`` (3) consecutive
  GWs, so with fewer GWs in the series the engine's verdict is *always*
  "Calendario sin rachas claras" -- true, and useless, for the one-match
  question a /fixtures cell tap asks. Below that length the wrapper replaces
  the verdict with a schedule-only description of each match (opponent,
  venue, difficulty band, relative overall strength) and stamps
  ``verdict_scope="match"``; otherwise ``verdict_scope="run"`` and the
  engine's verdict is passed through untouched.

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
    _MIN_RUN_LEN,
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
        # i78-A: fewer GWs than a run needs -> the run verdict is vacuous by
        # construction; describe the match(es) instead. Read the length off
        # the produced series, not off the requested horizon (a short season
        # tail or blank GWs can make them differ).
        if len(outlook["series"]) < _MIN_RUN_LEN:
            outlook["verdict"] = describe_short_horizon(outlook, team, bootstrap)
            outlook["verdict_scope"] = "match"
        else:
            outlook["verdict_scope"] = "run"
    else:
        outlook["status"] = "missing_context"
        outlook["message"] = (
            f"No upcoming fixtures for {outlook.get('team_name')} "
            f"in the next {horizon} GWs."
        )
    return outlook


# ---------------------------------------------------------------------------
# i78-A -- short-horizon verdict (one or two GWs: describe the match, no runs)
# ---------------------------------------------------------------------------

#: Band -> Spanish qualifier, per axis. Mirrors build_verdict's vocabulary
#: (asequible/exigente for attack, favorable/complicado for defence) so a
#: one-match read and a run read describe the same band with the same word.
_BAND_WORDS: dict[str, dict[int, str]] = {
    "attack":  {1: "muy asequible", 2: "asequible", 3: "media", 4: "exigente", 5: "muy exigente"},
    "defence": {1: "muy favorable", 2: "favorable", 3: "media", 4: "complicada", 5: "muy complicada"},
}

_AXIS_LABEL: dict[str, str] = {"attack": "ofensiva", "defence": "para portería a cero"}


def _overall_strength(team: dict[str, Any] | None, is_home: bool) -> int | None:
    """FPL's 1-5 overall strength at the venue the team plays, or None.

    ``strength_attack_*`` / ``strength_defence_*`` read 0 in the live
    bootstrap this season (see field-notes/artifacts/*bootstrap*.json), so the
    overall venue strength is the only relative-strength signal that is
    actually populated. Absent or zero -> the clause is omitted, not invented.
    """
    if not team:
        return None
    raw = team.get("strength_overall_home" if is_home else "strength_overall_away")
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def _teams_by_short(bootstrap: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(t.get("short_name", "")): t
        for t in bootstrap.get("teams", [])
        if t.get("short_name")
    }


def describe_short_horizon(
    outlook: dict[str, Any],
    team: dict[str, Any],
    bootstrap: dict[str, Any],
) -> str:
    """Schedule-only Spanish description of every match in a short series.

    One sentence per fixture: venue, opponent, difficulty band with its
    qualifier, and -- when both sides carry a usable overall strength -- the
    two venue strengths side by side with who holds the edge. A blank GW says
    so. Never mentions runs ("racha"/"tramo") and never buy/sell.
    """
    axis = str(outlook.get("axis", "attack"))
    words = _BAND_WORDS.get(axis, _BAND_WORDS["attack"])
    axis_label = _AXIS_LABEL.get(axis, _AXIS_LABEL["attack"])
    team_name = str(outlook.get("team_name") or team.get("name") or "?")
    by_short = _teams_by_short(bootstrap)

    sentences: list[str] = []
    for gw in outlook.get("series") or []:
        gw_tag = f"J{gw.get('gameweek', '?')}"
        fixtures = gw.get("fixtures") or []
        if not fixtures:
            sentences.append(f"{gw_tag}: {team_name} descansa (sin partido).")
            continue
        if gw.get("is_dgw"):
            gw_tag += " (doble jornada)"
        for f in fixtures:
            opp_short = str(f.get("opponent_short", "?"))
            opp = by_short.get(opp_short)
            opp_name = str((opp or {}).get("name") or opp_short)
            is_home = bool(f.get("is_home"))
            venue = "en casa ante" if is_home else "a domicilio ante"
            band = f.get("band")
            try:
                band_int = int(band)
            except (TypeError, ValueError):
                band_int = 3
            qualifier = words.get(band_int, "media")
            text = (
                f"{gw_tag}: {team_name} {venue} {opp_name} — "
                f"dificultad {axis_label} {band_int}/5 ({qualifier})"
            )
            ours = _overall_strength(team, is_home)
            theirs = _overall_strength(opp, not is_home)
            if ours is not None and theirs is not None:
                if ours > theirs:
                    edge = f"ventaja {team_name}"
                elif theirs > ours:
                    edge = f"ventaja {opp_name}"
                else:
                    edge = "fuerzas parejas"
                text += (
                    f"; fuerza global {team_name} {ours}/5 {'en casa' if is_home else 'fuera'} "
                    f"vs {opp_name} {theirs}/5 {'fuera' if is_home else 'en casa'} ({edge})"
                )
            sentences.append(text + ".")
    return " ".join(sentences) if sentences else "Sin fixtures en el horizonte."


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
            # i78-A: which verdict was produced -- "run" (engine, >= 3 GWs) or
            # "match" (per-fixture description, < 3 GWs). Read it back off the
            # output rather than inferring it from the requested horizon.
            "verdict_scope":    {"type": "string"},
        },
    },
)


TOOL_REGISTRY.register(FIXTURE_OUTLOOK_SPEC, _get_fixture_outlook_handler)

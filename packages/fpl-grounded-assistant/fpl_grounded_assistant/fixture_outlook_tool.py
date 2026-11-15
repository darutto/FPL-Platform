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
* **One named gameweek (i101).** ``target_gw=N`` (with ``team_query``)
  anchors the window at gameweek N instead of the current GW, so a question
  that names "J5" is answered about J5 whatever the current GW is. The model
  copies the number from the text; it never computes a horizon against a
  current GW the call does not tell it. A played GW and a GW beyond the data
  window are two distinct ``not_found`` messages, never an empty answer.
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
    TARGET_GW_BEYOND_DATA,
    TARGET_GW_PAST,
    _MIN_RUN_LEN,
    get_all_team_outlooks,
    get_team_outlook,
)
# Reuse the proven team-name resolver (name / short_name / alias).
from .catalogue import t
from .locale_types import DEFAULT_LOCALE, Locale, bootstrap_locale
from .team_fixture_calendar import _resolve_team


#: i101 -- the two ways a named gameweek can miss, told apart so the model
#: (and the user) hear the right thing: a played gameweek is a results
#: question, not a forecast; a gameweek beyond the loaded window is just not
#: there yet. Neither is "no fixtures".
_TARGET_GW_NOT_FOUND: dict[str, str] = {
    TARGET_GW_PAST:        "fxo.target_past",
    TARGET_GW_BEYOND_DATA: "fxo.target_beyond",
}


def _parse_target_gw(raw: Any) -> int | None:
    """``target_gw`` as an int, or None when absent/empty. Non-numeric raises
    ValueError so a model that passes 'J5' fails loudly instead of silently
    falling back to the horizon window (the exact failure i101 is about)."""
    if raw is None or raw == "":
        return None
    return int(raw)


def _get_fixture_outlook_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to the pure engine.

    Returns ``status`` ∈ {ok, not_found, missing_context, invalid_argument}.

    i101: ``target_gw`` (one absolute gameweek) takes precedence over
    ``horizon`` (a window from the current GW). The model is told to pass the
    literal number a "J5"-style question names; the engine anchors the window
    there, so no arithmetic against an unstated current GW happens anywhere.
    """
    axis = str(args.get("axis", "attack")).lower()
    if axis not in AXES:
        axis = "attack"
    locale = bootstrap_locale(bootstrap)
    horizon = int(args.get("horizon", DEFAULT_HORIZON))
    team_query = str(args.get("team_query", "") or "").strip()
    try:
        target_gw = _parse_target_gw(args.get("target_gw"))
    except (TypeError, ValueError):
        return {
            "status":  "invalid_argument",
            "code":    "target_gw_not_a_number",
            "message": f"target_gw must be a gameweek number, got {args.get('target_gw')!r}.",
        }

    team_fixtures: dict = bootstrap.get("team_fixtures", {})
    if not team_fixtures:
        return {
            "status": "missing_context",
            "message": "No team fixture schedule available (team_fixtures not in bootstrap).",
        }

    if not team_query:
        if target_gw is not None:
            # target_gw is a one-team, one-match read; the all-teams grid has
            # no single match to point at.
            return {
                "status":    "invalid_argument",
                "code":      "target_gw_requires_team",
                "target_gw": target_gw,
                "message":   "target_gw requires team_query (one team, one gameweek).",
            }
        # All teams — the grid data (status set by the engine).
        return get_all_team_outlooks(bootstrap, axis, horizon, locale=locale)

    team = _resolve_team(team_query, bootstrap)
    if team is None:
        return {
            "status":     "not_found",
            "team_query": team_query,
            "message":    f"No team found matching '{team_query}'.",
        }

    if target_gw is not None:
        outlook = get_team_outlook(
            bootstrap, int(team["id"]), axis, target_gw=target_gw, locale=locale
        )
        miss = _TARGET_GW_NOT_FOUND.get(str(outlook.get("target_gw_status")))
        if miss is not None:
            outlook["status"] = "not_found"
            outlook["message"] = t(miss, locale, gw=target_gw)
            return outlook
    else:
        outlook = get_team_outlook(bootstrap, int(team["id"]), axis, horizon, locale=locale)
    if outlook.get("series"):
        outlook["status"] = "ok"
        # i78-A: fewer GWs than a run needs -> the run verdict is vacuous by
        # construction; describe the match(es) instead. Read the length off
        # the produced series, not off the requested horizon (a short season
        # tail or blank GWs can make them differ).
        if len(outlook["series"]) < _MIN_RUN_LEN:
            outlook["verdict"] = describe_short_horizon(outlook, team, bootstrap, locale)
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
    locale: Locale = DEFAULT_LOCALE,
) -> str:
    """Schedule-only description (es by default) of every match in a short series.

    One sentence per fixture: venue, opponent, difficulty band with its
    qualifier, and -- when both sides carry a usable overall strength -- the
    two venue strengths side by side with who holds the edge. A blank GW says
    so. Never mentions runs ("racha"/"tramo") and never buy/sell.
    """
    axis = str(outlook.get("axis", "attack"))
    axis = axis if axis in ("attack", "defence") else "attack"
    axis_label = t(f"fxo.axis.{axis}", locale)
    team_name = str(outlook.get("team_name") or team.get("name") or "?")
    by_short = _teams_by_short(bootstrap)

    sentences: list[str] = []
    for gw in outlook.get("series") or []:
        gw_tag = t("fxo.gw", locale, n=gw.get("gameweek", "?"))
        fixtures = gw.get("fixtures") or []
        if not fixtures:
            sentences.append(t("fxo.rest", locale, gw_tag=gw_tag, team=team_name))
            continue
        if gw.get("is_dgw"):
            gw_tag += t("fxo.dgw", locale)
        for f in fixtures:
            opp_short = str(f.get("opponent_short", "?"))
            opp = by_short.get(opp_short)
            opp_name = str((opp or {}).get("name") or opp_short)
            is_home = bool(f.get("is_home"))
            venue = t("fxo.venue_home" if is_home else "fxo.venue_away", locale)
            band = f.get("band")
            try:
                band_int = int(band)
            except (TypeError, ValueError):
                band_int = 3
            qualifier = t(f"fxo.band.{axis}.{band_int}" if 1 <= band_int <= 5 else "fxo.band.attack.3", locale)
            text = t(
                "fxo.match", locale, gw_tag=gw_tag, team=team_name, venue=venue,
                opp=opp_name, axis_label=axis_label, band=band_int, qualifier=qualifier,
            )
            ours = _overall_strength(team, is_home)
            theirs = _overall_strength(opp, not is_home)
            if ours is not None and theirs is not None:
                if ours > theirs:
                    edge = t("fxo.edge_team", locale, name=team_name)
                elif theirs > ours:
                    edge = t("fxo.edge_team", locale, name=opp_name)
                else:
                    edge = t("fxo.edge_even", locale)
                at_home, away = t("fxo.at_home", locale), t("fxo.away", locale)
                text += t(
                    "fxo.strength", locale, team=team_name, ours=ours,
                    ours_venue=at_home if is_home else away, opp=opp_name, theirs=theirs,
                    theirs_venue=away if is_home else at_home, edge=edge,
                )
            sentences.append(text + ".")
    return " ".join(sentences) if sentences else t("fxo.no_series", locale)


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
            "target_gw": {
                "type":        "integer",
                "description": (
                    "One absolute gameweek (i101): the literal number named in "
                    "the question. Requires team_query; overrides horizon."
                ),
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
            # i101: which gameweek was targeted and whether it was in range
            # (ok | past | beyond_data); None when horizon was used instead.
            "target_gw":        {"type": ["integer", "null"]},
            "target_gw_status": {"type": ["string", "null"]},
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

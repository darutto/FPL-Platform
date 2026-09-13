"""
Tests for Track D / FI2 — get_fixture_outlook orchestrator tool.

Integration-level: verifies the tool is registered and runnable via run_tool,
that the LLM-facing schema is in the registry, and that the dispatcher maps the
tool to its intent. Uses the FDR-fallback bootstrap (no strength fields) so
per-fixture bands equal the difficulty values we set.
"""
from __future__ import annotations

import os as _os
import sys as _sys

import pytest

# sys.path bootstrap (mirror fpl_server.py's _SIB pattern) so the full package
# graph imports — fixture_outlook_tool registers in TOOL_REGISTRY on import.
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG = _os.path.dirname(_HERE)
_PKGS = _os.path.dirname(_PKG)
for _p in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
    _os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_grounded_assistant  # noqa: E402  (triggers tool self-registration)
from fpl_tool_runner import run_tool  # noqa: E402
from fpl_grounded_assistant.tool_schema_registry import (  # noqa: E402
    TOOL_NAMES,
    get_tool_schema,
)
from fpl_grounded_assistant.dispatcher import (  # noqa: E402
    _TOOL_TO_INTENT,
)


# ---------------------------------------------------------------------------
# Bootstrap builder (FDR fallback — no strength fields)
# ---------------------------------------------------------------------------

def _fx(gw: int, opp: int, is_home: bool, difficulty: int) -> dict:
    return {"gameweek": gw, "opponent_team": opp, "is_home": is_home,
            "difficulty": difficulty}


def _bootstrap() -> dict:
    return {
        "teams": [
            {"id": 1, "name": "Arsenal",   "short_name": "ARS"},
            {"id": 2, "name": "Brentford", "short_name": "BRE"},
            {"id": 3, "name": "Chelsea",   "short_name": "CHE"},
        ],
        "events": [{"id": 1, "is_current": True}],
        "team_fixtures": {
            1: [_fx(1, 2, True, 2), _fx(2, 3, False, 2), _fx(3, 2, True, 1)],
            2: [_fx(1, 1, False, 5), _fx(2, 3, True, 5), _fx(3, 1, False, 4)],
            3: [_fx(1, 3, True, 3), _fx(2, 1, False, 3), _fx(3, 2, True, 3)],
        },
    }


# ---------------------------------------------------------------------------
# Registration / wiring
# ---------------------------------------------------------------------------

def test_tool_is_registered_and_schema_present():
    assert "get_fixture_outlook" in TOOL_NAMES
    schema = get_tool_schema("get_fixture_outlook")
    assert schema is not None
    assert "axis" in schema.parameters["required"]


def test_tool_maps_to_renderable_intent():
    # FI4: get_fixture_outlook now maps to the renderable fixture_outlook intent
    # (the ticker card) via the orchestrator path. It is still intentionally
    # OUT of SUPPORTED_INTENTS / the classifier (deterministic routing + axis
    # extraction is FI4-3), which keeps the classifier-coverage contract green.
    from fpl_grounded_assistant.dispatcher import SUPPORTED_INTENTS, INTENT_FIXTURE_OUTLOOK
    assert _TOOL_TO_INTENT["get_fixture_outlook"] == INTENT_FIXTURE_OUTLOOK
    assert INTENT_FIXTURE_OUTLOOK not in SUPPORTED_INTENTS


# ---------------------------------------------------------------------------
# Execution via run_tool
# ---------------------------------------------------------------------------

def test_run_tool_all_teams_easiest_first():
    res = run_tool("get_fixture_outlook", {"axis": "attack"}, _bootstrap())
    assert res["status"] == "ok"
    assert res["axis"] == "attack"
    shorts = [t["team_short"] for t in res["teams"]]
    assert shorts[0] == "ARS"     # easiest schedule first
    assert shorts[-1] == "BRE"    # hardest last


def test_run_tool_single_team():
    res = run_tool(
        "get_fixture_outlook",
        {"axis": "attack", "team_query": "ARS"},
        _bootstrap(),
    )
    assert res["status"] == "ok"
    assert res["team_short"] == "ARS"
    assert "verdict" in res and isinstance(res["verdict"], str)
    assert [e["band"] for e in res["series"]] == [2, 2, 1]


def test_run_tool_alias_resolution():
    res = run_tool("get_fixture_outlook", {"axis": "defence", "team_query": "Arsenal"}, _bootstrap())
    assert res["status"] == "ok"
    assert res["team_short"] == "ARS"
    assert res["axis"] == "defence"


def test_run_tool_not_found():
    res = run_tool("get_fixture_outlook", {"axis": "attack", "team_query": "Nonexistent FC"}, _bootstrap())
    assert res["status"] == "not_found"


def test_run_tool_missing_context_without_fixtures():
    bs = _bootstrap()
    bs["team_fixtures"] = {}
    res = run_tool("get_fixture_outlook", {"axis": "attack"}, bs)
    assert res["status"] == "missing_context"


def test_run_tool_requires_axis():
    # axis is required → runner returns a structured error, not a crash.
    res = run_tool("get_fixture_outlook", {}, _bootstrap())
    assert res.get("status") != "ok"


# ---------------------------------------------------------------------------
# i78-A -- short horizon: describe the match, never "racha"
# ---------------------------------------------------------------------------
# A run needs 3 consecutive GWs, so with 1 or 2 GWs in the series the engine's
# verdict is ALWAYS "Calendario sin rachas claras" -- vacuous for the one-match
# question a /fixtures cell tap asks. Guard: len(series) < _MIN_RUN_LEN.
# Mutation log (each run separately, then restored):
#   `< _MIN_RUN_LEN` -> `< 0`   : test_horizon_1_describes_the_match_without_run_language dies
#   `< _MIN_RUN_LEN` -> `<= 3`  : test_horizon_3_without_runs_keeps_the_engine_verdict dies

def _verdict(res: dict) -> str:
    assert res["status"] == "ok", res
    return res["verdict"]


def test_horizon_1_describes_the_match_without_run_language():
    res = run_tool(
        "get_fixture_outlook",
        {"axis": "attack", "team_query": "ARS", "horizon": 1},
        _bootstrap(),
    )
    verdict = _verdict(res)
    assert len(res["series"]) == 1
    assert res["verdict_scope"] == "match"
    # The whole point: no run language on a single match. There is no English
    # variant of the run verdict in the engine (build_verdict is Spanish-only).
    assert "racha" not in verdict.lower()
    # Describes THE match: gameweek, venue, opponent, difficulty band.
    assert "J1" in verdict
    assert "en casa ante Brentford" in verdict
    assert "dificultad ofensiva 2/5 (asequible)" in verdict


def test_horizon_1_defence_axis_uses_defence_wording():
    res = run_tool(
        "get_fixture_outlook",
        {"axis": "defence", "team_query": "BRE", "horizon": 1},
        _bootstrap(),
    )
    verdict = _verdict(res)
    assert "racha" not in verdict.lower()
    assert "a domicilio ante Arsenal" in verdict
    assert "dificultad para portería a cero 5/5 (muy complicada)" in verdict


def test_horizon_2_is_still_short_and_lists_both_gameweeks():
    res = run_tool(
        "get_fixture_outlook",
        {"axis": "attack", "team_query": "ARS", "horizon": 2},
        _bootstrap(),
    )
    verdict = _verdict(res)
    assert res["verdict_scope"] == "match"
    assert "racha" not in verdict.lower()
    assert "J1:" in verdict and "J2:" in verdict
    assert "a domicilio ante Chelsea" in verdict


def test_horizon_5_keeps_the_run_verdict():
    # ARS bands 2,2,1 over GW1-3 -> a 3-GW good run -> the engine's run verdict.
    from fpl_grounded_assistant.fixture_outlook import build_verdict
    res = run_tool(
        "get_fixture_outlook",
        {"axis": "attack", "team_query": "ARS", "horizon": 5},
        _bootstrap(),
    )
    verdict = _verdict(res)
    assert res["verdict_scope"] == "run"
    assert res["runs"], "fixture assumption: ARS has a good run over GW1-3"
    assert verdict == build_verdict(res["runs"], "attack", res["series"])
    assert verdict.startswith("Buen tramo ofensivo")


def test_horizon_3_without_runs_keeps_the_engine_verdict():
    # CHE bands 3,3,3 -> no run; at 3 GWs the run read is legitimate, so the
    # engine's "sin rachas claras" must survive (pins the guard's direction).
    res = run_tool(
        "get_fixture_outlook",
        {"axis": "attack", "team_query": "CHE", "horizon": 3},
        _bootstrap(),
    )
    verdict = _verdict(res)
    assert res["verdict_scope"] == "run"
    assert "sin rachas claras" in verdict


def test_short_horizon_double_gameweek_mentions_both_matches():
    bs = _bootstrap()
    bs["team_fixtures"][1].append(_fx(1, 3, False, 4))   # ARS also away at CHE in GW1
    res = run_tool(
        "get_fixture_outlook",
        {"axis": "attack", "team_query": "ARS", "horizon": 1},
        bs,
    )
    verdict = _verdict(res)
    assert res["series"][0]["is_dgw"] is True
    assert "racha" not in verdict.lower()
    assert "doble jornada" in verdict
    assert "en casa ante Brentford" in verdict
    assert "a domicilio ante Chelsea" in verdict
    assert "4/5 (exigente)" in verdict


def test_short_horizon_blank_gameweek_says_so():
    bs = _bootstrap()
    # ARS has no GW2 fixture while GW2 is active for the others -> blank.
    bs["team_fixtures"][1] = [f for f in bs["team_fixtures"][1] if f["gameweek"] != 2]
    res = run_tool(
        "get_fixture_outlook",
        {"axis": "attack", "team_query": "ARS", "horizon": 2},
        bs,
    )
    verdict = _verdict(res)
    assert res["series"][1]["is_bgw"] is True
    assert "J2: Arsenal descansa (sin partido)." in verdict
    assert "racha" not in verdict.lower()


def test_short_horizon_relative_strength_only_when_both_sides_have_it():
    # The FDR-fallback bootstrap carries no strength fields -> no clause.
    res = run_tool(
        "get_fixture_outlook",
        {"axis": "attack", "team_query": "ARS", "horizon": 1},
        _bootstrap(),
    )
    assert "fuerza global" not in _verdict(res)

    # With overall venue strengths on both sides the clause names the edge:
    # ARS home 4 vs BRE away 2 -> ventaja Arsenal.
    bs = _bootstrap()
    for t in bs["teams"]:
        t["strength_overall_home"] = 4 if t["short_name"] == "ARS" else 3
        t["strength_overall_away"] = 2 if t["short_name"] == "BRE" else 3
    res = run_tool(
        "get_fixture_outlook",
        {"axis": "attack", "team_query": "ARS", "horizon": 1},
        bs,
    )
    verdict = _verdict(res)
    assert "fuerza global Arsenal 4/5 en casa vs Brentford 2/5 fuera (ventaja Arsenal)" in verdict

    # Equal strengths -> "fuerzas parejas", never a made-up edge.
    for t in bs["teams"]:
        t["strength_overall_home"] = 3
        t["strength_overall_away"] = 3
    res = run_tool(
        "get_fixture_outlook",
        {"axis": "attack", "team_query": "ARS", "horizon": 1},
        bs,
    )
    assert "(fuerzas parejas)" in _verdict(res)


def test_all_teams_path_is_untouched_by_the_short_horizon_rule():
    # The grid (no team_query) never gets a per-match verdict: it has no
    # single verdict to replace and the /fixtures export reads it as-is.
    res = run_tool("get_fixture_outlook", {"axis": "attack", "horizon": 1}, _bootstrap())
    assert res["status"] == "ok"
    assert "verdict_scope" not in res
    assert "verdict" not in res

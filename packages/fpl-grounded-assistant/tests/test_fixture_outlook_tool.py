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

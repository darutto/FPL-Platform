"""
Tests for Track D / FI4-1 — FixtureOutlookMeta extraction (the ticker card data).

Verifies _extract_fixture_outlook_meta normalises both get_fixture_outlook
shapes (all-teams grid + single-team) into a FixtureOutlookMeta, and that the
tool→intent mapping renders as fixture_outlook.
"""
from __future__ import annotations

import os as _os
import sys as _sys

import pytest

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

import fpl_grounded_assistant  # noqa: E402,F401
from fpl_tool_runner import run_tool  # noqa: E402
from fpl_grounded_assistant.final_response import (  # noqa: E402
    FixtureOutlookMeta,
    TeamOutlook,
    _extract_fixture_outlook_meta,
)
from fpl_grounded_assistant.dispatcher import (  # noqa: E402
    _TOOL_TO_INTENT,
    INTENT_FIXTURE_OUTLOOK,
)


def _fx(gw, opp, is_home, difficulty):
    return {"gameweek": gw, "opponent_team": opp, "is_home": is_home,
            "difficulty": difficulty}


def _bootstrap():
    return {
        "teams": [
            {"id": 1, "name": "Arsenal",   "short_name": "ARS"},
            {"id": 2, "name": "Brentford", "short_name": "BRE"},
            {"id": 3, "name": "Chelsea",   "short_name": "CHE"},
        ],
        "events": [{"id": 1, "is_current": True}],
        "team_fixtures": {
            1: [_fx(1, 2, True, 2), _fx(2, 3, False, 2), _fx(3, 2, True, 1)],   # easy run
            2: [_fx(1, 1, False, 5), _fx(2, 3, True, 5), _fx(3, 1, False, 4)],  # hard run
            3: [_fx(1, 3, True, 3), _fx(2, 1, False, 3), _fx(3, 2, True, 3)],
        },
    }


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_tool_maps_to_fixture_outlook_intent():
    assert _TOOL_TO_INTENT["get_fixture_outlook"] == INTENT_FIXTURE_OUTLOOK


# ---------------------------------------------------------------------------
# Extraction — all-teams shape
# ---------------------------------------------------------------------------

def test_extract_all_teams_grid():
    ro = run_tool("get_fixture_outlook", {"axis": "attack"}, _bootstrap())
    meta = _extract_fixture_outlook_meta(ro)
    assert isinstance(meta, FixtureOutlookMeta)
    assert meta.axis == "attack"
    assert len(meta.teams) == 3
    ars = next(t for t in meta.teams if t.team_short == "ARS")
    assert isinstance(ars, TeamOutlook)
    assert ars.series, "expected a per-GW series"
    assert ars.verdict
    # Arsenal's easy stretch should produce a good run.
    assert any(r.type == "good" for r in ars.runs)
    # Series cells carry opponent + band.
    gw1 = ars.series[0]
    assert gw1.fixtures[0].opponent_short
    assert 1 <= gw1.fixtures[0].band <= 5


# ---------------------------------------------------------------------------
# Extraction — single-team shape
# ---------------------------------------------------------------------------

def test_extract_single_team_shape():
    ro = run_tool("get_fixture_outlook", {"axis": "attack", "team_query": "ARS"}, _bootstrap())
    meta = _extract_fixture_outlook_meta(ro)
    assert isinstance(meta, FixtureOutlookMeta)
    assert len(meta.teams) == 1
    assert meta.teams[0].team_short == "ARS"


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

def test_extract_missing_context_is_empty_not_crash():
    meta = _extract_fixture_outlook_meta({"status": "missing_context", "message": "x"})
    assert isinstance(meta, FixtureOutlookMeta)
    assert meta.teams == ()


def test_extract_garbage_returns_meta_or_none():
    # Must not raise on unexpected input.
    meta = _extract_fixture_outlook_meta({"teams": "not a list"})
    assert meta is None or isinstance(meta, FixtureOutlookMeta)

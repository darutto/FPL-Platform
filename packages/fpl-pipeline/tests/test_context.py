"""
tests/test_context.py
======================
Regression test for `_build_team_fixtures`'s handling of an explicit
`strength: null` in bootstrap team data.

`team.get("strength", 3)` only falls back to 3 when the "strength" key is
absent entirely — the live FPL API can (and does, e.g. before a new
season's ratings are published) return the key present with an explicit
JSON `null`, which that default does not catch, and `int(None)` then
raises `TypeError`. Confirmed live on 2026-07-23: every one of the 20
teams in the bootstrap-static response had `strength: null`.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PKGS = os.path.dirname(_PKG)
for _p in [_PKG, os.path.join(_PKGS, "fpl-api-client")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fpl_pipeline import context  # noqa: E402
from fpl_pipeline.context import _build_team_fixtures  # noqa: E402


def _bootstrap_with_null_strength() -> dict:
    return {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS", "strength": None},
            {"id": 2, "name": "Aston Villa", "short_name": "AVL", "strength": None},
        ],
    }


def test_null_strength_does_not_raise():
    """The exact live-data crash: every team has strength=None, and neither
    fixture carries an explicit team_h_difficulty/team_a_difficulty, so the
    strength_by_id fallback is actually exercised."""
    bootstrap = _bootstrap_with_null_strength()
    fixture_batches = {
        1: [
            {"event": 1, "team_h": 1, "team_a": 2},
        ],
    }
    # Must not raise TypeError: int() argument must be ... not 'NoneType'
    result = _build_team_fixtures(fixture_batches, bootstrap)
    assert result[1][0]["difficulty"] == 3  # fell back to the default
    assert result[2][0]["difficulty"] == 3


def test_null_strength_with_explicit_fixture_difficulty_uses_that_instead():
    """When the fixture itself carries an explicit difficulty, the (broken)
    strength fallback is never even consulted — this must keep working."""
    bootstrap = _bootstrap_with_null_strength()
    fixture_batches = {
        1: [
            {"event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 4, "team_a_difficulty": 2},
        ],
    }
    result = _build_team_fixtures(fixture_batches, bootstrap)
    assert result[1][0]["difficulty"] == 4
    assert result[2][0]["difficulty"] == 2


def test_present_numeric_strength_still_used_normally():
    """Non-regression: a real strength value is still used as before."""
    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS", "strength": 5},
            {"id": 2, "name": "Aston Villa", "short_name": "AVL", "strength": 2},
        ],
    }
    fixture_batches = {
        1: [
            {"event": 1, "team_h": 1, "team_a": 2},
        ],
    }
    result = _build_team_fixtures(fixture_batches, bootstrap)
    # home team's difficulty comes from the AWAY team's strength, and vice versa
    assert result[1][0]["difficulty"] == 2
    assert result[2][0]["difficulty"] == 5


def test_missing_strength_key_entirely_still_falls_back_to_default():
    """Non-regression: the original .get(..., 3) behavior for a genuinely
    absent key (not the explicit-null case) still works."""
    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Aston Villa", "short_name": "AVL"},
        ],
    }
    fixture_batches = {
        1: [
            {"event": 1, "team_h": 1, "team_a": 2},
        ],
    }
    result = _build_team_fixtures(fixture_batches, bootstrap)
    assert result[1][0]["difficulty"] == 3
    assert result[2][0]["difficulty"] == 3


def test_live_bootstrap_is_reweighted_before_context_consumers(monkeypatch):
    """The live path injects strength before resolving or building fixtures."""
    bootstrap = _bootstrap_with_null_strength()
    calls: list[str] = []

    monkeypatch.setattr(context, "get_bootstrap", lambda: bootstrap)
    monkeypatch.setattr(
        context,
        "_inject_walk_forward_team_strength",
        lambda actual: calls.append("strength") or actual is bootstrap,
    )
    monkeypatch.setattr(
        context, "get_current_gameweek", lambda actual: calls.append("gw") or 1
    )
    monkeypatch.setattr(
        context,
        "get_fixtures",
        lambda gameweek: calls.append("fixtures") or [
            {
                "event": gameweek,
                "team_h": 1,
                "team_a": 2,
                "team_h_difficulty": 3,
                "team_a_difficulty": 3,
            }
        ],
    )

    assembled = context.assemble_captain_context()

    assert assembled["bootstrap"] is bootstrap
    assert calls[0] == "strength"
    assert calls.index("strength") < calls.index("gw") < calls.index("fixtures")

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
        lambda actual, fixtures: calls.append("strength") or actual is bootstrap,
    )
    monkeypatch.setattr(context, "get_all_fixtures", lambda: [])
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


def test_all_fixtures_inject_completed_minutes_context_without_network():
    bootstrap = {
        "events": [
            {"id": 1, "is_current": False, "is_next": False, "finished": True},
            {"id": 2, "is_current": True, "is_next": False, "finished": False},
        ],
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS", "strength": 4},
            {"id": 2, "name": "Aston Villa", "short_name": "AVL", "strength": 3},
        ],
    }
    current = [{
        "event": 2,
        "team_h": 1,
        "team_a": 2,
        "finished": False,
        "kickoff_time": "2026-08-22T14:00:00Z",
        "minutes": 0,
    }]
    official = [
        {
            "event": 1,
            "team_h": 1,
            "team_a": 2,
            "finished": True,
            "kickoff_time": "2026-08-15T14:00:00Z",
            "minutes": 90,
        },
        *current,
    ]

    assembled = context.assemble_captain_context(
        bootstrap=bootstrap,
        fixtures=current,
        all_fixtures=official,
    )

    team_rows = assembled["bootstrap"]["team_fixtures"][1]
    assert len(team_rows) == 2
    assert team_rows[0]["finished"] is True
    assert team_rows[0]["minutes"] == 90
    assert all(row["official_fixture_context_complete"] for row in team_rows)
    assert assembled["meta"]["minutes_fixture_source"] == "official_all_fixtures"


# ---------------------------------------------------------------------------
# i150 follow-up: no per-GW fetches when the all-fixtures answer is usable
# ---------------------------------------------------------------------------

def _season_bootstrap() -> dict:
    return {
        "events": [
            {"id": 1, "is_current": False, "is_next": False, "finished": True},
            {"id": 2, "is_current": True, "is_next": False, "finished": False},
            {"id": 3, "is_current": False, "is_next": True, "finished": False},
            {"id": 4, "is_current": False, "is_next": False, "finished": False},
        ],
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS", "strength": 4},
            {"id": 2, "name": "Aston Villa", "short_name": "AVL", "strength": 3},
        ],
    }


def _all_fx() -> list:
    return [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "finished": True,
         "team_h_difficulty": 2, "team_a_difficulty": 4},
        {"id": 2, "event": 2, "team_h": 2, "team_a": 1,
         "team_h_difficulty": 3, "team_a_difficulty": 5},
        {"id": 3, "event": 3, "team_h": 1, "team_a": 2,
         "team_h_difficulty": 2, "team_a_difficulty": 4},
        {"id": 4, "event": 4, "team_h": 2, "team_a": 1,
         "team_h_difficulty": 3, "team_a_difficulty": 3},
    ]


def _wire(monkeypatch, *, all_fixtures_impl):
    """Patch the network edge; return the list recording get_fixtures calls."""
    per_gw_calls: list = []
    monkeypatch.setattr(context, "get_bootstrap", _season_bootstrap)
    monkeypatch.setattr(context, "get_all_fixtures", all_fixtures_impl)
    monkeypatch.setattr(
        context, "_inject_walk_forward_team_strength", lambda b, f: True
    )

    def fake_get_fixtures(gameweek):
        per_gw_calls.append(gameweek)
        return [f for f in _all_fx() if f["event"] == gameweek]

    monkeypatch.setattr(context, "get_fixtures", fake_get_fixtures)
    return per_gw_calls


def test_all_fixtures_ok_makes_no_per_gw_calls(monkeypatch):
    calls = _wire(monkeypatch, all_fixtures_impl=_all_fx)
    out = context.assemble_captain_context()
    assert calls == []
    assert out["gameweek"] == 2
    assert [f["id"] for f in out["fixtures"]] == [2]
    assert out["meta"]["minutes_fixture_source"] == "official_all_fixtures"


def test_all_fixtures_failure_falls_back_to_per_gw_path(monkeypatch):
    def boom():
        raise OSError("fpl down")

    calls = _wire(monkeypatch, all_fixtures_impl=boom)
    out = context.assemble_captain_context()
    assert calls == [2, 3, 4]            # current + remaining, as before
    assert out["meta"]["minutes_fixture_source"] == "unavailable"


def test_empty_all_fixtures_falls_back_to_per_gw_path(monkeypatch):
    calls = _wire(monkeypatch, all_fixtures_impl=lambda: [])
    context.assemble_captain_context()
    assert calls == [2, 3, 4]


def test_both_paths_agree_on_gw_fixtures_and_fdr(monkeypatch):
    _wire(monkeypatch, all_fixtures_impl=_all_fx)
    fast = context.assemble_captain_context()

    def boom():
        raise OSError("x")

    _wire(monkeypatch, all_fixtures_impl=boom)
    slow = context.assemble_captain_context()

    assert fast["gameweek"] == slow["gameweek"]
    assert fast["fixtures"] == slow["fixtures"]
    assert fast["fixture_difficulty_map"] == slow["fixture_difficulty_map"]


def test_season_over_gw_none_does_not_pick_unscheduled_fixtures(monkeypatch):
    """gw is None (all events finished): the shortcut must not match
    fixtures whose ``event`` is None (postponed / unscheduled)."""
    def over():
        b = _season_bootstrap()
        for e in b["events"]:
            e["finished"], e["is_current"], e["is_next"] = True, False, False
        return b

    calls = _wire(monkeypatch, all_fixtures_impl=lambda: _all_fx() + [
        {"id": 9, "event": None, "team_h": 1, "team_a": 2}
    ])
    monkeypatch.setattr(context, "get_bootstrap", over)
    out = context.assemble_captain_context()
    assert out["gameweek"] is None
    assert out["fixtures"] == [] and calls == []


def test_explicit_fixtures_win_over_all_fixtures(monkeypatch):
    _wire(monkeypatch, all_fixtures_impl=_all_fx)
    mine = [{"id": 99, "event": 2, "team_h": 1, "team_a": 2,
             "team_h_difficulty": 2, "team_a_difficulty": 2}]
    out = context.assemble_captain_context(fixtures=mine)
    assert out["fixtures"] == mine

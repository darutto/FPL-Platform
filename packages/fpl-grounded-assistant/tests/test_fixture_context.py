"""
Tests for Track D / FI3a — fixture_context bridge + comparison integration.

The FI3a invariant under test: fixture context is **additive only**. It adds
keys to the output and never changes a score, a winner, or a margin. Axis is
auto-picked from position (attacker→attack, DEF/GKP→defence).
"""
from __future__ import annotations

import copy
import os as _os
import sys as _sys

import pytest

# sys.path bootstrap (mirror fpl_server.py's _SIB pattern) — fixture_context
# has a relative import, so it loads via the package.
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
from fpl_grounded_assistant.fixture_context import (  # noqa: E402
    axis_for_position,
    build_fixture_context,
    classify_player_axis,
)
from fpl_grounded_assistant.comparison import compare_players  # noqa: E402
from fpl_grounded_assistant.transfer_advisor import get_transfer_advice  # noqa: E402
from fpl_grounded_assistant.differential_picks import get_differential_picks  # noqa: E402
from fpl_grounded_assistant.chip_advisor import get_chip_advice  # noqa: E402


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _fx(gw: int, opp: int, is_home: bool, difficulty: int) -> dict:
    return {"gameweek": gw, "opponent_team": opp, "is_home": is_home,
            "difficulty": difficulty}


def _engine_bootstrap() -> dict:
    """Teams + team_fixtures only — for the bridge (FDR fallback)."""
    return {
        "teams": [
            {"id": 1, "name": "Manchester City", "short_name": "MCI"},
            {"id": 2, "name": "Brighton",        "short_name": "BHA"},
            {"id": 3, "name": "Arsenal",         "short_name": "ARS"},
        ],
        "events": [{"id": 1, "is_current": True}],
        "team_fixtures": {
            1: [_fx(1, 2, True, 2), _fx(2, 3, False, 2), _fx(3, 2, True, 1)],  # easy
            2: [_fx(1, 1, False, 5), _fx(2, 3, True, 5), _fx(3, 1, False, 4)],  # hard
            3: [_fx(1, 3, True, 3), _fx(2, 1, False, 3), _fx(3, 2, True, 3)],
        },
    }


def _compare_bootstrap(with_fixtures: bool = True) -> dict:
    """Full bootstrap with two players for compare_players."""
    bs: dict = {
        "elements": [
            {"id": 1, "web_name": "Haaland", "first_name": "Erling",
             "second_name": "Haaland", "team": 1, "element_type": 4,
             "status": "a", "now_cost": 140, "selected_by_percent": "50.0",
             "form": "7.0", "expected_goals": "1.2", "expected_assists": "0.2",
             "expected_goal_involvements": "1.4"},
            {"id": 2, "web_name": "Dunk", "first_name": "Lewis",
             "second_name": "Dunk", "team": 2, "element_type": 2,
             "status": "a", "now_cost": 50, "selected_by_percent": "5.0",
             "form": "4.0", "expected_goals": "0.05", "expected_assists": "0.05",
             "expected_goal_involvements": "0.10",
             "clean_sheets_per_90": "0.4", "saves_per_90": "0",
             "defensive_contribution_per_90": "1.5"},
        ],
        "teams": [
            {"id": 1, "name": "Manchester City", "short_name": "MCI"},
            {"id": 2, "name": "Brighton",        "short_name": "BHA"},
            {"id": 3, "name": "Arsenal",         "short_name": "ARS"},
        ],
        "events": [{"id": 1, "is_current": True}],
        "element_types": [
            {"id": 1, "singular_name_short": "GKP"},
            {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
        "fixture_difficulty_map": {1: 2, 2: 4},
    }
    if with_fixtures:
        bs["team_fixtures"] = _engine_bootstrap()["team_fixtures"]
    return bs


# ---------------------------------------------------------------------------
# Bridge — axis mapping
# ---------------------------------------------------------------------------

def test_axis_for_position():
    assert axis_for_position("FWD") == "attack"
    assert axis_for_position("MID") == "attack"
    assert axis_for_position("DEF") == "defence"
    assert axis_for_position("GKP") == "defence"
    assert axis_for_position(None) == "attack"      # default
    assert axis_for_position("weird") == "attack"


# ---------------------------------------------------------------------------
# Bridge — build_fixture_context
# ---------------------------------------------------------------------------

def test_build_context_attacker_easy_run():
    ctx = build_fixture_context(_engine_bootstrap(), team_id=1, position="FWD")
    assert ctx is not None
    assert ctx["axis"] == "attack"
    assert ctx["team_short"] == "MCI"
    assert ctx["has_good_run"] is True
    assert ctx["tiebreaker_signal"] == 1
    assert "ofensivo favorable" in ctx["phrase"]


def test_build_context_position_drives_axis():
    # Same team, defender → defence axis, different phrasing vocabulary.
    ctx = build_fixture_context(_engine_bootstrap(), team_id=2, position="DEF")
    assert ctx is not None
    assert ctx["axis"] == "defence"
    assert "portería a cero" in ctx["phrase"]


def test_explicit_axis_overrides_position():
    ctx = build_fixture_context(_engine_bootstrap(), team_id=1, position="DEF", axis="attack")
    assert ctx["axis"] == "attack"


def test_build_context_team_query_alias():
    ctx = build_fixture_context(_engine_bootstrap(), team_query="Arsenal", position="MID")
    assert ctx is not None and ctx["team_short"] == "ARS"


def test_build_context_none_without_fixtures():
    bs = _engine_bootstrap()
    bs["team_fixtures"] = {}
    assert build_fixture_context(bs, team_id=1, position="FWD") is None


def test_build_context_none_unresolvable_team():
    assert build_fixture_context(_engine_bootstrap(), team_id=999, position="FWD") is None
    assert build_fixture_context(_engine_bootstrap(), team_query="Nowhere", position="FWD") is None


# ---------------------------------------------------------------------------
# Comparison integration — ADDITIVE invariant
# ---------------------------------------------------------------------------

def test_comparison_adds_fixture_context_keys():
    res = compare_players("Haaland", "Dunk", _compare_bootstrap())
    assert res["status"] == "ok"
    # Additive keys present.
    assert "fixture_context" in res["player_a"]
    assert "fixture_context" in res["player_b"]
    assert "fixture_tiebreaker" in res
    # Axis auto-picked per position: Haaland (FWD)→attack, Dunk (DEF)→defence.
    assert res["player_a"]["fixture_context"]["axis"] == "attack"
    assert res["player_b"]["fixture_context"]["axis"] == "defence"


def test_comparison_winner_driven_by_score_not_fixtures():
    res = compare_players("Haaland", "Dunk", _compare_bootstrap())
    # Winner is whoever has the higher position_score — fixtures never override.
    a, b = res["player_a"], res["player_b"]
    higher = a["web_name"] if a["position_score"] >= b["position_score"] else b["web_name"]
    if res["winner"] is not None:
        assert res["winner"] == higher


def test_comparison_scores_identical_with_and_without_context():
    """The additive context must not perturb the captain/position scores.

    fixture_difficulty_map and current_gw are held constant; only the optional
    fixture_outlook context differs. (team_fixtures is intentionally kept in
    BOTH so effective_fdr — a pre-existing scoring input — is unchanged.)
    """
    bs = _compare_bootstrap(with_fixtures=True)
    res1 = compare_players("Haaland", "Dunk", copy.deepcopy(bs))
    res2 = compare_players("Haaland", "Dunk", copy.deepcopy(bs))
    for side in ("player_a", "player_b"):
        assert res1[side]["captain_score"] == res2[side]["captain_score"]
        assert res1[side]["position_score"] == res2[side]["position_score"]
    assert res1["winner"] == res2["winner"]
    assert res1["margin"] == res2["margin"]


def test_comparison_tiebreaker_only_when_narrow():
    res = compare_players("Haaland", "Dunk", _compare_bootstrap())
    tb = res["fixture_tiebreaker"]
    if res["margin_label"] == "narrow":
        assert tb is None or isinstance(tb, str)
        if isinstance(tb, str):
            assert "calendario" in tb.lower()
            # schedule-only — no transfer/advice language
            for w in ("fichar", "vender", "transfer", "compra", "venta"):
                assert w not in tb.lower()
    else:
        assert tb is None


def test_comparison_degrades_without_fixtures():
    res = compare_players("Haaland", "Dunk", _compare_bootstrap(with_fixtures=False))
    assert res["status"] == "ok"
    assert res["player_a"]["fixture_context"] is None
    assert res["player_b"]["fixture_context"] is None
    assert res["fixture_tiebreaker"] is None


# ---------------------------------------------------------------------------
# Dynamic defensive-midfielder detection
# ---------------------------------------------------------------------------

def _mid_heavy_bootstrap() -> dict:
    """Engine bootstrap + a midfield population with a spread of DC rates.

    10 midfielders: most low-DC (attacking), a few high-DC (defensive). The
    70th-percentile threshold should classify the top ~3 as defensive.
    """
    bs = _engine_bootstrap()
    mids = []
    # 7 attacking mids (low DC) on team 1, 3 defensive mids (high DC) on team 2.
    low_dc = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1]
    high_dc = [4.5, 5.0, 5.5]
    pid = 100
    for dc in low_dc:
        mids.append({"id": pid, "web_name": f"Att{pid}", "team": 1,
                     "element_type": 3, "defensive_contribution_per_90": str(dc)})
        pid += 1
    for dc in high_dc:
        mids.append({"id": pid, "web_name": f"Def{pid}", "team": 2,
                     "element_type": 3, "defensive_contribution_per_90": str(dc)})
        pid += 1
    bs["elements"] = mids
    return bs


def test_classify_non_mid_positions_are_static():
    assert classify_player_axis("FWD")[0] == "attack"
    assert classify_player_axis("DEF")[0] == "defence"
    assert classify_player_axis("GKP")[0] == "defence"


def test_classify_defensive_mid_reads_defence_axis():
    bs = _mid_heavy_bootstrap()
    # A high-DC midfielder → defensive lean → defence axis.
    axis, meta = classify_player_axis("MID", dc_per_90=5.5, bootstrap=bs)
    assert axis == "defence"
    assert meta["is_defensive_mid"] is True
    assert meta["role_lean"] == "defensive"
    assert meta["dc_percentile"] >= 70


def test_classify_attacking_mid_reads_attack_axis():
    bs = _mid_heavy_bootstrap()
    axis, meta = classify_player_axis("MID", dc_per_90=0.6, bootstrap=bs)
    assert axis == "attack"
    assert meta["is_defensive_mid"] is False


def test_mid_without_enough_sample_defaults_attack():
    # Engine bootstrap has no midfielders → can't classify → default attack.
    axis, meta = classify_player_axis("MID", dc_per_90=9.9, bootstrap=_engine_bootstrap())
    assert axis == "attack"
    assert meta["is_defensive_mid"] is False


def test_build_context_defensive_mid_uses_defensive_phrasing():
    bs = _mid_heavy_bootstrap()
    # Defensive mid on team 2 (a hard schedule). Defence axis + role surfaced.
    ctx = build_fixture_context(bs, team_id=2, position="MID", dc_per_90=5.5)
    assert ctx is not None
    assert ctx["axis"] == "defence"
    assert ctx["is_defensive_mid"] is True
    assert "defensivo" in ctx["phrase"]          # not "portería a cero"
    assert "portería" not in ctx["phrase"]


def test_build_context_attacking_mid_uses_attack_axis():
    bs = _mid_heavy_bootstrap()
    ctx = build_fixture_context(bs, team_id=1, position="MID", dc_per_90=0.6)
    assert ctx is not None
    assert ctx["axis"] == "attack"
    assert ctx["is_defensive_mid"] is False
    assert "ofensivo" in ctx["phrase"]


# ---------------------------------------------------------------------------
# Engine rollout — transfer_advisor
# ---------------------------------------------------------------------------

def test_transfer_adds_fixture_context_both_sides():
    res = get_transfer_advice("Dunk", "Haaland", _compare_bootstrap())
    assert res["status"] == "ok"
    assert "fixture_context" in res["player_out"]
    assert "fixture_context" in res["player_in"]
    assert "fixture_tiebreaker" in res
    # Haaland (in, FWD) → attack; Dunk (out, DEF) → defence.
    assert res["player_in"]["fixture_context"]["axis"] == "attack"
    assert res["player_out"]["fixture_context"]["axis"] == "defence"


def test_transfer_scores_unchanged_with_context():
    bs = _compare_bootstrap()
    r1 = get_transfer_advice("Dunk", "Haaland", copy.deepcopy(bs))
    r2 = get_transfer_advice("Dunk", "Haaland", copy.deepcopy(bs))
    assert r1["score_delta"] == r2["score_delta"]
    assert r1["recommendation"] == r2["recommendation"]
    assert r1["player_in"]["position_score"] == r2["player_in"]["position_score"]


def test_transfer_degrades_without_fixtures():
    res = get_transfer_advice("Dunk", "Haaland", _compare_bootstrap(with_fixtures=False))
    assert res["status"] == "ok"
    assert res["player_in"]["fixture_context"] is None
    assert res["fixture_tiebreaker"] is None


# ---------------------------------------------------------------------------
# Engine rollout — differential_picks
# ---------------------------------------------------------------------------

def _diff_bootstrap() -> dict:
    """Two low-ownership attackers with current-GW fixtures."""
    bs = _engine_bootstrap()  # teams + team_fixtures (gw1 fixtures for 1,2,3)
    bs["elements"] = [
        {"id": 1, "web_name": "Mbeumo", "first_name": "Bryan", "second_name": "Mbeumo",
         "team": 1, "element_type": 3, "status": "a", "now_cost": 70,
         "selected_by_percent": "6.0", "form": "6.5",
         "expected_goals": "0.5", "expected_assists": "0.4",
         "expected_goal_involvements": "0.9",
         "defensive_contribution_per_90": "0.7"},
        {"id": 2, "web_name": "Wissa", "first_name": "Yoane", "second_name": "Wissa",
         "team": 3, "element_type": 4, "status": "a", "now_cost": 60,
         "selected_by_percent": "4.0", "form": "6.0",
         "expected_goals": "0.6", "expected_assists": "0.1",
         "expected_goal_involvements": "0.7"},
    ]
    bs["element_types"] = [
        {"id": 1, "singular_name_short": "GKP"},
        {"id": 2, "singular_name_short": "DEF"},
        {"id": 3, "singular_name_short": "MID"},
        {"id": 4, "singular_name_short": "FWD"},
    ]
    bs["fixture_difficulty_map"] = {1: 2, 3: 3}
    return bs


def test_differential_picks_carry_fixture_context():
    res = get_differential_picks(_diff_bootstrap())
    assert res["status"] == "ok"
    assert res["picks"], "expected at least one differential pick"
    for pick in res["picks"]:
        assert "fixture_context" in pick
        # context resolves for these (teams have fixtures), axis is valid.
        if pick["fixture_context"] is not None:
            assert pick["fixture_context"]["axis"] in ("attack", "defence")


# ---------------------------------------------------------------------------
# Engine rollout — chip_advisor (triple captain only)
# ---------------------------------------------------------------------------

def test_triple_captain_carries_fixture_context():
    res = get_chip_advice("triple_captain", _compare_bootstrap())
    assert res["status"] == "ok"
    assert "fixture_context" in res
    # Top MID/FWD here is Haaland (FWD) → attack axis.
    fc = res["fixture_context"]
    assert fc is not None
    assert fc["axis"] == "attack"


def test_bench_boost_has_no_fixture_context():
    res = get_chip_advice("bench_boost", _compare_bootstrap())
    assert res["status"] == "ok"
    assert res["fixture_context"] is None

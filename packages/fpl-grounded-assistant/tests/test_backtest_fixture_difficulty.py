"""
tests/test_backtest_fixture_difficulty.py
==========================================
Unit tests for the ML0 evaluation harness's load-bearing pieces:
  * build_team_fixture_outcomes — the xG aggregation + transfer-proof team
    attribution (the one place a silent join bug would poison everything);
  * the metric helpers (spearman, skill_correlation sign convention,
    band_spread orientation).

The model comparison itself is analysis (run the script), not asserted here.
"""
from __future__ import annotations

import importlib.util as _ilu
import os as _os

import pandas as pd
import pytest

# Load the harness script from its file. Its top-level runs the engine load +
# adds fpl-historical to sys.path, so rolling_strength imports cleanly even
# though pytest.ini doesn't list that sibling.
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_MOD_PATH = _os.path.join(
    _os.path.dirname(_HERE), "scripts", "backtest_fixture_difficulty.py"
)
_spec = _ilu.spec_from_file_location("backtest_fixture_difficulty", _MOD_PATH)
bt = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(bt)


def _synthetic_one_match():
    """Team 1 (home) beat team 2 (away) 2-1; team 1 out-xG'd them 2.0 to 0.9."""
    fixtures = pd.DataFrame([{
        "event_id": 1, "fixture_id": 1, "team_h": 1, "team_a": 2,
        "team_h_score": 2, "team_a_score": 1,
        "team_h_difficulty": 3, "team_a_difficulty": 4,
    }])
    gw = pd.DataFrame([
        # team 1 players (home, facing team 2)
        {"player_id": 10, "event_id": 1, "opponent_team": 2, "was_home": True, "expected_goals": "1.50"},
        {"player_id": 11, "event_id": 1, "opponent_team": 2, "was_home": True, "expected_goals": "0.50"},
        # team 2 players (away, facing team 1)
        {"player_id": 20, "event_id": 1, "opponent_team": 1, "was_home": False, "expected_goals": "0.90"},
    ])
    return gw, fixtures


class TestBuildOutcomes:
    def test_xg_and_goals_attributed_to_the_right_team(self):
        gw, fixtures = _synthetic_one_match()
        out = bt.build_team_fixture_outcomes(gw, fixtures)
        assert len(out) == 2
        t1 = out[out["team_id"] == 1].iloc[0]
        t2 = out[out["team_id"] == 2].iloc[0]

        assert t1["xg_for"] == pytest.approx(2.0)
        assert t1["xg_against"] == pytest.approx(0.9)
        assert t1["goals_for"] == 2 and t1["goals_against"] == 1
        assert bool(t1["was_home"]) is True

        assert t2["xg_for"] == pytest.approx(0.9)
        assert t2["xg_against"] == pytest.approx(2.0)
        assert t2["goals_for"] == 1 and t2["goals_against"] == 2
        assert bool(t2["was_home"]) is False

    def test_attribution_is_by_match_facts_not_roster(self):
        """A player whose parquet roster team is wrong for this GW (mid-season
        transfer) must still land on the team he actually PLAYED for. The
        function never reads a roster — it keys on (opponent_team, was_home) —
        so adding a 'moved' player to team 1's side lifts team 1's xG."""
        gw, fixtures = _synthetic_one_match()
        # This player later transfers to team 99, but in GW1 he played for
        # team 1 (home vs team 2). No roster/team column is consulted.
        gw = pd.concat([gw, pd.DataFrame([{
            "player_id": 12, "event_id": 1, "opponent_team": 2,
            "was_home": True, "expected_goals": "1.00",
        }])], ignore_index=True)
        out = bt.build_team_fixture_outcomes(gw, fixtures)
        t1 = out[out["team_id"] == 1].iloc[0]
        assert t1["xg_for"] == pytest.approx(3.0)  # 1.5 + 0.5 + 1.0


class TestMetrics:
    def test_spearman_perfect_and_inverse(self):
        assert bt.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
        assert bt.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)

    def test_spearman_handles_ties_without_crashing(self):
        assert -1.0 <= bt.spearman([1, 1, 2, 2], [5, 6, 5, 6]) <= 1.0

    def test_skill_correlation_positive_when_bands_track_outcomes(self):
        # Attack: EASY band (1) -> HIGH xg_for; HARD band (5) -> LOW. A correct
        # model should score POSITIVE skill despite the raw corr being negative.
        df = pd.DataFrame({
            "attack_band": [1, 2, 4, 5],
            "xg_for": [2.5, 2.0, 1.0, 0.5],
        })
        assert bt.skill_correlation(df, "attack") > 0.9

        # Defence: EASY band (1) -> LOW xg_against; correct model POSITIVE skill.
        dfd = pd.DataFrame({
            "defence_band": [1, 2, 4, 5],
            "xg_against": [0.5, 1.0, 2.0, 2.5],
        })
        assert bt.skill_correlation(dfd, "defence") > 0.9

    def test_absolute_thresholds_are_equal_width_over_the_range(self):
        # 5 teams spanning attack strengths 1000..1400 (home) / same away.
        boot = {"teams": [
            {"id": i + 1,
             "strength_attack_home": 1000 + i * 100,
             "strength_attack_away": 1000 + i * 100,
             "strength_defence_home": 1000 + i * 100,
             "strength_defence_away": 1000 + i * 100}
            for i in range(5)
        ]}
        cuts = bt._absolute_axis_thresholds(boot, "attack")
        assert cuts == sorted(cuts)  # increasing
        assert len(cuts) == 4
        # Equal-width over [1000, 1400]: cuts at 1080/1160/1240/1320.
        assert cuts == pytest.approx([1080.0, 1160.0, 1240.0, 1320.0])

    def test_band_spread_orientation(self):
        # Attack spread positive when band 1 out-xGs band 5.
        df = pd.DataFrame({
            "attack_band": [1, 1, 5, 5],
            "xg_for": [2.4, 2.6, 0.4, 0.6],
            "goals_for": [2, 3, 0, 1],
        })
        assert bt.band_spread(df, "attack") == pytest.approx(2.0)

        # Defence spread positive when band 5 concedes more than band 1.
        dfd = pd.DataFrame({
            "defence_band": [1, 1, 5, 5],
            "xg_against": [0.4, 0.6, 2.4, 2.6],
            "goals_against": [0, 1, 2, 3],
        })
        assert bt.band_spread(dfd, "defence") == pytest.approx(2.0)

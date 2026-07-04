"""
tests/test_rolling_strength.py
===============================
Tests for fpl_historical.rolling_strength (Track D Step 2).

Synthetic-data tests use injected DataFrames (_teams_df/_fixtures_df) so they
don't depend on real captured data. One sanity test runs against the real
2025-2026 season to confirm the GW1 degenerate case (no matches played yet)
exactly preserves FPL's own captured rank order.
"""
from __future__ import annotations

import pandas as pd
import pytest

from fpl_historical.rolling_strength import (
    DEFAULT_HALF_LIFE_GWS,
    STRENGTH_FIELDS,
    _decay_weight,
    _percentile_rank,
    compute_rolling_strength,
)


def test_decay_weight_halves_at_the_half_life():
    assert _decay_weight(0, 5.0) == pytest.approx(1.0)
    assert _decay_weight(5.0, 5.0) == pytest.approx(0.5)
    assert _decay_weight(10.0, 5.0) == pytest.approx(0.25)


def test_decay_weight_monotonically_decreasing():
    weights = [_decay_weight(g, DEFAULT_HALF_LIFE_GWS) for g in range(0, 20)]
    assert weights == sorted(weights, reverse=True)


def test_decay_weight_rejects_future_matches():
    # A negative gw_ago would mean "the match hasn't happened yet" — no
    # lookahead allowed.
    assert _decay_weight(-1, 5.0) == 0.0


def test_percentile_rank_orders_low_to_high():
    ranks = _percentile_rank({1: 10.0, 2: 30.0, 3: 20.0})
    assert ranks[1] == 0.0
    assert ranks[3] == 0.5
    assert ranks[2] == 1.0


def test_percentile_rank_single_value():
    assert _percentile_rank({1: 999.0}) == {1: 0.5}


def _synthetic_teams(n: int = 6) -> pd.DataFrame:
    """n teams, fallback strength spread out so rank order is unambiguous."""
    rows = []
    for i in range(n):
        row = {"team_id": i + 1}
        for f in STRENGTH_FIELDS:
            row[f] = 1000 + i * 50  # team 1 weakest fallback, team n strongest
        rows.append(row)
    return pd.DataFrame(rows)


def _fixture_row(gw, home_id, away_id, home_score, away_score):
    return {
        "event_id": gw,
        "team_h": home_id,
        "team_a": away_id,
        "team_h_score": home_score,
        "team_a_score": away_score,
    }


class TestColdStart:
    def test_as_of_gw1_has_no_matches_and_exactly_preserves_fallback_rank(self):
        """At GW1 (no matches played), the model must reduce to pure fallback:
        blended rank == fallback rank exactly, for every team and field."""
        teams = _synthetic_teams(6)
        fixtures = pd.DataFrame(
            [_fixture_row(1, 1, 2, 1, 1), _fixture_row(1, 3, 4, 2, 0)]
        )
        result = compute_rolling_strength(
            "synthetic", 1, _teams_df=teams, _fixtures_df=fixtures
        )
        # Team 6 has the highest fallback strength on every field; team 1 the
        # lowest. With zero prior matches, that same order must hold exactly.
        for field in STRENGTH_FIELDS:
            assert result[6][field] > result[3][field] > result[1][field]

    def test_team_with_zero_own_matches_gets_pure_fallback_even_mid_season(self):
        """A team that hasn't played yet (blank fixture list) at some GW
        should fall back cleanly rather than error or rank as 0."""
        teams = _synthetic_teams(6)
        # Teams 1-5 have played several matches by GW6; team 6 has none.
        rows = []
        for gw in range(1, 6):
            rows.append(_fixture_row(gw, 1, 2, 2, 0))
            rows.append(_fixture_row(gw, 3, 4, 1, 1))
            rows.append(_fixture_row(gw, 5, 1, 0, 3))
        fixtures = pd.DataFrame(rows)
        result = compute_rolling_strength(
            "synthetic", 6, _teams_df=teams, _fixtures_df=fixtures
        )
        # Team 6 never played — its value must come from fallback rank alone,
        # i.e. sit exactly where its fallback percentile places it (team 6 is
        # the strongest fallback team, so it should score highest of all).
        assert result[6]["strength_attack_home"] == max(
            result[t]["strength_attack_home"] for t in range(1, 7)
        )


class TestConvergence:
    def test_more_own_matches_shifts_result_toward_own_signal(self):
        """A weak-fallback team that has actually been scoring heavily at
        home should see its strength_attack_home value RISE as more of its
        own (strong) matches accumulate, versus its GW1 (pure-fallback) value.

        Venues rotate every GW (real seasons alternate home/away) so all 6
        teams accumulate home-venue observations quickly enough to clear
        _MIN_TEAMS_FOR_OWN_RANK — a fixed one-sided venue assignment would
        leave only half the teams with any "home" data at all.
        """
        teams = _synthetic_teams(6)  # team 1 has the WEAKEST fallback
        rows = []
        for gw in range(1, 6):
            if gw % 2 == 1:
                # Team 1 smashes 4 goals at home every home game — a strong
                # own signal despite a weak fallback rating.
                rows.append(_fixture_row(gw, 1, 2, 4, 0))
                rows.append(_fixture_row(gw, 3, 4, 1, 1))
                rows.append(_fixture_row(gw, 5, 6, 1, 0))
            else:
                rows.append(_fixture_row(gw, 2, 1, 0, 0))
                rows.append(_fixture_row(gw, 4, 3, 1, 1))
                rows.append(_fixture_row(gw, 6, 5, 0, 1))
        fixtures = pd.DataFrame(rows)

        gw1 = compute_rolling_strength("synthetic", 1, _teams_df=teams, _fixtures_df=fixtures)
        gw6 = compute_rolling_strength("synthetic", 6, _teams_df=teams, _fixtures_df=fixtures)

        assert gw6[1]["strength_attack_home"] > gw1[1]["strength_attack_home"]


class TestDefenceSign:
    def test_fewer_conceded_gives_higher_strength_defence(self):
        """strength_defence must follow FPL's convention: high = GOOD defence
        (concedes FEW). Regression guard for the sign bug where the own signal
        (rank by goals conceded) fought the FPL fallback and blended to noise.

        Team 1 keeps clean sheets at home; team 3 ships 3 at home — and team 1
        has the WEAKER fallback (harder test: the correctly-signed own signal
        must overcome the fallback). Venues rotate so all 6 teams clear
        _MIN_TEAMS_FOR_OWN_RANK; a low prior_weight lets own data dominate.
        """
        teams = _synthetic_teams(6)  # team 1 has the weakest fallback defence
        rows = []
        for gw in range(1, 11):
            if gw % 2 == 1:
                rows.append(_fixture_row(gw, 1, 2, 1, 0))  # team 1 home clean sheet
                rows.append(_fixture_row(gw, 3, 4, 1, 3))  # team 3 home ships 3
                rows.append(_fixture_row(gw, 5, 6, 1, 1))
            else:
                rows.append(_fixture_row(gw, 2, 1, 1, 1))
                rows.append(_fixture_row(gw, 4, 3, 1, 1))
                rows.append(_fixture_row(gw, 6, 5, 1, 1))
        fixtures = pd.DataFrame(rows)
        res = compute_rolling_strength(
            "synthetic", 11, prior_weight=0.5, _teams_df=teams, _fixtures_df=fixtures
        )
        assert res[1]["strength_defence_home"] > res[3]["strength_defence_home"]


class TestRealSeasonSanity:
    def test_real_2025_26_gw1_preserves_fpl_fallback_rank_order(self):
        """No lookahead + no matches played yet at GW1 => the model's output
        rank order must exactly match FPL's own captured strength values."""
        result = compute_rolling_strength("2025-2026", 1)
        assert len(result) == 20
        # Spot-check: whichever team FPL rated highest for strength_attack_home
        # must also be ranked highest by the (pure-fallback) model output.
        from fpl_historical.paths import merged_parquet_dir

        teams_df = pd.read_parquet(merged_parquet_dir("2025-2026") / "teams.parquet")
        # kind="mergesort" for a stable sort — several teams tie on raw
        # strength (e.g. 1090, 1120, 1130), and pandas' default quicksort
        # isn't stable, so an unqualified sort_values() would tie-break
        # differently than our function's stable sorted() for no meaningful
        # reason. Match sort algorithms to compare on value order, not
        # incidental tie-break order.
        fpl_order = teams_df.sort_values("strength_attack_home", kind="mergesort")["team_id"].tolist()
        model_order = sorted(result.keys(), key=lambda tid: result[tid]["strength_attack_home"])
        assert model_order == fpl_order

    def test_real_2025_26_all_fields_present_and_positive(self):
        result = compute_rolling_strength("2025-2026", 8)
        assert len(result) == 20
        for team_id, fields in result.items():
            for f in STRENGTH_FIELDS:
                assert fields[f] > 0

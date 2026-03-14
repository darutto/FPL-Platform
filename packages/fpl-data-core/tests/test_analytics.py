"""
Tests for fpl_data_core.analytics

Covers TEST_PLAN.md §1.6 — compute_rolling_xgi_per_90 (promoted from placeholder).

Run from fpl-data-core/:
    pytest tests/test_analytics.py -v
"""

import pytest
import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _df(*rows):
    """Build a minimal playermatchstats DataFrame from (player_id, xg, xa, mins) tuples."""
    return pd.DataFrame(rows, columns=["player_id", "xg", "xa", "minutes_played"])


# ---------------------------------------------------------------------------
# Smoke / import
# ---------------------------------------------------------------------------

class TestAnalyticsImport:

    def test_compute_rolling_xgi_per_90_is_callable(self):
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        assert callable(compute_rolling_xgi_per_90)

    def test_importable_from_package_root(self):
        from fpl_data_core import compute_rolling_xgi_per_90
        assert callable(compute_rolling_xgi_per_90)


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------

class TestComputeRollingXgiPer90:

    def test_returns_zero_for_unknown_player(self):
        """Player not present in the DataFrame → 0.0."""
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        df = _df((1, 0.5, 0.3, 90))
        result = compute_rolling_xgi_per_90(df, player_id=999)
        assert result == 0.0

    def test_returns_zero_for_empty_dataframe(self):
        """Empty DataFrame → 0.0 (no crash)."""
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        df = pd.DataFrame(columns=["player_id", "xg", "xa", "minutes_played"])
        result = compute_rolling_xgi_per_90(df, player_id=1)
        assert result == 0.0

    def test_returns_zero_for_zero_minutes(self):
        """Player has data but played 0 minutes → 0.0 (no division by zero)."""
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        df = _df((1, 1.0, 0.5, 0), (1, 0.5, 0.3, 0))
        result = compute_rolling_xgi_per_90(df, player_id=1)
        assert result == 0.0

    def test_correct_xgi_per_90_single_match(self):
        """One match: xg=0.9, xa=0.0, minutes=90 → xgi/90 = 0.9."""
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        df = _df((1, 0.9, 0.0, 90))
        result = compute_rolling_xgi_per_90(df, player_id=1)
        assert abs(result - 0.9) < 1e-10

    def test_correct_xgi_per_90_three_match_lookback(self):
        """
        3 matches: each xg=0.5, xa=0.3, minutes=90.
        total_xg = 1.5, total_xa = 0.9, total_mins = 270
        xgi/90 = (1.5 + 0.9) / 270 * 90 = 2.4 / 3 = 0.8
        """
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        df = _df(
            (1, 0.5, 0.3, 90),
            (1, 0.5, 0.3, 90),
            (1, 0.5, 0.3, 90),
        )
        result = compute_rolling_xgi_per_90(df, player_id=1)
        assert abs(result - 0.8) < 1e-10

    def test_lookback_truncation_uses_last_n_rows_only(self):
        """
        5 rows in df, lookback=3. Only the last 3 should be used.
        Row layout: player 1 has rows [0.0 xg, ...] × 2 then [1.0 xg, ...] × 3.
        If only last 3 rows are used → xg/90 = (3.0+0.0)/270*90 = 1.0.
        If all 5 rows are used      → xg/90 = (3.0+0.0)/450*90 = 0.6.
        """
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        df = _df(
            (1, 0.0, 0.0, 90),   # old match (should be excluded)
            (1, 0.0, 0.0, 90),   # old match (should be excluded)
            (1, 1.0, 0.0, 90),   # recent
            (1, 1.0, 0.0, 90),   # recent
            (1, 1.0, 0.0, 90),   # recent
        )
        result = compute_rolling_xgi_per_90(df, player_id=1, lookback=3)
        assert abs(result - 1.0) < 1e-10, (
            f"Expected 1.0 (last 3 only), got {result} — lookback not respected"
        )

    def test_lookback_one_uses_only_most_recent_match(self):
        """lookback=1 uses only the most recent row."""
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        df = _df(
            (1, 0.0, 0.0, 90),   # old (excluded)
            (1, 1.8, 0.0, 90),   # most recent → xgi/90 = 1.8
        )
        result = compute_rolling_xgi_per_90(df, player_id=1, lookback=1)
        assert abs(result - 1.8) < 1e-10

    def test_result_is_float(self):
        """Return type is always float."""
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        df = _df((1, 0.5, 0.5, 90))
        result = compute_rolling_xgi_per_90(df, player_id=1)
        assert isinstance(result, float)

    def test_does_not_modify_input_dataframe(self):
        """The function must not mutate the input DataFrame."""
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        df = _df((1, 0.5, 0.3, 90))
        original_shape = df.shape
        original_values = df.copy()
        compute_rolling_xgi_per_90(df, player_id=1)
        assert df.shape == original_shape
        pd.testing.assert_frame_equal(df, original_values)

    def test_multiple_players_isolated(self):
        """Stats for player 1 are not contaminated by player 2's rows."""
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        df = _df(
            (1, 1.0, 0.0, 90),
            (2, 0.0, 0.0, 90),   # different player, xg=0
            (2, 0.0, 0.0, 90),
        )
        p1 = compute_rolling_xgi_per_90(df, player_id=1)
        p2 = compute_rolling_xgi_per_90(df, player_id=2)
        assert abs(p1 - 1.0) < 1e-10
        assert p2 == 0.0

    def test_lookback_larger_than_available_rows_uses_all(self):
        """lookback=10 with only 2 rows → all 2 rows are used (tail behaviour)."""
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        df = _df(
            (1, 0.9, 0.0, 90),
            (1, 0.9, 0.0, 90),
        )
        # total_xg=1.8, total_xa=0, total_mins=180 → 1.8/180*90 = 0.9
        result = compute_rolling_xgi_per_90(df, player_id=1, lookback=10)
        assert abs(result - 0.9) < 1e-10

    def test_xgi_per_90_with_partial_minutes(self):
        """
        Substituted-on player: 2 matches of 45 minutes each.
        xg=0.3+0.3=0.6, xa=0.0, minutes=90 → xgi/90 = 0.6/90*90 = 0.6
        """
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        df = _df(
            (1, 0.3, 0.0, 45),
            (1, 0.3, 0.0, 45),
        )
        result = compute_rolling_xgi_per_90(df, player_id=1)
        assert abs(result - 0.6) < 1e-10

    def test_fixture_from_conftest(self, minimal_playermatchstats_df):
        """
        Conftest fixture:
        Player 1: 3 rows × (xg=0.5, xa=0.3, mins=90)
        Expected: (1.5+0.9)/270*90 = 2.4/3 = 0.8
        """
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        result = compute_rolling_xgi_per_90(
            minimal_playermatchstats_df, player_id=1, lookback=3
        )
        assert abs(result - 0.8) < 1e-10

    def test_default_lookback_is_three(self, minimal_playermatchstats_df):
        """Calling without lookback arg should use 3 (default)."""
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        with_default = compute_rolling_xgi_per_90(minimal_playermatchstats_df, player_id=1)
        with_explicit = compute_rolling_xgi_per_90(minimal_playermatchstats_df, player_id=1, lookback=3)
        assert with_default == with_explicit


# ---------------------------------------------------------------------------
# Parity with TypeScript performanceEnricher
# ---------------------------------------------------------------------------

class TestAnalyticsParityWithTypeScript:
    """
    Cross-language parity: Python output must match the TypeScript
    performanceEnricher.ts::buildAggMap rolling aggregation logic.

    Reference values come from the dataEngine.epicA.test.ts stdout output
    (captured in POST_PHASE0_REPORT.md), which shows Haaland's xGI/90 = 1.74
    for GW1 2025-2026 over a 3-match lookback.

    These parity tests use synthetic data with known outputs to validate the
    formula independently of real data.
    """

    def test_formula_matches_ts_for_high_volume_striker(self):
        """
        Haaland-like: 3 matches, total xg+xa=5.22, total_mins=270
        → xgi/90 = 5.22/270*90 = 1.74
        This matches the printed GW1 table output: Haaland xGI/90='1.74'
        """
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        # total_xg=4.5, total_xa=0.72, total_mins=270 → (5.22)/270*90 = 1.74
        df = _df(
            (1, 1.50, 0.24, 90),
            (1, 1.50, 0.24, 90),
            (1, 1.50, 0.24, 90),
        )
        result = compute_rolling_xgi_per_90(df, player_id=1)
        assert abs(result - 1.74) < 1e-10

    def test_formula_matches_ts_for_moderate_midfielder(self):
        """
        Mid-tier player: 3 matches, total xg+xa=1.26, total_mins=270
        → xgi/90 = 1.26/270*90 = 0.42
        """
        from fpl_data_core.analytics import compute_rolling_xgi_per_90
        df = _df(
            (1, 0.30, 0.12, 90),
            (1, 0.30, 0.12, 90),
            (1, 0.30, 0.12, 90),
        )
        result = compute_rolling_xgi_per_90(df, player_id=1)
        assert abs(result - 0.42) < 1e-10



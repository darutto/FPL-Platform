"""
Tests for fpl_data_core.schemas

Covers TEST_PLAN.md §1.2 (Smoke) and §1.4 (Upstream Contract — data-conditional).

Run from fpl-data-core/:
    pytest tests/test_schemas.py -v
"""

import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# §1.2  Smoke Tests
# ---------------------------------------------------------------------------

class TestSchemasSmoke:

    def test_cumulative_cols_count(self):
        """CUMULATIVE_COLS has exactly 26 entries (matches upstream source)."""
        from fpl_data_core.schemas import CUMULATIVE_COLS
        assert len(CUMULATIVE_COLS) == 26, (
            f"Expected 26 CUMULATIVE_COLS, got {len(CUMULATIVE_COLS)}"
        )

    def test_cumulative_cols_contains_expected_goals(self):
        from fpl_data_core.schemas import CUMULATIVE_COLS
        assert "expected_goals" in CUMULATIVE_COLS

    def test_cumulative_cols_contains_ict_index(self):
        """ict_index is the last entry in the canonical column list."""
        from fpl_data_core.schemas import CUMULATIVE_COLS
        assert "ict_index" in CUMULATIVE_COLS

    def test_id_cols_contains_id(self):
        from fpl_data_core.schemas import ID_COLS
        assert "id" in ID_COLS

    def test_id_cols_contains_web_name(self):
        from fpl_data_core.schemas import ID_COLS
        assert "web_name" in ID_COLS

    def test_snapshot_cols_contains_now_cost(self):
        from fpl_data_core.schemas import SNAPSHOT_COLS
        assert "now_cost" in SNAPSHOT_COLS

    def test_snapshot_cols_contains_form(self):
        from fpl_data_core.schemas import SNAPSHOT_COLS
        assert "form" in SNAPSHOT_COLS

    def test_no_overlap_cumulative_and_id_cols(self):
        """No column should appear in both CUMULATIVE_COLS and ID_COLS."""
        from fpl_data_core.schemas import CUMULATIVE_COLS, ID_COLS
        overlap = set(CUMULATIVE_COLS) & set(ID_COLS)
        assert not overlap, f"Unexpected overlap: {overlap}"

    def test_no_overlap_cumulative_and_snapshot_cols(self):
        """No column should appear in both CUMULATIVE_COLS and SNAPSHOT_COLS."""
        from fpl_data_core.schemas import CUMULATIVE_COLS, SNAPSHOT_COLS
        overlap = set(CUMULATIVE_COLS) & set(SNAPSHOT_COLS)
        assert not overlap, f"Unexpected overlap: {overlap}"

    def test_tournament_name_map_covers_canonical_slugs(self):
        """All four canonical tournament slugs are present in the map."""
        from fpl_data_core.schemas import TOURNAMENT_NAME_MAP
        for slug in ["premier-league", "champions-league", "efl-cup", "europa-league"]:
            assert slug in TOURNAMENT_NAME_MAP, f"Missing slug: {slug}"

    def test_tournament_name_map_friendly_maps_to_friendlies(self):
        from fpl_data_core.schemas import TOURNAMENT_NAME_MAP
        assert TOURNAMENT_NAME_MAP["friendly"] == "Friendlies"

    def test_excluded_tournaments_contains_friendly(self):
        from fpl_data_core.schemas import EXCLUDED_TOURNAMENTS
        assert "friendly" in EXCLUDED_TOURNAMENTS

    def test_excluded_gameweeks_contains_zero(self):
        from fpl_data_core.schemas import EXCLUDED_GAMEWEEKS
        assert 0 in EXCLUDED_GAMEWEEKS


class TestNormalisePosition:

    def test_numeric_3_maps_to_mid(self):
        from fpl_data_core.schemas import normalise_position
        assert normalise_position(3) == "MID"

    def test_string_mid_returns_mid(self):
        from fpl_data_core.schemas import normalise_position
        assert normalise_position("MID") == "MID"

    def test_string_midfielder_returns_mid(self):
        from fpl_data_core.schemas import normalise_position
        assert normalise_position("Midfielder") == "MID"

    def test_numeric_1_maps_to_gkp(self):
        from fpl_data_core.schemas import normalise_position
        assert normalise_position(1) == "GKP"

    def test_numeric_2_maps_to_def(self):
        from fpl_data_core.schemas import normalise_position
        assert normalise_position(2) == "DEF"

    def test_numeric_4_maps_to_fwd(self):
        from fpl_data_core.schemas import normalise_position
        assert normalise_position(4) == "FWD"

    def test_unknown_int_returns_unknown(self):
        from fpl_data_core.schemas import normalise_position
        assert normalise_position(99) == "Unknown"

    def test_garbage_string_returns_unknown(self):
        from fpl_data_core.schemas import normalise_position
        assert normalise_position("garbage") == "Unknown"

    def test_case_insensitive_fwd(self):
        from fpl_data_core.schemas import normalise_position
        assert normalise_position("fwd") == "FWD"
        assert normalise_position("Forward") == "FWD"

    def test_striker_alias(self):
        from fpl_data_core.schemas import normalise_position
        assert normalise_position("Striker") == "FWD"

    def test_goalkeeper_alias(self):
        from fpl_data_core.schemas import normalise_position
        assert normalise_position("Goalkeeper") == "GKP"
        assert normalise_position("GK") == "GKP"

    def test_numeric_string_is_coerced(self):
        """The string '3' should resolve the same as int 3."""
        from fpl_data_core.schemas import normalise_position
        assert normalise_position("3") == "MID"


# ---------------------------------------------------------------------------
# §1.4  Upstream Contract Tests (data-conditional)
# ---------------------------------------------------------------------------

_GW1_CSV = (
    Path(__file__).parent.parent /
    "data" / "2025-2026" / "By Gameweek" / "GW1" / "playerstats.csv"
)


@pytest.mark.skipif(
    not _GW1_CSV.exists(),
    reason="Upstream GW1 CSV not available — skipped in CI"
)
class TestSchemasUpstreamContract:
    """
    UPSTREAM CONTRACT: validates schemas.py reflects the actual upstream CSV output.
    If any of these fail, update schemas.py and record the upstream commit SHA in
    the '# aligned-with:' comment at the top of the file.
    """

    def test_cumulative_cols_present_in_upstream_csv(self):
        import pandas as pd
        from fpl_data_core.schemas import CUMULATIVE_COLS
        df = pd.read_csv(_GW1_CSV, nrows=1)
        missing = [c for c in CUMULATIVE_COLS if c not in df.columns]
        assert not missing, (
            f"UPSTREAM DRIFT — columns in CUMULATIVE_COLS missing from upstream CSV: {missing}\n"
            "Update schemas.py and add '# aligned-with: <commit-sha>' to the file header."
        )

    def test_id_cols_present_in_upstream_csv(self):
        import pandas as pd
        from fpl_data_core.schemas import ID_COLS
        df = pd.read_csv(_GW1_CSV, nrows=1)
        missing = [c for c in ID_COLS if c not in df.columns]
        assert not missing, f"ID_COLS missing from upstream CSV: {missing}"

    def test_snapshot_cols_subset_present_in_upstream_csv(self):
        """At least the core snapshot columns exist in the upstream output."""
        import pandas as pd
        df = pd.read_csv(_GW1_CSV, nrows=1)
        # Some snapshot cols are FPL-API only and may not appear in the exported CSV.
        # Test only the ones that appear in the export_data.py output.
        core_snapshot = ["now_cost", "selected_by_percent"]
        missing = [c for c in core_snapshot if c not in df.columns]
        assert not missing, f"Core snapshot cols missing from upstream CSV: {missing}"



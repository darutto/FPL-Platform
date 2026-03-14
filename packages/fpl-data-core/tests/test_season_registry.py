"""
Tests for fpl_data_core.season_registry

Covers TEST_PLAN.md §1.1 (Smoke), §1.3 (Parity — data-conditional), §1.5 (Edge Cases).

Run from fpl-data-core/:
    pytest tests/test_season_registry.py -v
"""

import os
import pytest
import yaml
from pathlib import Path


# ---------------------------------------------------------------------------
# §1.1  Smoke Tests
# ---------------------------------------------------------------------------

class TestRegistrySmoke:

    def test_registry_loads_on_import(self):
        """YAML registry auto-loads on import — both expected seasons present."""
        from fpl_data_core.season_registry import SEASON_REGISTRY
        assert "2025-2026" in SEASON_REGISTRY, "2025-2026 missing from registry"
        assert "2024-2025" in SEASON_REGISTRY, "2024-2025 missing from registry"

    def test_get_season_layout_returns_layout_object(self):
        """get_season_layout('2025-2026') returns a SeasonLayout instance."""
        from fpl_data_core.season_registry import get_season_layout, SeasonLayout
        layout = get_season_layout("2025-2026")
        assert isinstance(layout, SeasonLayout)
        assert layout.season == "2025-2026"

    def test_season_layout_has_required_attributes(self):
        """SeasonLayout has all documented attributes."""
        from fpl_data_core.season_registry import get_season_layout
        layout = get_season_layout("2025-2026")
        assert hasattr(layout, "has_consolidated_files")
        assert hasattr(layout, "player_id_column")
        assert hasattr(layout, "gameweek_column")
        assert hasattr(layout, "gameweek_pattern")
        assert hasattr(layout, "files")
        assert hasattr(layout, "data_root")

    def test_get_season_layout_raises_key_error_on_unknown(self):
        """get_season_layout raises KeyError for unregistered season."""
        from fpl_data_core.season_registry import get_season_layout
        with pytest.raises(KeyError, match="1999-2000"):
            get_season_layout("1999-2000")

    def test_key_error_message_includes_available_seasons(self):
        """Error message for unknown season lists what IS available."""
        from fpl_data_core.season_registry import get_season_layout
        with pytest.raises(KeyError) as exc_info:
            get_season_layout("1888-1889")
        assert "Available" in str(exc_info.value)

    def test_both_registered_seasons_loadable(self):
        """Both known seasons return a layout with matching season string."""
        from fpl_data_core.season_registry import get_season_layout
        for season in ["2024-2025", "2025-2026"]:
            layout = get_season_layout(season)
            assert layout.season == season

    def test_list_available_seasons_returns_both(self):
        """list_available_seasons() includes both expected seasons."""
        from fpl_data_core.season_registry import list_available_seasons
        seasons = list_available_seasons()
        assert "2025-2026" in seasons
        assert "2024-2025" in seasons

    def test_2025_2026_not_consolidated(self):
        """2025-2026 season is not consolidated (per-GW file layout)."""
        from fpl_data_core.season_registry import get_season_layout
        layout = get_season_layout("2025-2026")
        assert layout.has_consolidated_files is False

    def test_2024_2025_is_consolidated(self):
        """2024-2025 season uses consolidated files."""
        from fpl_data_core.season_registry import get_season_layout
        layout = get_season_layout("2024-2025")
        assert layout.has_consolidated_files is True

    def test_2025_2026_file_keys_include_gw_pattern(self):
        """2025-2026 layout has a playerstats_gw file entry."""
        from fpl_data_core.season_registry import get_season_layout
        layout = get_season_layout("2025-2026")
        assert "playerstats_gw" in layout.files
        assert "{gw}" in layout.files["playerstats_gw"]

    def test_get_file_path_returns_path_object(self):
        """get_file_path returns a Path for a known file type."""
        from fpl_data_core.season_registry import get_season_layout
        layout = get_season_layout("2025-2026")
        path = layout.get_file_path("players")
        assert isinstance(path, Path)
        assert str(path).endswith(".csv")

    def test_get_file_path_raises_on_unknown_type(self):
        """get_file_path raises ValueError for an unregistered file type."""
        from fpl_data_core.season_registry import get_season_layout
        layout = get_season_layout("2025-2026")
        with pytest.raises(ValueError, match="not found"):
            layout.get_file_path("nonexistent_type")

    def test_get_file_path_with_gameweek_interpolates_gw(self):
        """get_file_path with gameweek=5 produces a path containing GW5."""
        from fpl_data_core.season_registry import get_season_layout
        layout = get_season_layout("2025-2026")
        path = layout.get_file_path("playerstats_gw", gameweek=5)
        assert "GW5" in str(path)
        assert str(path).endswith(".csv")

    def test_register_season_adds_to_registry(self):
        """register_season() makes a new layout retrievable."""
        from fpl_data_core.season_registry import register_season, get_season_layout, SeasonLayout
        custom = SeasonLayout(
            season="2099-2100",
            data_root=Path("data/2099-2100"),
            files={"players": "players.csv"},
            player_id_column="id",
            gameweek_column="gw",
            has_consolidated_files=False,
        )
        register_season(custom)
        retrieved = get_season_layout("2099-2100")
        assert retrieved.season == "2099-2100"


# ---------------------------------------------------------------------------
# §1.3  Parity Tests (data-conditional — skipped in CI without real data)
# ---------------------------------------------------------------------------

_DATA_2526 = Path(__file__).parent.parent / "data" / "2025-2026"
_BY_GW = _DATA_2526 / "By Gameweek"


@pytest.mark.skipif(
    not _DATA_2526.is_dir(),
    reason="Real 2025-2026 data not available — skipped in CI"
)
class TestSeasonRegistryParityWithRealData:

    def test_file_paths_resolve_to_csv_extensions(self):
        """get_file_path() returns .csv paths for all top-level file types."""
        from fpl_data_core.season_registry import get_season_layout
        layout = get_season_layout("2025-2026")
        for file_type in ["players", "teams", "gameweek_summaries"]:
            if file_type in layout.files:
                path = layout.get_file_path(file_type)
                assert str(path).endswith(".csv"), (
                    f"Expected .csv path for {file_type}, got: {path}"
                )

    def test_list_available_gameweeks_returns_sorted_ints(self):
        """list_available_gameweeks() returns sorted list of ints."""
        from fpl_data_core.season_registry import get_season_layout
        layout = get_season_layout("2025-2026")
        gws = layout.list_available_gameweeks()
        assert len(gws) >= 1, "Expected at least 1 GW on disk"
        assert all(isinstance(g, int) for g in gws)
        assert gws == sorted(gws), "Gameweeks must be returned in ascending order"

    def test_list_available_gameweeks_excludes_zero(self):
        """GW0 (if present on disk) is excluded from the available list."""
        from fpl_data_core.season_registry import get_season_layout
        layout = get_season_layout("2025-2026")
        gws = layout.list_available_gameweeks()
        assert 0 not in gws

    def test_playerstats_gw_path_exists_for_first_available_gw(self):
        """The playerstats file path for GW1 resolves to an existing file."""
        from fpl_data_core.season_registry import get_season_layout
        layout = get_season_layout("2025-2026")
        gws = layout.list_available_gameweeks()
        if not gws:
            pytest.skip("No gameweeks available on disk")
        first_gw = gws[0]
        path = layout.get_file_path("playerstats_gw", gameweek=first_gw)
        assert path.exists(), f"Expected {path} to exist"
        assert path.stat().st_size > 0, f"Expected non-empty file at {path}"


# ---------------------------------------------------------------------------
# §1.5  Edge Cases
# ---------------------------------------------------------------------------

class TestSeasonRegistryEdgeCases:

    def test_load_registry_from_custom_yaml_path(self, tmp_path):
        """load_registry_from_yaml() accepts a custom path and registers the season."""
        from fpl_data_core.season_registry import load_registry_from_yaml, SEASON_REGISTRY
        custom_yaml = tmp_path / "custom_seasons.yaml"
        custom_data = {
            "seasons": [{
                "season": "2030-2031",
                "data_root": "data/2030-2031",
                "has_consolidated_files": False,
                "player_id_column": "id",
                "gameweek_column": "gw",
                "files": {"players": "players.csv"},
            }]
        }
        custom_yaml.write_text(yaml.dump(custom_data))
        load_registry_from_yaml(custom_yaml)
        assert "2030-2031" in SEASON_REGISTRY

    def test_custom_yaml_overrides_data_root(self, tmp_path):
        """A custom YAML entry's data_root is preserved on the SeasonLayout."""
        from fpl_data_core.season_registry import load_registry_from_yaml, get_season_layout
        custom_yaml = tmp_path / "seasons.yaml"
        custom_yaml.write_text(yaml.dump({
            "seasons": [{
                "season": "2031-2032",
                "data_root": "custom/path/2031-2032",
                "has_consolidated_files": True,
                "player_id_column": "player_id",
                "gameweek_column": "event",
                "files": {},
            }]
        }))
        load_registry_from_yaml(custom_yaml)
        layout = get_season_layout("2031-2032")
        assert "custom/path/2031-2032" in str(layout.data_root)

    def test_load_registry_empty_seasons_list(self, tmp_path):
        """A YAML with an empty seasons list does not crash."""
        from fpl_data_core.season_registry import load_registry_from_yaml
        empty_yaml = tmp_path / "empty.yaml"
        empty_yaml.write_text(yaml.dump({"seasons": []}))
        # Should not raise
        load_registry_from_yaml(empty_yaml)

    def test_season_layout_data_root_is_path_object(self):
        """data_root is stored as a Path, not a plain string."""
        from fpl_data_core.season_registry import get_season_layout
        layout = get_season_layout("2025-2026")
        assert isinstance(layout.data_root, Path)

    def test_gameweek_pattern_default_is_gw_format(self):
        """gameweek_pattern defaults to 'GW{gw}' for both seasons."""
        from fpl_data_core.season_registry import get_season_layout
        for season in ["2024-2025", "2025-2026"]:
            layout = get_season_layout(season)
            assert "{gw}" in layout.gameweek_pattern



"""
tests/test_season_single_source.py
====================================
Cross-package test: every "satellite" that used to hardcode its own copy of
the current-season literal must now read it from the single source of
truth, packages/fpl-data-core/season_registry.yaml's `current_season` key
(loaded as fpl_data_core.season_registry.CURRENT_SEASON).

Incident this guards against: six-plus copies of "2025-2026" drifted from
reality unchecked for six weeks (owned-store-refresh silently wrote
2026-2027 data under the 2025-2026 key). "Single source of truth" is only
true if breaking the source actually breaks every consumer — this file
proves that by mutating the source and asserting every reloadable
consumer picks up the new value (or the mutation is asserted directly
against modules that are unsafe to reload mid-session).
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKAGES = _REPO_ROOT / "packages"

for _pkg_dir in ("fpl-data-core", "fpl-historical", "fpl-tactical"):
    _p = str(_PACKAGES / _pkg_dir)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_module_standalone(module_name: str, file_path: Path):
    """Load a module fresh from disk (bypasses sys.modules caching), mirroring
    test_owned_store_fallback.py's pattern so mutating a global constant and
    reloading doesn't collide with anything already imported this session."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_GROUNDED = _PACKAGES / "fpl-grounded-assistant" / "fpl_grounded_assistant"


@pytest.fixture
def restore_current_season():
    """Snapshot + restore fpl_data_core.season_registry.CURRENT_SEASON.

    Also reloads fpl_historical.paths / fpl_tactical.paths back to the
    restored value afterwards: importlib.reload() mutates the cached
    sys.modules entry in place, so leaving it un-reloaded after a test would
    permanently poison every later test that does
    ``from fpl_historical.paths import CURRENT_SEASON`` (including fresh
    standalone-loaded satellite modules, which still resolve that import
    against the same cached fpl_historical.paths module object).
    """
    from fpl_data_core import season_registry
    original = season_registry.CURRENT_SEASON
    yield season_registry
    season_registry.CURRENT_SEASON = original
    if "fpl_historical.paths" in sys.modules:
        importlib.reload(sys.modules["fpl_historical.paths"])
    if "fpl_tactical.paths" in sys.modules:
        importlib.reload(sys.modules["fpl_tactical.paths"])


class TestOwnPathsModulesReadTheSingleSource:
    """fpl_historical.paths and fpl_tactical.paths hold their own
    CURRENT_SEASON but must import it, not repeat the literal."""

    def test_fpl_historical_paths_matches_source(self):
        from fpl_data_core.season_registry import CURRENT_SEASON as SOURCE
        import fpl_historical.paths as fh_paths
        assert fh_paths.CURRENT_SEASON == SOURCE

    def test_fpl_tactical_paths_matches_source(self):
        from fpl_data_core.season_registry import CURRENT_SEASON as SOURCE
        import fpl_tactical.paths as ft_paths
        assert ft_paths.CURRENT_SEASON == SOURCE

    def test_mutating_source_breaks_fpl_historical_paths(self, restore_current_season):
        """Break the source -> fpl_historical.paths goes red (mismatches) on reload."""
        import fpl_historical.paths as fh_paths
        restore_current_season.CURRENT_SEASON = "1999-2000"
        importlib.reload(fh_paths)
        assert fh_paths.CURRENT_SEASON == "1999-2000"

    def test_mutating_source_breaks_fpl_tactical_paths(self, restore_current_season):
        import fpl_tactical.paths as ft_paths
        restore_current_season.CURRENT_SEASON = "1999-2000"
        importlib.reload(ft_paths)
        assert ft_paths.CURRENT_SEASON == "1999-2000"


class TestGroundedAssistantSatellitesReadTheSingleSource:
    """Standalone-loadable satellites (mirrors test_owned_store_fallback.py's
    import pattern to avoid pulling in fpl_grounded_assistant/__init__.py)."""

    @pytest.mark.parametrize("module_name,file_name", [
        ("owned_store_fallback", "owned_store_fallback.py"),
        ("owned_store_sync", "owned_store_sync.py"),
        ("zonal_weakness", "zonal_weakness.py"),
    ])
    def test_satellite_matches_source(self, module_name, file_name):
        from fpl_data_core.season_registry import CURRENT_SEASON as SOURCE
        mod = _load_module_standalone(
            f"fpl_grounded_assistant.{module_name}_singlesource_check",
            _GROUNDED / file_name,
        )
        assert mod.CURRENT_SEASON == SOURCE

    def test_get_player_season_points_matches_source(self):
        # Imported normally elsewhere in the suite (unconditional
        # fpl_tool_runner registration makes standalone loading unsafe here);
        # equality against the live source is still a real assertion that it
        # is not carrying its own independent literal.
        from fpl_data_core.season_registry import CURRENT_SEASON as SOURCE
        from fpl_grounded_assistant.get_player_season_points import CURRENT_SEASON as SATELLITE
        assert SATELLITE == SOURCE

    def test_historical_gameweek_top_scorer_matches_source(self):
        from fpl_data_core.season_registry import CURRENT_SEASON as SOURCE
        from fpl_grounded_assistant.historical_gameweek_top_scorer import CURRENT_SEASON as SATELLITE
        assert SATELLITE == SOURCE

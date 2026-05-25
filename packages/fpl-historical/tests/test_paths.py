"""
tests/test_paths.py
===================
Tests for fpl_historical.paths
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest


class TestHistoricalRoot:
    def test_env_var_override(self, tmp_historical_root, monkeypatch):
        """historical_root() returns the value of FPL_HISTORICAL_ROOT when set."""
        # Re-import to pick up the monkeypatched env var
        import importlib
        import fpl_historical.paths as paths_mod
        importlib.reload(paths_mod)
        from fpl_historical.paths import historical_root
        result = historical_root()
        assert result == tmp_historical_root

    def test_default_is_inside_repo(self, monkeypatch):
        """When FPL_HISTORICAL_ROOT is unset, historical_root() is inside the repo."""
        monkeypatch.delenv("FPL_HISTORICAL_ROOT", raising=False)
        import importlib
        import fpl_historical.paths as paths_mod
        importlib.reload(paths_mod)
        from fpl_historical.paths import historical_root
        result = historical_root()
        assert "fpl-historical" in str(result)
        assert "historical" in str(result)


class TestNewRawDir:
    def test_produces_windows_safe_path(self, tmp_historical_root):
        """new_raw_dir produces a directory name with no colons."""
        from fpl_historical.paths import new_raw_dir
        raw_dir = new_raw_dir("2025-2026")
        # Directory name must not contain colons (Windows unsafe)
        assert ":" not in raw_dir.name
        # Must end with Z (UTC marker)
        assert raw_dir.name.endswith("Z")

    def test_creates_directory(self, tmp_historical_root):
        """new_raw_dir actually creates the directory on disk."""
        from fpl_historical.paths import new_raw_dir
        raw_dir = new_raw_dir("2025-2026")
        assert raw_dir.exists()
        assert raw_dir.is_dir()

    def test_two_calls_produce_distinct_dirs(self, tmp_historical_root):
        """Two calls to new_raw_dir return different directory paths."""
        from fpl_historical.paths import new_raw_dir
        dir1 = new_raw_dir("2025-2026")
        time.sleep(1.1)  # ensure second-level timestamp differs
        dir2 = new_raw_dir("2025-2026")
        assert dir1 != dir2
        assert dir1.name != dir2.name


class TestSeasonDir:
    def test_season_dir_structure(self, tmp_historical_root):
        """season_dir returns path rooted at historical_root/seasons/<season>."""
        from fpl_historical.paths import season_dir
        d = season_dir("2025-2026")
        assert d.name == "2025-2026"
        assert d.parent.name == "seasons"


class TestListRawDirs:
    def test_empty_when_no_raw_dirs(self, tmp_historical_root):
        """list_raw_dirs returns [] when no raw dirs exist."""
        from fpl_historical.paths import list_raw_dirs
        assert list_raw_dirs("2025-2026") == []

    def test_sorted_oldest_newest(self, tmp_historical_root):
        """list_raw_dirs returns dirs sorted oldest to newest by name."""
        from fpl_historical.paths import list_raw_dirs, season_dir
        raw_parent = season_dir("2025-2026") / "raw"
        raw_parent.mkdir(parents=True)
        # Create dirs with sortable names
        names = ["2026-01-01T10-00-00Z", "2026-03-01T10-00-00Z", "2026-02-01T10-00-00Z"]
        for name in names:
            (raw_parent / name).mkdir()
        result = list_raw_dirs("2025-2026")
        assert [d.name for d in result] == sorted(names)

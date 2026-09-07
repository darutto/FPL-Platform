"""
fpl_tactical.paths
==================
Filesystem layout helpers for the fpl-tactical store, mirroring
``fpl_historical.paths``.

All paths are relative to ``tactical_root()``, which respects the
``FPL_TACTICAL_ROOT`` environment variable (default:
``packages/fpl-tactical/data/tactical/`` relative to the repo root,
resolved from this file's location).

Public API (CONTRACT):
    CURRENT_SEASON                str constant, sourced from fpl_data_core.season_registry
    tactical_root()               Path to the root of the tactical data store
    season_dir(season)            .../seasons/<season>
    shots_parquet_path(season)    .../seasons/<season>/understat_shots.parquet
    latest_pointer_path(season)   .../seasons/<season>/_tactical_latest.json
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Repo root — three levels up from this file (packages/fpl-tactical/fpl_tactical/)
_REPO_ROOT: Path = Path(__file__).resolve().parents[3]

# Season constant — single source of truth is
# packages/fpl-data-core/season_registry.yaml (`current_season` key); import
# it rather than repeating the literal (see incident: six-plus copies of
# this string drifted from reality unchecked for six weeks).
_FPL_DATA_CORE = str(_REPO_ROOT / "packages" / "fpl-data-core")
if _FPL_DATA_CORE not in sys.path:
    # append, not insert(0): inserting first would shadow this package's own
    # local `tests` namespace package with fpl-data-core's `tests` package
    # (regular packages, i.e. ones with __init__.py, take precedence over
    # namespace packages found later in sys.path).
    sys.path.append(_FPL_DATA_CORE)

from fpl_data_core.season_registry import CURRENT_SEASON  # noqa: E402

_DEFAULT_TACTICAL_ROOT: Path = (
    _REPO_ROOT / "packages" / "fpl-tactical" / "data" / "tactical"
)


def tactical_root() -> Path:
    """Return the root of the tactical data store.

    Respects ``FPL_TACTICAL_ROOT`` env var; defaults to
    ``packages/fpl-tactical/data/tactical/`` within the repo.
    """
    env_val = os.environ.get("FPL_TACTICAL_ROOT")
    if env_val:
        return Path(env_val)
    return _DEFAULT_TACTICAL_ROOT


def season_dir(season: str) -> Path:
    """Return ``.../tactical/seasons/<season>``."""
    return tactical_root() / "seasons" / season


def shots_parquet_path(season: str) -> Path:
    """Return ``.../seasons/<season>/understat_shots.parquet``."""
    return season_dir(season) / "understat_shots.parquet"


def latest_pointer_path(season: str) -> Path:
    """Return ``.../seasons/<season>/_tactical_latest.json``."""
    return season_dir(season) / "_tactical_latest.json"

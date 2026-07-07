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
    CURRENT_SEASON                str constant — "2025-2026"
    tactical_root()               Path to the root of the tactical data store
    season_dir(season)            .../seasons/<season>
    shots_parquet_path(season)    .../seasons/<season>/understat_shots.parquet
    latest_pointer_path(season)   .../seasons/<season>/_tactical_latest.json
"""

from __future__ import annotations

import os
from pathlib import Path

# Season key style matches fpl_historical.paths.CURRENT_SEASON
CURRENT_SEASON: str = "2025-2026"

# Repo root — three levels up from this file (packages/fpl-tactical/fpl_tactical/)
_REPO_ROOT: Path = Path(__file__).resolve().parents[3]
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

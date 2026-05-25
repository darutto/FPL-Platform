"""
fpl_historical.paths
====================
Filesystem layout helpers for the fpl-historical capture pipeline.

All paths are relative to ``historical_root()``, which respects the
``FPL_HISTORICAL_ROOT`` environment variable (default:
``packages/fpl-historical/data/historical/`` relative to the repo root,
resolved from this file's location).

Public API (CONTRACT §7):
    CURRENT_SEASON          str constant — "2025-2026"
    historical_root()       Path to the root of the historical data store
    season_dir(season)      .../seasons/<season>
    new_raw_dir(season)     creates .../seasons/<season>/raw/<utcnow_iso_safe>/
    parquet_dir(season)     .../seasons/<season>/parquet
    latest_pointer_path(season)  .../seasons/<season>/_latest.json
    list_raw_dirs(season)   sorted list of existing raw capture dirs
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Season constant — must match packages/fpl-data-core/season_registry.yaml
# Verified: line 36 of season_registry.yaml has `- season: "2025-2026"`
# ---------------------------------------------------------------------------
CURRENT_SEASON: str = "2025-2026"

# Repo root — two levels up from this file (packages/fpl-historical/fpl_historical/)
_REPO_ROOT: Path = Path(__file__).resolve().parents[3]
_DEFAULT_HISTORICAL_ROOT: Path = (
    _REPO_ROOT / "packages" / "fpl-historical" / "data" / "historical"
)


def historical_root() -> Path:
    """Return the root of the historical data store.

    Respects ``FPL_HISTORICAL_ROOT`` env var; defaults to
    ``packages/fpl-historical/data/historical/`` within the repo.
    """
    env_val = os.environ.get("FPL_HISTORICAL_ROOT")
    if env_val:
        return Path(env_val)
    return _DEFAULT_HISTORICAL_ROOT


def season_dir(season: str) -> Path:
    """Return ``.../historical/seasons/<season>``."""
    return historical_root() / "seasons" / season


def new_raw_dir(season: str) -> Path:
    """Create and return a new timestamped raw capture directory.

    Directory name uses ISO 8601 UTC timestamp with ``:`` replaced by ``-``
    for Windows filesystem compatibility, e.g. ``2026-05-25T14-22-03Z``.
    The directory is created immediately so two rapid calls produce distinct paths.
    """
    now = datetime.now(tz=timezone.utc)
    # Format: 2026-05-25T14:22:03Z -> replace colons for Windows
    ts = now.strftime("%Y-%m-%dT%H-%M-%SZ")
    raw_dir = season_dir(season) / "raw" / ts
    raw_dir.mkdir(parents=True, exist_ok=True)
    # Also create element-summary subdirectory
    (raw_dir / "element-summary").mkdir(exist_ok=True)
    return raw_dir


def parquet_dir(season: str) -> Path:
    """Return ``.../seasons/<season>/parquet``."""
    return season_dir(season) / "parquet"


def latest_pointer_path(season: str) -> Path:
    """Return ``.../seasons/<season>/_latest.json``."""
    return season_dir(season) / "_latest.json"


def list_raw_dirs(season: str) -> list[Path]:
    """Return sorted list of existing raw capture dirs, oldest to newest.

    Sorting by directory name works because the timestamp format is
    lexicographically ordered (ISO 8601 with ``-`` instead of ``:``).
    """
    raw_parent = season_dir(season) / "raw"
    if not raw_parent.exists():
        return []
    dirs = [d for d in raw_parent.iterdir() if d.is_dir()]
    return sorted(dirs, key=lambda d: d.name)


# ---------------------------------------------------------------------------
# Incremental capture helpers (CONTRACT §9.1)
# ---------------------------------------------------------------------------

def incremental_dir(season: str) -> Path:
    """Return ``.../seasons/<season>/incremental``."""
    return season_dir(season) / "incremental"


def gw_dir(season: str, gw: int) -> Path:
    """Return ``.../seasons/<season>/incremental/gw{NN}`` (zero-padded).

    GW directory names are zero-padded so lexicographic sort matches numeric
    sort (``gw01 < gw02 < ... < gw38``).
    """
    return incremental_dir(season) / f"gw{gw:02d}"


def new_incremental_dir(season: str, gw: int) -> Path:
    """Create and return a new timestamped incremental capture directory.

    Uses the same ISO 8601 UTC timestamp format as :func:`new_raw_dir`:
    ``2026-05-25T14-22-03Z``.  The directory is created immediately so two
    rapid calls produce distinct paths.
    """
    now = datetime.now(tz=timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H-%M-%SZ")
    inc_dir = gw_dir(season, gw) / ts
    inc_dir.mkdir(parents=True, exist_ok=True)
    return inc_dir


def list_incremental_dirs(season: str, gw: int) -> list[Path]:
    """Return sorted list of timestamped subdirs under ``gw_dir``.

    Returns an empty list if the directory does not exist.  Sorted oldest to
    newest (lexicographic by directory name, which equals chronological order
    given the ISO timestamp format).
    """
    parent = gw_dir(season, gw)
    if not parent.exists():
        return []
    dirs = [d for d in parent.iterdir() if d.is_dir()]
    return sorted(dirs, key=lambda d: d.name)

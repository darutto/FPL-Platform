"""
fpl_tactical.store
==================
Parquet + provenance-pointer persistence for the tactical store, mirroring
the atomic-write conventions of ``fpl_historical.merge`` (temp file →
``os.replace``).

Layout (under ``paths.tactical_root()``):
    seasons/<season>/understat_shots.parquet
    seasons/<season>/_tactical_latest.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from fpl_tactical.paths import latest_pointer_path, shots_parquet_path


def _write_parquet_atomic(df: pd.DataFrame, dest: Path) -> None:
    """Write *df* to *dest* via a .parquet.tmp file, then os.replace (atomic)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(str(tmp), str(dest))


def write_shots(df: pd.DataFrame, season: str) -> Path:
    """Atomically (re)write the season's ``understat_shots`` parquet."""
    dest = shots_parquet_path(season)
    _write_parquet_atomic(df, dest)
    return dest


def read_shots(season: str) -> pd.DataFrame | None:
    """Return the season's shots, or ``None`` if the store has no parquet."""
    path = shots_parquet_path(season)
    if not path.exists():
        return None
    return pd.read_parquet(path)


def write_pointer(pointer: dict, season: str) -> Path:
    """Atomically (re)write ``_tactical_latest.json`` for the season."""
    dest = latest_pointer_path(season)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(pointer, indent=2).encode("utf-8")
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_bytes(payload)
    os.replace(str(tmp), str(dest))
    return dest


def read_pointer(season: str) -> dict | None:
    """Return the season's provenance pointer, or ``None`` if absent."""
    path = latest_pointer_path(season)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

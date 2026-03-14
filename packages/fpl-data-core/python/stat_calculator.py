"""
fpl-data-core · packages/fpl-data-core/python/stat_calculator.py
=================================================================
Discrete (per-gameweek) stat calculation engine.

SOURCE:  Extracted and generalised from:
  - FPL-Elo-Insights/scripts/export_data.py
    • calculate_discrete_gameweek_stats() (lines 75-186)
    • The subtraction loop (lines 115-126)

REPLACES (do NOT delete originals until migration is approved):
  - FPL-Elo-Insights/scripts/export_data.py::calculate_discrete_gameweek_stats
  - fpl-elo-insights-clean/scripts/export_data.py  (same function, diverged copy)

CONSUMERS AFTER MIGRATION:
  - FPL-Elo-Insights/scripts/export_data.py  → call from here
  - fpl-platform/pipelines/sync_from_supabase.py
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from .schemas import CUMULATIVE_COLS, ID_COLS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core discrete-stat calculation
# ---------------------------------------------------------------------------

def make_discrete(
    current_df: pd.DataFrame,
    prev_df: Optional[pd.DataFrame],
    cumulative_cols: list[str] = CUMULATIVE_COLS,
    id_cols: list[str] = ID_COLS,
) -> pd.DataFrame:
    """Subtract previous-GW cumulative values to produce per-GW stats.

    Given:
        current_df  — playerstats CSV for GW N  (cumulative season totals)
        prev_df     — playerstats CSV for GW N-1 (cumulative season totals)
                      or None for GW1 (result equals current_df as-is)

    Returns:
        DataFrame where each CUMULATIVE_COL contains the delta (GW N only).
        Non-cumulative columns (snapshot, identity) are unchanged.

    SOURCE: FPL-Elo-Insights/scripts/export_data.py lines 100-135
    """
    if prev_df is None or prev_df.empty:
        # GW1: cumulative == discrete (no previous week)
        return current_df.copy()

    # Only keep id + cumulative cols from prev to avoid column collisions
    prev_cols = [c for c in id_cols + cumulative_cols if c in prev_df.columns]
    merged = pd.merge(
        current_df,
        prev_df[prev_cols],
        on="id",
        how="left",
        suffixes=("", "_prev"),
    )

    for col in cumulative_cols:
        if col in merged.columns and f"{col}_prev" in merged.columns:
            merged[f"{col}_prev"] = merged[f"{col}_prev"].fillna(0)
            merged[col] = merged[col] - merged[f"{col}_prev"]

    # Drop the _prev helper columns
    prev_suffix_cols = [c for c in merged.columns if c.endswith("_prev")]
    return merged.drop(columns=prev_suffix_cols)


# ---------------------------------------------------------------------------
# Folder-based batch calculation
# ---------------------------------------------------------------------------

def calculate_discrete_gameweek_stats(
    base_path: Path,
    subfolder: str = "By Gameweek",
    playerstats_filename: str = "playerstats.csv",
    output_filename: str = "player_gameweek_stats.csv",
    cumulative_cols: list[str] = CUMULATIVE_COLS,
) -> None:
    """Walk a by-gameweek folder tree and write discrete stat files.

    Reads  `base_path / subfolder / GW{n} / playerstats_filename`
    Writes `base_path / subfolder / GW{n} / output_filename`

    Also writes a master `base_path / output_filename` concatenating all GWs.

    SOURCE: FPL-Elo-Insights/scripts/export_data.py::calculate_discrete_gameweek_stats
            (lines 75-186, generalised to accept configurable paths)
    """
    gw_dir = base_path / subfolder
    if not gw_dir.exists():
        logger.warning(f"Gameweek directory not found: {gw_dir}")
        return

    # Collect and sort GW directories
    gw_entries: list[tuple[int, Path]] = []
    for d in gw_dir.iterdir():
        if d.is_dir() and d.name.startswith("GW"):
            try:
                gw_num = int(d.name[2:])
                ps_file = d / playerstats_filename
                if ps_file.exists() and ps_file.stat().st_size > 0:
                    gw_entries.append((gw_num, d))
            except ValueError:
                continue

    gw_entries.sort(key=lambda x: x[0])
    logger.info(f"Found {len(gw_entries)} gameweeks to process in {gw_dir}")

    all_discrete: list[pd.DataFrame] = []
    prev_df: Optional[pd.DataFrame] = None

    for gw_num, gw_folder in gw_entries:
        ps_path = gw_folder / playerstats_filename
        try:
            current_df = pd.read_csv(ps_path)
        except Exception as exc:
            logger.error(f"  GW{gw_num}: failed to read {ps_path}: {exc}")
            continue

        discrete_df = make_discrete(current_df, prev_df, cumulative_cols)
        discrete_df["gw"] = gw_num  # tag the gameweek

        out_path = gw_folder / output_filename
        discrete_df.to_csv(out_path, index=False)
        logger.info(f"  GW{gw_num}: wrote {len(discrete_df)} rows → {out_path.name}")

        all_discrete.append(discrete_df)
        prev_df = current_df  # current becomes prev for next iteration

    if all_discrete:
        master_df = pd.concat(all_discrete, ignore_index=True)
        master_path = base_path / output_filename
        master_df.to_csv(master_path, index=False)
        logger.info(
            f"Wrote master discrete file: {master_path} ({len(master_df)} rows total)"
        )


# ---------------------------------------------------------------------------
# Rolling metrics (used by performanceEnricher.ts equivalent)
# ---------------------------------------------------------------------------

def compute_rolling_xgi_per_90(
    playermatchstats_df: pd.DataFrame,
    player_id: int,
    lookback: int = 3,
) -> float:
    """Compute rolling xGI/90 for a player over the last N matches.

    SOURCE: captaincy-showdown/src/utils/performanceEnricher.ts::buildAggMap (lines 32-93)
            Python equivalent of the TypeScript rolling aggregation.

    Args:
        playermatchstats_df: DataFrame with columns player_id, xg, xa, minutes_played
        player_id:           FPL player ID
        lookback:            Number of recent matches to include

    Returns:
        xGI per 90 minutes (0.0 if no data available)
    """
    player_rows = playermatchstats_df[
        playermatchstats_df["player_id"] == player_id
    ].tail(lookback)

    if player_rows.empty:
        return 0.0

    total_xg = player_rows.get("xg", pd.Series([0])).sum()
    total_xa = player_rows.get("xa", pd.Series([0])).sum()
    total_minutes = player_rows.get("minutes_played", pd.Series([0])).sum()

    if total_minutes <= 0:
        return 0.0

    return float((total_xg + total_xa) / total_minutes * 90)



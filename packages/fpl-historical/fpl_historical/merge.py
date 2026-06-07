"""
fpl_historical.merge
====================
Owned merge projection — fuses the H1 baseline parquet build with the H2a
per-GW incremental snapshots into a new, owned parquet output.

Public API:
    build_merged_parquet(season: str) -> dict
        Build parquet_merged/ + _owned_latest.json from baseline + complete
        incrementals.  Returns the _owned_latest.json dict that was written.
        Implements CONTRACT §10 verbatim.
"""

from __future__ import annotations

import gzip
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from fpl_historical.manifest import read_manifest
from fpl_historical.paths import (
    latest_pointer_path,
    list_incremental_dirs,
    merged_parquet_dir,
    owned_latest_pointer_path,
    season_dir,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Matches a season directory segment, e.g. "seasons/2024-2025/" — used to
# backfill the `season` column from the directory path when reading a
# pre-H6 parquet that predates the `season` column (Decision 2 transition).
_SEASON_DIR_RE = re.compile(r"seasons[\\/](\d{4}-\d{4})[\\/]")


def _season_from_path(path: Path) -> str | None:
    """Extract a season key (e.g. ``"2024-2025"``) from a path via regex.

    Returns ``None`` if no ``seasons/{season}/`` segment is found.
    """
    match = _SEASON_DIR_RE.search(str(path))
    if match:
        return match.group(1)
    return None


def _ensure_season_column(df: pd.DataFrame, season: str, source_path: Path | None = None) -> pd.DataFrame:
    """Ensure *df* carries a ``season`` column with the expected value.

    Backward-compatibility (Decision 2): if *df* was loaded from a pre-H6
    parquet that lacks the ``season`` column, fill it from *source_path* by
    regexing out the ``seasons/{season}/`` directory segment. Falls back to
    the explicitly-provided *season* if the column is absent and the path
    can't be parsed (or no path is given).
    """
    if "season" not in df.columns:
        value = season
        if source_path is not None:
            from_path = _season_from_path(source_path)
            if from_path is not None:
                value = from_path
        df = df.copy()
        df["season"] = value
    return df


def _utcnow_iso_safe() -> str:
    """Return UTC now in the filesystem-safe ISO 8601 format used by §3/§9."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _load_gz_json(path: Path):
    with gzip.open(path, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def _write_parquet_atomic(df: pd.DataFrame, dest: Path) -> None:
    """Write *df* to *dest* via a .parquet.tmp file, then os.replace (atomic)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".parquet.tmp")
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, str(tmp))
    os.replace(str(tmp), str(dest))


# ---------------------------------------------------------------------------
# Column-rename logic — duplicated from projections.py per H2b §10 boundary
# (projections.py must not be modified; these are the same 5 renames it uses)
# ---------------------------------------------------------------------------

def _build_season_state_tables(
    bootstrap: dict,
    fixtures_list: list,
    captured_at: str,
    *,
    season: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build players/teams/events/fixtures DataFrames from raw JSON."""
    # players
    players_df = pd.json_normalize(bootstrap.get("elements", []))
    players_df = players_df.rename(columns={"id": "player_id", "team": "team_id"})
    players_df["season"] = season
    players_df["captured_at"] = captured_at

    # teams
    teams_df = pd.json_normalize(bootstrap.get("teams", []))
    teams_df = teams_df.rename(columns={"id": "team_id"})
    teams_df["season"] = season
    teams_df["captured_at"] = captured_at

    # events
    events_df = pd.json_normalize(bootstrap.get("events", []))
    events_df = events_df.rename(columns={"id": "event_id"})
    events_df["season"] = season
    events_df["captured_at"] = captured_at

    # fixtures
    fixtures_df = pd.json_normalize(fixtures_list)
    fixtures_df = fixtures_df.rename(columns={"id": "fixture_id", "event": "event_id"})
    fixtures_df["season"] = season
    fixtures_df["captured_at"] = captured_at

    return players_df, teams_df, events_df, fixtures_df


def _build_baseline_gw_stats(
    raw_dir: Path,
    captured_at: str,
    *,
    season: str,
) -> pd.DataFrame:
    """Load element-summary history rows from a baseline raw dir.

    Returns a DataFrame with source='baseline' and source_captured_at set.
    """
    es_dir = raw_dir / "element-summary"
    gw_rows: list[dict] = []
    if es_dir.exists():
        for gz_file in sorted(es_dir.glob("*.json.gz")):
            player_id = int(gz_file.stem.split(".")[0])
            try:
                summary = _load_gz_json(gz_file)
            except Exception:
                continue
            for row in summary.get("history", []):
                row = dict(row)
                row["player_id"] = player_id
                gw_rows.append(row)

    if gw_rows:
        gw_df = pd.json_normalize(gw_rows)
        # rename 'event' → 'event_id'; also accept 'round' as the gameweek field
        # (duplicated from projections.py per H2b §10 boundary)
        rename_map: dict[str, str] = {}
        if "event" in gw_df.columns:
            rename_map["event"] = "event_id"
        elif "round" in gw_df.columns and "event_id" not in gw_df.columns:
            rename_map["round"] = "event_id"
        if rename_map:
            gw_df = gw_df.rename(columns=rename_map)
        gw_df["season"] = season
        gw_df["captured_at"] = captured_at
        gw_df["source"] = "baseline"
        gw_df["source_captured_at"] = captured_at
    else:
        gw_df = pd.DataFrame(columns=[
            "player_id", "event_id", "total_points", "minutes",
            "goals_scored", "assists", "clean_sheets", "goals_conceded",
            "bonus", "bps", "expected_goals", "expected_assists",
            "expected_goal_involvements", "value", "was_home",
            "opponent_team", "season", "captured_at", "source", "source_captured_at",
        ])

    return gw_df


def _build_incremental_gw_stats(
    inc_dir: Path,
    gameweek: int,
    captured_at: str,
    *,
    season: str,
) -> pd.DataFrame:
    """Load event-live rows from an incremental snapshot directory.

    Returns a DataFrame with source='incremental' and source_captured_at set.
    """
    event_live = _load_gz_json(inc_dir / "event-live.json.gz")
    rows: list[dict] = []
    for element in event_live.get("elements", []):
        row: dict = {"player_id": element["id"], "event_id": gameweek}
        stats = element.get("stats", {})
        row.update(stats)
        row["season"] = season
        row["captured_at"] = captured_at
        row["source"] = "incremental"
        row["source_captured_at"] = captured_at
        rows.append(row)

    if rows:
        return pd.json_normalize(rows)
    else:
        return pd.DataFrame(columns=[
            "player_id", "event_id", "season", "captured_at", "source", "source_captured_at",
        ])


# ---------------------------------------------------------------------------
# Relative-path helper
# ---------------------------------------------------------------------------

def _rel(path: Path, season: str) -> str:
    """Return path relative to data/historical/seasons/{season}/.

    CONTRACT §10.6: all raw_dir paths inside _owned_latest.json are relative
    to data/historical/seasons/{season}/.
    """
    base = season_dir(season)
    return str(path.relative_to(base)).replace("\\", "/")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_merged_parquet(season: str) -> dict:
    """Build parquet_merged/ + _owned_latest.json from baseline + complete incrementals.

    Returns the _owned_latest.json dict that was written.
    Implements CONTRACT §10 verbatim.
    """
    s_dir = season_dir(season)
    out_dir = merged_parquet_dir(season)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # §10.2 — Baseline contribution
    # ------------------------------------------------------------------
    latest_path = latest_pointer_path(season)
    baseline_info: dict | None = None
    baseline_bootstrap: dict | None = None
    baseline_fixtures: list | None = None
    baseline_captured_at: str | None = None
    baseline_raw_dir: Path | None = None
    baseline_gw_df: pd.DataFrame = pd.DataFrame()

    if latest_path.exists():
        latest_data = json.loads(latest_path.read_text(encoding="utf-8"))
        raw_dir_name = latest_data["raw_dir"]
        baseline_raw_dir = s_dir / "raw" / raw_dir_name
        baseline_manifest = read_manifest(baseline_raw_dir)
        baseline_captured_at = baseline_manifest.captured_at_utc

        baseline_bootstrap = _load_gz_json(baseline_raw_dir / "bootstrap-static.json.gz")
        baseline_fixtures = _load_gz_json(baseline_raw_dir / "fixtures.json.gz")
        baseline_gw_df = _build_baseline_gw_stats(baseline_raw_dir, baseline_captured_at, season=season)

        baseline_info = {
            "raw_dir": _rel(baseline_raw_dir, season),
            "captured_at_utc": baseline_captured_at,
            "manifest_status": baseline_manifest.status,
        }

    # ------------------------------------------------------------------
    # §10.2 — Incremental contributions: newest complete per GW
    # ------------------------------------------------------------------
    chosen_incrementals: list[dict] = []  # sorted by gameweek asc (built in order)
    incremental_gw_dfs: list[pd.DataFrame] = []

    # best (newest captured_at) source for season-state tables
    best_state_captured_at: str = baseline_captured_at or ""
    best_state_bootstrap: dict | None = baseline_bootstrap
    best_state_fixtures: list | None = baseline_fixtures

    for gw in range(1, 39):
        inc_dirs = list_incremental_dirs(season, gw)
        # Reverse-iterate to find most recent with status == "complete"
        chosen_dir: Path | None = None
        chosen_manifest = None
        for d in reversed(inc_dirs):
            try:
                m = read_manifest(d)
            except Exception:
                continue
            if m.status == "complete":
                chosen_dir = d
                chosen_manifest = m
                break

        if chosen_dir is None:
            continue

        inc_captured_at = chosen_manifest.captured_at_utc
        chosen_incrementals.append({
            "gameweek": gw,
            "raw_dir": _rel(chosen_dir, season),
            "captured_at_utc": inc_captured_at,
        })

        # Load incremental gw stats
        inc_gw_df = _build_incremental_gw_stats(chosen_dir, gw, inc_captured_at, season=season)
        incremental_gw_dfs.append(inc_gw_df)

        # Update best season-state source (§10.3: newest captured_at wins)
        if inc_captured_at > best_state_captured_at:
            best_state_captured_at = inc_captured_at
            inc_bootstrap = _load_gz_json(chosen_dir / "bootstrap-static.json.gz")
            inc_fixtures = _load_gz_json(chosen_dir / "fixtures.json.gz")
            best_state_bootstrap = inc_bootstrap
            best_state_fixtures = inc_fixtures

    # ------------------------------------------------------------------
    # §10.3 — Build season-state tables (players/teams/events/fixtures)
    # ------------------------------------------------------------------
    if best_state_bootstrap is not None:
        players_df, teams_df, events_df, fixtures_df = _build_season_state_tables(
            best_state_bootstrap,
            best_state_fixtures or [],
            best_state_captured_at,
            season=season,
        )
    else:
        # No baseline, no incrementals — write empty schema-preserved tables
        players_df = pd.DataFrame(columns=["player_id", "team_id", "season", "captured_at"])
        teams_df = pd.DataFrame(columns=["team_id", "season", "captured_at"])
        events_df = pd.DataFrame(columns=["event_id", "season", "captured_at"])
        fixtures_df = pd.DataFrame(columns=["fixture_id", "event_id", "season", "captured_at"])

    # ------------------------------------------------------------------
    # §10.4 — Build player_gw_stats with dedup
    # ------------------------------------------------------------------
    all_gw_dfs: list[pd.DataFrame] = []
    if not baseline_gw_df.empty:
        all_gw_dfs.append(baseline_gw_df)
    all_gw_dfs.extend(incremental_gw_dfs)

    if all_gw_dfs:
        combined = pd.concat(all_gw_dfs, ignore_index=True)

        # Dedup by (player_id, event_id): most recent source_captured_at wins;
        # ties go to incremental.  Add a sort key where incremental=0, baseline=1
        # so that ascending sort puts incremental first within tied timestamps.
        combined["_sort_source"] = (combined["source"] == "baseline").astype(int)
        combined = combined.sort_values(
            by=["source_captured_at", "_sort_source"],
            ascending=[False, True],   # newest captured_at first; incremental (0) before baseline (1)
        ).drop_duplicates(subset=["player_id", "event_id"], keep="first")
        combined = combined.drop(columns=["_sort_source"])
        combined = combined.reset_index(drop=True)
    else:
        combined = pd.DataFrame(columns=[
            "player_id", "event_id", "total_points", "minutes",
            "goals_scored", "assists", "clean_sheets", "goals_conceded",
            "bonus", "bps", "expected_goals", "expected_assists",
            "expected_goal_involvements", "value", "was_home",
            "opponent_team", "season", "captured_at", "source", "source_captured_at",
        ])

    # ------------------------------------------------------------------
    # §10.7 — Write all 5 parquet files atomically
    # ------------------------------------------------------------------
    tables = {
        "players": players_df,
        "teams": teams_df,
        "events": events_df,
        "fixtures": fixtures_df,
        "player_gw_stats": combined,
    }
    for name, df in tables.items():
        # Decision 2 backward-compat: guarantee the `season` column is present
        # (e.g. if a future source DataFrame predates this change), filling
        # from the season directory path when it can't be sourced otherwise.
        df = _ensure_season_column(df, season, source_path=out_dir)
        _write_parquet_atomic(df, out_dir / f"{name}.parquet")

    # ------------------------------------------------------------------
    # §10.6 — Build and write _owned_latest.json atomically (last)
    # ------------------------------------------------------------------
    row_counts = {name: len(df) for name, df in tables.items()}

    pointer: dict = {
        "schema_version": 1,
        "season": season,
        "merged_at": _utcnow_iso_safe(),
        "baseline": baseline_info,
        "incrementals": chosen_incrementals,  # already sorted by gw asc
        "row_counts": row_counts,
    }

    owned_path = owned_latest_pointer_path(season)
    owned_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(pointer, indent=2).encode("utf-8")
    tmp_path = owned_path.with_suffix(".json.tmp")
    tmp_path.write_bytes(payload)
    os.replace(str(tmp_path), str(owned_path))

    return pointer

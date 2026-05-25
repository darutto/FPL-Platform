"""
fpl_historical.projections
==========================
Parquet promotion logic for the fpl-historical capture pipeline.

Public API:
    build_parquet_from_raw(raw_dir, parquet_dir, *, promote_with_gaps) -> None
"""

from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from fpl_historical.manifest import read_manifest
from fpl_historical.paths import latest_pointer_path


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_gz_json(path: Path):
    with gzip.open(path, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def _write_parquet_atomic(df: pd.DataFrame, dest: Path) -> None:
    """Write *df* to *dest* via a .tmp file, then os.replace (atomic)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".parquet.tmp")
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, str(tmp))
    os.replace(str(tmp), str(dest))


def build_parquet_from_raw(
    raw_dir: Path,
    out_parquet_dir: Path,
    *,
    promote_with_gaps: bool = False,
) -> None:
    """Build the 5 parquet tables from a raw capture directory.

    Parameters
    ----------
    raw_dir:
        Path to a timestamped raw capture directory that contains
        ``_manifest.json``, ``bootstrap-static.json.gz``,
        ``fixtures.json.gz``, and ``element-summary/``.
    out_parquet_dir:
        Destination directory for the parquet files.
    promote_with_gaps:
        Allow promotion when ``manifest.status == "complete_with_gaps"``.
        Has no effect on ``"failed"`` status (always raises).

    Raises
    ------
    ValueError
        If the manifest status is ``"failed"``, or if it is
        ``"complete_with_gaps"`` and *promote_with_gaps* is ``False``.
    """
    manifest = read_manifest(raw_dir)

    if manifest.status == "failed":
        raise ValueError("cannot promote failed capture")
    if manifest.status == "complete_with_gaps" and not promote_with_gaps:
        raise ValueError("complete_with_gaps requires promote_with_gaps=True")

    captured_at = manifest.captured_at_utc
    season = manifest.season

    # ------------------------------------------------------------------
    # Load source JSON
    # ------------------------------------------------------------------
    bootstrap = _load_gz_json(raw_dir / "bootstrap-static.json.gz")
    fixtures_list = _load_gz_json(raw_dir / "fixtures.json.gz")

    # ------------------------------------------------------------------
    # 1. players  (bootstrap.elements[])
    # ------------------------------------------------------------------
    players_df = pd.json_normalize(bootstrap.get("elements", []))
    players_df = players_df.rename(columns={"id": "player_id", "team": "team_id"})
    players_df["captured_at"] = captured_at

    # ------------------------------------------------------------------
    # 2. teams  (bootstrap.teams[])
    # ------------------------------------------------------------------
    teams_df = pd.json_normalize(bootstrap.get("teams", []))
    teams_df = teams_df.rename(columns={"id": "team_id"})
    teams_df["captured_at"] = captured_at

    # ------------------------------------------------------------------
    # 3. events  (bootstrap.events[])
    # ------------------------------------------------------------------
    events_df = pd.json_normalize(bootstrap.get("events", []))
    events_df = events_df.rename(columns={"id": "event_id"})
    events_df["captured_at"] = captured_at

    # ------------------------------------------------------------------
    # 4. fixtures  (fixtures.json top-level list)
    # ------------------------------------------------------------------
    fixtures_df = pd.json_normalize(fixtures_list)
    fixtures_df = fixtures_df.rename(columns={"id": "fixture_id", "event": "event_id"})
    fixtures_df["captured_at"] = captured_at

    # ------------------------------------------------------------------
    # 5. player_gw_stats  (element-summary/{id}.json → history[])
    # ------------------------------------------------------------------
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
    else:
        gw_df = pd.DataFrame()

    if not gw_df.empty:
        # rename 'event' → 'event_id'; also accept 'round' as the gameweek field
        # (some FPL API history entries use 'round' instead of 'event')
        rename_map: dict[str, str] = {}
        if "event" in gw_df.columns:
            rename_map["event"] = "event_id"
        elif "round" in gw_df.columns and "event_id" not in gw_df.columns:
            rename_map["round"] = "event_id"
        if rename_map:
            gw_df = gw_df.rename(columns=rename_map)
        gw_df["captured_at"] = captured_at
    else:
        # Produce an empty but correctly typed DataFrame
        gw_df = pd.DataFrame(columns=[
            "player_id", "event_id", "total_points", "minutes",
            "goals_scored", "assists", "clean_sheets", "goals_conceded",
            "bonus", "bps", "expected_goals", "expected_assists",
            "expected_goal_involvements", "value", "was_home",
            "opponent_team", "captured_at",
        ])

    # ------------------------------------------------------------------
    # Write all 5 tables atomically
    # ------------------------------------------------------------------
    tables = {
        "players": players_df,
        "teams": teams_df,
        "events": events_df,
        "fixtures": fixtures_df,
        "player_gw_stats": gw_df,
    }
    for name, df in tables.items():
        _write_parquet_atomic(df, out_parquet_dir / f"{name}.parquet")

    # ------------------------------------------------------------------
    # Update _latest.json (atomic)
    # ------------------------------------------------------------------
    latest_path = latest_pointer_path(season)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "raw_dir": raw_dir.name,
            "parquet_built_at": _utcnow_iso(),
        },
        indent=2,
    ).encode("utf-8")
    tmp_latest = latest_path.with_suffix(".json.tmp")
    tmp_latest.write_bytes(payload)
    os.replace(str(tmp_latest), str(latest_path))

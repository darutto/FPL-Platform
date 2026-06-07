"""
tests/test_vaastav_import.py
============================
Unit tests for fpl_historical.vaastav_import (Track A H6).

Six scenarios per plan §9:
    1. Happy path — all 5 tables produced, each carries a `season` column,
       row counts match the fixture.
    2. player_gw_stats per-GW concatenation — correct event_id per row,
       season identical across rows.
    3. events reconstruction — fixtures grouped by event, deadline_time
       computed as min(kickoff_time).
    4. Missing optional column (xP absent in gw2.csv) — import succeeds,
       column is null for those rows, WARNING logged.
    5. Pointer file shape — `_owned_latest.json` has season, merged_at,
       source == "vaastav@<sha>", row_counts.
    6. Re-import overwrites — running twice produces a clean (non-duplicated)
       parquet, not a concatenation.

All tests build a temp "vaastav clone" directory that mirrors the real
layout (`<source>/data/<vaastav_dir>/...`) by copying the hand-crafted
fixtures from tests/fixtures/vaastav/2024-2025/ into
`<tmp>/_vaastav_source/data/2024-25/` (vaastav's own directory naming is
YYYY-YY, e.g. "2024-25" for our "2024-2025" season key — see
vaastav_import._vaastav_dir_name).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from conftest import VAASTAV_FIXTURE_DIR
from fpl_historical.paths import merged_parquet_dir, owned_latest_pointer_path
from fpl_historical.vaastav_import import (
    VAASTAV_PINNED_SHA,
    ImportResult,
    _read_csv,
    _vaastav_dir_name,
    import_season,
)

SEASON = "2024-2025"
VAASTAV_DIR_NAME = "2024-25"


# ---------------------------------------------------------------------------
# Helper: stage a fake vaastav clone directory from our fixtures
# ---------------------------------------------------------------------------

def _stage_vaastav_source(tmp_path: Path, season_fixture_dir: Path | None = None) -> Path:
    """Copy the hand-crafted fixture CSVs into a fake-clone layout.

    Returns the path to the fake clone root (i.e. the value to pass as
    `source_path` to `import_season`).
    """
    if season_fixture_dir is None:
        season_fixture_dir = VAASTAV_FIXTURE_DIR / SEASON

    source_root = tmp_path / "_vaastav_source"
    dest = source_root / "data" / VAASTAV_DIR_NAME
    shutil.copytree(season_fixture_dir, dest)
    return source_root


# ---------------------------------------------------------------------------
# 0. _vaastav_dir_name conversion sanity check
# ---------------------------------------------------------------------------

def test_vaastav_dir_name_conversion():
    assert _vaastav_dir_name("2024-2025") == "2024-25"
    assert _vaastav_dir_name("2016-2017") == "2016-17"
    # Already-vaastav-shaped keys pass through unchanged
    assert _vaastav_dir_name("2024-25") == "2024-25"


# ---------------------------------------------------------------------------
# 0b. _read_csv encoding fallback (older vaastav seasons are latin-1, not UTF-8)
# ---------------------------------------------------------------------------

def test_read_csv_latin1_fallback(tmp_path):
    # 0xe9 is "é" in latin-1/cp1252 but invalid as standalone UTF-8.
    csv_path = tmp_path / "legacy.csv"
    csv_path.write_bytes(b"name,team\nC\xe9dric,Arsenal\n")

    df = _read_csv(csv_path)

    assert len(df) == 1
    assert df.iloc[0]["name"] == "Cédric"
    assert df.iloc[0]["team"] == "Arsenal"


def test_read_csv_missing_returns_empty(tmp_path):
    assert _read_csv(tmp_path / "nope.csv").empty


# ---------------------------------------------------------------------------
# 1. Happy path — all 5 tables, season column, row counts
# ---------------------------------------------------------------------------

def test_happy_path_all_five_tables(tmp_historical_root, tmp_path):
    source = _stage_vaastav_source(tmp_path)

    result = import_season(SEASON, source)

    assert isinstance(result, ImportResult)
    assert result.ok is True
    assert result.season == SEASON
    assert result.error is None

    out_dir = merged_parquet_dir(SEASON)
    expected_tables = ["players", "teams", "events", "fixtures", "player_gw_stats"]
    for name in expected_tables:
        path = out_dir / f"{name}.parquet"
        assert path.exists(), f"missing {path}"
        df = pd.read_parquet(path)
        assert "season" in df.columns, f"{name} missing season column"
        assert (df["season"] == SEASON).all(), f"{name} has wrong season value(s)"

    # Row counts match the fixture sizes
    assert result.row_counts["players"] == 3
    assert result.row_counts["teams"] == 2
    assert result.row_counts["fixtures"] == 3
    assert result.row_counts["player_gw_stats"] == 6  # 3 players x 2 gw files
    assert result.row_counts["events"] == 2  # events 1 and 2

    players_df = pd.read_parquet(out_dir / "players.parquet")
    assert set(players_df["player_id"].tolist()) == {1, 2, 3}
    assert "web_name" in players_df.columns
    assert "Haaland" in players_df["web_name"].tolist()


# ---------------------------------------------------------------------------
# 2. player_gw_stats per-GW concatenation
# ---------------------------------------------------------------------------

def test_player_gw_stats_concatenation_event_ids(tmp_historical_root, tmp_path):
    source = _stage_vaastav_source(tmp_path)

    result = import_season(SEASON, source)
    assert result.ok is True

    out_dir = merged_parquet_dir(SEASON)
    gw_df = pd.read_parquet(out_dir / "player_gw_stats.parquet")

    assert len(gw_df) == 6
    assert set(gw_df["event_id"].unique().tolist()) == {1, 2}
    assert (gw_df["season"] == SEASON).all()

    # 3 rows per event_id (one per player)
    assert (gw_df["event_id"] == 1).sum() == 3
    assert (gw_df["event_id"] == 2).sum() == 3

    # player_id sourced from `element`
    assert set(gw_df.loc[gw_df["event_id"] == 1, "player_id"].tolist()) == {1, 2, 3}
    assert set(gw_df.loc[gw_df["event_id"] == 2, "player_id"].tolist()) == {1, 2, 3}

    # source / source_captured_at / captured_at injected
    assert (gw_df["source"] == "vaastav").all()
    assert gw_df["captured_at"].notna().all()
    assert gw_df["source_captured_at"].notna().all()


# ---------------------------------------------------------------------------
# 3. events reconstruction from fixtures
# ---------------------------------------------------------------------------

def test_events_reconstruction_from_fixtures(tmp_historical_root, tmp_path):
    source = _stage_vaastav_source(tmp_path)

    result = import_season(SEASON, source)
    assert result.ok is True

    out_dir = merged_parquet_dir(SEASON)
    events_df = pd.read_parquet(out_dir / "events.parquet")

    assert len(events_df) == 2
    assert set(events_df["event_id"].tolist()) == {1, 2}
    assert (events_df["season"] == SEASON).all()
    assert (events_df["data_checked"] == True).all()  # noqa: E712
    assert (events_df["finished"] == True).all()  # noqa: E712

    # event 1 has two fixtures (rows 1,2): min kickoff = 2024-08-17T14:00:00Z
    ev1 = events_df.loc[events_df["event_id"] == 1].iloc[0]
    assert ev1["deadline_time"] == "2024-08-17T14:00:00Z"
    assert ev1["name"] == "Gameweek 1"

    # event 2 has one fixture (row 3): kickoff = 2024-08-24T14:00:00Z
    ev2 = events_df.loc[events_df["event_id"] == 2].iloc[0]
    assert ev2["deadline_time"] == "2024-08-24T14:00:00Z"
    assert ev2["name"] == "Gameweek 2"


# ---------------------------------------------------------------------------
# 4. Missing optional column → null + WARNING (Decision 4)
# ---------------------------------------------------------------------------

def test_missing_optional_column_nulls_and_warns(tmp_historical_root, tmp_path, caplog):
    source = _stage_vaastav_source(tmp_path)

    with caplog.at_level(logging.WARNING, logger="fpl_historical.vaastav_import"):
        result = import_season(SEASON, source)

    assert result.ok is True

    # gw2.csv has no `xP` column -> rows for event_id == 2 should be null in xP
    out_dir = merged_parquet_dir(SEASON)
    gw_df = pd.read_parquet(out_dir / "player_gw_stats.parquet")
    assert "xP" in gw_df.columns

    gw2_rows = gw_df.loc[gw_df["event_id"] == 2]
    assert gw2_rows["xP"].isna().all()

    # gw1.csv DOES have xP -> those rows should be populated
    gw1_rows = gw_df.loc[gw_df["event_id"] == 1]
    assert gw1_rows["xP"].notna().all()

    # missing_columns recorded on the result
    assert "player_gw_stats" in result.missing_columns
    assert "xP" in result.missing_columns["player_gw_stats"]

    # WARNING logged
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("missing_columns" in r.getMessage() for r in warning_records)
    assert any("xP" in r.getMessage() for r in warning_records)


# ---------------------------------------------------------------------------
# 5. Pointer file shape
# ---------------------------------------------------------------------------

def test_pointer_file_shape(tmp_historical_root, tmp_path):
    source = _stage_vaastav_source(tmp_path)

    result = import_season(SEASON, source)
    assert result.ok is True

    pointer_path = owned_latest_pointer_path(SEASON)
    assert pointer_path.exists()

    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))

    assert pointer["season"] == SEASON
    assert "merged_at" in pointer and pointer["merged_at"]
    # merged_at must use the store's canonical Windows-safe dash format
    # (%Y-%m-%dT%H-%M-%SZ) so the sync layer can parse it for staleness.
    from datetime import datetime
    datetime.strptime(pointer["merged_at"], "%Y-%m-%dT%H-%M-%SZ")
    # The staged source is a plain directory (not a git clone), so the
    # provenance label falls back to the pinned SHA flagged -unverified.
    assert pointer["source"] == f"vaastav@{VAASTAV_PINNED_SHA}-unverified"
    assert pointer["row_counts"] == result.row_counts
    assert set(pointer["row_counts"].keys()) == {
        "players", "teams", "events", "fixtures", "player_gw_stats",
    }


# ---------------------------------------------------------------------------
# 6. Re-import overwrites cleanly (idempotent, no duplication)
# ---------------------------------------------------------------------------

def test_reimport_overwrites_cleanly(tmp_historical_root, tmp_path):
    source = _stage_vaastav_source(tmp_path)

    result1 = import_season(SEASON, source)
    assert result1.ok is True

    out_dir = merged_parquet_dir(SEASON)
    gw_df_first = pd.read_parquet(out_dir / "player_gw_stats.parquet")
    assert len(gw_df_first) == 6

    result2 = import_season(SEASON, source)
    assert result2.ok is True

    gw_df_second = pd.read_parquet(out_dir / "player_gw_stats.parquet")
    # No concatenation: row count stays the same, no duplicate (player_id, event_id)
    assert len(gw_df_second) == 6
    dup_mask = gw_df_second.duplicated(subset=["player_id", "event_id"])
    assert not dup_mask.any()

    players_df = pd.read_parquet(out_dir / "players.parquet")
    assert len(players_df) == 3

    # Pointer reflects the second run's row counts (still correct/clean)
    pointer = json.loads(owned_latest_pointer_path(SEASON).read_text(encoding="utf-8"))
    assert pointer["row_counts"]["player_gw_stats"] == 6


# ---------------------------------------------------------------------------
# Bonus: missing season directory -> clean failure (no raise)
# ---------------------------------------------------------------------------

def test_missing_season_directory_returns_failed_result(tmp_historical_root, tmp_path):
    # Stage a source with NO matching season directory
    source_root = tmp_path / "_vaastav_source_empty"
    (source_root / "data").mkdir(parents=True)

    result = import_season(SEASON, source_root)

    assert result.ok is False
    assert result.season == SEASON
    assert result.error is not None
    assert "not found" in result.error


# ---------------------------------------------------------------------------
# Bonus: a real git clone stamps the actual HEAD SHA into the pointer
# ---------------------------------------------------------------------------

def test_pointer_stamps_actual_git_sha(tmp_historical_root, tmp_path):
    import subprocess

    source = _stage_vaastav_source(tmp_path)
    # Turn the staged source into a real git repo with one commit.
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "-C", str(source), "init", "-q"], check=True, env=env)
    subprocess.run(["git", "-C", str(source), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "fixture"], check=True, env=env)
    head = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True, env=env,
    ).stdout.strip()

    result = import_season(SEASON, source)
    assert result.ok is True

    pointer = json.loads(owned_latest_pointer_path(SEASON).read_text(encoding="utf-8"))
    assert pointer["source"] == f"vaastav@{head}"

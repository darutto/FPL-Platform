"""Offline tests for fpl_tactical.store + ingest_season with a stub client."""

from __future__ import annotations

import pandas as pd

from fpl_tactical import store
from fpl_tactical.ingest import ingest_season, normalize_shots
from fpl_tactical.paths import (
    latest_pointer_path,
    shots_parquet_path,
    tactical_root,
)
from tests.conftest import SAMPLE_SEASON, load_sample_frames


class StubClient:
    """UnderstatClient stand-in that serves the canned frames (no network)."""

    def fetch_raw(self, season):
        return load_sample_frames()

    @staticmethod
    def source_version():
        return "stub-1.0"


def test_tactical_root_respects_env(tmp_tactical_root):
    assert tactical_root() == tmp_tactical_root
    assert shots_parquet_path("2025-2026").is_relative_to(tmp_tactical_root)


def test_read_shots_none_when_absent(tmp_tactical_root):
    assert store.read_shots(SAMPLE_SEASON) is None
    assert store.read_pointer(SAMPLE_SEASON) is None


def test_write_read_round_trip(tmp_tactical_root, sample_frames):
    shots, schedule = sample_frames
    df = normalize_shots(shots, schedule, SAMPLE_SEASON)
    store.write_shots(df, SAMPLE_SEASON)
    back = store.read_shots(SAMPLE_SEASON)
    assert len(back) == len(df)
    assert list(back.columns) == list(df.columns)
    # parquet round-trips object string columns as pandas StringDtype —
    # values must match exactly, dtype flavor may differ
    pd.testing.assert_frame_equal(back, df.reset_index(drop=True), check_dtype=False)


def test_rewrite_is_idempotent_no_duplication(tmp_tactical_root, sample_frames):
    shots, schedule = sample_frames
    df = normalize_shots(shots, schedule, SAMPLE_SEASON)
    store.write_shots(df, SAMPLE_SEASON)
    store.write_shots(df, SAMPLE_SEASON)
    assert len(store.read_shots(SAMPLE_SEASON)) == len(df)
    # no stray temp file left behind
    assert not shots_parquet_path(SAMPLE_SEASON).with_suffix(".parquet.tmp").exists()


def test_pointer_round_trip(tmp_tactical_root):
    pointer = {"season": SAMPLE_SEASON, "ingested_at": "2026-07-07T00:00:00Z"}
    store.write_pointer(pointer, SAMPLE_SEASON)
    assert store.read_pointer(SAMPLE_SEASON) == pointer
    assert latest_pointer_path(SAMPLE_SEASON).exists()


def test_ingest_season_end_to_end_with_stub(tmp_tactical_root):
    pointer = ingest_season(SAMPLE_SEASON, client=StubClient())
    assert pointer["season"] == SAMPLE_SEASON
    assert pointer["source"] == "understat via soccerdata"
    assert pointer["source_version"] == "stub-1.0"
    assert pointer["n_matches"] == 2
    assert pointer["n_shots"] == 6
    assert set(pointer) == {
        "season", "ingested_at", "source", "source_version", "n_matches", "n_shots",
    }
    assert len(store.read_shots(SAMPLE_SEASON)) == 6
    assert store.read_pointer(SAMPLE_SEASON) == pointer


def test_reingest_updates_pointer_same_counts(tmp_tactical_root):
    first = ingest_season(SAMPLE_SEASON, client=StubClient())
    second = ingest_season(SAMPLE_SEASON, client=StubClient())
    assert second["n_shots"] == first["n_shots"]
    assert second["n_matches"] == first["n_matches"]
    assert len(store.read_shots(SAMPLE_SEASON)) == first["n_shots"]
    # ingested_at refreshes (equal timestamps allowed within one second)
    assert second["ingested_at"] >= first["ingested_at"]
    assert store.read_pointer(SAMPLE_SEASON) == second

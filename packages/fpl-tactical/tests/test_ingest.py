"""Offline tests for fpl_tactical.ingest.normalize_shots (no network)."""

from __future__ import annotations

import pandas as pd
import pytest

from fpl_tactical import PENALTY_SITUATION
from fpl_tactical.ingest import SHOT_COLUMNS, IngestError, normalize_shots
from tests.conftest import SAMPLE_SEASON


def _normalized(sample_frames):
    shots, schedule = sample_frames
    return normalize_shots(shots, schedule, SAMPLE_SEASON)


def test_schema_columns_exact_order(sample_frames):
    out = _normalized(sample_frames)
    assert list(out.columns) == SHOT_COLUMNS


def test_season_and_match_id(sample_frames):
    out = _normalized(sample_frames)
    assert (out["season"] == SAMPLE_SEASON).all()
    assert out["match_id"].dtype == "int64"
    assert set(out["match_id"]) == {1001, 1002}


def test_home_shot_derivation(sample_frames):
    out = _normalized(sample_frames)
    ana = out[out["player"] == "Ana Striker"]
    assert ana["is_home_shot"].all()  # Alpha FC is home in game 1001
    assert (ana["conceding_team"] == "Beta United").all()


def test_away_shot_derivation(sample_frames):
    out = _normalized(sample_frames)
    dani = out[out["player"] == "Dani Nine"]
    assert not dani["is_home_shot"].any()  # Delta Town is away in game 1002
    assert (dani["conceding_team"] == "Gamma City").all()


def test_situation_strings_stored_verbatim(sample_frames):
    out = _normalized(sample_frames)
    assert "Open Play" in set(out["situation"])
    assert "From Corner" in set(out["situation"])
    assert "OpenPlay" not in set(out["situation"])  # raw Understat style must not appear


def test_on_signature_na_row_relabelled_to_penalty(sample_frames):
    out = _normalized(sample_frames)
    pens = out[out["situation"] == PENALTY_SITUATION]
    assert len(pens) == 1
    assert pens.iloc[0]["player"] == "Bruno Wing"
    assert out["situation"].notna().all()


def test_off_signature_na_row_fails_loudly(sample_frames):
    shots, schedule = sample_frames
    bad = shots.copy()
    # NA situation at a normal open-play coordinate — not the penalty spot
    bad.loc[len(bad)] = {
        "game_id": 1002, "team": "Gamma City", "player": "Eve Drift",
        "minute": 55, "location_x": 0.75, "location_y": 0.40, "xg": 0.06,
        "situation": None, "body_part": "Right Foot", "result": "Missed Shot",
    }
    with pytest.raises(IngestError, match="penalty"):
        normalize_shots(bad, schedule, SAMPLE_SEASON)


def test_off_signature_xg_alone_trips_guard(sample_frames):
    shots, schedule = sample_frames
    bad = shots.copy()
    # Penalty-spot coordinates but implausible xG — still schema drift
    bad.loc[len(bad)] = {
        "game_id": 1002, "team": "Delta Town", "player": "Eve Drift",
        "minute": 60, "location_x": 0.885, "location_y": 0.5, "xg": 0.30,
        "situation": None, "body_part": "Right Foot", "result": "Saved Shot",
    }
    with pytest.raises(IngestError):
        normalize_shots(bad, schedule, SAMPLE_SEASON)


def test_missing_required_column_fails(sample_frames):
    shots, schedule = sample_frames
    with pytest.raises(IngestError, match="missing expected columns"):
        normalize_shots(shots.drop(columns=["xg"]), schedule, SAMPLE_SEASON)


def test_game_id_absent_from_schedule_fails(sample_frames):
    shots, schedule = sample_frames
    with pytest.raises(IngestError, match="absent from the schedule"):
        normalize_shots(shots, schedule[schedule["game_id"] != 1002], SAMPLE_SEASON)


def test_team_matching_neither_side_fails(sample_frames):
    shots, schedule = sample_frames
    bad = shots.copy()
    bad.loc[bad.index[0], "team"] = "Zeta Rovers"
    with pytest.raises(IngestError, match="neither home nor"):
        normalize_shots(bad, schedule, SAMPLE_SEASON)


def test_date_is_iso_string(sample_frames):
    out = _normalized(sample_frames)
    assert (out["date"] == "2025-08-16T15:00:00").sum() == 4  # game 1001 rows

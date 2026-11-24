"""
tests/test_merge.py
===================
Tests for fpl_historical.merge.build_merged_parquet (CONTRACT §10 / H2b).

Seven scenarios covering: baseline-only, baseline+incremental, overlap dedup,
tie-break, failed incremental ignored, idempotency, and pointer correctness.
"""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

import pandas as pd
import pytest

from conftest import (
    MINIMAL_BOOTSTRAP,
    MINIMAL_ELEMENT_SUMMARY,
    MINIMAL_EVENT_LIVE,
    MINIMAL_FIXTURES,
)
from fpl_historical.manifest import Manifest, write_manifest
from fpl_historical.merge import build_merged_parquet, validate_player_gw_stats
from fpl_historical.paths import (
    merged_parquet_dir,
    owned_latest_pointer_path,
    season_dir,
)

SEASON = "2025-2026"

# ---------------------------------------------------------------------------
# Helper: write baseline (raw dir) and update _latest.json
# ---------------------------------------------------------------------------

def _write_gz(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(json.dumps(data).encode("utf-8"))


def _write_baseline_complete(
    tmp_path: Path,
    captured_at: str = "2026-05-25T14-22-03Z",
    element_summary: dict | None = None,
    bootstrap: dict | None = None,
) -> Path:
    """Write a minimal complete baseline raw dir and a _latest.json pointer."""
    if bootstrap is None:
        bootstrap = MINIMAL_BOOTSTRAP
    if element_summary is None:
        element_summary = MINIMAL_ELEMENT_SUMMARY

    raw_dir = tmp_path / "seasons" / SEASON / "raw" / captured_at
    raw_dir.mkdir(parents=True, exist_ok=True)
    es_dir = raw_dir / "element-summary"
    es_dir.mkdir(exist_ok=True)

    bs_bytes = json.dumps(bootstrap).encode("utf-8")
    _write_gz(raw_dir / "bootstrap-static.json.gz", bootstrap)
    _write_gz(raw_dir / "fixtures.json.gz", MINIMAL_FIXTURES)

    for elem in bootstrap.get("elements", []):
        eid = elem["id"]
        _write_gz(es_dir / f"{eid}.json.gz", element_summary)

    m = Manifest(
        schema_version=1,
        season=SEASON,
        status="complete",
        captured_at_utc=captured_at,
        git_sha="abc1234",
        fpl_endpoints={
            "bootstrap-static": {"url": "https://...", "status": 200,
                                  "bytes": len(bs_bytes), "sha256": ""},
            "fixtures": {"url": "https://...", "status": 200, "bytes": 0, "sha256": ""},
            "element-summary": {"count": 2, "failures": [], "sha256_aggregate": ""},
        },
        current_event_id=38,
        elapsed_seconds=1.0,
    )
    write_manifest(raw_dir, m)

    # Write _latest.json pointing to this raw dir
    latest_path = tmp_path / "seasons" / SEASON / "_latest.json"
    latest_path.write_text(
        json.dumps({"raw_dir": captured_at, "parquet_built_at": captured_at}),
        encoding="utf-8",
    )
    return raw_dir


def _write_incremental_complete(
    tmp_path: Path,
    gw: int,
    captured_at: str,
    status: str = "complete",
    event_live: dict | None = None,
    bootstrap: dict | None = None,
) -> Path:
    """Write a minimal incremental snapshot dir."""
    if event_live is None:
        event_live = MINIMAL_EVENT_LIVE
    if bootstrap is None:
        bootstrap = MINIMAL_BOOTSTRAP

    inc_dir = (
        tmp_path / "seasons" / SEASON / "incremental" / f"gw{gw:02d}" / captured_at
    )
    inc_dir.mkdir(parents=True, exist_ok=True)

    _write_gz(inc_dir / "bootstrap-static.json.gz", bootstrap)
    _write_gz(inc_dir / "fixtures.json.gz", MINIMAL_FIXTURES)
    _write_gz(inc_dir / "event-live.json.gz", event_live)

    m = Manifest(
        schema_version=2,
        season=SEASON,
        status=status,  # type: ignore[arg-type]
        captured_at_utc=captured_at,
        git_sha="abc1234",
        fpl_endpoints={
            "bootstrap-static": {"url": "https://...", "status": 200, "bytes": 0, "sha256": ""},
            "fixtures": {"url": "https://...", "status": 200, "bytes": 0, "sha256": ""},
            "event-live": {"url": "https://...", "status": 200, "bytes": 0, "sha256": ""},
        },
        current_event_id=None,
        elapsed_seconds=0.5,
        kind="incremental",
        gameweek=gw,
        gw_state={
            "finished": True,
            "data_checked": True,
            "is_current": False,
            "deadline_time": "2026-05-12T17:30:00Z",
        },
    )
    write_manifest(inc_dir, m)
    return inc_dir


# ---------------------------------------------------------------------------
# (i) Baseline-only: no incrementals present
# ---------------------------------------------------------------------------

class TestBaselineOnly:
    def test_five_parquet_files_written(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root)
        build_merged_parquet(SEASON)
        out_dir = merged_parquet_dir(SEASON)
        for name in ("players", "teams", "events", "fixtures", "player_gw_stats"):
            assert (out_dir / f"{name}.parquet").exists(), f"{name}.parquet missing"

    def test_owned_latest_json_written(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root)
        build_merged_parquet(SEASON)
        ptr_path = owned_latest_pointer_path(SEASON)
        assert ptr_path.exists()

    def test_player_gw_stats_source_is_baseline(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root)
        build_merged_parquet(SEASON)
        df = pd.read_parquet(merged_parquet_dir(SEASON) / "player_gw_stats.parquet")
        assert (df["source"] == "baseline").all(), "All rows should have source='baseline'"

    def test_incrementals_empty_in_pointer(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root)
        pointer = build_merged_parquet(SEASON)
        assert pointer["incrementals"] == []

    def test_row_count_matches_element_summary(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root)
        build_merged_parquet(SEASON)
        df = pd.read_parquet(merged_parquet_dir(SEASON) / "player_gw_stats.parquet")
        # MINIMAL_ELEMENT_SUMMARY.history has 1 row; 2 players → 2 rows
        # (both elements get the same summary written for each player id)
        assert len(df) == len(MINIMAL_BOOTSTRAP["elements"]) * len(MINIMAL_ELEMENT_SUMMARY["history"])

    def test_sampled_row_values(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root)
        build_merged_parquet(SEASON)
        df = pd.read_parquet(merged_parquet_dir(SEASON) / "player_gw_stats.parquet")
        row = df[df["player_id"] == 1].iloc[0]
        assert row["total_points"] == 12
        assert row["goals_scored"] == 2


# ---------------------------------------------------------------------------
# (ii) One incremental, no overlap with baseline history
# ---------------------------------------------------------------------------

class TestBaselinePlusNonOverlappingIncremental:
    def test_both_sources_present(self, tmp_historical_root):
        # Baseline covers GW 37 only (via MINIMAL_ELEMENT_SUMMARY round=37)
        _write_baseline_complete(tmp_historical_root, captured_at="2026-05-25T14-22-03Z")
        # Incremental covers GW 38
        _write_incremental_complete(
            tmp_historical_root, gw=38, captured_at="2026-05-25T18-22-03Z"
        )
        build_merged_parquet(SEASON)
        df = pd.read_parquet(merged_parquet_dir(SEASON) / "player_gw_stats.parquet")

        baseline_rows = df[df["source"] == "baseline"]
        incremental_rows = df[df["source"] == "incremental"]
        assert len(baseline_rows) > 0, "Should have baseline rows (GW37)"
        assert len(incremental_rows) > 0, "Should have incremental rows (GW38)"

    def test_baseline_rows_have_event_id_37(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root, captured_at="2026-05-25T14-22-03Z")
        _write_incremental_complete(
            tmp_historical_root, gw=38, captured_at="2026-05-25T18-22-03Z"
        )
        build_merged_parquet(SEASON)
        df = pd.read_parquet(merged_parquet_dir(SEASON) / "player_gw_stats.parquet")
        assert (df[df["source"] == "baseline"]["event_id"] == 37).all()

    def test_incremental_rows_have_event_id_38(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root, captured_at="2026-05-25T14-22-03Z")
        _write_incremental_complete(
            tmp_historical_root, gw=38, captured_at="2026-05-25T18-22-03Z"
        )
        build_merged_parquet(SEASON)
        df = pd.read_parquet(merged_parquet_dir(SEASON) / "player_gw_stats.parquet")
        assert (df[df["source"] == "incremental"]["event_id"] == 38).all()

    def test_pointer_incrementals_has_one_entry(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root, captured_at="2026-05-25T14-22-03Z")
        _write_incremental_complete(
            tmp_historical_root, gw=38, captured_at="2026-05-25T18-22-03Z"
        )
        pointer = build_merged_parquet(SEASON)
        assert len(pointer["incrementals"]) == 1
        assert pointer["incrementals"][0]["gameweek"] == 38


# ---------------------------------------------------------------------------
# (iii) Overlap — baseline and incremental cover same (player_id, event_id)
# ---------------------------------------------------------------------------

class TestOverlapDedup:
    def _make_summary_for_gw38(self) -> dict:
        """Element summary where history row has round=38."""
        return {
            "history": [{
                "element": 1,
                "fixture": 380,
                "opponent_team": 11,
                "total_points": 5,
                "was_home": True,
                "kickoff_time": "2026-05-17T14:00:00Z",
                "team_h_score": 1,
                "team_a_score": 1,
                "round": 38,
                "minutes": 90,
                "goals_scored": 1,
                "assists": 0,
                "clean_sheets": 0,
                "goals_conceded": 1,
                "bonus": 0,
                "bps": 20,
                "expected_goals": "0.60",
                "expected_assists": "0.10",
                "expected_goal_involvements": "0.70",
                "value": 145,
            }],
            "fixtures": [],
        }

    def test_newer_incremental_wins(self, tmp_historical_root):
        """Baseline has (1, 38) at T1; incremental has (1, 38) at T2 > T1 → incremental wins."""
        summary = self._make_summary_for_gw38()
        _write_baseline_complete(
            tmp_historical_root,
            captured_at="2026-05-25T10-00-00Z",
            element_summary=summary,
        )
        el = {"id": 1, "stats": {"minutes": 90, "goals_scored": 2, "total_points": 11},
              "explain": [], "modified": False}
        inc_event_live = {"elements": [el]}
        _write_incremental_complete(
            tmp_historical_root, gw=38,
            captured_at="2026-05-25T18-00-00Z",
            event_live=inc_event_live,
        )
        build_merged_parquet(SEASON)
        df = pd.read_parquet(merged_parquet_dir(SEASON) / "player_gw_stats.parquet")

        overlap = df[(df["player_id"] == 1) & (df["event_id"] == 38)]
        assert len(overlap) == 1, "Exactly one row should survive for (1, 38)"
        assert overlap.iloc[0]["source"] == "incremental"

    def test_newer_baseline_wins(self, tmp_historical_root):
        """Baseline has (1, 38) at T2 > T1; incremental has (1, 38) at T1 → baseline wins."""
        summary = self._make_summary_for_gw38()
        _write_baseline_complete(
            tmp_historical_root,
            captured_at="2026-05-25T20-00-00Z",
            element_summary=summary,
        )
        el = {"id": 1, "stats": {"minutes": 90, "goals_scored": 2, "total_points": 11},
              "explain": [], "modified": False}
        inc_event_live = {"elements": [el]}
        _write_incremental_complete(
            tmp_historical_root, gw=38,
            captured_at="2026-05-25T10-00-00Z",
            event_live=inc_event_live,
        )
        build_merged_parquet(SEASON)
        df = pd.read_parquet(merged_parquet_dir(SEASON) / "player_gw_stats.parquet")

        overlap = df[(df["player_id"] == 1) & (df["event_id"] == 38)]
        assert len(overlap) == 1, "Exactly one row should survive for (1, 38)"
        assert overlap.iloc[0]["source"] == "baseline"


# ---------------------------------------------------------------------------
# (iv) Tie-break: incremental wins
# ---------------------------------------------------------------------------

class TestTieBreak:
    def test_incremental_wins_on_identical_captured_at(self, tmp_historical_root):
        """When baseline and incremental have same captured_at, incremental wins."""
        same_ts = "2026-05-25T14-00-00Z"
        summary = {
            "history": [{
                "element": 1,
                "round": 38,
                "total_points": 5,
                "minutes": 45,
                "goals_scored": 0,
                "assists": 0,
                "clean_sheets": 0,
                "goals_conceded": 2,
                "bonus": 0,
                "bps": 10,
                "value": 145,
                "was_home": True,
                "opponent_team": 11,
                "expected_goals": "0.0",
                "expected_assists": "0.0",
                "expected_goal_involvements": "0.0",
            }],
            "fixtures": [],
        }
        _write_baseline_complete(
            tmp_historical_root, captured_at=same_ts, element_summary=summary
        )
        inc_el = {"id": 1,
                  "stats": {"minutes": 90, "goals_scored": 1, "total_points": 8},
                  "explain": [], "modified": False}
        _write_incremental_complete(
            tmp_historical_root, gw=38, captured_at=same_ts,
            event_live={"elements": [inc_el]},
        )
        build_merged_parquet(SEASON)
        df = pd.read_parquet(merged_parquet_dir(SEASON) / "player_gw_stats.parquet")

        overlap = df[(df["player_id"] == 1) & (df["event_id"] == 38)]
        assert len(overlap) == 1
        assert overlap.iloc[0]["source"] == "incremental", \
            "On tie, incremental should win per CONTRACT §10.4"


# ---------------------------------------------------------------------------
# (v) Failed incremental ignored
# ---------------------------------------------------------------------------

class TestFailedIncrementalIgnored:
    def test_failed_snapshot_not_contributed(self, tmp_historical_root):
        """Incremental with status='failed' for gw=38 contributes no rows."""
        summary_gw38 = {
            "history": [{
                "element": 1,
                "round": 38,
                "total_points": 5,
                "minutes": 90,
                "goals_scored": 0,
                "assists": 0,
                "clean_sheets": 0,
                "goals_conceded": 1,
                "bonus": 0,
                "bps": 15,
                "value": 145,
                "was_home": True,
                "opponent_team": 11,
                "expected_goals": "0.0",
                "expected_assists": "0.0",
                "expected_goal_involvements": "0.0",
            }],
            "fixtures": [],
        }
        _write_baseline_complete(
            tmp_historical_root,
            captured_at="2026-05-25T10-00-00Z",
            element_summary=summary_gw38,
        )
        # Write a failed incremental for gw=38 with a LATER captured_at
        _write_incremental_complete(
            tmp_historical_root, gw=38,
            captured_at="2026-05-25T18-00-00Z",
            status="failed",
        )
        build_merged_parquet(SEASON)
        df = pd.read_parquet(merged_parquet_dir(SEASON) / "player_gw_stats.parquet")

        # The failed incremental must not contribute — only baseline data present
        inc_rows = df[df["source"] == "incremental"]
        assert len(inc_rows) == 0, "Failed incremental should not contribute rows"

        # Baseline row for (1, 38) should survive
        overlap = df[(df["player_id"] == 1) & (df["event_id"] == 38)]
        assert len(overlap) > 0, "Baseline row for (1, 38) should be present"
        assert overlap.iloc[0]["source"] == "baseline"

    def test_failed_snapshot_not_in_pointer(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root, captured_at="2026-05-25T10-00-00Z")
        _write_incremental_complete(
            tmp_historical_root, gw=38,
            captured_at="2026-05-25T18-00-00Z",
            status="failed",
        )
        pointer = build_merged_parquet(SEASON)
        assert pointer["incrementals"] == [], \
            "Failed incremental should not appear in pointer"


# ---------------------------------------------------------------------------
# (vi) Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_parquet_contents_identical_on_rerun(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root, captured_at="2026-05-25T14-22-03Z")
        _write_incremental_complete(
            tmp_historical_root, gw=38, captured_at="2026-05-25T18-22-03Z"
        )

        build_merged_parquet(SEASON)
        out_dir = merged_parquet_dir(SEASON)

        snapshots_1 = {
            name: pd.read_parquet(out_dir / f"{name}.parquet")
            for name in ("players", "teams", "events", "fixtures", "player_gw_stats")
        }

        # Small sleep to ensure merged_at would differ
        time.sleep(0.01)
        build_merged_parquet(SEASON)

        snapshots_2 = {
            name: pd.read_parquet(out_dir / f"{name}.parquet")
            for name in ("players", "teams", "events", "fixtures", "player_gw_stats")
        }

        for name in snapshots_1:
            df1 = snapshots_1[name].reset_index(drop=True)
            df2 = snapshots_2[name].reset_index(drop=True)
            assert df1.equals(df2), f"{name}.parquet differs between runs"

    def test_pointer_merged_at_differs_but_rest_same(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root, captured_at="2026-05-25T14-22-03Z")
        ptr1 = build_merged_parquet(SEASON)
        time.sleep(1.1)  # ensure second-level granularity differs
        ptr2 = build_merged_parquet(SEASON)

        assert ptr1["merged_at"] != ptr2["merged_at"], "merged_at should differ"
        assert ptr1["baseline"] == ptr2["baseline"]
        assert ptr1["incrementals"] == ptr2["incrementals"]
        assert ptr1["row_counts"] == ptr2["row_counts"]


# ---------------------------------------------------------------------------
# (vii) Pointer correctness
# ---------------------------------------------------------------------------

class TestPointerCorrectness:
    def test_schema_version_is_1(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root)
        ptr = build_merged_parquet(SEASON)
        assert ptr["schema_version"] == 1

    def test_incrementals_sorted_by_gameweek_ascending(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root)
        _write_incremental_complete(
            tmp_historical_root, gw=38, captured_at="2026-05-25T18-00-00Z"
        )
        _write_incremental_complete(
            tmp_historical_root, gw=1, captured_at="2026-05-25T08-00-00Z"
        )
        ptr = build_merged_parquet(SEASON)
        gws = [e["gameweek"] for e in ptr["incrementals"]]
        assert gws == sorted(gws), f"incrementals not sorted by gameweek: {gws}"

    def test_relative_paths(self, tmp_historical_root):
        _write_baseline_complete(
            tmp_historical_root, captured_at="2026-05-25T14-22-03Z"
        )
        _write_incremental_complete(
            tmp_historical_root, gw=1, captured_at="2026-05-25T08-00-00Z"
        )
        ptr = build_merged_parquet(SEASON)
        # Baseline raw_dir should not be absolute
        assert not ptr["baseline"]["raw_dir"].startswith("/")
        assert not ptr["baseline"]["raw_dir"].startswith("C:")
        assert ptr["baseline"]["raw_dir"].startswith("raw/")
        # Incremental raw_dir should start with incremental/
        assert ptr["incrementals"][0]["raw_dir"].startswith("incremental/")

    def test_row_counts_match_parquet(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root)
        _write_incremental_complete(
            tmp_historical_root, gw=38, captured_at="2026-05-25T18-22-03Z"
        )
        ptr = build_merged_parquet(SEASON)
        out_dir = merged_parquet_dir(SEASON)
        for name in ("players", "teams", "events", "fixtures", "player_gw_stats"):
            df = pd.read_parquet(out_dir / f"{name}.parquet")
            assert ptr["row_counts"][name] == len(df), \
                f"row_count mismatch for {name}: ptr={ptr['row_counts'][name]} vs actual={len(df)}"

    def test_baseline_none_when_no_latest_json(self, tmp_historical_root):
        """When _latest.json is absent, pointer.baseline must be null."""
        ptr = build_merged_parquet(SEASON)
        assert ptr["baseline"] is None

    def test_merged_at_format(self, tmp_historical_root):
        """merged_at must follow the filesystem-safe ISO format YYYY-MM-DDTHH-MM-SSZ."""
        ptr = build_merged_parquet(SEASON)
        import re
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$"
        assert re.match(pattern, ptr["merged_at"]), \
            f"merged_at format wrong: {ptr['merged_at']!r}"

    def test_pointer_written_to_disk_matches_returned_dict(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root)
        ptr = build_merged_parquet(SEASON)
        on_disk = json.loads(owned_latest_pointer_path(SEASON).read_text(encoding="utf-8"))
        assert ptr == on_disk


# ---------------------------------------------------------------------------
# (viii) Double gameweek — one row per FIXTURE must survive (CONTRACT §5.1/§10.4)
# ---------------------------------------------------------------------------

def _hist_row(fixture: int, rnd: int, pts: int, mins: int = 90, goals: int = 0) -> dict:
    row = dict(MINIMAL_ELEMENT_SUMMARY["history"][0])
    row.update({"fixture": fixture, "round": rnd, "total_points": pts, "minutes": mins, "goals_scored": goals})
    return row


def _double_summary(rnd: int = 37) -> dict:
    """Player history for a double gameweek: two fixtures share `round`."""
    return {"history": [_hist_row(371, rnd, 7, goals=1), _hist_row(372, rnd, 5)], "fixtures": []}


def _merged() -> pd.DataFrame:
    return pd.read_parquet(merged_parquet_dir(SEASON) / "player_gw_stats.parquet")


class TestDoubleGameweek:
    def test_both_fixture_rows_survive(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root, element_summary=_double_summary())
        build_merged_parquet(SEASON)
        rows = _merged()
        p1 = rows[(rows.player_id == 1) & (rows.event_id == 37)]
        assert sorted(p1.fixture.tolist()) == [371, 372], "second fixture of a double GW must not be dropped"

    def test_merged_points_equal_raw_history_sum(self, tmp_historical_root):
        """Invariant: per-player merged points == sum of that player's raw history."""
        summary = {"history": [_hist_row(371, 37, 7), _hist_row(372, 37, 5), _hist_row(381, 38, 2)], "fixtures": []}
        _write_baseline_complete(tmp_historical_root, element_summary=summary)
        build_merged_parquet(SEASON)
        got = _merged().groupby("player_id").total_points.sum()
        expected = sum(r["total_points"] for r in summary["history"])
        assert (got == expected).all() and len(got) == len(MINIMAL_BOOTSTRAP["elements"])

    def test_true_duplicate_still_collapses(self, tmp_historical_root):
        summary = {"history": [_hist_row(371, 37, 7), _hist_row(371, 37, 7)], "fixtures": []}  # same fixture twice
        _write_baseline_complete(tmp_historical_root, element_summary=summary)
        build_merged_parquet(SEASON)
        p1 = _merged()
        assert len(p1[(p1.player_id == 1) & (p1.event_id == 37)]) == 1

    def test_newer_incremental_aggregate_replaces_both_baseline_rows(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root, captured_at="2026-05-25T10-00-00Z", element_summary=_double_summary(38))
        el = {"id": 1, "stats": {"minutes": 180, "goals_scored": 1, "total_points": 12}, "explain": [], "modified": False}
        _write_incremental_complete(tmp_historical_root, gw=38, captured_at="2026-05-25T18-00-00Z",
                                    event_live={"elements": [el]})
        build_merged_parquet(SEASON)
        rows = _merged()
        p1 = rows[(rows.player_id == 1) & (rows.event_id == 38)]
        assert len(p1) == 1 and p1.iloc[0].source == "incremental" and p1.iloc[0].fixture != p1.iloc[0].fixture  # NaN fixture
        assert p1.iloc[0].total_points == 12

    def test_newer_baseline_keeps_both_rows_and_no_incremental(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root, captured_at="2026-05-25T18-00-00Z", element_summary=_double_summary(38))
        el = {"id": 1, "stats": {"minutes": 180, "goals_scored": 1, "total_points": 12}, "explain": [], "modified": False}
        _write_incremental_complete(tmp_historical_root, gw=38, captured_at="2026-05-25T10-00-00Z",
                                    event_live={"elements": [el]})
        build_merged_parquet(SEASON)
        rows = _merged()
        p1 = rows[(rows.player_id == 1) & (rows.event_id == 38)]
        assert sorted(p1.fixture.tolist()) == [371, 372]
        assert (p1.source == "baseline").all(), "an incremental aggregate must never sit beside per-fixture rows"
        assert p1.total_points.sum() == 12

    def test_rerun_is_idempotent_with_doubles(self, tmp_historical_root):
        _write_baseline_complete(tmp_historical_root, element_summary=_double_summary())
        build_merged_parquet(SEASON)
        first = _merged()
        build_merged_parquet(SEASON)
        pd.testing.assert_frame_equal(first, _merged())


class TestValidatePlayerGwStats:
    def _df(self, rows):
        return pd.DataFrame(rows, columns=["player_id", "event_id", "fixture", "source", "source_captured_at"])

    def test_valid_double_passes(self):
        validate_player_gw_stats(self._df([(1, 5, 51, "baseline", "T1"), (1, 5, 52, "baseline", "T1"),
                                           (2, 5, None, "incremental", "T2"), (3, 5, None, "vaastav", "T0")]))

    def test_duplicate_pk_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            validate_player_gw_stats(self._df([(1, 5, 51, "baseline", "T1"), (1, 5, 51, "baseline", "T1")]))

    def test_mixed_sources_for_one_key_rejected(self):
        with pytest.raises(ValueError, match="mix rows"):
            validate_player_gw_stats(self._df([(1, 5, 51, "baseline", "T1"), (1, 5, None, "incremental", "T2")]))

    def test_null_fixture_only_for_incremental_or_vaastav(self):
        with pytest.raises(ValueError, match="NULL fixture"):
            validate_player_gw_stats(self._df([(1, 5, None, "baseline", "T1")]))

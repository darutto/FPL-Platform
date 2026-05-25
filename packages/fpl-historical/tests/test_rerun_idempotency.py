"""
tests/test_rerun_idempotency.py
================================
Idempotency and freshness tests for capture + projection pipeline.

Uses the same mock pattern as test_capture.py.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests as _requests

from conftest import MINIMAL_BOOTSTRAP, MINIMAL_ELEMENT_SUMMARY, MINIMAL_FIXTURES
from fpl_historical.paths import latest_pointer_path, list_raw_dirs

_PATCH_TARGET = "fpl_historical._io.requests.get"

# Fixed base datetime for deterministic timestamps in tests
_BASE_DT = datetime(2026, 5, 25, 18, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Shared mock helpers (mirrors test_capture.py)
# ---------------------------------------------------------------------------

def _ok_response(payload) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    mock = MagicMock()
    mock.status_code = 200
    mock.content = body
    mock.json.return_value = copy.deepcopy(payload)
    mock.raise_for_status.return_value = None
    return mock


def _error_response(status_code: int = 500) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.content = b""
    mock.raise_for_status.side_effect = _requests.HTTPError(
        f"Mock HTTP {status_code}", response=mock
    )
    return mock


def _build_side_effects(
    element_summary_fail_ids: set[int] | None = None,
) -> list:
    fail_ids = element_summary_fail_ids or set()
    effects: list = [
        _ok_response(MINIMAL_BOOTSTRAP),
        _ok_response(MINIMAL_FIXTURES),
    ]
    for element in MINIMAL_BOOTSTRAP["elements"]:
        eid = element["id"]
        if eid in fail_ids:
            effects.append(_error_response(500))
        else:
            effects.append(_ok_response(MINIMAL_ELEMENT_SUMMARY))
    return effects


def _run_capture_and_project(
    season: str = "2025-2026",
    allow_missing: int = 0,
    promote_with_gaps: bool = False,
    element_summary_fail_ids: set[int] | None = None,
    ts_offset_seconds: int = 0,
):
    """Helper: run capture + conditional projection, return (manifest, raw_dir).

    *ts_offset_seconds* offsets the deterministic timestamp to ensure distinct
    directory names across rapid successive calls.
    """
    from fpl_historical.capture import capture_season
    from fpl_historical.paths import list_raw_dirs, parquet_dir, season_dir
    from fpl_historical.projections import build_parquet_from_raw

    ts_dt = _BASE_DT + timedelta(seconds=ts_offset_seconds)
    ts_safe = ts_dt.strftime("%Y-%m-%dT%H-%M-%SZ")

    # Create the raw dir with the controlled name before calling capture_season
    # by patching paths.new_raw_dir (imported into capture as new_raw_dir)
    def _fake_new_raw_dir(s: str) -> Path:
        raw_dir = season_dir(s) / "raw" / ts_safe
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "element-summary").mkdir(exist_ok=True)
        return raw_dir

    side_effects = _build_side_effects(element_summary_fail_ids)
    with patch(_PATCH_TARGET, side_effect=side_effects):
        with patch("fpl_historical.capture.time.sleep"):
            with patch("fpl_historical.capture.new_raw_dir", side_effect=_fake_new_raw_dir):
                manifest = capture_season(season, allow_missing_summaries=allow_missing)

    raw_dirs = list_raw_dirs(season)
    raw_dir = raw_dirs[-1]

    status = manifest.status
    should_promote = (
        status == "complete"
        or (status == "complete_with_gaps" and promote_with_gaps)
    )
    if should_promote:
        p_dir = parquet_dir(season)
        build_parquet_from_raw(raw_dir, p_dir, promote_with_gaps=promote_with_gaps)

    return manifest, raw_dir


# ---------------------------------------------------------------------------
# Test: two runs produce two distinct raw dirs
# ---------------------------------------------------------------------------

class TestTwoRunsDistinctDirs:
    def test_two_distinct_raw_dirs(self, tmp_historical_root):
        """Two captures produce two separate raw/ directories."""
        _run_capture_and_project(ts_offset_seconds=0)
        _run_capture_and_project(ts_offset_seconds=1)

        dirs = list_raw_dirs("2025-2026")
        assert len(dirs) == 2
        assert dirs[0].name != dirs[1].name

    def test_latest_json_points_to_newest(self, tmp_historical_root):
        """_latest.json points to the most recent complete snapshot after two runs."""
        _run_capture_and_project(ts_offset_seconds=0)
        _, second_raw_dir = _run_capture_and_project(ts_offset_seconds=1)

        latest_path = latest_pointer_path("2025-2026")
        assert latest_path.exists()
        data = json.loads(latest_path.read_text(encoding="utf-8"))
        assert data["raw_dir"] == second_raw_dir.name


# ---------------------------------------------------------------------------
# Test: complete_with_gaps without --promote-with-gaps → _latest.json
#        still points to the previous complete snapshot
# ---------------------------------------------------------------------------

class TestGapsDoNotAdvanceLatest:
    def test_gaps_without_promote_does_not_update_latest(self, tmp_historical_root):
        """A complete_with_gaps run (no promote flag) must not overwrite _latest.json."""
        # First run: complete (ts_offset=0)
        _, first_raw_dir = _run_capture_and_project(allow_missing=0, ts_offset_seconds=0)
        first_latest = json.loads(
            latest_pointer_path("2025-2026").read_text(encoding="utf-8")
        )
        first_raw_dir_name = first_latest["raw_dir"]

        # Second run: complete_with_gaps (1 failure, allow=1 → gaps status, ts_offset=1)
        fail_id = MINIMAL_BOOTSTRAP["elements"][0]["id"]
        _run_capture_and_project(
            allow_missing=1,
            promote_with_gaps=False,
            element_summary_fail_ids={fail_id},
            ts_offset_seconds=1,
        )

        # _latest.json should still point to the first (complete) snapshot
        latest_path = latest_pointer_path("2025-2026")
        data = json.loads(latest_path.read_text(encoding="utf-8"))
        assert data["raw_dir"] == first_raw_dir_name


# ---------------------------------------------------------------------------
# Test: --skip-if-fresh behavior (via CLI)
# ---------------------------------------------------------------------------

class TestSkipIfFresh:
    def test_skip_if_fresh_after_complete_run(self, tmp_historical_root):
        """After a complete run, --skip-if-fresh 24 exits 0 without writing."""
        from fpl_historical.cli import cmd_capture
        import argparse

        # First run via capture side effects (actually runs)
        side_effects = _build_side_effects()
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_historical.capture.time.sleep"):
                args = argparse.Namespace(
                    season="2025-2026",
                    skip_parquet=False,
                    skip_if_fresh=24,
                    allow_missing_summaries=0,
                    promote_with_gaps=False,
                    element_summary_timeout=20,
                )
                exit_code = cmd_capture(args)

        assert exit_code == 0
        raw_dirs_after_first = list_raw_dirs("2025-2026")

        # Second call: should skip because the snapshot is fresh (< 24 hours old)
        exit_code2 = cmd_capture(args)
        assert exit_code2 == 0

        # No new raw dir should have been created on the second (skipped) call
        raw_dirs_after_second = list_raw_dirs("2025-2026")
        assert len(raw_dirs_after_second) == len(raw_dirs_after_first)

    def test_skip_if_fresh_does_not_skip_after_complete_with_gaps(self, tmp_historical_root):
        """After a complete_with_gaps run, --skip-if-fresh does NOT skip.

        We verify this by checking that the CLI returns exit 0 (complete capture,
        not short-circuit skip) and that a new _manifest.json is produced. Because
        new_raw_dir has 1-second resolution, we patch it on the second call to use
        a distinct timestamp so both dirs are visible in list_raw_dirs.
        """
        from fpl_historical.cli import cmd_capture
        from fpl_historical.paths import season_dir
        import argparse

        fail_id = MINIMAL_BOOTSTRAP["elements"][0]["id"]

        # Run a complete_with_gaps capture via CLI (skip_parquet so no projection)
        side_effects = _build_side_effects(element_summary_fail_ids={fail_id})
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_historical.capture.time.sleep"):
                args_gaps = argparse.Namespace(
                    season="2025-2026",
                    skip_parquet=True,
                    skip_if_fresh=None,
                    allow_missing_summaries=1,
                    promote_with_gaps=False,
                    element_summary_timeout=20,
                )
                exit_code = cmd_capture(args_gaps)

        # complete_with_gaps + no promote → exit 2
        assert exit_code == 2

        raw_dirs_before = list_raw_dirs("2025-2026")

        # Second capture: use a deterministic ts 1 second later to guarantee new dir name
        ts2 = "2099-01-01T00-00-01Z"

        def _fake_new_raw_dir_2(s: str) -> Path:
            raw_dir = season_dir(s) / "raw" / ts2
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "element-summary").mkdir(exist_ok=True)
            return raw_dir

        # Now try skip-if-fresh: should NOT skip because complete_with_gaps doesn't count
        side_effects2 = _build_side_effects()
        with patch(_PATCH_TARGET, side_effect=side_effects2):
            with patch("fpl_historical.capture.time.sleep"):
                with patch("fpl_historical.capture.new_raw_dir", side_effect=_fake_new_raw_dir_2):
                    args_fresh = argparse.Namespace(
                        season="2025-2026",
                        skip_parquet=True,
                        skip_if_fresh=24,
                        allow_missing_summaries=0,
                        promote_with_gaps=False,
                        element_summary_timeout=20,
                    )
                    exit_code2 = cmd_capture(args_fresh)

        assert exit_code2 == 0
        raw_dirs_after = list_raw_dirs("2025-2026")
        # A new raw dir must have been created (did not skip)
        assert len(raw_dirs_after) > len(raw_dirs_before)

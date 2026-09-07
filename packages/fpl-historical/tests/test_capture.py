"""
tests/test_capture.py
=====================
Tests for fpl_historical.capture — four CONTRACT §2 scenarios.

Patch target: ``fpl_api_client.fpl_client.requests.get``
(same pattern as packages/fpl-api-client/tests/test_fpl_client.py)

Because capture.py calls ``requests.get`` via the imported ``requests``
module in ``fpl_historical.capture``, we patch at the location that
``capture.py`` uses — ``fpl_historical.capture.requests.get``.
"""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
import requests as _requests

from conftest import MINIMAL_BOOTSTRAP, MINIMAL_FIXTURES, MINIMAL_ELEMENT_SUMMARY

_PATCH_TARGET = "fpl_historical._io.requests.get"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_response(payload) -> MagicMock:
    """Mock requests.Response with status 200 and a JSON-serialisable body."""
    body = json.dumps(payload).encode("utf-8")
    mock = MagicMock()
    mock.status_code = 200
    mock.content = body
    mock.json.return_value = copy.deepcopy(payload)
    mock.raise_for_status.return_value = None
    return mock


def _error_response(status_code: int = 500) -> MagicMock:
    """Mock requests.Response with a non-200 status code."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.content = b""
    mock.raise_for_status.side_effect = _requests.HTTPError(
        f"Mock HTTP {status_code}", response=mock
    )
    return mock


def _build_side_effects(
    bootstrap_ok: bool = True,
    fixtures_ok: bool = True,
    element_summary_fail_ids: set[int] | None = None,
    bootstrap_status: int = 200,
) -> list:
    """Build the list of mock responses for requests.get side_effect.

    Call order mirrors capture.py:
        1. bootstrap-static
        2. fixtures (all)
        3. element-summary/{id} for each element in MINIMAL_BOOTSTRAP
    """
    fail_ids = element_summary_fail_ids or set()
    effects: list = []

    # 1. Bootstrap
    if bootstrap_ok:
        effects.append(_ok_response(MINIMAL_BOOTSTRAP))
    else:
        effects.append(_error_response(bootstrap_status))
        # If bootstrap fails, capture returns immediately — no more calls
        return effects

    # 2. Fixtures
    if fixtures_ok:
        effects.append(_ok_response(MINIMAL_FIXTURES))
    else:
        effects.append(_error_response(500))
        return effects

    # 3. Element summaries — one per element in MINIMAL_BOOTSTRAP
    for element in MINIMAL_BOOTSTRAP["elements"]:
        eid = element["id"]
        if eid in fail_ids:
            effects.append(_error_response(500))
        else:
            effects.append(_ok_response(MINIMAL_ELEMENT_SUMMARY))

    return effects


# ---------------------------------------------------------------------------
# Scenario (a): all 200 → complete
# ---------------------------------------------------------------------------

class TestScenarioAllSuccess:
    def test_status_is_complete(self, tmp_historical_root):
        """All fetches succeed → manifest.status == 'complete'."""
        from fpl_historical.capture import capture_season

        side_effects = _build_side_effects()
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_historical.capture.time.sleep"):
                manifest = capture_season("2025-2026", allow_missing_summaries=0)

        assert manifest.status == "complete"

    def test_no_failures_in_element_summary(self, tmp_historical_root):
        """All element-summary calls succeed → failures list is empty."""
        from fpl_historical.capture import capture_season

        side_effects = _build_side_effects()
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_historical.capture.time.sleep"):
                manifest = capture_season("2025-2026", allow_missing_summaries=0)

        es = manifest.fpl_endpoints["element-summary"]
        assert es["failures"] == []
        assert es["count"] == len(MINIMAL_BOOTSTRAP["elements"])

    def test_manifest_written_to_disk(self, tmp_historical_root):
        """capture_season writes _manifest.json to the raw dir."""
        from fpl_historical.capture import capture_season
        from fpl_historical.paths import list_raw_dirs

        side_effects = _build_side_effects()
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_historical.capture.time.sleep"):
                capture_season("2025-2026", allow_missing_summaries=0)

        raw_dirs = list_raw_dirs("2025-2026")
        assert len(raw_dirs) == 1
        assert (raw_dirs[0] / "_manifest.json").exists()

    def test_bootstrap_gz_written(self, tmp_historical_root):
        """bootstrap-static.json.gz is written to the raw dir."""
        from fpl_historical.capture import capture_season
        from fpl_historical.paths import list_raw_dirs

        side_effects = _build_side_effects()
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_historical.capture.time.sleep"):
                capture_season("2025-2026", allow_missing_summaries=0)

        raw_dir = list_raw_dirs("2025-2026")[0]
        gz_path = raw_dir / "bootstrap-static.json.gz"
        assert gz_path.exists()
        # Verify it's valid gzip
        with gzip.open(gz_path, "rb") as fh:
            content = json.loads(fh.read().decode("utf-8"))
        assert "elements" in content


# ---------------------------------------------------------------------------
# Scenario (b): 1 ES fail, allow=0 → failed
# ---------------------------------------------------------------------------

class TestScenarioOneFailureNoTolerance:
    def test_status_is_failed(self, tmp_historical_root):
        """1 element-summary failure with allow=0 → manifest.status == 'failed'."""
        from fpl_historical.capture import capture_season

        fail_id = MINIMAL_BOOTSTRAP["elements"][0]["id"]
        side_effects = _build_side_effects(element_summary_fail_ids={fail_id})
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_historical.capture.time.sleep"):
                manifest = capture_season("2025-2026", allow_missing_summaries=0)

        assert manifest.status == "failed"

    def test_failures_list_populated(self, tmp_historical_root):
        """Failing element-summary ID appears in fpl_endpoints failures list."""
        from fpl_historical.capture import capture_season

        fail_id = MINIMAL_BOOTSTRAP["elements"][0]["id"]
        side_effects = _build_side_effects(element_summary_fail_ids={fail_id})
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_historical.capture.time.sleep"):
                manifest = capture_season("2025-2026", allow_missing_summaries=0)

        failures = manifest.fpl_endpoints["element-summary"]["failures"]
        assert len(failures) == 1
        assert failures[0]["element_id"] == fail_id


# ---------------------------------------------------------------------------
# Scenario (c): 1 ES fail, allow=1 → complete_with_gaps
# ---------------------------------------------------------------------------

class TestScenarioOneFailureWithTolerance:
    def test_status_is_complete_with_gaps(self, tmp_historical_root):
        """1 element-summary failure with allow=1 → manifest.status == 'complete_with_gaps'."""
        from fpl_historical.capture import capture_season

        fail_id = MINIMAL_BOOTSTRAP["elements"][0]["id"]
        side_effects = _build_side_effects(element_summary_fail_ids={fail_id})
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_historical.capture.time.sleep"):
                manifest = capture_season("2025-2026", allow_missing_summaries=1)

        assert manifest.status == "complete_with_gaps"

    def test_successful_players_still_captured(self, tmp_historical_root):
        """Non-failing element summaries are still written to disk."""
        from fpl_historical.capture import capture_season
        from fpl_historical.paths import list_raw_dirs

        # Fail first element only; second should succeed
        fail_id = MINIMAL_BOOTSTRAP["elements"][0]["id"]
        ok_id = MINIMAL_BOOTSTRAP["elements"][1]["id"]
        side_effects = _build_side_effects(element_summary_fail_ids={fail_id})
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_historical.capture.time.sleep"):
                capture_season("2025-2026", allow_missing_summaries=1)

        raw_dir = list_raw_dirs("2025-2026")[0]
        ok_gz = raw_dir / "element-summary" / f"{ok_id}.json.gz"
        fail_gz = raw_dir / "element-summary" / f"{fail_id}.json.gz"
        assert ok_gz.exists()
        assert not fail_gz.exists()


# ---------------------------------------------------------------------------
# Scenario (d): bootstrap 500 → failed, fixtures/ES not fetched
# ---------------------------------------------------------------------------

class TestScenarioBootstrapFailure:
    def test_status_is_failed(self, tmp_historical_root):
        """Bootstrap 500 → manifest.status == 'failed'."""
        from fpl_historical.capture import capture_season

        side_effects = _build_side_effects(bootstrap_ok=False, bootstrap_status=500)
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_historical.capture.time.sleep"):
                manifest = capture_season("2025-2026", allow_missing_summaries=0)

        assert manifest.status == "failed"

    def test_only_one_request_made(self, tmp_historical_root):
        """When bootstrap fails, only 1 HTTP request is made (no fixtures/ES)."""
        from fpl_historical.capture import capture_season

        side_effects = _build_side_effects(bootstrap_ok=False, bootstrap_status=500)
        with patch(_PATCH_TARGET, side_effect=side_effects) as mock_get:
            with patch("fpl_historical.capture.time.sleep"):
                capture_season("2025-2026", allow_missing_summaries=0)

        assert mock_get.call_count == 1

    def test_bootstrap_endpoint_records_500(self, tmp_historical_root):
        """fpl_endpoints.bootstrap-static.status is 500 in the manifest."""
        from fpl_historical.capture import capture_season

        side_effects = _build_side_effects(bootstrap_ok=False, bootstrap_status=500)
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_historical.capture.time.sleep"):
                manifest = capture_season("2025-2026", allow_missing_summaries=0)

        bs = manifest.fpl_endpoints["bootstrap-static"]
        assert bs["status"] == 500

    def test_element_summary_count_is_zero(self, tmp_historical_root):
        """When bootstrap fails, element-summary count is 0."""
        from fpl_historical.capture import capture_season

        side_effects = _build_side_effects(bootstrap_ok=False, bootstrap_status=500)
        with patch(_PATCH_TARGET, side_effect=side_effects):
            with patch("fpl_historical.capture.time.sleep"):
                manifest = capture_season("2025-2026", allow_missing_summaries=0)

        es = manifest.fpl_endpoints["element-summary"]
        assert es["count"] == 0


# ---------------------------------------------------------------------------
# Retry behavior (default _RETRY_ATTEMPTS = 3, disabled in tmp_historical_root)
# ---------------------------------------------------------------------------

class TestRetryBehavior:
    """Verify _fetch_raw retries on 5xx/network errors and not on 4xx."""

    def test_retries_three_times_on_5xx_then_succeeds(self, tmp_path, monkeypatch):
        """Two 503s followed by a 200 → final status 200 after 3 calls."""
        monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(tmp_path))
        # Do NOT disable retries — the point of this test
        from fpl_historical._io import _fetch_raw

        responses = [_error_response(503), _error_response(503), _ok_response({"ok": True})]
        with patch(_PATCH_TARGET, side_effect=responses) as mock_get:
            with patch("fpl_historical._io.time.sleep"):
                status, body = _fetch_raw("https://example.com/")
        assert status == 200
        assert mock_get.call_count == 3

    def test_does_not_retry_on_4xx(self, tmp_path, monkeypatch):
        """A 404 returns immediately without retry."""
        monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(tmp_path))
        from fpl_historical._io import _fetch_raw

        with patch(_PATCH_TARGET, side_effect=[_error_response(404)]) as mock_get:
            with patch("fpl_historical._io.time.sleep"):
                status, body = _fetch_raw("https://example.com/")
        assert status == 404
        assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# Season-boundary guard (incident prevention — see fpl_historical.season_guard)
# ---------------------------------------------------------------------------

def _bootstrap_with_live_season(start_year: int) -> dict:
    """MINIMAL_BOOTSTRAP with event id=1's deadline moved to imply *start_year*-*start_year+1*.

    Replaces rather than appends: the fixture already carries an event id=1
    (see conftest), and derive_live_season() reads the *first* id=1 match, so
    appending a second one would be silently ignored.
    """
    bootstrap = copy.deepcopy(MINIMAL_BOOTSTRAP)
    event_one = next(e for e in bootstrap["events"] if e["id"] == 1)
    event_one["deadline_time"] = f"{start_year}-08-14T17:30:00Z"
    return bootstrap


def _bootstrap_without_event_one() -> dict:
    """MINIMAL_BOOTSTRAP with event id=1 removed -> live season cannot be derived."""
    bootstrap = copy.deepcopy(MINIMAL_BOOTSTRAP)
    bootstrap["events"] = [e for e in bootstrap["events"] if e["id"] != 1]
    return bootstrap


class TestSeasonBoundaryGuard:
    def test_matching_live_season_captures_normally(self, tmp_historical_root):
        """Live season == target season -> proceeds, writes files as usual."""
        from fpl_historical.capture import capture_season
        from fpl_historical.paths import list_raw_dirs

        bootstrap = _bootstrap_with_live_season(2025)
        effects = [_ok_response(bootstrap), _ok_response(MINIMAL_FIXTURES)]
        for element in MINIMAL_BOOTSTRAP["elements"]:
            effects.append(_ok_response(MINIMAL_ELEMENT_SUMMARY))

        with patch(_PATCH_TARGET, side_effect=effects):
            with patch("fpl_historical.capture.time.sleep"):
                manifest = capture_season("2025-2026", allow_missing_summaries=0)

        assert manifest.status == "complete"
        raw_dirs = list_raw_dirs("2025-2026")
        assert len(raw_dirs) == 1
        assert (raw_dirs[0] / "bootstrap-static.json.gz").exists()

    def test_mismatched_live_season_rejects_and_writes_nothing(self, tmp_historical_root):
        """Live season (2026-2027) != target (2025-2026) -> raises, zero writes."""
        from fpl_historical.capture import capture_season
        from fpl_historical.paths import list_raw_dirs
        from fpl_historical.season_guard import SeasonMismatchError

        bootstrap = _bootstrap_with_live_season(2026)  # -> "2026-2027"

        with patch(_PATCH_TARGET, side_effect=[_ok_response(bootstrap)]) as mock_get:
            with patch("fpl_historical.capture.time.sleep"):
                with pytest.raises(SeasonMismatchError) as exc_info:
                    capture_season("2025-2026", allow_missing_summaries=0)

        # Rejected before fixtures/element-summary were ever fetched.
        assert mock_get.call_count == 1
        # Nothing written: no raw dir was ever created for this season.
        assert list_raw_dirs("2025-2026") == []
        message = str(exc_info.value)
        assert "2026-2027" in message
        assert "2025-2026" in message

    def test_undeterminable_season_rejects_and_writes_nothing(self, tmp_historical_root):
        """Live season unreadable -> raises, zero writes. The guard fails CLOSED.

        Inverted from the original behaviour, which proceeded here. This is
        capture_season()'s full-rebuild path: the merge downstream of it
        rebuilds all five tables from scratch, so it is the worst possible
        place to admit an unverified season.
        """
        from fpl_historical.capture import capture_season
        from fpl_historical.paths import list_raw_dirs, season_dir
        from fpl_historical.season_guard import SeasonUndeterminedError

        bootstrap = _bootstrap_without_event_one()

        with patch(_PATCH_TARGET, side_effect=[_ok_response(bootstrap)]) as mock_get:
            with patch("fpl_historical.capture.time.sleep"):
                with pytest.raises(SeasonUndeterminedError) as exc_info:
                    capture_season("2025-2026", allow_missing_summaries=0)

        # Rejected before fixtures/element-summary were ever fetched.
        assert mock_get.call_count == 1
        assert list_raw_dirs("2025-2026") == []
        assert not (season_dir("2025-2026") / "raw").exists()
        assert "could not determine" in str(exc_info.value)

    def test_valve_lets_an_undeterminable_season_capture(self, tmp_historical_root):
        """--allow-unverified-season restores the permissive path, on purpose."""
        from fpl_historical.capture import capture_season
        from fpl_historical.paths import list_raw_dirs

        bootstrap = _bootstrap_without_event_one()
        effects = [_ok_response(bootstrap), _ok_response(MINIMAL_FIXTURES)]
        for element in MINIMAL_BOOTSTRAP["elements"]:
            effects.append(_ok_response(MINIMAL_ELEMENT_SUMMARY))

        with patch(_PATCH_TARGET, side_effect=effects):
            with patch("fpl_historical.capture.time.sleep"):
                manifest = capture_season(
                    "2025-2026",
                    allow_missing_summaries=0,
                    allow_unverified_season=True,
                )

        assert manifest.status == "complete"
        assert len(list_raw_dirs("2025-2026")) == 1

    def test_valve_does_not_let_a_mismatch_through_capture(self, tmp_historical_root):
        """The valve covers 'undetermined' only — a confirmed mismatch still rejects.

        This is the incident's exact shape (live 2026-2027, target 2025-2026);
        no flag may re-open it.
        """
        from fpl_historical.capture import capture_season
        from fpl_historical.paths import list_raw_dirs
        from fpl_historical.season_guard import SeasonMismatchError

        bootstrap = _bootstrap_with_live_season(2026)  # -> "2026-2027"

        with patch(_PATCH_TARGET, side_effect=[_ok_response(bootstrap)]):
            with patch("fpl_historical.capture.time.sleep"):
                with pytest.raises(SeasonMismatchError):
                    capture_season(
                        "2025-2026",
                        allow_missing_summaries=0,
                        allow_unverified_season=True,
                    )

        assert list_raw_dirs("2025-2026") == []

    def test_mismatched_season_leaves_no_partial_directory(self, tmp_historical_root):
        """No seasons/<season>/raw directory exists at all after a rejection."""
        from fpl_historical.capture import capture_season
        from fpl_historical.paths import season_dir
        from fpl_historical.season_guard import SeasonMismatchError

        bootstrap = _bootstrap_with_live_season(2026)
        with patch(_PATCH_TARGET, side_effect=[_ok_response(bootstrap)]):
            with patch("fpl_historical.capture.time.sleep"):
                with pytest.raises(SeasonMismatchError):
                    capture_season("2025-2026", allow_missing_summaries=0)

        assert not (season_dir("2025-2026") / "raw").exists()


# ---------------------------------------------------------------------------
# CLI wiring for the season guard's escape valve
# ---------------------------------------------------------------------------

class TestAllowUnverifiedSeasonCliWiring:
    """The valve is worthless if it stops at capture_season()'s signature."""

    def test_flag_defaults_to_off(self):
        from fpl_historical.cli import _parse_args

        args = _parse_args(["capture", "--season", "2025-2026"])
        assert args.allow_unverified_season is False

    def test_flag_parses_when_passed(self):
        from fpl_historical.cli import _parse_args

        args = _parse_args(
            ["capture", "--season", "2025-2026", "--allow-unverified-season"]
        )
        assert args.allow_unverified_season is True

    @pytest.mark.parametrize("flag_value", [True, False])
    def test_flag_reaches_capture_season(self, flag_value):
        """Whatever the CLI parsed must arrive at the guard's caller verbatim."""
        from fpl_historical import cli

        argv = ["capture", "--season", "2025-2026", "--skip-parquet"]
        if flag_value:
            argv.append("--allow-unverified-season")
        args = cli._parse_args(argv)

        fake_manifest = MagicMock()
        fake_manifest.status = "complete"
        fake_manifest.elapsed_seconds = 1.0
        fake_manifest.fpl_endpoints = {"element-summary": {"count": 2, "failures": []}}

        with patch.object(
            cli, "capture_season", return_value=fake_manifest
        ) as mock_capture:
            cli.cmd_capture(args)

        assert mock_capture.call_args.kwargs["allow_unverified_season"] is flag_value

    def test_both_rejections_exit_3_with_distinguishable_reasons(self, capsys):
        """Same exit code (CONTRACT §4: 'rejected, nothing written'), different text."""
        from fpl_historical import cli
        from fpl_historical.season_guard import (
            SeasonMismatchError,
            SeasonUndeterminedError,
        )

        args = cli._parse_args(["capture", "--season", "2025-2026", "--skip-parquet"])

        with patch.object(
            cli, "capture_season", side_effect=SeasonUndeterminedError("boom-undet")
        ):
            assert cli.cmd_capture(args) == 3
        undetermined_out = capsys.readouterr().err

        with patch.object(
            cli, "capture_season", side_effect=SeasonMismatchError("boom-mismatch")
        ):
            assert cli.cmd_capture(args) == 3
        mismatch_out = capsys.readouterr().err

        assert "season-undetermined" in undetermined_out
        assert "season-mismatch" not in undetermined_out
        assert "season-mismatch" in mismatch_out
        assert "season-undetermined" not in mismatch_out

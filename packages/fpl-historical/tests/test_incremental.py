"""
tests/test_incremental.py
=========================
Unit tests for fpl_historical.incremental — 9 scenarios from CONTRACT §9 / plan §9.

Patch target: ``fpl_historical._io.requests.get`` (same as test_capture.py after
the _io.py extraction).
"""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests as _requests

from conftest import (
    MINIMAL_BOOTSTRAP,
    MINIMAL_EVENT_LIVE,
    MINIMAL_FIXTURES,
)
from fpl_historical.manifest import read_manifest, write_manifest, Manifest
from fpl_historical.paths import (
    CURRENT_SEASON,
    gw_dir,
    list_incremental_dirs,
)

_PATCH_TARGET = "fpl_historical._io.requests.get"

# ---------------------------------------------------------------------------
# Bootstrap variants
# ---------------------------------------------------------------------------

# Bootstrap with gw36 finished + data_checked (the "final" GW)
BOOTSTRAP_GW36_CHECKED: dict = {
    **MINIMAL_BOOTSTRAP,
    "events": [
        {
            "id": 35,
            "deadline_time": "2026-04-28T17:30:00Z",
            "is_current": False,
            "is_next": False,
            "finished": True,
            "data_checked": True,
            "average_entry_score": 45,
        },
        {
            "id": 36,
            "deadline_time": "2026-05-05T17:30:00Z",
            "is_current": False,
            "is_next": False,
            "finished": True,
            "data_checked": True,
            "average_entry_score": 52,
        },
        {
            "id": 37,
            "deadline_time": "2026-05-12T17:30:00Z",
            "is_current": True,
            "is_next": False,
            "finished": False,
            "data_checked": False,
            "average_entry_score": 0,
        },
    ],
}

# Bootstrap with gw36 finished but data_checked=False (provisional scores)
BOOTSTRAP_GW36_NOT_CHECKED: dict = {
    **MINIMAL_BOOTSTRAP,
    "events": [
        {
            "id": 36,
            "deadline_time": "2026-05-05T17:30:00Z",
            "is_current": True,
            "is_next": False,
            "finished": True,
            "data_checked": False,
            "average_entry_score": 0,
        },
    ],
}


# ---------------------------------------------------------------------------
# Mock helpers (mirror test_capture.py)
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


def _empty_response() -> MagicMock:
    """200 response with empty body."""
    mock = MagicMock()
    mock.status_code = 200
    mock.content = b""
    mock.raise_for_status.return_value = None
    return mock


def _build_gw_side_effects(
    bootstrap=None,
    fixtures_ok: bool = True,
    event_live_ok: bool = True,
    event_live_empty: bool = False,
    bootstrap_status: int = 200,
) -> list:
    """Build mock side effects list for a single capture_gameweek call.

    Order: bootstrap, fixtures, event-live.
    """
    bs = bootstrap if bootstrap is not None else BOOTSTRAP_GW36_CHECKED
    effects: list = []

    # 1. Bootstrap bytes fetch
    if bootstrap_status == 200:
        effects.append(_ok_response(bs))
    else:
        effects.append(_error_response(bootstrap_status))
        return effects

    # 2. Fixtures
    if fixtures_ok:
        effects.append(_ok_response(MINIMAL_FIXTURES))
    else:
        effects.append(_error_response(500))

    # 3. Event-live
    if event_live_empty:
        effects.append(_empty_response())
    elif event_live_ok:
        effects.append(_ok_response(MINIMAL_EVENT_LIVE))
    else:
        effects.append(_error_response(500))

    return effects


# ---------------------------------------------------------------------------
# Scenario 1 — Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    """capture_gameweek(36) writes v2 manifest with status=complete."""

    def test_happy_path(self, tmp_historical_root):
        from fpl_historical.incremental import capture_gameweek

        effects = _build_gw_side_effects()
        with patch(_PATCH_TARGET, side_effect=effects):
            manifest = capture_gameweek(36, CURRENT_SEASON)

        assert manifest is not None
        assert manifest.status == "complete"
        assert manifest.schema_version == 2
        assert manifest.kind == "incremental"
        assert manifest.gameweek == 36
        assert manifest.gw_state is not None
        assert manifest.gw_state["data_checked"] is True

        # Check directory structure
        dirs = list_incremental_dirs(CURRENT_SEASON, 36)
        assert len(dirs) == 1
        snap_dir = dirs[0]
        assert (snap_dir / "bootstrap-static.json.gz").exists()
        assert (snap_dir / "fixtures.json.gz").exists()
        assert (snap_dir / "event-live.json.gz").exists()
        assert (snap_dir / "_manifest.json").exists()

        # Verify v2 fields in the on-disk manifest
        m_disk = read_manifest(snap_dir)
        assert m_disk.schema_version == 2
        assert m_disk.kind == "incremental"
        assert m_disk.gameweek == 36
        assert m_disk.gw_state["data_checked"] is True
        assert m_disk.status == "complete"

        # Verify gzipped files are readable
        with gzip.open(snap_dir / "bootstrap-static.json.gz") as f:
            bs_data = json.loads(f.read().decode("utf-8"))
        assert "events" in bs_data


# ---------------------------------------------------------------------------
# Scenario 2 — Failure path: event-live returns 500
# ---------------------------------------------------------------------------

class TestFailurePath:
    """event-live 500 → status=failed; bootstrap + fixtures still on disk."""

    def test_event_live_500(self, tmp_historical_root):
        from fpl_historical.incremental import capture_gameweek

        effects = _build_gw_side_effects(event_live_ok=False)
        with patch(_PATCH_TARGET, side_effect=effects):
            manifest = capture_gameweek(36, CURRENT_SEASON)

        assert manifest is not None
        assert manifest.status == "failed"

        dirs = list_incremental_dirs(CURRENT_SEASON, 36)
        assert len(dirs) == 1
        snap_dir = dirs[0]
        # Snapshot dir preserved; bootstrap + fixtures written; event-live not written
        assert (snap_dir / "bootstrap-static.json.gz").exists()
        assert (snap_dir / "fixtures.json.gz").exists()
        assert not (snap_dir / "event-live.json.gz").exists()
        assert (snap_dir / "_manifest.json").exists()

        el_ep = manifest.fpl_endpoints["event-live"]
        assert el_ep["status"] == 500

    def test_exit_code_1_on_failure(self, tmp_historical_root):
        """CLI returns exit code 1 when status==failed."""
        from fpl_historical.cli import main

        effects = _build_gw_side_effects(event_live_ok=False)
        with patch(_PATCH_TARGET, side_effect=effects):
            with pytest.raises(SystemExit) as exc_info:
                main(["capture-gw", "--gw", "36"])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Scenario 3 — Skip rule fires on second call when data_checked=True
# ---------------------------------------------------------------------------

class TestSkipRule:
    """Second call with data_checked=True returns None; no new dir written."""

    def test_skip_on_second_call(self, tmp_historical_root):
        from fpl_historical.incremental import capture_gameweek

        # First call — writes snapshot
        effects1 = _build_gw_side_effects()
        with patch(_PATCH_TARGET, side_effect=effects1):
            manifest1 = capture_gameweek(36, CURRENT_SEASON)
        assert manifest1 is not None
        assert manifest1.status == "complete"

        dirs_after_first = list_incremental_dirs(CURRENT_SEASON, 36)
        assert len(dirs_after_first) == 1

        # Second call — skip rule should fire (data_checked=True on disk + in bootstrap)
        effects2 = _build_gw_side_effects()
        with patch(_PATCH_TARGET, side_effect=effects2):
            result = capture_gameweek(36, CURRENT_SEASON)

        assert result is None
        dirs_after_second = list_incremental_dirs(CURRENT_SEASON, 36)
        assert len(dirs_after_second) == 1  # No new dir written


# ---------------------------------------------------------------------------
# Scenario 4 — No skip when data_checked=False
# ---------------------------------------------------------------------------

class TestNoSkipWhenNotChecked:
    """Two calls with data_checked=False produce two distinct timestamped dirs."""

    def test_two_dirs_when_not_checked(self, tmp_historical_root, monkeypatch):
        from fpl_historical.incremental import capture_gameweek
        import fpl_historical.paths as _paths_mod

        # Use a counter to guarantee distinct directory names
        _call_count = [0]
        _orig_new_incremental_dir = _paths_mod.new_incremental_dir

        def _fake_new_incremental_dir(season, gw):
            _call_count[0] += 1
            from datetime import datetime, timezone
            ts = f"2026-05-25T18-{_call_count[0]:02d}-00Z"
            inc_dir = _paths_mod.gw_dir(season, gw) / ts
            inc_dir.mkdir(parents=True, exist_ok=True)
            return inc_dir

        monkeypatch.setattr(_paths_mod, "new_incremental_dir", _fake_new_incremental_dir)
        # Also patch in incremental module
        import fpl_historical.incremental as _inc_mod
        monkeypatch.setattr(_inc_mod, "new_incremental_dir", _fake_new_incremental_dir)

        bs = BOOTSTRAP_GW36_NOT_CHECKED
        # First call
        effects1 = _build_gw_side_effects(bootstrap=bs)
        with patch(_PATCH_TARGET, side_effect=effects1):
            m1 = capture_gameweek(36, CURRENT_SEASON)
        assert m1 is not None
        assert m1.status == "complete"
        assert m1.gw_state["data_checked"] is False

        # Second call — data_checked still False; skip rule should NOT fire
        effects2 = _build_gw_side_effects(bootstrap=bs)
        with patch(_PATCH_TARGET, side_effect=effects2):
            m2 = capture_gameweek(36, CURRENT_SEASON)
        assert m2 is not None
        assert m2.status == "complete"

        dirs = list_incremental_dirs(CURRENT_SEASON, 36)
        assert len(dirs) == 2


# ---------------------------------------------------------------------------
# Scenario 5 — --force overrides skip rule
# ---------------------------------------------------------------------------

class TestForceOverridesSkip:
    """force=True always writes a new snapshot, even when skip rule would fire."""

    def test_force_bypasses_skip(self, tmp_historical_root, monkeypatch):
        from fpl_historical.incremental import capture_gameweek
        import fpl_historical.paths as _paths_mod
        import fpl_historical.incremental as _inc_mod

        _call_count = [0]

        def _fake_new_incremental_dir(season, gw):
            _call_count[0] += 1
            ts = f"2026-05-25T19-{_call_count[0]:02d}-00Z"
            inc_dir = _paths_mod.gw_dir(season, gw) / ts
            inc_dir.mkdir(parents=True, exist_ok=True)
            return inc_dir

        monkeypatch.setattr(_paths_mod, "new_incremental_dir", _fake_new_incremental_dir)
        monkeypatch.setattr(_inc_mod, "new_incremental_dir", _fake_new_incremental_dir)

        # First call — normal
        effects1 = _build_gw_side_effects()
        with patch(_PATCH_TARGET, side_effect=effects1):
            m1 = capture_gameweek(36, CURRENT_SEASON)
        assert m1 is not None
        assert m1.status == "complete"

        dirs_after_first = list_incremental_dirs(CURRENT_SEASON, 36)
        assert len(dirs_after_first) == 1

        # Second call with force=True — skip rule fires for non-force, but force overrides
        effects2 = _build_gw_side_effects()
        with patch(_PATCH_TARGET, side_effect=effects2):
            m2 = capture_gameweek(36, CURRENT_SEASON, force=True)
        assert m2 is not None
        assert m2.status == "complete"

        dirs_after_second = list_incremental_dirs(CURRENT_SEASON, 36)
        assert len(dirs_after_second) == 2


# ---------------------------------------------------------------------------
# Scenario 6 — --auto mode
# ---------------------------------------------------------------------------

class TestAutoMode:
    """--auto: existing complete snapshot for gw35 → skip; new snapshot for gw36."""

    def _make_existing_complete_snapshot(self, tmp_path, season: str, gw: int) -> None:
        """Create a pre-existing complete snapshot for gw to simulate a prior run."""
        import fpl_historical.paths as _paths_mod
        inc_dir = _paths_mod.gw_dir(season, gw) / "2026-05-01T00-00-00Z"
        inc_dir.mkdir(parents=True, exist_ok=True)
        m = Manifest(
            schema_version=2,
            season=season,
            status="complete",
            captured_at_utc="2026-05-01T00-00-00Z",
            git_sha="abc1234",
            fpl_endpoints={
                "bootstrap-static": {"url": "...", "status": 200, "bytes": 100, "sha256": "aaa"},
                "fixtures": {"url": "...", "status": 200, "bytes": 100, "sha256": "bbb"},
                "event-live": {"url": "...", "status": 200, "bytes": 100, "sha256": "ccc"},
            },
            current_event_id=None,
            elapsed_seconds=1.0,
            kind="incremental",
            gameweek=gw,
            gw_state={
                "finished": True,
                "data_checked": True,
                "is_current": False,
                "deadline_time": "2026-04-28T17:30:00Z",
            },
        )
        write_manifest(inc_dir, m)

    def test_auto_skips_existing_writes_new(self, tmp_historical_root):
        from fpl_historical.cli import main

        season = CURRENT_SEASON
        # Pre-create a complete snapshot for gw35
        self._make_existing_complete_snapshot(tmp_historical_root, season, 35)
        assert len(list_incremental_dirs(season, 35)) == 1

        # Bootstrap has gw35 and gw36 both finished+data_checked
        bootstrap = BOOTSTRAP_GW36_CHECKED  # events: id=35, 36 (both checked), 37 (current)

        # For --auto mode, _fetch_bootstrap_dict fetches once, then capture_gameweek
        # re-fetches bootstrap bytes for each GW. Events 35 and 36 both have
        # data_checked=True; 37 is not finished so excluded from auto.
        # gw35: skip rule fires (existing complete snapshot with data_checked=True).
        # gw36: no existing snapshot → write new one.
        # Call order for requests.get:
        #   1. _fetch_bootstrap_dict (in cmd_capture_gw --auto)
        #   2. capture_gameweek(35): bootstrap bytes, then skip fires (no further fetches)
        #   3. capture_gameweek(36): bootstrap bytes, fixtures, event-live

        effects = [
            _ok_response(bootstrap),       # 1. bootstrap for _fetch_bootstrap_dict
            _ok_response(bootstrap),       # 2. bootstrap bytes for gw35 capture
            # skip rule fires after checking existing snapshot — no fixtures/event-live for gw35
            _ok_response(bootstrap),       # 3. bootstrap bytes for gw36 capture
            _ok_response(MINIMAL_FIXTURES),  # 4. fixtures for gw36
            _ok_response(MINIMAL_EVENT_LIVE),  # 5. event-live for gw36
        ]

        with patch(_PATCH_TARGET, side_effect=effects):
            with pytest.raises(SystemExit) as exc_info:
                main(["capture-gw", "--auto", "--season", season])
        assert exc_info.value.code == 0

        # gw35: still exactly 1 snapshot (skipped)
        assert len(list_incremental_dirs(season, 35)) == 1
        # gw36: exactly 1 new snapshot written
        assert len(list_incremental_dirs(season, 36)) == 1
        m36 = read_manifest(list_incremental_dirs(season, 36)[0])
        assert m36.status == "complete"
        assert m36.gameweek == 36


# ---------------------------------------------------------------------------
# Scenario 7 — Invalid --gw (event not in bootstrap)
# ---------------------------------------------------------------------------

class TestInvalidGw:
    """--gw 99 against bootstrap with no event 99 → status=failed, exit 1."""

    def test_invalid_gw_returns_failed(self, tmp_historical_root):
        from fpl_historical.incremental import capture_gameweek

        # Bootstrap only has events 35, 36, 37
        effects = [_ok_response(BOOTSTRAP_GW36_CHECKED)]
        with patch(_PATCH_TARGET, side_effect=effects):
            manifest = capture_gameweek(99, CURRENT_SEASON)

        assert manifest is not None
        assert manifest.status == "failed"
        assert manifest.gameweek == 99

    def test_invalid_gw_cli_exits_1(self, tmp_historical_root):
        """CLI exits 1 for an invalid --gw."""
        from fpl_historical.cli import main

        effects = [_ok_response(BOOTSTRAP_GW36_CHECKED)]
        with patch(_PATCH_TARGET, side_effect=effects):
            with pytest.raises(SystemExit) as exc_info:
                main(["capture-gw", "--gw", "99"])
        assert exc_info.value.code == 1

    def test_invalid_gw_no_dirs_written(self, tmp_historical_root):
        """A failed 'not found' run still writes a dir (manifest preserved) but no gz files."""
        from fpl_historical.incremental import capture_gameweek
        import fpl_historical.paths as _paths_mod

        effects = [_ok_response(BOOTSTRAP_GW36_CHECKED)]
        with patch(_PATCH_TARGET, side_effect=effects):
            capture_gameweek(99, CURRENT_SEASON)

        # A dir is created for the failed manifest; no gz files
        gw99_dir = _paths_mod.gw_dir(CURRENT_SEASON, 99)
        snap_dirs = list(gw99_dir.iterdir()) if gw99_dir.exists() else []
        assert len(snap_dirs) == 1  # one failed snapshot dir
        snap = snap_dirs[0]
        assert (snap / "_manifest.json").exists()
        # No gz files should be present (event was not found, no fetches completed)
        assert not (snap / "fixtures.json.gz").exists()
        assert not (snap / "event-live.json.gz").exists()


# ---------------------------------------------------------------------------
# Scenario 8 — v1 manifest round-trip
# ---------------------------------------------------------------------------

class TestV1ManifestRoundTrip:
    """Write v1 manifest; read via updated read_manifest; v2 fields are None."""

    def test_v1_round_trip(self, tmp_path):
        from fpl_historical.manifest import write_manifest, read_manifest, Manifest

        raw_dir = tmp_path / "raw" / "2026-05-25T14-22-03Z"
        raw_dir.mkdir(parents=True)

        v1 = Manifest(
            schema_version=1,
            season="2025-2026",
            status="complete",
            captured_at_utc="2026-05-25T14-22-03Z",
            git_sha="abc1234",
            fpl_endpoints={
                "bootstrap-static": {"url": "...", "status": 200, "bytes": 100, "sha256": "aaa"},
                "fixtures": {"url": "...", "status": 200, "bytes": 100, "sha256": "bbb"},
                "element-summary": {"count": 2, "failures": [], "sha256_aggregate": "ccc"},
            },
            current_event_id=38,
            elapsed_seconds=187.4,
        )
        write_manifest(raw_dir, v1)

        # Verify on-disk file does NOT contain v2 keys
        import json
        raw_json = json.loads((raw_dir / "_manifest.json").read_text(encoding="utf-8"))
        assert "kind" not in raw_json
        assert "gameweek" not in raw_json
        assert "gw_state" not in raw_json

        # Read back and verify all v1 fields preserved; v2 fields are None
        m = read_manifest(raw_dir)
        assert m.schema_version == 1
        assert m.season == "2025-2026"
        assert m.status == "complete"
        assert m.captured_at_utc == "2026-05-25T14-22-03Z"
        assert m.git_sha == "abc1234"
        assert m.current_event_id == 38
        assert m.elapsed_seconds == 187.4
        assert m.fpl_endpoints["element-summary"]["count"] == 2
        # V2 extensions must be None
        assert m.kind is None
        assert m.gameweek is None
        assert m.gw_state is None


# ---------------------------------------------------------------------------
# Scenario 9 — Empty body on event-live
# ---------------------------------------------------------------------------

class TestEmptyBodyEventLive:
    """Empty body on event-live → status=failed; no bogus sha256."""

    def test_empty_event_live_body(self, tmp_historical_root):
        from fpl_historical.incremental import capture_gameweek

        effects = [
            _ok_response(BOOTSTRAP_GW36_CHECKED),  # bootstrap
            _ok_response(MINIMAL_FIXTURES),         # fixtures
            _empty_response(),                      # event-live: 200 but empty body
        ]
        with patch(_PATCH_TARGET, side_effect=effects):
            manifest = capture_gameweek(36, CURRENT_SEASON)

        assert manifest is not None
        assert manifest.status == "failed"

        el_ep = manifest.fpl_endpoints["event-live"]
        assert el_ep["status"] == 200
        assert el_ep["bytes"] == 0
        assert el_ep["sha256"] == ""  # No sha256 computed for empty body

        # event-live.json.gz must NOT exist (empty body was not written)
        dirs = list_incremental_dirs(CURRENT_SEASON, 36)
        assert len(dirs) == 1
        snap_dir = dirs[0]
        assert not (snap_dir / "event-live.json.gz").exists()

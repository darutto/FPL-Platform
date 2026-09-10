"""
tests/test_owned_store_healthz_season.py
=========================================
i73 Entrega 2: /healthz's owned_store_sync block must expose `season`,
mirroring tactical_store_sync. This is the central invariant of the season
rollover -- without it, the manual "Verify /healthz" workflow step only ever
confirmed a timestamp, never that production actually serves the correct
season for the owned store.

Covers:
(i)   Successful sync -> block exposes season == the synced season.
(ii)  No sync has run (get_last_sync_result() is None) -> block is null,
      same as before this change.
(iii) Failed sync (ok=False) -> block exposes season and error, no crash.
(iv)  The block leaks nothing beyond SyncResult's own fields (no paths, no
      credentials).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant.owned_store_sync import SyncResult

client = TestClient(fpl_server.app)


def test_successful_sync_exposes_season(monkeypatch):
    result = SyncResult(
        ok=True, season="2026-2027", files_synced=4,
        merged_at="2026-09-07T22-15-56Z", staleness_hours=1.5, error=None,
    )
    monkeypatch.setattr(fpl_server, "get_last_sync_result", lambda: result)
    payload = client.get("/healthz").json()
    osync = payload["owned_store_sync"]
    assert osync["season"] == "2026-2027"
    assert osync["ok"] is True
    assert osync["merged_at"] == "2026-09-07T22-15-56Z"


def test_no_sync_yet_is_null(monkeypatch):
    monkeypatch.setattr(fpl_server, "get_last_sync_result", lambda: None)
    payload = client.get("/healthz").json()
    assert payload["owned_store_sync"] is None


def test_failed_sync_exposes_season_and_error_without_crashing(monkeypatch):
    result = SyncResult(
        ok=False, season="2026-2027", files_synced=0,
        merged_at=None, staleness_hours=None, error="no credentials",
    )
    monkeypatch.setattr(fpl_server, "get_last_sync_result", lambda: result)
    payload = client.get("/healthz").json()
    osync = payload["owned_store_sync"]
    assert osync["ok"] is False
    assert osync["season"] == "2026-2027"
    assert osync["error"] == "no credentials"


def test_block_exposes_only_syncresult_fields(monkeypatch):
    result = SyncResult(
        ok=True, season="2026-2027", files_synced=4,
        merged_at="2026-09-07T22-15-56Z", staleness_hours=1.5, error=None,
    )
    monkeypatch.setattr(fpl_server, "get_last_sync_result", lambda: result)
    payload = client.get("/healthz").json()
    osync = payload["owned_store_sync"]
    assert set(osync.keys()) == {"ok", "season", "files_synced", "merged_at", "staleness_hours", "error"}
    for forbidden in ("pointer_path", "endpoint", "access_key", "secret_access_key"):
        assert forbidden not in osync

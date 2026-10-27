"""B4 PR 1: the licensed sync is wired into the server startup, off by default, and a failure cannot stop the server."""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

import fpl_server
from football_intelligence.distribution.runtime import RuntimeStatus


@pytest.fixture
def started(monkeypatch):
    """Enter the lifespan with no network: bootstrap preset, other optional syncs off."""
    monkeypatch.setattr(fpl_server, "_bootstrap", {"elements": [], "teams": [], "events": []})
    monkeypatch.setattr(fpl_server, "sync_owned_store_seasons", None)
    monkeypatch.setattr(fpl_server, "sync_tactical_store_from_r2", None)
    monkeypatch.setattr(fpl_server, "_football_startup_status", None)
    monkeypatch.setattr(fpl_server, "_start_bootstrap_refresh", lambda: None)
    monkeypatch.setattr(fpl_server, "_try_init_classifier_from_env", lambda: None)
    monkeypatch.delenv("FPL_FOOTBALL_LICENSED_SYNC_ENABLED", raising=False)


def test_the_licensed_sync_is_wired_and_defaults_to_disabled(started):
    assert fpl_server._football_licensed_sync is not None
    with TestClient(fpl_server.app) as client:
        status = client.app.state.football_licensed_status
    assert (status.state, status.reason_code) == ("disabled", "sync_not_enabled")


def test_the_startup_line_carries_state_and_reason_only(started, monkeypatch, caplog):
    stub = RuntimeStatus("ready", "synchronized", local_build_id="pass-secret-1", remote_build_id="pass-secret-1")
    monkeypatch.setattr(fpl_server, "_football_licensed_sync", lambda: stub)
    with caplog.at_level(logging.INFO, logger=fpl_server._LOG.name):
        with TestClient(fpl_server.app):
            pass
    lines = [r.getMessage() for r in caplog.records if "football licensed sync" in r.getMessage()]
    assert lines == ["football licensed sync: state=ready reason=synchronized"]


def test_no_resync_thread_runs_while_the_flag_is_off(started):
    with TestClient(fpl_server.app):
        assert fpl_server._licensed_resync is not None and fpl_server._licensed_resync._thread is None


def test_the_resync_thread_starts_with_the_flag_and_stops_with_the_server(started, monkeypatch):
    monkeypatch.setenv("FPL_FOOTBALL_LICENSED_SYNC_ENABLED", "true")
    monkeypatch.setattr(fpl_server, "_football_licensed_sync", lambda: RuntimeStatus("degraded", "sync_failed"))
    with TestClient(fpl_server.app):
        resync = fpl_server._licensed_resync
        assert resync._thread is not None and resync._thread.is_alive()
        assert (resync.status.state, resync.status.reason_code) == ("degraded", "sync_failed")
        thread = resync._thread
    assert not thread.is_alive() and resync._thread is None

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

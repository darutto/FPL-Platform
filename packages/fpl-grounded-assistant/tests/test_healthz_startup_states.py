"""/healthz shows the European manual layer and the licensed sync states: counts and codes only, never content."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import fpl_server

client = TestClient(fpl_server.app)


def _clear(monkeypatch):
    for attr in ("manual_calendar_status", "football_licensed_status"):
        if hasattr(fpl_server.app.state, attr):
            monkeypatch.delattr(fpl_server.app.state, attr)
    monkeypatch.setattr(fpl_server, "_licensed_resync", None)


def test_without_startup_states_the_payload_has_neither_key(monkeypatch):
    _clear(monkeypatch)
    body = client.get("/healthz").json()
    assert "manual_calendar" not in body and "football_licensed" not in body


def test_the_manual_layer_state_is_exposed_as_counts_only(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setattr(fpl_server.app.state, "manual_calendar_status",
                        {"state": "written", "matches": 44, "list_date": "2026-10-28", "extra": "never shown"},
                        raising=False)
    assert client.get("/healthz").json()["manual_calendar"] == {"state": "written", "matches": 44,
                                                                "list_date": "2026-10-28"}


def test_the_licensed_state_prefers_the_live_resync_and_shows_codes_only(monkeypatch):
    _clear(monkeypatch)
    startup = SimpleNamespace(state="unavailable", reason_code="remote_unavailable", local_build_id="b1")
    monkeypatch.setattr(fpl_server.app.state, "football_licensed_status", startup, raising=False)
    assert client.get("/healthz").json()["football_licensed"] == {"state": "unavailable",
                                                                  "reason_code": "remote_unavailable"}
    live = SimpleNamespace(state="ready", reason_code="synchronized", local_build_id="b2")
    monkeypatch.setattr(fpl_server, "_licensed_resync", SimpleNamespace(status=live))
    assert client.get("/healthz").json()["football_licensed"] == {"state": "ready", "reason_code": "synchronized"}

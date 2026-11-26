"""@resource ranking titles follow the request's locale, read off the serialized /ask body. Synthetic data only."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import fpl_server
from conftest import BOOTSTRAP
from fpl_grounded_assistant.quota import reset_quota

#: command -> (es, en)
TITLES = {
    "@form": ("Top forma", "Top Form"),
    "@xg": ("Top xGI — goles + asistencias esperados", "Top Expected Goal Involvements"),
    "@xa": ("Top xA — asistencias esperadas", "Top Expected Assists"),
    "@points": ("Top puntos", "Top Points"),
    "@minutes": ("Top minutos", "Top Minutes"),
    "@popular": ("Más seleccionados", "Most Selected"),
    "@injuries": ("Lesiones y disponibilidad", "Injuries & Availability"),
    "@minutes Saka": ("Minutos del jugador", "Player Minutes"),
    "@role Saka": ("Rol del jugador", "Player Role"),
    # The degraded envelopes carry the same titles.
    "@minutes Nadie Inventado": ("Minutos del jugador", "Player Minutes"),
    "@role": ("Rol del jugador", "Player Role"),
}


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    fpl_server._init_bootstrap(BOOTSTRAP)
    fpl_server._sessions.clear()
    reset_quota()
    monkeypatch.setenv("FPL_ORCH_ENABLED", "0")
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    yield TestClient(fpl_server.app)
    fpl_server._sessions.clear()
    reset_quota()


@pytest.mark.parametrize("command", list(TITLES))
@pytest.mark.parametrize("locale", ["es", "en"])
def test_ask_serializes_the_title_in_the_request_locale(server, command: str, locale: str) -> None:
    response = server.post("/ask", json={"question": command, "locale": locale}, headers={"X-User-Id": "u-titles"})
    assert response.status_code == 200
    body = response.json()
    expected = TITLES[command][0 if locale == "es" else 1]
    assert body["resource_rows"]["title"] == expected
    assert body["final_text"] == expected

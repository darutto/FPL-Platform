"""@xg and @xgi are two independent lists, read off the serialized /ask body. Synthetic data only; no provider."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant import intent_aliases
from fpl_grounded_assistant.quota import reset_quota

#: (name, xG, xGI): each metric has its own leader, far enough ahead for the gap line.
_PLAYERS = [("Alfa", "9.00", "1.00"), ("Bravo", "1.00", "12.00"), ("Charlie", "2.50", "3.00"),
            ("Delta", "0.50", "2.50"), ("Echo", "2.00", "2.00"), ("Foxtrot", "1.50", "1.50")]

#: resource -> (metric, es title, en title, first three rows)
LISTS = {
    "top_xg": ("expected_goals", "Top xG — goles esperados", "Top xG — expected goals",
               [("Alfa", 9.0), ("Charlie", 2.5), ("Echo", 2.0)]),
    "top_xgi": ("expected_goal_involvements", "Top xGI — goles + asistencias esperados",
                "Top Expected Goal Involvements", [("Bravo", 12.0), ("Charlie", 3.0), ("Delta", 2.5)]),
}

ALIASES = {
    "top_xg": ("@xg", "@XG", "@top_xg", "@goles_esperados", "@Goles_Esperados", "@expected_goals"),
    "top_xgi": ("@xgi", "@xGI", "@top_xgi", "@expected_goal_involvements"),
}


def _bootstrap() -> dict:
    elements = [{"id": i, "web_name": name, "team": i, "element_type": 3, "status": "a", "expected_goals": xg,
                 "expected_goal_involvements": xgi, "expected_assists": "0.10", "selected_by_percent": "50.0"}
                for i, (name, xg, xgi) in enumerate(_PLAYERS, 1)]
    return {"elements": elements, "teams": [{"id": i, "short_name": f"T{i}"} for i in range(1, 7)], "events": []}


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    fpl_server._init_bootstrap(_bootstrap())
    fpl_server._sessions.clear()
    reset_quota()
    monkeypatch.setenv("FPL_ORCH_ENABLED", "0")
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    yield TestClient(fpl_server.app)
    fpl_server._sessions.clear()
    reset_quota()


@pytest.mark.parametrize("locale", ["es", "en"])
@pytest.mark.parametrize("resource,command", [(r, c) for r, cs in ALIASES.items() for c in cs])
def test_each_alias_serves_its_own_season_list(server, resource: str, command: str, locale: str) -> None:
    metric, es_title, en_title, top = LISTS[resource]
    response = server.post("/ask", json={"question": command, "locale": locale}, headers={"X-User-Id": "u-xg"})
    assert response.status_code == 200
    body = response.json()
    title = es_title if locale == "es" else en_title
    assert body["resource_rows"]["resource"] == resource
    assert body["resource_rows"]["title"] == title == body["final_text"]
    assert [(r["web_name"], r["value"]) for r in body["resource_rows"]["rows"][:3]] == top
    gap = body["table_conclusions"][0]
    assert gap["key"] == "gap"
    assert gap["params"] == {"leaders": [top[0][0]], "metric": metric}


def test_the_unlisted_older_spellings_stay_on_the_xg_command() -> None:
    for alias in ("esperados", "expectativa", "top_xg_es"):
        assert intent_aliases.resolve_resource(alias) == "top_xg"


def test_both_lists_are_suggested_for_an_unknown_command(server) -> None:
    from fpl_grounded_assistant.decision_router import decide
    suggestions = decide("@nope", _bootstrap())["suggestions"]
    assert "@top_xg" in suggestions and "@top_xgi" in suggestions

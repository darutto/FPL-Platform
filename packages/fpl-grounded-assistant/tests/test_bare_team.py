"""A bare club name opens its team card on /ask and on a session turn, with no model. Made-up league."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant.bare_team import bare_team
from test_team_card import CLUB, league, team_of


@pytest.mark.parametrize("text", ["Alder Town", "  alder town? ", "¿Alder Town?", "ALDER TOWN"])
def test_the_whole_input_naming_a_club_matches(text):
    bootstrap, _ = league()
    assert bare_team(text, bootstrap) == team_of(bootstrap)


def test_the_short_code_matches():
    bootstrap, _ = league()
    team = team_of(bootstrap)
    assert bare_team(team["short_name"].lower(), bootstrap) == team


@pytest.mark.parametrize("text", ["Alder", "Alder Tow", "Alder Town fixtures", "how is Alder Town", "", "?"])
def test_a_part_of_a_name_or_extra_words_do_not_match(text):
    bootstrap, _ = league()
    assert bare_team(text, bootstrap) is None


def test_a_listed_alias_matches_only_when_its_club_is_in_the_league():
    teams = {"teams": [{"id": 1, "name": "Man City", "short_name": "MCI"}]}
    assert bare_team("Manchester City", teams)["id"] == 1
    assert bare_team("manchester", teams) is None
    assert bare_team("spurs", teams) is None


@pytest.fixture
def client(monkeypatch, tmp_path):
    bootstrap, _ = league()
    monkeypatch.setattr(fpl_server, "_bootstrap", bootstrap)
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("FPL_ORCH_ENABLED", "true")

    def boom(*a, **k):
        raise AssertionError("a bare club name must not reach a model")

    import fpl_grounded_assistant.orchestrator as orch
    import fpl_grounded_assistant.reference_resolver as resolver
    monkeypatch.setattr(orch, "ask_orchestrated", boom)
    monkeypatch.setattr(resolver, "resolve_reference", boom)
    monkeypatch.setattr(resolver, "resolve_comparison_followup_llm", boom)
    http = TestClient(fpl_server.app)
    http.bootstrap = bootstrap
    return http


def _check_team_answer(body, team):
    assert (body["intent"], body["outcome"], body["llm_used"]) == ("team_card", "ok", False)
    assert body["final_text"] == team["name"]
    assert body["team_card"]["kind"] == "team" and body["team_card"]["card"]["team"]["id"] == team["id"]
    assert body["player_snapshot"] is None and "team_chip" not in body


def test_ask_serves_the_team_card_and_the_same_body_as_post_card(client):
    team = team_of(client.bootstrap)
    body = client.post("/ask", json={"question": CLUB, "locale": "en"}).json()
    _check_team_answer(body, team)
    card = client.post("/card", json={"kind": "team", "team_id": team["id"], "locale": "en"}).json()
    assert body["team_card"] == card


def test_session_serves_the_team_card_even_with_context_to_resolve(client, monkeypatch):
    team = team_of(client.bootstrap)
    session_id = client.post("/session").json()["session_id"]
    from fpl_grounded_assistant.conversation_state import ConversationState
    monkeypatch.setattr(ConversationState, "has_resolvable_context", lambda self: True)
    body = client.post(f"/session/{session_id}/ask", json={"question": CLUB}).json()
    _check_team_answer(body, team)
    assert fpl_server._sessions[session_id].session.last_player_query is None


@pytest.mark.parametrize("path", ["ask", "session"])
def test_a_player_of_the_same_name_wins_and_offers_the_club(client, path):
    team = team_of(client.bootstrap)
    for element in client.bootstrap["elements"]:   # the fields a player snapshot reads
        element.setdefault("status", "a")
        element.setdefault("first_name", "Test")
        element.setdefault("second_name", element["web_name"])
    player = client.bootstrap["elements"][0]
    original = player["web_name"]
    player["web_name"] = CLUB
    try:
        if path == "ask":
            url = "/ask"
        else:
            url = f"/session/{client.post('/session').json()['session_id']}/ask"
        body = client.post(url, json={"question": CLUB}).json()
    finally:
        player["web_name"] = original
    assert body["intent"] == "player_snapshot" and "team_card" not in body
    assert body["team_chip"] == {"team_id": team["id"], "name": team["name"]}

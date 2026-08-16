"""PR 4: stable-id player wizard handoff across backend contracts."""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from fpl_grounded_assistant.conversation_state import ConversationSession
from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot
from fpl_grounded_assistant.harness import ask_v2
from fpl_grounded_assistant.suggestions import (
    player_disambiguation_suggestions,
    suggestions_to_list,
)


def _with_joao_pedros(bootstrap: dict) -> dict:
    result = copy.deepcopy(bootstrap)
    result["elements"].extend([
        {
            "id": 30, "first_name": "Joao", "second_name": "Pedro",
            "web_name": "Joao Pedro", "team": 8, "element_type": 4,
            "status": "a", "total_points": 80, "minutes": 900,
        },
        {
            "id": 31, "first_name": "Joao", "second_name": "Pedro",
            "web_name": "Joao Pedro", "team": 11, "element_type": 4,
            "status": "a", "total_points": 70, "minutes": 800,
        },
    ])
    return result


def test_snapshot_accepts_numeric_element_id(bootstrap: dict):
    result = get_player_snapshot(1, bootstrap=bootstrap)
    assert result["status"] == "ok"
    assert result["player"]["id"] == 1
    assert result["player"]["web_name"] == "Haaland"


def test_player_suggestions_distinguish_identical_labels_by_id():
    candidates = [
        {"id": 101, "web_name": "JoÃ£o Pedro", "team_short": "CHE"},
        {"id": 202, "web_name": "JoÃ£o Pedro", "team_short": "CHE"},
    ]
    wire = suggestions_to_list(player_disambiguation_suggestions(candidates))
    assert wire is not None
    assert [item["label"] for item in wire] == ["JoÃ£o Pedro (CHE)"] * 2
    assert [item["player_id"] for item in wire] == [101, 202]


def test_selected_id_bypasses_question_and_orchestration(monkeypatch, bootstrap: dict):
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *args, **kwargs: pytest.fail("orchestrator must not run"),
    )
    result = ask_v2(
        "This label deliberately names Salah",
        bootstrap,
        selected_player_id=1,
        orch_client=object(),
    )
    assert result["outcome"] == "ok"
    assert result["raw_output"]["player"]["id"] == 1
    assert result["routing_trace"]["player_lookup_branch"] == "selected_player_id"
    assert result["routing_trace"]["orchestrator_called"] is False


def test_joao_pedro_wizard_selects_chelsea_by_id_in_one_request(
    monkeypatch, bootstrap: dict
):
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *args, **kwargs: pytest.fail("orchestrator must not run"),
    )
    bs = _with_joao_pedros(bootstrap)
    ambiguous = ask_v2("Joao Pedro", bs, orch_client=object())
    assert ambiguous["outcome"] == "ambiguous"
    chelsea = next(
        suggestion
        for suggestion in ambiguous["player_suggestions"]
        if suggestion["label"].endswith("(CHE)")
    )
    assert chelsea["player_id"] == 30

    selected = ask_v2(
        chelsea["label"],
        bs,
        selected_player_id=chelsea["player_id"],
        orch_client=object(),
    )
    assert selected["outcome"] == "ok"
    assert selected["raw_output"]["player"]["id"] == 30
    assert selected["raw_output"]["player"]["team_short"] == "CHE"
    assert selected["routing_trace"]["orchestrator_called"] is False


def test_invalid_selected_id_never_falls_back_to_display_label(monkeypatch, bootstrap: dict):
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *args, **kwargs: pytest.fail("orchestrator must not run"),
    )
    result = ask_v2(
        "Haaland",
        bootstrap,
        selected_player_id=999_999,
        orch_client=object(),
    )
    assert result["outcome"] == "not_found"
    assert result["raw_output"]["status"] == "not_found"
    assert result["player_snapshot"] is None
    assert result["routing_trace"]["orchestrator_called"] is False


def test_session_selected_id_updates_player_context(bootstrap: dict):
    session = ConversationSession()
    response = session.respond_to_selected_player_id(
        1,
        bootstrap,
        question_text="Haaland (MCI)",
    )
    assert response.outcome == "ok"
    assert response.player_snapshot is not None
    assert response.player_snapshot.id == 1
    assert session.last_player_query == "Haaland"
    assert session.turn_count == 1
    assert session.last_tokens == 0


def test_stale_session_id_does_not_fall_back_or_overwrite_context(
    monkeypatch, bootstrap: dict
):
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *args, **kwargs: pytest.fail("orchestrator must not run"),
    )
    session = ConversationSession()
    session.respond_to_selected_player_id(1, bootstrap, question_text="Haaland (MCI)")
    stale = session.respond_to_selected_player_id(
        999_999,
        bootstrap,
        question_text="Salah (LIV)",
    )
    assert stale.outcome == "not_found"
    assert stale.player_snapshot is None
    assert session.last_player_query == "Haaland"
    assert session.turn_count == 2


def test_http_stateless_and_session_selected_id_contracts(monkeypatch, bootstrap: dict):
    import fpl_server

    monkeypatch.setenv("FPL_SESSION_ENABLED", "true")
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *args, **kwargs: pytest.fail("orchestrator must not run"),
    )
    fpl_server._init_bootstrap(bootstrap)
    fpl_server._clear_sessions()
    client = TestClient(fpl_server.app)
    headers = {"X-User-Id": "stable-id-handoff", "X-User-Tier": "premium"}
    try:
        stateless = client.post(
            "/ask",
            json={"question": "Salah (LIV)", "selected_player_id": 1},
            headers=headers,
        )
        assert stateless.status_code == 200
        stateless_body = stateless.json()
        assert stateless_body["intent"] == "player_snapshot"
        assert stateless_body["outcome"] == "ok"
        assert stateless_body["llm_used"] is False
        assert stateless_body["player_snapshot"]["id"] == 1

        created = client.post("/session", headers=headers)
        session_id = created.json()["session_id"]
        stateful = client.post(
            f"/session/{session_id}/ask",
            json={"question": "Salah (LIV)", "selected_player_id": 1},
            headers=headers,
        )
        assert stateful.status_code == 200
        stateful_body = stateful.json()
        assert stateful_body["intent"] == "player_snapshot"
        assert stateful_body["outcome"] == "ok"
        assert stateful_body["llm_used"] is False
        assert stateful_body["player_snapshot"]["id"] == 1
        assert fpl_server._sessions[session_id].session.last_player_query == "Haaland"

        stale = client.post(
            "/ask",
            json={"question": "Haaland", "selected_player_id": 999_999},
            headers={**headers, "X-User-Id": "stable-id-stale"},
        )
        assert stale.status_code == 200
        stale_body = stale.json()
        assert stale_body["intent"] == "player_snapshot"
        assert stale_body["outcome"] == "not_found"
        assert stale_body["player_snapshot"] is None
        assert stale_body["llm_used"] is False
    finally:
        fpl_server._clear_sessions()


def test_selected_id_cannot_bypass_quota_with_slash_display_text(monkeypatch, bootstrap: dict):
    import fpl_server

    denied = fpl_server.QuotaCheck(
        allowed=False,
        tier="free",
        daily_tokens_used=0,
        daily_message_count=0,
        monthly_tokens_used=0,
        monthly_message_count=0,
        daily_token_cap=0,
        monthly_token_cap=0,
        daily_message_cap=0,
        monthly_message_cap=0,
        reason="message_cap",
        upgrade_prompt_es="quota bloqueada",
        upgrade_prompt_en="quota blocked",
    )
    monkeypatch.setattr(fpl_server, "check_quota", lambda *args, **kwargs: denied)
    fpl_server._init_bootstrap(bootstrap)
    response = TestClient(fpl_server.app).post(
        "/ask",
        json={"question": "/", "selected_player_id": 1},
        headers={"X-User-Id": "stable-id-quota", "X-User-Tier": "free"},
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "quota_exceeded"
    assert response.json()["player_snapshot"] is None


@pytest.mark.parametrize("invalid_id", ["1", 1.5, True])
def test_http_selected_player_id_is_strict_integer(invalid_id, bootstrap: dict):
    import fpl_server

    fpl_server._init_bootstrap(bootstrap)
    response = TestClient(fpl_server.app).post(
        "/ask",
        json={"question": "Haaland", "selected_player_id": invalid_id},
        headers={"X-User-Id": "stable-id-validation", "X-User-Tier": "premium"},
    )
    assert response.status_code == 422


def test_null_selected_player_id_preserves_typed_lookup(bootstrap: dict):
    import fpl_server

    fpl_server._init_bootstrap(bootstrap)
    response = TestClient(fpl_server.app).post(
        "/ask",
        json={"question": "Haaland", "selected_player_id": None},
        headers={"X-User-Id": "stable-id-null", "X-User-Tier": "premium"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "ok"
    assert body["player_snapshot"]["id"] == 1

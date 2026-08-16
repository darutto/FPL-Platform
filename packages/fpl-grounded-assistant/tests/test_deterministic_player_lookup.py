"""PR 2: deterministic rich-card routing and safe fallthrough coverage."""
from __future__ import annotations

import copy

import pytest

from fpl_grounded_assistant.conversation_state import ConversationSession
from fpl_grounded_assistant.harness import ask_v2
from fpl_grounded_assistant.harness_adapter import to_ask_response
from fpl_grounded_assistant.orchestrator import OrchestratorResult
from fpl_grounded_assistant.player_lookup import classify_player_lookup


def _with_collisions(bootstrap: dict) -> dict:
    bs = copy.deepcopy(bootstrap)
    bs["elements"].extend([
        {
            "id": 30, "first_name": "João", "second_name": "Pedro",
            "web_name": "João Pedro", "team": 8, "element_type": 4,
            "status": "a", "total_points": 80, "minutes": 900,
        },
        {
            "id": 31, "first_name": "João", "second_name": "Pedro",
            "web_name": "João Pedro", "team": 11, "element_type": 4,
            "status": "a", "total_points": 70, "minutes": 800,
        },
        {
            "id": 32, "first_name": "Diego", "second_name": "Costa",
            "web_name": "Costa", "team": 8, "element_type": 4,
            "status": "a", "total_points": 60, "minutes": 700,
        },
    ])
    return bs


def _orch_result(tool: str = "get_current_gameweek") -> OrchestratorResult:
    output = {"status": "ok", "gameweek": 28}
    if tool == "rank_captain_candidates":
        output = {"status": "ok", "rankings": []}
    return OrchestratorResult(
        question="controlled",
        tool_chosen=tool,
        tool_args={},
        tool_output=output,
        answer_text="controlled orchestrated answer",
        llm_used=True,
        model="controlled",
        outcome="ok",
    )


def _orch_no_tool_result() -> OrchestratorResult:
    return OrchestratorResult(
        question="controlled",
        tool_chosen=None,
        tool_args={},
        tool_output={},
        answer_text="No grounded tool was selected.",
        llm_used=True,
        model="controlled",
        outcome="no_tool",
        primary_input_tokens=9,
        primary_output_tokens=4,
        total_tokens=13,
    )


@pytest.fixture(autouse=True)
def _orch_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr(
        "fpl_grounded_assistant.harness._build_eval_client",
        lambda *args, **kwargs: None,
    )


@pytest.mark.parametrize(
    ("question", "strategy"),
    [
        ("Haaland", "web_name"),
        ("KDB", "alias"),
        ("Haal", "prefix"),
        ("who is Haaland?", "web_name"),
        ("stats for Haaland", "web_name"),
        ("quién es Haaland?", "web_name"),
        ("dame un resumen de Haaland", "web_name"),
    ],
)
def test_classifier_recognises_bare_and_explicit_player_inputs(
    bootstrap: dict, question: str, strategy: str
):
    decision = classify_player_lookup(question, bootstrap)
    assert decision.status == "ok"
    assert decision.resolution_strategy == strategy
    assert decision.candidate_count == 1


def test_explicit_discovery_allows_substring_but_bare_input_does_not(bootstrap: dict):
    assert classify_player_lookup("land", bootstrap).status == "not_found"
    explicit = classify_player_lookup("find land", bootstrap)
    assert explicit.status == "ok"
    assert explicit.resolution_strategy == "substring"


def test_bare_prefix_requires_four_non_stopword_characters(bootstrap: dict):
    assert classify_player_lookup("Haa", bootstrap).status == "not_found"
    assert classify_player_lookup("Haal", bootstrap).status == "ok"


def test_team_code_narrows_a_complete_bare_name(bootstrap: dict):
    bs = _with_collisions(bootstrap)
    assert classify_player_lookup("Joao Pedro", bs).status == "ambiguous"
    narrowed = classify_player_lookup("Joao Pedro CHE", bs)
    assert narrowed.status == "ok"
    assert narrowed.resolution is not None
    assert narrowed.resolution.player is not None
    assert narrowed.resolution.player.record.id == 30


@pytest.mark.parametrize("question", ["vamos a la costa", "la costa está bonita"])
def test_contextual_homonym_sentences_do_not_intercept(bootstrap: dict, question: str):
    decision = classify_player_lookup(question, _with_collisions(bootstrap))
    assert not decision.terminal


def test_bare_exact_homonym_is_fpl_first(bootstrap: dict):
    decision = classify_player_lookup("Costa", _with_collisions(bootstrap))
    assert decision.status == "ok"
    assert decision.resolution is not None
    assert decision.resolution.player is not None
    assert decision.resolution.player.record.id == 32


def test_unique_lookup_returns_card_without_orchestrator(monkeypatch, bootstrap: dict):
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *args, **kwargs: pytest.fail("orchestrator must not run"),
    )
    result = ask_v2("Haaland", bootstrap, orch_client=object())
    assert result["selected_tool"] == "get_player_snapshot"
    assert result["outcome"] == "ok"
    assert result["player_snapshot"].web_name == "Haaland"
    trace = result["routing_trace"]
    assert trace["branch"] == "route"
    assert trace["orchestrator_called"] is False
    assert trace["player_resolution_strategy"] == "web_name"
    assert trace["player_candidate_count"] == 1
    assert trace["player_lookup_branch"] == "bare_ok"


def test_ambiguous_lookup_returns_wizard_without_orchestrator(monkeypatch, bootstrap: dict):
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *args, **kwargs: pytest.fail("orchestrator must not run"),
    )
    result = ask_v2("Joao Pedro", _with_collisions(bootstrap), orch_client=object())
    assert result["outcome"] == "ambiguous"
    assert result["selected_tool"] == "get_player_snapshot"
    assert len(result["player_suggestions"]) == 2
    assert result["routing_trace"]["player_candidate_count"] == 2


def test_explicit_ambiguous_lookup_returns_same_wizard(monkeypatch, bootstrap: dict):
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *args, **kwargs: pytest.fail("orchestrator must not run"),
    )
    result = ask_v2(
        "who is Joao Pedro?", _with_collisions(bootstrap), orch_client=object()
    )
    assert result["outcome"] == "ambiguous"
    assert len(result["player_suggestions"]) == 2
    assert result["routing_trace"]["player_lookup_branch"] == "explicit_ambiguous"


@pytest.mark.parametrize(
    "question",
    [
        "who is Zidane?",
        "tell me about the best transfers this week",
        "vamos a la costa",
        "la costa está bonita",
    ],
)
def test_misses_and_contextual_sentences_reach_orchestration_unchanged(
    monkeypatch, bootstrap: dict, question: str
):
    seen: list[str] = []

    def fake_orchestrator(actual_question: str, *args, **kwargs):
        seen.append(actual_question)
        return _orch_result()

    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated", fake_orchestrator
    )
    result = ask_v2(question, _with_collisions(bootstrap), orch_client=object())
    assert seen == [question]
    assert result["routing_trace"]["branch"] == "orchestrator"


def test_analytical_who_is_question_reaches_captain_orchestration(
    monkeypatch, bootstrap: dict
):
    question = "who is the best captain pick this week?"
    seen: list[str] = []

    def fake_orchestrator(actual_question: str, *args, **kwargs):
        seen.append(actual_question)
        return _orch_result("rank_captain_candidates")

    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated", fake_orchestrator
    )
    result = ask_v2(question, bootstrap, orch_client=object())
    assert seen == [question]
    assert result["selected_tool"] == "rank_captain_candidates"
    assert result["routing_trace"]["player_lookup_branch"] in {
        "specialized_fallthrough", "explicit_not_found_fallthrough"
    }


@pytest.mark.parametrize("question", ["Haaland", "who is Haaland?", "stats for Haaland"])
def test_stateless_and_session_unique_responses_match(bootstrap: dict, question: str):
    import fpl_server

    stateless = to_ask_response(
        ask_v2(question, bootstrap, orch_client=object()),
        fpl_server.AskRequest(question=question),
    )
    session = ConversationSession()
    stateful = session.respond(question, bootstrap)
    assert (stateless.intent, stateless.outcome, stateless.llm_used) == (
        stateful.intent, stateful.outcome, stateful.llm_used
    )
    assert stateless.player_snapshot is not None
    assert stateful.player_snapshot is not None
    assert stateless.player_snapshot["web_name"] == stateful.player_snapshot.web_name
    assert session.last_player_query is not None


def test_invalid_session_intent_hint_does_not_suppress_player_lookup(bootstrap: dict):
    response = ConversationSession().respond(
        "Haaland", bootstrap, intent_hint="not_a_registered_hint"
    )
    assert response.intent == "player_snapshot"
    assert response.outcome == "ok"
    assert response.llm_used is False


def test_valid_specialized_session_intent_hint_retains_priority(bootstrap: dict):
    response = ConversationSession().respond(
        "Haaland", bootstrap, intent_hint="captain_score"
    )
    assert response.intent == "captain_score"


def test_session_explicit_miss_reaches_orchestration_with_original_question(
    monkeypatch, bootstrap: dict
):
    question = "who is Zidane?"
    seen: list[str] = []

    def fake_orchestrator(actual_question: str, *args, **kwargs):
        seen.append(actual_question)
        return _orch_result()

    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated", fake_orchestrator
    )
    response = ConversationSession().respond(question, bootstrap, client=object())
    assert seen == [question]
    assert response.intent == "current_gameweek"
    assert response.llm_used is True


def test_session_uses_one_orchestration_call_when_fi_is_enabled(
    monkeypatch, bootstrap: dict
):
    calls: list[str] = []

    def fake_orchestrator(actual_question: str, *args, **kwargs):
        calls.append(actual_question)
        return _orch_result("rank_captain_candidates")

    monkeypatch.setenv("FOOTBALL_INTELLIGENCE_ENABLED", "1")
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated", fake_orchestrator
    )
    response = ConversationSession().respond(
        "who is the best captain pick this week?", bootstrap, client=object()
    )
    assert calls == ["who is the best captain pick this week?"]
    assert response.intent == "rank_candidates"


def test_session_orchestration_records_response_telemetry_once(
    monkeypatch, bootstrap: dict
):
    events: list[dict] = []
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *args, **kwargs: _orch_result(),
    )
    monkeypatch.setattr(
        "fpl_grounded_assistant.final_response._telemetry.record_response",
        lambda **kwargs: events.append(kwargs),
    )
    ConversationSession().respond("who is Zidane?", bootstrap, client=object())
    assert len(events) == 1
    assert events[0]["intent"] == "current_gameweek"
    assert events[0]["outcome"] == "ok"


def test_session_no_tool_does_not_make_a_second_provider_call(
    monkeypatch, bootstrap: dict
):
    calls: list[str] = []

    def fake_orchestrator(actual_question: str, *args, **kwargs):
        calls.append(actual_question)
        return _orch_no_tool_result()

    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated", fake_orchestrator
    )
    session = ConversationSession()
    response = session.respond("who is Zidane?", bootstrap, client=object())
    assert calls == ["who is Zidane?"]
    assert response.intent == "unsupported"
    assert response.outcome == "unsupported_intent"
    assert response.llm_used is False
    assert session.last_tokens == 13


def test_stateless_and_session_ambiguity_match(bootstrap: dict):
    import fpl_server

    bs = _with_collisions(bootstrap)
    stateless = to_ask_response(
        ask_v2("Joao Pedro", bs, orch_client=object()),
        fpl_server.AskRequest(question="Joao Pedro"),
    )
    stateful = ConversationSession().respond("Joao Pedro", bs)
    assert stateless.intent == stateful.intent == "player_snapshot"
    assert stateless.outcome == stateful.outcome == "ambiguous"
    assert stateless.llm_used is stateful.llm_used is False
    assert stateless.suggestions is not None
    assert stateful.suggestions is not None
    assert [item["send_text"] for item in stateless.suggestions] == [
        item.send_text for item in stateful.suggestions
    ]
    assert [item["player_id"] for item in stateless.suggestions] == [
        item.player_id for item in stateful.suggestions
    ]


def test_http_stateless_and_session_player_contracts_match(monkeypatch, bootstrap: dict):
    from fastapi.testclient import TestClient
    import fpl_server

    bs = _with_collisions(bootstrap)
    monkeypatch.setenv("FPL_SESSION_ENABLED", "true")
    fpl_server._init_bootstrap(bs)
    fpl_server._clear_sessions()
    client = TestClient(fpl_server.app)
    headers = {"X-User-Id": "pr2-player-parity", "X-User-Tier": "premium"}
    try:
        stateless = client.post(
            "/ask", json={"question": "Joao Pedro"}, headers=headers
        )
        created = client.post("/session", headers=headers)
        session_id = created.json()["session_id"]
        stateful = client.post(
            f"/session/{session_id}/ask",
            json={"question": "Joao Pedro"},
            headers=headers,
        )
        assert stateless.status_code == stateful.status_code == 200
        left, right = stateless.json(), stateful.json()
        assert (left["intent"], left["outcome"], left["llm_used"]) == (
            right["intent"], right["outcome"], right["llm_used"]
        )
        assert left["suggestions"] == right["suggestions"]
    finally:
        fpl_server._init_bootstrap(bootstrap)
        fpl_server._clear_sessions()

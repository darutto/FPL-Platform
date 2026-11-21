"""Web search vs the deterministic player fast path (mocked clients only)."""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.harness import ask_v2
from fpl_grounded_assistant.orchestrator import OrchestratorResult
from fpl_grounded_assistant.player_lookup import (
    classify_player_lookup,
    has_availability_intent,
    should_divert_player_lookup,
)


def _orch_result(*, ran_search: bool = False) -> OrchestratorResult:
    trace = [{"name": "search_web", "args": {"query": "q"}, "output": {"status": "ok"}}] if ran_search else []
    return OrchestratorResult(
        question="controlled",
        tool_chosen="get_current_gameweek",
        tool_args={},
        tool_output={"status": "ok", "gameweek": 28},
        answer_text="controlled orchestrated answer",
        llm_used=True,
        model="controlled",
        outcome="ok",
        synthesis_turn=True,
        tool_calls_trace=trace,
    )


@pytest.fixture(autouse=True)
def _orch_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr(
        "fpl_grounded_assistant.harness._build_eval_client",
        lambda *args, **kwargs: None,
    )


@pytest.mark.parametrize(
    "question",
    [
        "tiene algún problema de lesión Saka? en FPL aparece con 75% de posibilidad de jugar",
        "¿tiene lesión Saka?",
        "¿está lesionado Saka?",
        "¿hay duda con Saka?",
        "Saka está en duda?",
        "¿jugará Saka este fin de semana?",
        "¿va a jugar Saka?",
        "noticias de Saka",
        "is Saka injured",
        "will Saka play this week?",
        "Saka injury news",
        "is Saka fit?",
        "is Saka available?",
        "Saka chance of playing",
    ],
)
def test_availability_intent_positives(question: str):
    assert has_availability_intent(question)


@pytest.mark.parametrize(
    "question",
    [
        "Saka",
        "who is Saka?",
        "stats for Saka",
        "Saka fixtures",
        "Saka fixture run",
        "fitness",
        "profit from Saka",
        "dame un resumen de Saka",
        "quién es Saka?",
        "who is the best captain pick this week?",
    ],
)
def test_availability_intent_negatives(question: str):
    assert not has_availability_intent(question)


def test_decision_table(bootstrap: dict):
    bare = classify_player_lookup("Saka", bootstrap)
    explicit = classify_player_lookup("¿tiene lesión Saka?", bootstrap)
    who = classify_player_lookup("who is Saka?", bootstrap)
    assert not bare.explicit and explicit.explicit and who.explicit
    # bare name: free in every mode
    assert should_divert_player_lookup(bare, "Saka", False) == (False, None)
    assert should_divert_player_lookup(bare, "Saka", True) == (False, None)
    # availability question diverts with search off and on
    assert should_divert_player_lookup(explicit, "¿tiene lesión Saka?", False) == (
        True, "availability_intent",
    )
    assert should_divert_player_lookup(explicit, "¿tiene lesión Saka?", True) == (
        True, "web_search",
    )
    # plain question-shaped turn: free with search off, diverted with search on
    assert should_divert_player_lookup(who, "who is Saka?", False) == (False, None)
    assert should_divert_player_lookup(who, "who is Saka?", True) == (True, "web_search")


def _spy(monkeypatch, *, ran_search: bool = False) -> list[dict]:
    calls: list[dict] = []

    def fake(question, *args, **kwargs):
        calls.append({"question": question, **kwargs})
        return _orch_result(ran_search=ran_search)

    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", fake)
    return calls


def test_bare_name_with_search_on_stays_free(monkeypatch, bootstrap: dict):
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *a, **k: pytest.fail("orchestrator must not run"),
    )
    result = ask_v2("Saka", bootstrap, orch_client=object(), web_search_enabled=True)
    assert result["selected_tool"] == "get_player_snapshot"
    trace = result["routing_trace"]
    assert trace["orchestrator_called"] is False
    assert trace["web_search_enabled"] is True
    assert trace["search_web_ran"] is False


def test_question_with_search_on_reaches_orchestrator_with_search(monkeypatch, bootstrap: dict):
    calls = _spy(monkeypatch, ran_search=True)
    result = ask_v2("who is Saka?", bootstrap, orch_client=object(), web_search_enabled=True)
    assert len(calls) == 1 and calls[0]["web_search_enabled"] is True
    trace = result["routing_trace"]
    assert trace["branch"] == "orchestrator"
    assert trace["player_lookup_diverted"] == "web_search"
    assert trace["search_web_ran"] is True


def test_search_offered_but_not_run_is_recorded(monkeypatch, bootstrap: dict):
    _spy(monkeypatch, ran_search=False)
    result = ask_v2("¿tiene lesión Saka?", bootstrap, orch_client=object(), web_search_enabled=True)
    trace = result["routing_trace"]
    assert trace["web_search_enabled"] is True
    assert trace["search_web_ran"] is False


def test_availability_question_with_search_off_reaches_orchestrator(monkeypatch, bootstrap: dict):
    calls = _spy(monkeypatch)
    result = ask_v2("¿tiene lesión Saka?", bootstrap, orch_client=object())
    assert len(calls) == 1 and not calls[0]["web_search_enabled"]
    trace = result["routing_trace"]
    assert trace["branch"] == "orchestrator"
    assert trace["player_lookup_diverted"] == "availability_intent"
    assert trace["web_search_enabled"] is False


def test_plain_question_with_search_off_keeps_card(monkeypatch, bootstrap: dict):
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *a, **k: pytest.fail("orchestrator must not run"),
    )
    result = ask_v2("who is Saka?", bootstrap, orch_client=object())
    assert result["selected_tool"] == "get_player_snapshot"
    assert "player_lookup_diverted" not in result["routing_trace"]


def test_search_web_schema_steers_injury_questions_to_search_and_snapshot():
    from fpl_grounded_assistant.tool_schema_registry import SEARCH_WEB_SCHEMA

    text = SEARCH_WEB_SCHEMA.description
    assert "injury, availability, fitness or latest news" in text
    assert "call search_web as well as get_player_snapshot" in text
    assert "say which source says what" in text
    # still forbidden for stats and the like; no longer a blanket last resort
    assert "NEVER use it for player stats, prices, fixtures, or form" in text
    assert "LAST RESORT" not in text
    assert "Salah" not in text

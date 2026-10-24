"""
The deterministic router and the fixture-cell question the calendar UI sends.

A tap on a calendar cell hands the chat a composed question (packages/fpl-ui/lib/i18n
fx.q.cell; the shape is pinned on the UI side in __tests__/fixture-question-contract.test.ts).
It asks for BOTH sides of one match, which needs two outlook axes plus the team snapshot,
composed by the orchestrator. The deterministic fallback cannot answer that, so it must
decline (None) instead of routing it to a tool that answers something else:

* "Arsenal vs EVE (en casa), J7: ..." went to compare_players (the bare "vs" rule).
* "... GW7 (double gameweek): ..." went to get_current_gameweek (the bare "gameweek" word).

Both wordings are pinned here, in Spanish and English, with the router's exact input.
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.router import route

ES_SINGLE = "Arsenal vs EVE (en casa), J7: ¿qué tal pinta ofensivamente y defensivamente para el Arsenal?"
ES_DOUBLE = (
    "Arsenal vs EVE (en casa) y Arsenal vs NFO (a domicilio), J7 (doble jornada): "
    "¿qué tal pinta ofensivamente y defensivamente para el Arsenal?"
)
EN_SINGLE = "Arsenal vs EVE (at home), GW7: how do they look attacking and defensively for Arsenal?"
EN_DOUBLE = (
    "Arsenal vs EVE (at home) and Arsenal vs NFO (away), GW7 (double gameweek): "
    "how do they look attacking and defensively for Arsenal?"
)


@pytest.mark.parametrize("question", [ES_SINGLE, ES_DOUBLE, EN_SINGLE, EN_DOUBLE])
def test_a_fixture_cell_question_is_not_routed_deterministically(question):
    assert route(question) is None


@pytest.mark.parametrize("question", [ES_SINGLE, EN_SINGLE])
def test_the_cell_is_not_a_comparison(question):
    r = route(question)
    assert r is None or r.tool_name != "compare_players"


@pytest.mark.parametrize("question", [EN_SINGLE, EN_DOUBLE])
def test_an_english_gameweek_word_in_a_cell_is_not_the_current_gameweek(question):
    r = route(question)
    assert r is None or r.tool_name != "get_current_gameweek"


@pytest.mark.parametrize("question", [
    # team-row questions from the calendar, English and Spanish
    "How does Arsenal's attacking fixture run look over the next gameweeks?",
    "How good is Arsenal's fixture run for clean sheets coming up?",
    "¿Cómo pinta el calendario ofensivo del Arsenal en las próximas jornadas?",
])
def test_calendar_questions_with_gameweek_wording_are_not_the_current_gameweek(question):
    r = route(question)
    assert r is None or r.tool_name != "get_current_gameweek"


# -- the gameweek intent still answers real gameweek questions ----------------------

@pytest.mark.parametrize("question", [
    "what gameweek is it",
    "which gameweek are we in?",
    "current gameweek",
    "what gw is it",
    "gameweek?",
    "what's the next gameweek",
    "what is the upcoming gameweek",
])
def test_plain_gameweek_questions_still_route_to_the_current_gameweek(question):
    r = route(question)
    assert r is not None and r.tool_name == "get_current_gameweek", question


# -- ordinary comparisons are untouched ---------------------------------------------

@pytest.mark.parametrize("question, query_a, query_b", [
    ("Salah vs Haaland", "Salah", "Haaland"),
    ("compare Salah and Haaland", "Salah", "Haaland"),
])
def test_a_plain_versus_is_still_a_comparison(question, query_a, query_b):
    r = route(question)
    assert r is not None and r.tool_name == "compare_players"
    assert r.tool_args == {"query_a": query_a, "query_b": query_b}


def test_a_comparison_with_a_venue_word_but_no_attack_phrase_is_still_a_comparison():
    r = route("Salah vs Haaland at home")
    assert r is not None and r.tool_name == "compare_players"

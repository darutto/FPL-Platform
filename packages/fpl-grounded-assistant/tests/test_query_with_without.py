"""The with/without question must answer: four texts typed on the local stack, each with a stub model doing what
the audit line showed. The audit keeps no arguments, so each call is the smallest one that produces the logged
state and reason. The league and every number are synthetic; no network, no paid call.
"""
from __future__ import annotations

import pytest

import fpl_server
from fpl_grounded_assistant import query_catalogue as cat, query_tool
from fpl_grounded_assistant.query_with_without import detect

from test_query_door import Script, _offline, ask, calls, ne, says, server, v  # noqa: F401 -- fixtures


def _rename(bootstrap):
    bootstrap["teams"][0].update(name="Man City", short_name="MCI")
    bootstrap["teams"][1].update(name="Birch Vale")                  # one "City" only, as in the real league
    next(e for e in bootstrap["elements"] if e["id"] == 106).update(web_name="Semenyo", second_name="Semenyo",
                                                                    first_name="Antoine")


@pytest.fixture
def city(server):
    import fpl_server

    _rename(fpl_server._bootstrap)
    return server


def _sets(player="Semenyo"):
    return {"shape": v("comparison"), "grain": v("team"),
            "filters": [{"field": "club", "op": "eq", "value": "City", "quote": "City"}],
            "match_set": [{"pred": "player_played_60", "value": player, "quote": player}],
            "compare_to": [{"pred": "player_absent", "value": player, "quote": player}]}


LOGGED = {
    "asked_back": ("¿Cómo le fue al ataque del City con Semenyo y sin él?",
                   says("¿Quieres comparar los **goles** o el **xG** del City?")),
    "single_value": ("¿Cómo cambió la producción ofensiva del City con Semenyo y sin él?",
                     calls(("query", {"not_expressible": [ne("single_value", "producción ofensiva")]}))),
    "team_xgi": ("¿Cómo cambió el xgi del City con Semenyo y sin él?",
                 calls(("query", {"metric": v("xgi"), **_sets()}))),
    "player_attribute": ("Compara el xgi del city con Semenyo y sin el en el equipo",
                         calls(("query", {"metric": v("team_expected_goals"), **_sets(),
                                          "not_expressible": [ne("player_attribute", "xgi")]}))),
}


@pytest.mark.parametrize("surface", ["ask", "session"])
@pytest.mark.parametrize("case", LOGGED)
def test_the_logged_questions_answer_with_goals_and_xg(city, monkeypatch, case, surface):
    question, response = LOGGED[case]
    script = Script(response)
    body = ask(city, monkeypatch, question, script, surface, locale="es")
    block = body["query"]

    assert (body["outcome"], body["intent"], body["llm_used"]) == ("ok", "query", False), body
    assert block["state"] == "complete" and not body["clarification_asked"]
    assert (len(script.queue), script.extra) == (0, 0)
    sides = block["comparison"]["sides"]
    assert [s["gameweeks"] for s in sides] == [[1, 2, 3, 8], [4, 5, 6]]
    assert block["comparison"]["mixed"] == [{"gameweek": 7, "minutes": 13}]
    assert [s["n"] for s in sides] == [len(s["per_match_values_text"]) for s in sides]
    assert block["spec"]["metric"] == "team_goals" and block["spec"]["operator"] == "per_match"
    assert block["comparison"]["metric_header"] == "Goles y xG por partido de Man City"
    assert "Goles y xG por partido de Man City" in block["reading"]["text"]
    assert block["notes"][0].startswith("xG por partido: Con Semenyo")
    assert ("xGI es un dato de jugador" in block["reading"]["text"]) == ("xgi" in question)
    assert "¿Quieres" not in body["final_text"]
    assert body["final_text"].splitlines()[0] == "Muestro: " + block["reading"]["text"]
    assert city.audit[-1].branch == ("session" if surface == "session" else "orchestrator_query")


def test_english_with_no_metric(city, monkeypatch):
    body = ask(city, monkeypatch, "How did City do with and without Semenyo?", Script(says()))
    assert body["query"]["state"] == "complete"
    assert body["query"]["comparison"]["metric_header"] == "Man City goals and xG per match"


def test_a_complete_answer_to_one_named_metric_is_kept(city, monkeypatch):
    call = calls(("query", {"metric": v("team_goals"), **_sets()}))
    body = ask(city, monkeypatch, "Goles del City con Semenyo y sin él", Script(call), locale="es")
    assert body["query"]["state"] == "complete" and body["query"]["spec"]["operator"] == "sum"


@pytest.mark.parametrize("question", [
    "¿Cuántos goles recibió el City con Semenyo y sin él?",
    "Tarjetas del City con Semenyo y sin él",
    "Ataque del City en casa con Semenyo y sin él",
    "Ataque del City en las últimas 5 con Semenyo y sin él",
    "Ataque del Cedar Rovers con Semenyo y sin él",
    "Ataque con Semenyo y sin StrikerCed",
    "¿Cómo le fue al ataque del City?",
])
def test_anything_more_than_the_plain_question_is_left_to_the_model(city, question):
    import fpl_server

    assert detect(question, fpl_server._bootstrap) is None


def test_the_default_card_needs_the_door(city, monkeypatch):
    monkeypatch.delenv("FPL_QUERY_LAYER")
    body = ask(city, monkeypatch, LOGGED["asked_back"][0], Script(says()), locale="es")
    assert body.get("query") is None


def test_a_report_beside_a_valid_comparison_is_shown_as_unused(city, monkeypatch):
    call = calls(("query", {"metric": v("team_goals"), **_sets(),
                            "not_expressible": [ne("player_attribute", "en el equipo")]}))
    body = ask(city, monkeypatch, "Goles del City con Semenyo y sin él mirando su rol en el equipo",
               Script(call), locale="es")
    assert body["query"]["state"] == "complete", body["query"]
    assert "Sin usar: atributos del jugador" in body["query"]["reading"]["text"]


def _beside_a_comparison(report):
    args = {"metric": v("team_goals"), **_sets(), "not_expressible": [report]}
    return query_tool.answer_call(args, {**fpl_server._bootstrap, "_question": "City con Semenyo y sin Semenyo"})


@pytest.mark.parametrize("kind,quote", [("single_value", "producción ofensiva"), ("player_attribute", "xgi"),
                                        ("player_attribute", ["en el equipo"])])
def test_a_report_that_restricts_nothing_does_not_cancel(city, kind, quote):
    block = _beside_a_comparison(ne(kind, quote))["query"]
    assert block["state"] == "complete", block
    assert any(p["kind"] == "unused" and p["value"] == kind for p in block["reading"]["parts"])


@pytest.mark.parametrize("kind,quote", [
    *((k, "algo") for k in cat.UNSUPPORTED_KINDS if k not in ("single_value", "player_attribute")),  # result too
    ("player_attribute", "jugadores zurdos"), ("player_attribute", ["en el equipo", "zurdos"]),
    ("player_attribute", ""),
])
def test_a_report_that_restricts_keeps_the_comparison_unsupported(city, kind, quote):
    block = _beside_a_comparison(ne(kind, quote))["query"]
    assert block["state"] == "unsupported_constraint" and block["comparison"] is None, block


@pytest.mark.parametrize("question,locale", [
    ("¿Cómo le fue al City con Semenyo y sin él en defensa?", "es"),
    ("¿Cómo cambió el City defensivamente con Semenyo y sin él?", "es"),
    ("Goles recibidos del City con Semenyo y sin él", "es"),
    ("How was City's defence with and without Semenyo?", "en"),
    ("How did City do defensively with and without Semenyo?", "en"),
    ("City goals conceded with and without Semenyo", "en"),
])
def test_the_defence_answers_with_conceded_xgc_and_clean_sheets(city, monkeypatch, question, locale):
    # the logged turn: a goals-conceded comparison with a stray "result" report beside it
    call = calls(("query", {"metric": v("team_goals_conceded"), **_sets(),
                            "not_expressible": [ne("result", "Cómo le fue")]}))
    body = ask(city, monkeypatch, question, Script(call), locale=locale)
    block = body["query"]
    assert block["state"] == "complete", block
    assert block["spec"]["metric"] == "team_goals_conceded" and block["spec"]["operator"] == "per_match"
    header, xgc, clean = (("Goles recibidos y xGC por partido de Man City", "xGC por partido:", "Porterías a cero:")
                          if locale == "es" else
                          ("Man City goals conceded and xGC per match", "xGC per match:", "Clean sheets:"))
    assert block["comparison"]["metric_header"] == header
    assert block["notes"][0].startswith(xgc) and block["notes"][1].startswith(clean)


@pytest.mark.parametrize("question", [
    "City en ataque y defensa con Semenyo y sin él",
    "Defensa del City en casa con Semenyo y sin él",
    "Defensa del City cuando ganó con Semenyo y sin él",
])
def test_a_defence_question_with_more_in_it_is_left_to_the_model(city, question):
    assert detect(question, fpl_server._bootstrap) is None


@pytest.mark.parametrize("quote,state", [("¿Cómo le fue", "complete"), ("en defensa", "complete"),
                                         ("cuando ganaron", "unsupported_constraint"),
                                         ("en las derrotas", "unsupported_constraint")])
def test_a_result_report_brakes_only_when_it_names_a_result(city, quote, state):
    assert _beside_a_comparison(ne("result", quote))["query"]["state"] == state

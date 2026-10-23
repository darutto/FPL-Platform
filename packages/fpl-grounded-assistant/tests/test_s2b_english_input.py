"""S2b: the English input side. Deterministic routing only, no provider, no network.

Pins, for each English phrase the plan found missing, that it routes, and that the Spanish
spelling of the same input still routes exactly as before.
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.catalogue import t
from fpl_grounded_assistant.decision_router import (
    PAST_SEASON_GOALS_REPLY, decide, is_past_season_goals_question,
)
from fpl_grounded_assistant.harness import ask_v2
from fpl_grounded_assistant.intent_aliases import resolve_prompt, resolve_resource
from fpl_grounded_assistant.router import _strip_spanish_name_prefix, route


# -- glossary command and resource names ------------------------------------------

@pytest.mark.parametrize("english, spanish", [
    ("captain", "capitan"), ("compare", "comparar"), ("transfer", "transferencia"),
    ("fixtures", "calendarios"), ("differentials", "diferenciales"), ("chips", "chips"),
    ("rankings", "clasificacion"),
])
def test_glossary_command_names_resolve_to_the_same_prompt_as_the_spanish_ones(english, spanish):
    assert resolve_prompt(english) == resolve_prompt(spanish) == spanish
    assert resolve_prompt("/" + english.upper()) == spanish


@pytest.mark.parametrize("english, spanish, canonical", [
    ("injuries", "lesionados", "injuries"), ("form", "forma", "top_form"), ("points", "puntos", "top_points"),
    ("minutes", "minutos", "top_minutes"), ("popular", "populares", "popular"), ("xg", "xg", "top_xg"),
])
def test_glossary_resource_names_resolve_in_both_languages(english, spanish, canonical):
    assert resolve_resource("@" + english) == resolve_resource("@" + spanish) == canonical


# -- English argument aliases ------------------------------------------------------

def _args(text: str) -> dict:
    d = decide(text, {"elements": [], "teams": [], "events": []})
    assert d["kind"] == "prompt", d
    assert d["outcome"] in ("ok_prompt_expansion", "ok_prompt_dispatch"), d
    return d["args"]


@pytest.mark.parametrize("english, spanish, expected", [
    ("/compare player_a=Salah player_b=Haaland", "/comparar jugador_a=Salah jugador_b=Haaland",
     {"a": "Salah", "b": "Haaland"}),
    ("/compare player1=Salah player2=Haaland", "/comparar p1=Salah p2=Haaland", {"a": "Salah", "b": "Haaland"}),
    ("/transfer sell=Salah buy=Haaland", "/transferencia vender=Salah comprar=Haaland",
     {"out": "Salah", "in": "Haaland"}),
    ("/transfer transfer_out=Salah bring_in=Haaland", "/transferencia salida=Salah entrada=Haaland",
     {"out": "Salah", "in": "Haaland"}),
    ("/fixtures Salah gameweeks=3", "/calendarios Salah h=3", {"player": "Salah", "horizon": 3}),
    ("/fixtures Salah gws=4", "/calendarios Salah n=4", {"player": "Salah", "horizon": 4}),
    ("/differentials count=3", "/diferenciales top=3", {"threshold": 15.0, "top_n": 3}),
    ("/differentials max_owned=8 limit=2", "/diferenciales umbral=8 n=2", {"threshold": 8.0, "top_n": 2}),
    ("/rankings count=7", "/clasificacion top=7", {"n": 7}),
])
def test_english_argument_names_parse_to_the_same_args_as_the_spanish_ones(english, spanish, expected):
    assert _args(english) == _args(spanish) == expected


@pytest.mark.parametrize("text, canonical", [
    ("/compare Salah vs Haaland", "compare Salah and Haaland"),
    ("/compare Salah versus Haaland", "compare Salah and Haaland"),
    ("/comparar Salah por Haaland", "compare Salah and Haaland"),
    ("/captain Salah", "should I captain Salah"),
    ("/capitan Salah", "should I captain Salah"),
    ("/transfer Salah for Haaland", "should I sell Salah for Haaland"),
])
def test_positional_forms_keep_expanding_to_the_same_canonical_text(text, canonical):
    assert decide(text, {})["canonical_text"] == canonical


def test_an_unknown_argument_name_is_still_not_silently_swallowed_as_a_known_one():
    # "weeks" is not an alias: it must stay in the positional text, as before this change.
    assert _args("/fixtures Salah weeks=3") == {"player": "Salah weeks=3", "horizon": 5}


# -- "I have ..." squad-context prefix ----------------------------------------------

@pytest.mark.parametrize("token, expected", [
    ("I have Salah", "Salah"), ("i have Salah", "Salah"), ("I've got Salah", "Salah"),
    ("I’ve got Salah", "Salah"), ("Ive got Salah", "Salah"), ("I own Salah", "Salah"),
    ("I have De Bruyne", "De Bruyne"),
    # Spanish and plain tokens are untouched.
    ("tengo a Salah", "Salah"), ("a Salah", "Salah"), ("al Saka", "Saka"), ("Salah", "Salah"),
    ("Ihave Salah", "Ihave Salah"), ("Ivan Toney", "Ivan Toney"),
    # a sentence, not "I have <player>": left alone (it fails to resolve either way)
    ("I have to sell Salah", "I have to sell Salah"),
])
def test_the_name_prefix_strip(token, expected):
    assert _strip_spanish_name_prefix(token) == expected


def test_i_have_resolves_to_the_player_in_a_routed_question():
    es = route("should I sell tengo a Salah for Haaland")
    en = route("should I sell I have Salah for Haaland")
    assert en is not None and es is not None
    assert en.tool_name == es.tool_name == "get_transfer_advice"
    assert en.tool_args == es.tool_args == {"query_out": "Salah", "query_in": "Haaland"}


# -- goals of a past season (_GOALS_RE) ----------------------------------------------

@pytest.mark.parametrize("q", [
    "who was the top goal scorer last season",
    "who were the top goal-scorers last season",
    "Who won the Golden Boot last season?",
    "golden boot winner 2024-25",
    "who was the top goalscorer last season",   # already matched before S2b
])
def test_english_goals_phrases_with_a_past_season_marker_are_refused(q):
    assert is_past_season_goals_question(q)


@pytest.mark.parametrize("q", [
    # "top scorer" is the POINTS question in FPL; it must keep reaching the tools.
    "who was the top scorer in gw3 last season",
    "who was the top scorer last season",
    "top scorers",
    # Goals phrase but no past-season marker: current season, the ranker's job.
    "who is the top goal scorer",
    "golden boot race",
    # Points, not goals.
    "how many points did Salah score last season",
])
def test_english_points_and_current_season_questions_are_left_alone(q):
    assert not is_past_season_goals_question(q)


def test_the_refusal_follows_the_locale_and_spanish_is_byte_identical():
    bootstrap = {"elements": [], "teams": [], "events": []}
    q = "who was the top goal scorer last season"
    es = decide(q, bootstrap)
    en = decide(q, bootstrap, locale="en")
    assert es["rule"] == en["rule"] == "past_season_goals"
    assert es["message"] == PAST_SEASON_GOALS_REPLY == t("decision.past_season_goals", "es")
    assert PAST_SEASON_GOALS_REPLY == (
        "No tengo goles por jornada de temporadas pasadas; sí puedo decirte quién "
        "hizo más **puntos**. ¿Te sirve?"
    )
    assert en["message"] == t("decision.past_season_goals", "en")
    assert "points" in en["message"] and "puntos" not in en["message"]
    # The locale, not the question's language, picks the reply (plan section 2).
    assert decide("¿Quién fue el máximo goleador de la temporada pasada?", bootstrap, locale="en")["message"] == en["message"]


def test_end_to_end_english_locale_gets_the_english_refusal(monkeypatch, bootstrap):
    def fake_orchestrator(question, *args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("orchestrator must not be reached")

    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", fake_orchestrator)
    result = ask_v2("who was the top goal scorer last season", bootstrap, orch_client=object(), locale="en")
    assert result["outcome"] == "unsupported" and result["selected_tool"] is None
    assert result["answer_text"] == t("decision.past_season_goals", "en")

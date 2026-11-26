"""Query layer PR 5: the three brakes, the year of a date, and the user's raw text.

A made-up bootstrap with real club names (the alias tables are about those) and invented players, two of them
with a surname that is an ordinary word.
"""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.orchestrator import OUTCOME_NO_TOOL, OrchestratorResult
from fpl_grounded_assistant.query_brakes import THEN_WORDS, apply_brakes, assign_years, season_start
from fpl_grounded_assistant.query_engine import NEEDS_CLARIFICATION, UNSUPPORTED
from fpl_grounded_assistant.query_reading import render_reading
from fpl_grounded_assistant.query_spec import parse_spec
from fpl_grounded_assistant.quota import reset_quota

from test_query_engine import flt, pred

TODAY = dt.date(2026, 11, 26)

_CLUBS = [(1, "ARS", "Arsenal"), (2, "MUN", "Man Utd"), (3, "LEE", "Leeds"), (4, "NEW", "Newcastle"),
          (5, "NFO", "Nott'm Forest"), (6, "BOU", "Bournemouth"), (7, "MCI", "Man City"), (8, "EVE", "Everton"),
          (9, "SUN", "Sunderland"), (10, "LIV", "Liverpool")]
# (id, web_name, first, second, team)
_PLAYERS = [(101, "Zorrin", "Pavel", "Zorrin", 6), (102, "Wood", "Carl", "Wood", 5),
            (103, "King", "Joshua", "King", 8), (104, "Veldt", "Ruud", "Veldt", 1),
            (105, "B.Quillon", "Bruno", "Quillon", 2), (106, "Ostrow", "Jan", "Ostrow", 3),
            (107, "Ostrow", "Piet", "Ostrow", 4), (108, "Rico", "Ricardo", "Salgado", 7)]

BOOTSTRAP = {
    "teams": [{"id": i, "short_name": c, "name": n, "code": i} for i, c, n in _CLUBS],
    "elements": [{"id": i, "web_name": w, "first_name": f, "second_name": s, "team": t, "team_code": t,
                  "element_type": 3, "now_cost": 60, "selected_by_percent": "4.0", "total_points": 10}
                 for i, w, f, s, t in _PLAYERS],
    "events": [{"id": gw, "deadline_time": f"{dt.date(2026, 8, 14) + dt.timedelta(weeks=gw - 1)}T17:30:00Z",
                "finished": gw <= 11} for gw in range(1, 39)],
}

POINTS = {"metric": "total_points"}


def brake(text, raw=POINTS, lang="es", **kw):
    return apply_brakes(parse_spec(raw), text, BOOTSTRAP, TODAY, lang, **kw)


def club(name, op="eq"):
    return {"metric": "total_points", "filters": [flt("club", op, name)]}


@pytest.mark.parametrize("text", [
    "¿Quién suma más puntos en las últimas 5?", "Most points over the last 5 gameweeks",
    "Los delanteros baratos con más goles", "Which midfielders have the most points this season?",
    "¿Quiénes son los que más puntos llevan en casa de apuestas?", "who will white wood king cash in on",
    "El más rico en puntos", "¿Qué jugadores de la liga no son caros?", "points per game for forwards",
])
def test_ordinary_questions_brake_nothing(text):
    result = brake(text)
    assert (result.state, result.brake, result.chips) == (None, None, ())


# -- B1 -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,lang", [
    ("Más puntos con menos del 10% de propiedad en ese momento", "es"),
    ("Más puntos con poca propiedad, en aquel momento", "es"),
    ("Los que tenían baja propiedad por aquel entonces", "es"),
    ("Baja propiedad cuando empezó la jornada", "es"),
    ("¿Propiedad de ENTONCES menor a 10?", "es"),
    ("Most points with under 10% ownership at that time", "en"),
    ("Low owned at the time", "en"), ("Ownership back then under 10", "en"),
])
def test_b1_ownership_at_the_time_is_unsupported(text, lang):
    raw = {"metric": "total_points", "filters": [flt("owned_now", "lt", 10)]}
    result = brake(text, raw, lang)
    assert (result.state, result.brake, result.unsupported) == (UNSUPPORTED, "B1", ("ownership_then",))
    assert [c["spec"] for c in result.chips] == [parse_spec(raw).to_dict()]
    assert ("otra pregunta" if lang == "es" else "different question") in result.chips[0]["label"]


def test_b1_then_words_are_whole_words():
    assert brake("strengthen the midfield with points").state is None
    assert len(THEN_WORDS) == len(set(THEN_WORDS))


def test_b1_with_no_ownership_filter_offers_no_nearest_ranking():
    assert brake("puntos de entonces").chips == ()


# -- B3 -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,quote,lang", [
    ("Goles contra el Arsenal", "contra el Arsenal", "es"),
    ("Goals against Arsenal this season", "against Arsenal", "en"),
    ("Puntos contra el United", "contra el United", "es"),
    ("Points when Zorrin faces Man City", "faces Man City", "en"),
])
def test_b3_a_reported_opponent_is_unsupported_not_a_missing_club(text, quote, lang):
    raw = {"metric": "total_points", "match_set": [pred("player_played_60", "Zorrin")]} if "Zorrin" in text else POINTS
    result = brake(text, raw, lang, not_expressible=[{"kind": "opponent", "quote": quote}])
    assert (result.state, result.brake, result.unsupported) == (UNSUPPORTED, "B3", ("opponent",))


def test_b3_what_the_spec_itself_cannot_run():
    result = brake("puntos de local", {"metric": "total_points", "match_set": [pred("venue", "home")]})
    assert (result.state, result.brake, result.reason) == (UNSUPPORTED, "B3", "player_venue")


def test_b3_wins_over_a_missing_club():
    result = brake("goles del Arsenal en octubre", not_expressible=[{"kind": "month", "quote": "en octubre"}])
    assert (result.state, result.unsupported) == (UNSUPPORTED, ("month",))


def test_a_kind_outside_the_vocabulary_is_an_error():
    with pytest.raises(ValueError):
        brake("x", not_expressible=[{"kind": "whatever", "quote": "x"}])


def test_only_a_not_expressible_quote_covers_a_club():
    result = brake("goles del Arsenal", not_expressible=[{"kind": "opponent", "quote": "contra el Arsenal"}])
    assert result.state == UNSUPPORTED                      # still reported, and still unsupported
    result = brake("goles del Arsenal", ambiguous=[{"quote": "Arsenal"}])
    assert (result.brake, result.reason) == ("B2", "missing_club_in_spec")


# -- B2: clubs ------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,short,lang,label", [
    ("Máximos goleadores del Arsenal", "ARS", "es", "¿Solo del Arsenal?"),
    ("Top scorers for the Gunners", "ARS", "en", "Only Arsenal?"),
    ("puntos de manchester united", "MUN", "es", "¿Solo del Man Utd?"),
    ("points for Leeds United players", "LEE", "en", "Only Leeds?"),
    ("los del Nottm Forest", "NFO", "es", "¿Solo del Nott'm Forest?"),
    ("los del Nott’m Forest", "NFO", "es", "¿Solo del Nott'm Forest?"),
    ("puntos del city", "MCI", "es", "¿Solo del Man City?"),
    ("puntos mun", "MUN", "es", "¿Solo del Man Utd?"),
    ("Who leads LIV in points?", "LIV", "en", "Only Liverpool?"),
    ("Arsenal's best", "ARS", "en", "Only Arsenal?"),
])
def test_b2_a_club_the_spec_leaves_out_is_asked_about(text, short, lang, label):
    result = brake(text, lang=lang)
    assert (result.state, result.brake, result.clarify["kind"]) == (NEEDS_CLARIFICATION, "B2", "missing_club")
    assert [c["label"] for c in result.chips] == [label]
    assert parse_spec(result.chips[0]["spec"]).filters[0].value == short
    assert brake(text, result.chips[0]["spec"], lang).state is None       # the chip's spec brakes nothing


@pytest.mark.parametrize("text", ["the new signings with most points", "LOS DEL SUN", "puntos che"])
def test_b2_a_code_that_is_also_a_word_does_not_fire(text):
    assert brake(text).state is None


@pytest.mark.parametrize("written", ["Arsenal", "ARS", "Gunners"])
def test_b2_the_club_in_the_spec_covers_it_however_written(written):
    assert brake("puntos del Arsenal", club(written)).state is None
    assert brake("puntos sin contar al Arsenal", club(written, "not")).state is None


def test_b2_the_second_club_named_is_added_to_the_first():
    result = brake("puntos de Arsenal o Everton", club("Arsenal"))
    assert result.clarify["written"] == "Everton"
    assert result.chips[0]["spec"]["filters"] == [flt("club", "in", ["Arsenal", "EVE"])]


@pytest.mark.parametrize("raw", [POINTS, club("Man Utd")])
def test_b2_a_bare_united_is_always_asked_about(raw):
    result = brake("puntos del United", raw)
    assert (result.state, result.reason) == (NEEDS_CLARIFICATION, "club_ambiguous")
    assert {c["short_name"] for c in result.clarify["candidates"]} == {"MUN", "LEE", "NEW"}
    assert len(result.chips) == 3


def test_b2_a_player_condition_covers_his_own_club():
    raw = {"metric": "team_expected_goals", "shape": "comparison",
           "match_set": [pred("player_played_60", "Zorrin")], "compare_to": [pred("player_absent", "Zorrin")]}
    assert brake("xG del Bournemouth con y sin Zorrin", raw).state is None


# -- B2: players ----------------------------------------------------------------------------------

@pytest.mark.parametrize("text,written,lang", [
    ("puntos desde que falta Zorrin", "Zorrin", "es"), ("points since zorrin was out", "zorrin", "en"),
    ("cuántos puntos lleva Bruno Quillon", "Bruno Quillon", "es"),
])
def test_b2_a_player_the_spec_leaves_out_is_asked_about(text, written, lang):
    result = brake(text, lang=lang)
    assert (result.brake, result.clarify["kind"], result.clarify["written"]) == ("B2", "missing_player", written)
    assert len(result.chips) == 2
    for chip in result.chips:
        assert brake(text, chip["spec"], lang).state is None


@pytest.mark.parametrize("text", ["¿Cuántos goles lleva Wood?", "How many goals has King scored?",
                                  "los puntos de Rico"])
def test_b2_a_common_word_name_counts_when_capitalised_mid_sentence(text):
    assert brake(text).clarify["kind"] == "missing_player"


@pytest.mark.parametrize("text", ["cuántos goles lleva wood", "the king of points", "el más rico en puntos",
                                  "Wood is the best material. Most points?", "¿King? no sé"])
def test_b2_a_common_word_in_lower_case_or_opening_a_sentence_does_not(text):
    assert brake(text).state is None


def test_b2_a_full_name_counts_even_if_its_words_are_ordinary():
    assert brake("puntos de carl wood").clarify["written"] == "carl wood"


def test_b2_a_shared_surname_lists_both_and_either_one_covers_it():
    result = brake("puntos sin Ostrow")
    assert {c["id"] for c in result.clarify["candidates"]} == {106, 107} and result.chips == ()
    raw = {"metric": "total_points", "match_set": [pred("player_absent", "Piet Ostrow")]}
    assert brake("puntos sin Ostrow", raw).state is None


def test_b2_a_player_condition_covers_the_name_as_the_user_wrote_it():
    raw = {"metric": "total_points", "match_set": [pred("player_absent", "Quillon")]}
    assert brake("puntos sin Bruno Quillon", raw).state is None


# -- the year -------------------------------------------------------------------------------------

def since(value):
    return {"metric": "goals_scored", "match_set": [pred("since_date", value)]}


def placed(text, value):
    spec, problem = assign_years(parse_spec(since(value)), text, BOOTSTRAP, TODAY)
    return spec.match_set[0].value, problem


@pytest.mark.parametrize("text,sent,expected", [
    ("goles desde el 10 de octubre", "10-10", "2026-10-10"),
    ("goals since 10 Oct", "2025-10-10", "2026-10-10"),              # the model's year is not in the text
    ("goles desde el 26 de noviembre", "11-26", "2026-11-26"),       # today
    ("goles de la 2026/27 desde el 10 oct", "10-10", "2026-10-10"),  # a season label is not a year
    ("goles desde el 10 oct 2026", "10-10", "2026-10-10"),
    ("goals since 10/10/2026", "2026-10-10", "2026-10-10"),
])
def test_the_year_is_the_latest_such_day_in_the_season(text, sent, expected):
    assert placed(text, sent) == (expected, None)


@pytest.mark.parametrize("text,sent", [("goles desde el 10 oct 2025", "10-10"),
                                       ("goals since 10 Oct 2025", "2025-10-10")])
def test_a_past_year_in_the_text_stays_and_is_a_past_season(text, sent):
    result = brake(text, since(sent))
    assert (result.state, result.brake, result.unsupported) == (UNSUPPORTED, "date", ("past_season",))
    assert result.spec.match_set[0].value == "2025-10-10"
    assert "2025" in render_reading(result.spec, "es", result.as_query_result())["text"]


@pytest.mark.parametrize("text,sent,reason", [
    ("goles desde el 1 de diciembre", "12-01", "date_outside_season"),     # still to come, and last year's is out
    ("goles desde el 1 de julio", "07-01", "date_outside_season"),         # before the first deadline
    ("goles desde el 1 dic 2026", "12-01", "date_in_the_future"),
    ("de 2024 o 2025, desde el 10 oct", "10-10", "which_year"),
    ("desde el 29 feb 2027", "02-29", "no_such_date"),
])
def test_a_date_that_cannot_be_placed_is_asked_about(text, sent, reason):
    result = brake(text, since(sent))
    assert (result.state, result.brake, result.reason) == (NEEDS_CLARIFICATION, "date", reason)
    block = render_reading(result.spec, "es", result.as_query_result())
    assert [p["kind"] for p in block["parts"] if p["braked"]] == ["window"]


def test_a_date_early_next_calendar_year_takes_last_year():
    spec, problem = assign_years(parse_spec(since("11-20")), "desde el 20 nov", BOOTSTRAP, dt.date(2027, 1, 15))
    assert (spec.match_set[0].value, problem) == ("2026-11-20", None)


def test_both_sides_of_a_comparison_get_a_year():
    raw = {"metric": "team_goals", "shape": "comparison", "filters": [flt("club", "eq", "Arsenal")],
           "match_set": [pred("since_date", "10-10")], "compare_to": [pred("since_date", "09-12")]}
    result = brake("Arsenal desde el 10 oct contra desde el 12 sep", raw)
    assert result.state is None
    assert (result.spec.match_set[0].value, result.spec.compare_to[0].value) == ("2026-10-10", "2026-09-12")


def test_the_season_starts_at_the_first_deadline_and_without_one_no_year_is_guessed():
    assert season_start(BOOTSTRAP) == dt.date(2026, 8, 14)
    spec, problem = assign_years(parse_spec(since("10-10")), "x", {"events": []}, TODAY)
    assert (spec.match_set[0].value, problem) == ("10-10", "date_outside_season")


# -- the model's vague phrase, and the line -------------------------------------------------------

def test_a_phrase_the_model_calls_vague_is_asked_about():
    result = brake("los que mejor vienen", ambiguous=[{"quote": "mejor vienen"}])
    assert (result.state, result.brake) == (NEEDS_CLARIFICATION, "ambiguous")


@pytest.mark.parametrize("lang,expected", [("es", "⚠ Sin usar: Arsenal"), ("en", "⚠ Not used: Arsenal")])
def test_the_line_of_a_b2_question_says_what_was_left_out(lang, expected):
    result = brake("goles del Arsenal", lang=lang)
    block = render_reading(result.spec, lang, result.as_query_result(), BOOTSTRAP)
    assert block["text"].endswith(expected) and block["parts"][-1]["kind"] == "unused"


def test_nothing_to_report_is_not_a_refusal():
    with pytest.raises(ValueError):
        brake("puntos").as_query_result()


# -- the raw text over HTTP (carried since brief 0a; pinned here for the query layer) --------------

@pytest.fixture()
def seen(monkeypatch):
    """What reaches the orchestrator: (the question it is asked, the raw text beside it)."""
    calls: list[tuple[str, str | None]] = []

    def _stub(question, bootstrap, *args, **kwargs):
        calls.append((question, kwargs.get("raw_question")))
        return OrchestratorResult(question=question, tool_chosen=None, tool_args={}, tool_output={},
                                  answer_text="x", llm_used=True, model="stub", outcome=OUTCOME_NO_TOOL,
                                  primary_input_tokens=1, primary_output_tokens=1, total_tokens=2)

    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", _stub)
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    reset_quota()
    yield calls
    fpl_server._sessions.clear()
    reset_quota()


TYPED = "¿y los defensas, desde el 10 de octubre?"
REWRITE = "cuántos puntos llevan los defensas del Arsenal"


def test_the_raw_text_survives_a_session_rewrite(seen, monkeypatch):
    monkeypatch.setattr("fpl_grounded_assistant.conversation_state.resolve_comparison_followup",
                        lambda question, state: REWRITE)
    client = TestClient(fpl_server.app)
    sid = client.post("/session").json()["session_id"]
    response = client.post(f"/session/{sid}/ask", json={"question": TYPED, "locale": "es"},
                           headers={"X-User-Id": "qb-sess"})
    assert response.status_code == 200
    assert seen == [(REWRITE, TYPED)]


def test_the_raw_text_survives_an_intent_hint_rewrite_on_ask(seen, monkeypatch):
    monkeypatch.setattr("fpl_grounded_assistant.dispatcher._try_route_with_hint",
                        lambda question, hint: (None, REWRITE))
    response = TestClient(fpl_server.app).post(
        "/ask", json={"question": TYPED, "locale": "es", "intent_hint": "captain_score"},
        headers={"X-User-Id": "qb-ask"})
    assert response.status_code == 200
    assert seen == [(REWRITE, TYPED)]

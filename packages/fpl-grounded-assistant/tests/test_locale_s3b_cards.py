"""i18n S3b -- generic_card and the harness metadata follow the locale.

* every composer's es output is what it was (titles, pills, headers, FDR bands);
* the en output is the glossary's wording and keeps the injury card's header
  vocabulary the UI adapter matches on (player/team/pos/status/chance/news/date);
* the locale reaches the cards through the real entry points (``ask_v2`` with a
  fake orchestrator client), not just through the composers.

No network, no model call.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace as NS

import pytest

from conftest import BOOTSTRAP
from fpl_grounded_assistant import generic_card as gc


def _teams():
    return (
        NS(rank=1, team_short="ARS", fixture_count=3, avg_fdr=2.0),
        NS(rank=2, team_short="CHE", fixture_count=2, avg_fdr=4.4),
    )


# ---------------------------------------------------------------------------
# FDR bands + venue
# ---------------------------------------------------------------------------

def test_fdr_and_venue_labels():
    assert [gc._fdr_label_es(v) for v in (1, 2, 3, 4, 5)] == [
        "Muy favorable", "Favorable", "Media", "Exigente", "Muy exigente",
    ]
    assert [gc._fdr_label_es(v, "en") for v in (1, 2, 3, 4, 5)] == [
        "Very favourable", "Favourable", "Average", "Tough", "Very tough",
    ]
    assert gc._fdr_label_es(None, "en") == "-"
    assert (gc._venue_label_es(True), gc._venue_label_es(False)) == ("Casa", "Fuera")
    assert (gc._venue_label_es(True, "en"), gc._venue_label_es(False, "en")) == ("Home", "Away")


# ---------------------------------------------------------------------------
# Composers
# ---------------------------------------------------------------------------

def test_team_calendar_es_and_en():
    meta = NS(mode="easiest", horizon=5, teams=_teams())
    es = gc.compose_team_fixture_calendar(meta)
    assert (es.title, es.subtitle, es.pills[0].label) == ("CALENDARIO", "Calendario más favorable", "5 JORNADAS")
    assert [c.header for c in es.columns] == ["#", "EQUIPO", "PARTIDOS", "FDR MEDIO", "DIFICULTAD"]
    assert es.rows[0] == ("1", "ARS", "3", "2.0", "Favorable")
    en = gc.compose_team_fixture_calendar(meta, "en")
    assert (en.title, en.subtitle, en.pills[0].label) == ("FIXTURES", "Most favourable fixtures", "5 GAMEWEEKS")
    assert [c.header for c in en.columns] == ["#", "TEAM", "FIXTURES", "AVG FDR", "DIFFICULTY"]
    assert en.rows[1] == ("2", "CHE", "2", "4.4", "Tough")
    assert gc.compose_team_fixture_calendar(NS(mode="hardest", horizon=3, teams=()), "en").subtitle == "Toughest fixtures"
    assert gc.compose_team_fixture_calendar(NS(mode="other", horizon=3, teams=())).subtitle is None


def test_position_fixture_run_es_and_en():
    meta = NS(mode="hardest", horizon=4, teams=_teams(), position_label="Defensas", position="DEF")
    es = gc.compose_position_fixture_run(meta)
    assert (es.title, es.subtitle) == ("CALENDARIO POR POSICIÓN", "Defensas · Calendario más exigente")
    en = gc.compose_position_fixture_run(meta, "en")
    assert (en.title, en.subtitle) == ("FIXTURES BY POSITION", "Defensas · Toughest fixtures")


def test_team_schedule_es_and_en():
    fx = (NS(gameweek=7, opponent_short="LIV", is_home=True, difficulty=5),)
    meta = NS(team_name="Arsenal", team_short="ARS", avg_fdr=3.0, fixture_count=1, has_dgw=True, has_bgw=True, fixtures=fx)
    es = gc.compose_team_schedule(meta)
    assert es.hero.label == "FDR MEDIO"
    assert [p.label for p in es.pills] == ["1 PARTIDOS", "DOBLE JORNADA", "JORNADA EN BLANCO"]
    assert [c.header for c in es.columns] == ["JOR", "RIVAL", "SEDE", "FDR"]
    assert es.rows[0] == ("GW7", "LIV", "Casa", "Muy exigente")
    en = gc.compose_team_schedule(meta, "en")
    assert en.hero.label == "AVG FDR"
    assert [p.label for p in en.pills] == ["1 FIXTURES", "DOUBLE GAMEWEEK", "BLANK GAMEWEEK"]
    assert [c.header for c in en.columns] == ["GW", "OPP", "VENUE", "FDR"]
    assert en.rows[0] == ("GW7", "LIV", "Home", "Very tough")


def test_current_gameweek_es_and_en():
    es, en = gc.compose_current_gameweek(9), gc.compose_current_gameweek(9, "en")
    assert (es.title, es.hero.label, es.hero.value) == ("JORNADA ACTUAL", "JORNADA EN CURSO", "GW9")
    assert (en.title, en.hero.label, en.hero.value) == ("CURRENT GAMEWEEK", "GAMEWEEK IN PROGRESS", "GW9")


def test_player_form_es_and_en():
    history = (NS(gameweek=3, minutes=90, goals_scored=1, assists=0, bonus=2, total_points=9),)
    meta = NS(history=history, n_games=1, web_name="Saka", team_short="ARS", position="MID")
    es, en = gc.compose_player_form(meta), gc.compose_player_form(meta, "en")
    assert (es.title, es.hero.label, es.columns[0].header) == ("FORMA RECIENTE", "PUNTOS · 1 JOR", "JOR")
    assert (en.title, en.hero.label, en.columns[0].header) == ("RECENT FORM", "POINTS · 1 GW", "GW")
    assert es.rows == en.rows == (("GW3", "90", "1", "0", "2", "9"),)


def test_price_changes_es_and_en():
    riser = NS(web_name="Saka", team_short="ARS", now_cost_m=10.1, cost_change_event=1)
    faller = NS(web_name="Palmer", team_short="CHE", now_cost_m=10.4, cost_change_event=-1)
    meta = NS(risers=(riser,), fallers=(faller,))
    es, en = gc.compose_price_changes(meta), gc.compose_price_changes(meta, "en")
    assert es.title == "CAMBIOS DE PRECIO" and [p.label for p in es.pills] == ["1 SUBEN", "1 BAJAN"]
    assert [c.header for c in es.columns] == ["JUGADOR", "EQUIPO", "PRECIO", "CAMBIO"]
    assert en.title == "PRICE CHANGES" and [p.label for p in en.pills] == ["1 RISING", "1 FALLING"]
    assert [c.header for c in en.columns] == ["PLAYER", "TEAM", "PRICE", "CHANGE"]
    assert es.rows == en.rows


def _injury(status_label, news="", chance=75):
    return NS(web_name="Saka", team_short="ARS", position="MID", status_label=status_label,
              chance_of_playing=chance, news=news, news_added="2026-10-20")


def test_injury_card_es_and_en_keep_the_ui_header_vocabulary():
    meta = NS(
        injured=(_injury("Injured"),), doubtful=(_injury("Doubtful", "Knock - 75% chance of playing"),),
        other=(_injury("Unavailable"),),
    )
    es, en = gc.compose_injury_list(meta), gc.compose_injury_list(meta, "en")
    assert es.title == "LESIONES"
    assert [p.label for p in es.pills] == ["1 LESIONADOS", "1 EN DUDA", "1 NO DISPONIBLES"]
    assert [c.header for c in es.columns] == [
        "JUGADOR", "EQUIPO", "POS", "ESTADO", "PROBABILIDAD %", "NOTICIA", "FECHA",
    ]
    assert en.title == "INJURIES"
    assert [p.label for p in en.pills] == ["1 INJURED", "1 DOUBTFUL", "1 UNAVAILABLE"]
    assert [c.header for c in en.columns] == ["PLAYER", "TEAM", "POS", "STATUS", "CHANCE %", "NEWS", "DATE"]
    # news: es translates when it can, en passes the original through
    assert en.rows[1][5] == "Knock - 75% chance of playing"
    assert [r[3] for r in es.rows] != [r[3] for r in en.rows]


_UI_MATCHERS = [  # fpl-ui InjuryListTable HEADER_MATCHERS, first match wins
    ("web_name", ["jugador", "player", "nombre", "name"]),
    ("team_short", ["equipo", "team"]),
    ("position", ["pos"]),
    ("status_label", ["estado", "status"]),
    ("chance_of_playing", ["%", "chance", "probabilidad"]),
    ("news", ["noticia", "news", "detalle"]),
    ("news_added", ["fecha", "date", "added", "actualizado"]),
]


@pytest.mark.parametrize("locale", ["es", "en"])
def test_injury_headers_map_one_to_one_onto_the_ui_fields(locale):
    def _field(header):
        low = header.lower()
        for field, keywords in _UI_MATCHERS:
            if any(k in low for k in keywords):
                return field
        return None

    fields = [_field(c.header) for c in gc._injury_columns(locale)]
    assert fields == [f for f, _ in _UI_MATCHERS], fields


# ---------------------------------------------------------------------------
# Through the real entry point
# ---------------------------------------------------------------------------

def _orchestrated(monkeypatch, locale, tool, args, question):
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    from fpl_grounded_assistant import harness

    class _Client:
        def __init__(self) -> None:
            self.messages = self
            self.n = 0

        def create(self, **kwargs):
            self.n += 1
            usage = NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0)
            if self.n == 1:
                block = NS(type="tool_use", id="c1", name=tool, input=args)
                return NS(content=[block], stop_reason="tool_use", usage=usage)
            return NS(content=[NS(type="text", text="done")], stop_reason="end_turn", usage=usage)

    shared = copy.deepcopy(BOOTSTRAP)
    return harness.ask_v2(question, shared, locale=locale, orch_client=_Client(), orch_api_key="x")


@pytest.mark.parametrize("locale,title", [("es", "LESIONES"), ("en", "INJURIES")])
def test_injury_card_through_ask_v2(monkeypatch, locale, title):
    result = _orchestrated(monkeypatch, locale, "get_injury_list", {}, "any news on injuries, think carefully")
    card = result["generic_card"]
    assert card is not None, result["routing_trace"]
    assert card.title == title


@pytest.mark.parametrize("locale,label", [("es", "Dudoso"), ("en", "Doubtful")])
def test_player_snapshot_status_label_through_ask_v2(locale, label):
    from fpl_grounded_assistant import harness

    result = harness.ask_v2("Who is Saka?", copy.deepcopy(BOOTSTRAP), locale=locale)
    assert result["player_snapshot"].status_label == label

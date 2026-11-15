"""i18n S5-B -- ranking card + get_my_squad / get_team_results error text follow the locale.

es is pinned to the exact pre-change strings; en carries no Spanish. No network, no model call.
"""
from __future__ import annotations

import re

import pytest

from fpl_grounded_assistant.atomic_tool_cards import (
    _METRIC_HEADER_EN,
    _METRIC_HEADER_ES,
    maybe_atomic_tool_card,
)
from fpl_grounded_assistant.get_my_squad import get_my_squad
from fpl_grounded_assistant.get_team_results import get_team_results
from fpl_grounded_assistant.locale_types import BOOTSTRAP_LOCALE_KEY

_SPANISH = re.compile(r"[áéíóúñ¿¡]|\b(?:jugador|equipo|conectado|plantilla|encontré|falta|debe)\b", re.I)


def _out(metric="total_points", **extra):
    out = {
        "status": "ok", "metric": metric,
        "ranked": [{"rank": 1, "web_name": "Saka", "team_short": "ARS", "position": "MID", "metric_value": 50}],
    }
    out.update(extra)
    return out


def test_header_tables_cover_the_same_metrics():
    assert set(_METRIC_HEADER_EN) == set(_METRIC_HEADER_ES)


def test_rank_card_es_unchanged_and_en_clean():
    es = maybe_atomic_tool_card("rank_players_by_metric", _out(position_filter="MID", min_minutes_filter=60), None, "es")
    assert es.title == "TOP 1 · Puntos" and es.subtitle == "posición: MID, min. minutos: 60"
    assert [c.header for c in es.columns] == ["#", "Jugador", "Equipo", "Pos", "Puntos"]
    en = maybe_atomic_tool_card("rank_players_by_metric", _out(position_filter="MID", min_minutes_filter=60), None, "en")
    assert en.title == "TOP 1 · Points" and en.subtitle == "position: MID, min. minutes: 60"
    assert [c.header for c in en.columns] == ["#", "Player", "Team", "Pos", "Points"]
    asc = maybe_atomic_tool_card("rank_players_by_metric", _out("now_cost", order="asc"), None, "en")
    assert asc.title == "1 WITH LOWEST · Price (£m)"
    asc_es = maybe_atomic_tool_card("rank_players_by_metric", _out("now_cost", order="asc"), None, "es")
    assert asc_es.title == "1 CON MENOR · Precio (£m)"


def _boot(locale=None, **extra):
    boot = dict(extra)
    if locale:
        boot[BOOTSTRAP_LOCALE_KEY] = locale
    return boot


def test_get_my_squad_no_team_both_locales():
    es = get_my_squad(_boot())["message"]
    en = get_my_squad(_boot("en"))["message"]
    assert es == "No hay ningún equipo conectado. Conecta tu equipo desde la pestaña Plantilla para que pueda evaluarlo."
    assert en == "No team is connected. Connect your team from the Squad tab so I can assess it."
    assert not _SPANISH.search(en)


def test_get_my_squad_invalid_gw():
    boot = _boot(_my_team_id=1, events=[])
    es = get_my_squad(dict(boot), gw=999)
    assert es["code"] == "invalid_gw" and es["message"].startswith("gw debe estar entre")
    en = get_my_squad({**boot, BOOTSTRAP_LOCALE_KEY: "en"}, gw=999)
    assert en["message"].startswith("gw must be between")


def test_get_team_results_errors():
    es = get_team_results("", {})
    en = get_team_results("", {BOOTSTRAP_LOCALE_KEY: "en"})
    assert es["message"] == "Falta el nombre del equipo."
    assert en["message"] == "The team name is missing."
    bad = get_team_results("Arsenal", {BOOTSTRAP_LOCALE_KEY: "en"}, last_n="x")
    assert bad["message"] == "last_n must be an integer, not 'x'."
    assert get_team_results("Arsenal", {}, last_n="x")["message"] == "last_n debe ser un entero, no 'x'."
    assert get_team_results("Arsenal", {}, venue="zz")["message"].startswith("venue debe ser uno de ")

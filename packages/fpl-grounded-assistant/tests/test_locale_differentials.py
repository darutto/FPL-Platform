"""Differentials answer text: en unchanged, es readable Spanish (FPL price/format kept)."""
from __future__ import annotations

from fpl_grounded_assistant.renderer import render

_OK = {
    "status": "ok", "ownership_threshold": 10.0,
    "picks": [{
        "rank": 1, "web_name": "Johnson", "team_short": "CHE", "position": "MID",
        "now_cost": 50, "captain_score": 30.0, "position_score": 32.0, "ownership": 0.5,
    }],
}


def test_en_text_is_the_original():
    assert render("get_differential_picks", _OK, locale="en") == (
        "Top differentials (ownership < 10%):\n"
        "  1. Johnson (CHE, MID) \u2014 score 32.0, 0.5% owned, \u00a35.0m"
    )


def test_es_text_is_spanish():
    assert render("get_differential_picks", _OK, locale="es") == (
        "Mejores diferenciales (propiedad < 10%):\n"
        "  1. Johnson (CHE, MID) \u2014 puntuación 32.0, 0.5% de propiedad, \u00a35.0m"
    )


def test_empty_and_none_are_paired():
    none = {"status": "ok", "ownership_threshold": 5.0, "picks": []}
    assert render("get_differential_picks", none, locale="en") == "No differential picks found (ownership < 5%)."
    assert render("get_differential_picks", none, locale="es") == "No se encontraron diferenciales (propiedad < 5%)."
    assert render("get_differential_picks", {"status": "empty"}, locale="es") == "No se encontraron diferenciales."

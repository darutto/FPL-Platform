"""i18n S5-B -- the zonal backend text follows the request's locale.

Engine-level (no store, no network, no model call): verdicts, pills, the season
stamp and the player-outlook sentence, with ``es`` pinned to the exact
pre-change bytes and ``en`` free of Spanish and of the word "weakness".
"""
from __future__ import annotations

import re

import pytest

from fpl_grounded_assistant import zonal_weakness as zw
from fpl_grounded_assistant.player_snapshot_zonal import _verdict as snap_verdict


def _zone(name: str, xga: float, avg: float) -> dict:
    return {"zone": name, "xga_per_game": xga, "league_avg": avg, "delta_vs_avg": xga - avg}


CLEAR = [_zone("in-box / left", 1.5, 1.0)]  # +50%
MARGINAL = [_zone("edge-of-box / central", 1.02, 1.0)]  # +2%
NONE = [_zone("in-box / right", 0.5, 1.0)]
MULTI = [_zone("in-box / left", 1.5, 1.0), _zone("edge-of-box / right", 1.4, 1.0)]

_SPANISH = re.compile(r"[áéíóúñ¿¡]|\bb(?:jornadas?|ataca|cruce|temporada|datos|ventaja)\b", re.I)


def test_es_verdicts_and_labels_are_byte_identical():
    assert zw._opportunity_verdict("Fulham", CLEAR, "es") == (
        "Ataca a Fulham por la izquierda dentro del área — concede un +50% sobre un equipo medio ahí."
    )
    assert zw._opportunity_verdict("Fulham", MARGINAL, "es") == (
        "Fulham no concede claramente por encima de la media en ninguna zona — la lectura más "
        "favorable es por el centro en la frontal del área (+2%), una ventaja leve."
    )
    assert zw._opportunity_verdict("Fulham", NONE, "es") == (
        "Fulham no concede por encima de la media de la liga en ninguna zona del área."
    )
    assert zw._weakness_verdict("Fulham", MULTI, "es") == (
        "Ataca a Fulham por la izquierda dentro del área y por la derecha en la frontal del área"
        " — concede por encima de la media de la liga ahí."
    )
    assert zw._weakness_label(CLEAR, "es") == "Ataca dentro del área"
    assert zw._weakness_label(MARGINAL, "es") == "Ventaja leve en la frontal del área"
    assert zw._weakness_label(NONE, "es") == "Sin ventaja clara"
    # the default is es
    assert zw._weakness_label(CLEAR) == zw._weakness_label(CLEAR, "es")


def test_en_has_no_spanish_and_stays_in_opportunity_frame():
    texts = [
        zw._opportunity_verdict("Fulham", CLEAR, "en"),
        zw._opportunity_verdict("Fulham", MARGINAL, "en"),
        zw._opportunity_verdict("Fulham", NONE, "en"),
        zw._weakness_verdict("Fulham", MULTI, "en"),
        zw._weakness_label(CLEAR, "en"),
        zw._weakness_label(MARGINAL, "en"),
        zw._weakness_label(NONE, "en"),
    ]
    for text in texts:
        assert not _SPANISH.search(text), text
        assert "weak" not in text.lower(), text
    assert texts[0] == "Attack Fulham down the left inside the box — they concede +50% over an average side there."


def test_provenance_labels_both_locales():
    live = "2026-27"
    ptr = {"season": live, "n_matches": 10}
    es = zw.build_data_provenance(ptr, live, "es")["label"]
    en = zw.build_data_provenance(ptr, live, "en")["label"]
    assert es.startswith("⚠ Datos de ") and "sólo 1 jornada de liga" in es
    assert "only 1 GW of league data" in en and not _SPANISH.search(en)
    assert zw.build_data_provenance(None, live, "es")["label"] == (
        "⚠ El almacén táctico no declara de qué temporada son estos datos"
    )
    assert "does not declare" in zw.build_data_provenance(None, live, "en")["label"]
    assert zw.build_data_provenance(ptr, None, "es")["label"].endswith("(no se pudo verificar la temporada en curso)")
    stale = zw.build_data_provenance({"season": "2025-26", "n_matches": 380}, live, "en")["label"]
    assert "not from the current season" in stale and not _SPANISH.search(stale)


def test_snapshot_player_verdicts():
    fav = [{"status": "favorable", "gameweek": 9, "opponent": "FUL"}]
    assert snap_verdict("Saka", fav, "es") == (
        "favorable",
        "Saka genera su xG justo en zonas donde el rival concede por encima de la media — cruce favorable en J9 (FUL).",
    )
    kind, en = snap_verdict("Saka", fav, "en")
    assert kind == "favorable" and "GW9 (FUL)" in en and not _SPANISH.search(en)
    assert snap_verdict("Saka", [{"status": "no_data", "gameweek": 9, "opponent": "X"}], "es")[1] == (
        "Sin datos zonales de los rivales de estos partidos, no se puede valorar el cruce."
    )
    neutral = [{"status": "neutral", "gameweek": 9, "opponent": "X"}]
    assert snap_verdict("Saka", neutral, "es")[1] == (
        "Sin cruce zonal destacado para Saka en los partidos de las próximas 3 jornadas."
    )
    assert not _SPANISH.search(snap_verdict("Saka", neutral, "en")[1])


@pytest.mark.parametrize("locale", ["es", "en"])
def test_locale_switch_in_same_process_gives_different_text(locale):
    # no module-level cache of the rendered text: es then en within one process differ.
    es = zw._weakness_label(CLEAR, "es")
    en = zw._weakness_label(CLEAR, "en")
    assert es != en
    assert zw._weakness_label(CLEAR, locale) == (es if locale == "es" else en)

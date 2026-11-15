"""i18n S5-B -- fixture outlook / fixture context text follows the request's locale.

``es`` is pinned to the exact pre-change bytes (the /fixtures bundle and the UI's
``fixtureVerdict`` matcher depend on them); ``en`` has no Spanish. No network,
no model call.
"""
from __future__ import annotations

import re

import pytest

from fpl_grounded_assistant.fixture_context import _phrase, fixture_tiebreaker_line
from fpl_grounded_assistant.fixture_outlook import build_verdict
from fpl_grounded_assistant.fixture_outlook_tool import describe_short_horizon

_SPANISH = re.compile(r"[áéíóúñ¿¡]|\b(?:jornadas?|calendario|portería|tramo|ofensivo|ventaja|casa|fuera)\b", re.I)

SERIES = [{"gameweek": 5}]


def _run(kind: str, intensity: str) -> dict:
    return {"type": kind, "intensity": intensity, "start_gw": 5, "end_gw": 7, "length": 3}


ES_VERDICTS = {
    ("attack", "good", "normal"): "Buen tramo ofensivo: 3 jornadas de calendario asequible (J5–J7).",
    ("attack", "good", "strong"): "Buen tramo ofensivo: 3 jornadas de calendario muy asequible (J5–J7).",
    ("attack", "bad", "normal"): "Tramo ofensivo exigente: 3 jornadas duras (J5–J7).",
    ("attack", "bad", "strong"): "Tramo ofensivo muy exigente: 3 jornadas duras (J5–J7).",
    ("defence", "good", "normal"): "Buen tramo para portería a cero: calendario favorable (J5–J7).",
    ("defence", "good", "strong"): "Buen tramo para portería a cero: calendario muy favorable (J5–J7).",
    ("defence", "bad", "normal"): "Tramo complicado para mantener la portería a cero (J5–J7).",
    ("defence", "bad", "strong"): "Tramo muy complicado para mantener la portería a cero (J5–J7).",
}


@pytest.mark.parametrize("key", list(ES_VERDICTS))
def test_run_verdicts_es_byte_identical_en_clean(key):
    axis, kind, intensity = key
    runs = [_run(kind, intensity)]
    assert build_verdict(runs, axis, SERIES) == ES_VERDICTS[key]
    assert build_verdict(runs, axis, SERIES, "es") == ES_VERDICTS[key]
    en = build_verdict(runs, axis, SERIES, "en")
    assert "GW5–GW7" in en and not _SPANISH.search(en), en


def test_edge_verdicts():
    assert build_verdict([], "attack", []) == "Sin fixtures en el horizonte."
    assert build_verdict([], "attack", SERIES) == "Calendario sin rachas claras en el horizonte."
    assert build_verdict([], "attack", [], "en") == "No fixtures in the horizon."
    assert not _SPANISH.search(build_verdict([], "attack", SERIES, "en"))


def _outlook() -> dict:
    return {
        "axis": "defence",
        "team_name": "Arsenal",
        "series": [
            {"gameweek": 5, "is_dgw": True, "fixtures": [{"opponent_short": "FUL", "is_home": True, "band": 2}]},
            {"gameweek": 6, "fixtures": []},
        ],
    }


_TEAM = {"name": "Arsenal", "strength_overall_home": 5, "strength_overall_away": 4}
_BOOT = {"teams": [{"short_name": "FUL", "name": "Fulham", "strength_overall_home": 3, "strength_overall_away": 3}]}


def test_short_horizon_es_byte_identical():
    assert describe_short_horizon(_outlook(), _TEAM, _BOOT) == (
        "J5 (doble jornada): Arsenal en casa ante Fulham — dificultad para portería a cero 2/5 (favorable); "
        "fuerza global Arsenal 5/5 en casa vs Fulham 3/5 fuera (ventaja Arsenal). "
        "J6: Arsenal descansa (sin partido)."
    )


def test_short_horizon_en_clean():
    en = describe_short_horizon(_outlook(), _TEAM, _BOOT, "en")
    assert "GW5 (double gameweek): Arsenal at home to Fulham" in en and "GW6: Arsenal have a blank" in en
    assert not _SPANISH.search(en), en


def test_context_phrases_and_tiebreaker():
    run = [_run("good", "normal")]
    assert _phrase("attack", run) == "calendario ofensivo favorable (J5–J7)"
    assert _phrase("defence", run, True) == "calendario defensivo favorable (J5–J7)"
    assert _phrase("defence", [_run("bad", "normal")]) == "calendario difícil para portería a cero (J5–J7)"
    assert _phrase("attack", [], locale="es") == "calendario sin rachas marcadas"
    for axis, mid in (("attack", False), ("defence", True), ("defence", False)):
        for kind in ("good", "bad"):
            assert not _SPANISH.search(_phrase(axis, [_run(kind, "normal")], mid, "en"))
    entries = [("Saka", {"phrase": "x"}), ("Haaland", None)]
    assert fixture_tiebreaker_line(entries, emit=True) == "Muy parejos; por calendario — Saka: x."
    assert fixture_tiebreaker_line(entries, emit=True, locale="en") == "Too close to call; on fixtures — Saka: x."
    assert fixture_tiebreaker_line(entries, emit=False) is None


def test_tool_handler_locale_not_cached_between_calls():
    # no tool-level cache: es then en inside one process give different text
    # (single-match horizon -> describe_short_horizon path) and past/beyond misses.
    from fpl_grounded_assistant.locale_types import BOOTSTRAP_LOCALE_KEY
    from fpl_grounded_assistant.fixture_outlook_tool import _get_fixture_outlook_handler

    def fx(gw, opp, home, d):
        return {"gameweek": gw, "opponent_team": opp, "is_home": home, "difficulty": d}

    boot = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Brentford", "short_name": "BRE"},
        ],
        "events": [{"id": 1, "is_current": True}],
        "team_fixtures": {1: [fx(1, 2, True, 2), fx(2, 2, False, 2)], 2: [fx(1, 1, False, 4), fx(2, 1, True, 4)]},
    }
    args = {"axis": "attack", "team_query": "Arsenal", "horizon": 1}
    es = _get_fixture_outlook_handler(dict(args), dict(boot))
    en = _get_fixture_outlook_handler(dict(args), {**boot, BOOTSTRAP_LOCALE_KEY: "en"})
    es_again = _get_fixture_outlook_handler(dict(args), dict(boot))
    assert es["status"] == en["status"] == "ok"
    assert es["verdict"].startswith("J1: Arsenal en casa ante Brentford")
    assert en["verdict"].startswith("GW1: Arsenal at home to Brentford") and not _SPANISH.search(en["verdict"])
    assert es_again["verdict"] == es["verdict"]
    miss_en = _get_fixture_outlook_handler(
        {"axis": "attack", "team_query": "Arsenal", "target_gw": 99}, {**boot, BOOTSTRAP_LOCALE_KEY: "en"}
    )
    assert miss_en["message"] == "No fixture data up to GW99 yet."
    miss_es = _get_fixture_outlook_handler({"axis": "attack", "team_query": "Arsenal", "target_gw": 99}, dict(boot))
    assert miss_es["message"] == "No hay datos de fixtures hasta la jornada 99 todavía."

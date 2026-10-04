"""i123 -- internal field names never reach the user's answer.

Prod 2026-10-02, free hit 6/7/8: «… con `dgw_teams=[]` y `bgw_teams=[]`».
Fixed as a synthesis-prompt rule (PLAIN_LANGUAGE), not a final_text_guard
reason: the guard replaces a whole answer, and a leaked field name inside an
otherwise good answer is not a reason to throw it away. The grader below is
the measurement instrument (scripts/grade_i123_internal_names.py); these tests
pin the rule's presence and the grader's behaviour on real prod/local texts.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from fpl_grounded_assistant.orchestrator import _LOOP_SYSTEM_PROMPT, _SYSTEM_PROMPT

_spec = importlib.util.spec_from_file_location(
    "_i123_grader", Path(__file__).resolve().parents[1] / "scripts" / "grade_i123_internal_names.py")
grader = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = grader
_spec.loader.exec_module(grader)

#: Real leaking answers (prod audit 2026-10-02; local i124 measurement).
LEAKS = [
    "La herramienta marca la jornada como **normal**, con `dgw_teams=[]` y `bgw_teams=[]`.",
    "El análisis devuelve conditions_unfavorable y `fixture_context: null` para GW6.",
    "Mitrović: estado `a`, sin `news` reportadas.",
]
#: Real clean answers in the same family (local i124 / i125 measurements).
CLEAN = [
    "**Free Hit — jornada poco favorable.** No usaría el Free Hit en GW6: no hay jornada doble ni en blanco.",
    "Groß llega con forma 10,7 y lanza penaltis; Tarkowski suma por portería a cero (FDR 2).",
    "Calendario del Arsenal: racha favorable J6-J8, con 5 * 2 = 10 puntos esperados en dos jornadas.",
    "Precio: £5,5m · Propiedad: 12,3% · Minutos: 450/450.",
]


@pytest.mark.parametrize("text", LEAKS)
def test_grader_flags_every_real_leak(text):
    assert not grader.is_clean(text)


@pytest.mark.parametrize("text", CLEAN)
def test_grader_leaves_real_clean_answers_alone(text):
    assert grader.is_clean(text), grader.leaks(text)


def test_each_detector_fires_on_its_own_shape():
    assert grader.leaks("dgw_teams")["snake"] == ["dgw_teams"]
    assert grader.leaks("estado `a`")["backtick"] == ["`a`"]
    assert grader.leaks("bgw_teams=[]")["fieldeq"] == ["bgw_teams=[]"]
    assert grader.leaks("ok") == {"snake": [], "backtick": [], "fieldeq": []}


def test_rule_is_in_both_system_prompts():
    for prompt in (_SYSTEM_PROMPT, _LOOP_SYSTEM_PROMPT):
        assert "PLAIN_LANGUAGE:" in prompt
        assert "dgw_teams" in prompt and "no backticks" in prompt


# ---------------------------------------------------------------------------
# i143 -- the model talking about the machinery, and chip names in Spanish
# ---------------------------------------------------------------------------

#: Real served / primary texts (prod 2026-10-04 captures and the i143 before arm).
TOOL_TALK_REAL = [
    "no baso la decisión en afirmar que no la hay, porque la salida de recomendación no muestra una alerta explícita",
    "esta salida no incluye explícitamente su estado médico",
    "Está disponible; la herramienta no aporta una novedad médica adicional",
    "aun así, el sistema no puede confirmar si tus cuatro suplentes tienen minutos garantizados",
    "con los datos disponibles no se puede confirmar esa profundidad",
    "En esta evaluación no aparece un campo separado de estado actual",
    "no se aporta ninguna noticia adicional sobre él en los datos recibidos",
]
FOOTBALL_PROSE = [
    "Buena salida de balón del Brighton desde atrás",
    "La salida en largo del portero rompe la presión",
    "El resultado del partido fue 2-1 para el City",
    "Juega en su campo y presiona alto",
    "Haaland ha jugado 450 minutos y está disponible.",
]


@pytest.mark.parametrize("text", TOOL_TALK_REAL)
def test_tool_talk_detector_fires_on_real_answers(text):
    assert grader.tool_talk(text), text


@pytest.mark.parametrize("text", FOOTBALL_PROSE)
def test_tool_talk_detector_leaves_football_prose_alone(text):
    assert grader.tool_talk(text) == []


def test_spanish_chip_name_detector():
    assert grader.spanish_chip_names("¿a qué chip te refieres: comodín, golpe de suerte o banco extra?") == [
        "comodin", "golpe de suerte", "banco extra"]
    assert grader.spanish_chip_names("el triple capitán es defendible") == ["triple capitan"]
    assert grader.spanish_chip_names("el Triple Captain, el Wildcard, el Bench Boost y el Free Hit") == []


def test_leaks_keeps_its_i123_contract():
    assert grader.leaks("la herramienta no aporta nada") == {"snake": [], "backtick": [], "fieldeq": []}


def test_i143_rules_are_in_both_system_prompts():
    for prompt in (_SYSTEM_PROMPT, _LOOP_SYSTEM_PROMPT):
        assert "NO_TOOL_TALK:" in prompt and "\"la herramienta\"" in prompt and "\"la salida\"" in prompt
        assert "CHIP_NAMES:" in prompt and "Triple Captain" in prompt and "never comodín" in prompt

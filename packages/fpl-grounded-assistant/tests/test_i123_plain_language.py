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

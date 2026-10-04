"""i119 -- the clarification gate blocks urgency, not neutral transfer words.

Decided by Leo (option C): when the user asks about transfers, «transfer» and
«¿qué jugador venderías?» are fine; «vende ya», «hay que sacarlo», «peligro»
are not. ``urgency_hits`` is that rule; the grader script applies it to the
served ad-05 texts. Pure functions, no I/O beyond the tmp file.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from fpl_grounded_assistant.opportunity_framing import transaction_hits, urgency_hits

_SPEC = importlib.util.spec_from_file_location(
    "grade_i119", Path(__file__).resolve().parents[1] / "scripts" / "grade_i119_clarification_urgency.py")
grader = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(grader)

#: A real ad-05 clarification (i111 E3, no team, r0): neutral transfer words only.
REAL_AD05 = ("Sobre el **transfer**, no puedo recomendar hacerlo sin saber el cambio concreto. "
             "Pásame:\n\n- Jugador que venderías\n- Jugador que comprarías\n- Qué chip estás "
             "pensando usar\n\nCon eso te digo si el movimiento justifica gastar el transfer.")


@pytest.mark.parametrize("text", [
    "¿Qué jugador venderías?",
    REAL_AD05,
    "Con eso comparo el valor de usar el transfer ahora frente a reservarlo.",
    "Indica jugador que sale y jugador que entra.",
    "Newcastle puede generar peligro en su ataque",          # football idiom
])
def test_neutral_transfer_wording_passes(text):
    assert urgency_hits(text) == []


def test_real_ad05_still_has_transaction_words_so_the_gates_differ():
    assert transaction_hits(REAL_AD05)           # what the old gate would have failed
    assert urgency_hits(REAL_AD05) == []         # what the decided gate measures


@pytest.mark.parametrize("text,label", [
    ("Vende ya a Salah", "ya"),
    ("véndelo cuanto antes", "ya"),
    ("sácalo ya del equipo", "ya"),
    ("Hay que sacarlo esta semana", "hay_que"),
    ("tienes que venderlo", "hay_que"),
    ("Es urgente hacer el cambio", "urgent"),
    ("Peligro: lleva tres jornadas sin jugar", "peligr"),
    ("sell him now", "en"),
])
def test_urgency_fails(text, label):
    hits = urgency_hits(text)
    assert hits and hits[0].startswith(f"{label}:")


def test_grader_gate_on_rows(tmp_path):
    rows = [
        {"question_id": "ad-05", "rep": 0, "answer_text_full": REAL_AD05},
        {"question_id": "ad-05", "rep": 1, "answer_text_full": "¿Qué jugador venderías?"},
        {"question_id": "ad-03", "rep": 0, "answer_text_full": "Vende ya"},   # other id: ignored
    ]
    s = grader.summarize(rows, {"ad-05"})
    assert s["rows"] == 2 and s["urgency_rows"] == 0 and s["gate"] is True
    rows.append({"question_id": "ad-05", "rep": 2, "answer_text_full": "Vende ya a Salah"})
    s = grader.summarize(rows, {"ad-05"})
    assert s["urgency_rows"] == 1 and s["gate"] is False
    arm = tmp_path / "arm.jsonl"
    arm.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    assert grader.main([str(arm)]) == 1

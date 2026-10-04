"""i119 -- "vendría" is VENIR, not VENDER: the framing check must not flag it.

Found in the i111 E3 run (2026-10-03): a chip body wrote «el beneficio
principal vendría de Ndiaye y Ballard» and ``transaction_hits`` reported
``vend:vendria``. The future/conditional of *venir* is exempt; every form of
*vender* stays a hit. Pure function, no I/O.
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.opportunity_framing import transaction_hits


@pytest.mark.parametrize("text", [
    "el beneficio principal vendría de Ndiaye y Ballard",   # the measured row
    "si lo usas, ¿de dónde vendrías a sacar puntos?",
    "vendríamos de una racha favorable",
    "los puntos vendrían del banquillo",
    "la ventaja vendrá de su calendario",
    "cuando vendrás a ver la jornada",
    "los goles vendrán de Haaland",
    "yo vendré con los datos",
    "VENDRÍA de su forma reciente",
])
def test_venir_is_not_a_transaction(text):
    assert transaction_hits(text) == []


@pytest.mark.parametrize("text,word", [
    ("deberías vender a Salah", "vender"),
    ("el City vende a Haaland", "vende"),
    ("véndelo esta semana", "vendelo"),
    ("yo vendería a Palmer", "venderia"),
    ("venderás a Saka", "venderas"),
])
def test_vender_is_still_a_transaction(text, word):
    assert transaction_hits(text) == [f"vend:{word}"]


def test_venir_does_not_mask_a_real_hit_in_the_same_text():
    text = "el valor vendría de Ndiaye, pero conviene vender a Ballard"
    assert transaction_hits(text) == ["vend:vender"]

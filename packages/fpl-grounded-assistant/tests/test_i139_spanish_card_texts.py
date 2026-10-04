"""i139 -- the comparison card's reasons, and the budget block, in Spanish at the origin.

Seen 2026-10-04 in prod: the comparison card showed ``reasons`` as built in
comparison.py («stronger form», «higher xGI output»). They are now Spanish
where they are made; so is the recommendation sentence that splices them in
(served as the answer on the deterministic path: an English sentence around
Spanish reasons reads worse than either). The budget hard block gets i137's
treatment: a Spanish lead and the turn's answer below.

The shared set-piece helper keeps English by default: the transfer reasons
use it too and are listed in the sweep, not changed here. No network.
"""
from __future__ import annotations

import re

import pytest

from fpl_grounded_assistant.comparison import _build_recommendation, _explain_comparison
from fpl_grounded_assistant.final_response import TransferMeta, _apply_squad_overrides
from fpl_grounded_assistant.scoring_shared import _set_piece_advantage_phrase

_ENGLISH = re.compile(r"\b(stronger|easier|fixture|higher|output|better|security|advantage|edges|"
                      r"margin|tied|Advantages|Budget|bringing|bank)\b", re.I)


def _p(form=5.0, fdr=3, efdr=None, xgi=0.3, risk=10.0, home=None, bonus=0.0, notes=()):
    return {"score_inputs": {"form": form, "fixture_difficulty": fdr,
                             "effective_fdr": fdr if efdr is None else efdr,
                             "xgi_per_90": xgi, "minutes_risk": risk, "is_home": home},
            "role_signals": {"role_bonus": bonus, "set_piece_notes": list(notes)}}


# ---------------------------------------------------------------------------
# comparison reasons
# ---------------------------------------------------------------------------

def test_every_reason_is_spanish():
    winner = _p(form=8.5, fdr=2, home=True, xgi=0.7, risk=5.0, bonus=10.0, notes=["penalty_taker_1"])
    loser = _p(form=6.0, fdr=4, home=False, xgi=0.3, risk=40.0, bonus=0.0, notes=["freekick_taker_2"])
    assert _explain_comparison(winner, loser) == [
        "mejor forma (8.5 vs 6.0)",
        "partido más fácil (FDR 2L vs 4V)",
        "más xGI por 90",
        "minutos más asegurados",
        "ventaja a balón parado (penales vs 2.º en tiros libres)",
    ]


def test_unknown_venue_has_no_tag():
    reasons = _explain_comparison(_p(fdr=2), _p(fdr=4))
    assert reasons == ["partido más fácil (FDR 2 vs 4)"]


@pytest.mark.parametrize("notes_w,notes_l,expected", [
    ([], [], "ventaja a balón parado"),
    (["penalty_taker_2"], [], "ventaja a balón parado (2.º en penales)"),
    (["freekick_taker_1"], ["penalty_taker_2"], "ventaja a balón parado (tiros libres vs 2.º en penales)"),
])
def test_set_piece_phrase_in_spanish(notes_w, notes_l, expected):
    w = {"role_bonus": 5.0, "set_piece_notes": notes_w}
    l = {"role_bonus": 0.0, "set_piece_notes": notes_l}
    assert _set_piece_advantage_phrase(w, l, locale="es") == expected


def test_set_piece_phrase_default_stays_english_for_transfers():
    w = {"role_bonus": 5.0, "set_piece_notes": ["penalty_taker_1"]}
    assert _set_piece_advantage_phrase(w, {"role_bonus": 0.0}) == "set-piece advantage (pen)"


# ---------------------------------------------------------------------------
# recommendation sentence
# ---------------------------------------------------------------------------

def test_recommendation_with_reasons():
    text = _build_recommendation("Haaland", 82.0, "Palmer", 70.0, "Haaland", 12.0,
                                 ["mejor forma (8.5 vs 6.0)", "más xGI por 90"])
    assert text == ("Haaland (82.0) supera a Palmer (70.0) — diferencia clara (12.0)."
                    "  Ventajas: mejor forma (8.5 vs 6.0); más xGI por 90.")
    assert not _ENGLISH.search(text)


@pytest.mark.parametrize("margin,word", [(1.0, "ajustada"), (5.0, "moderada"), (12.0, "clara")])
def test_margin_words_match_the_card(margin, word):
    text = _build_recommendation("A", 60.0, "B", 60.0 - margin, "A", margin, [])
    assert f"diferencia {word} ({margin})." in text


def test_tie():
    assert _build_recommendation("A", 60.0, "B", 60.0, None, 0.0, []) == "A (60.0) y B (60.0) empatan en puntuación."


# ---------------------------------------------------------------------------
# budget hard block
# ---------------------------------------------------------------------------

def _transfer(price_delta: int) -> TransferMeta:
    return TransferMeta(player_out="Salah", player_in="Haaland", recommendation="transfer_in",
                        score_delta=8.0, price_delta=price_delta, reasons=("mejor forma",))


def test_budget_lead_in_spanish_and_the_answer_kept_below():
    transfer, _, text = _apply_squad_overrides(transfer=_transfer(25), chip=None,
                                               final_text="Análisis del cambio.", squad_context={"itb": 10})
    assert transfer.budget_constraint is True
    assert text.startswith("No te alcanza el presupuesto: Haaland cuesta +£2.5m más y tienes £1.0m en el banco.")
    assert text.endswith("Análisis del cambio.")
    assert not _ENGLISH.search(text)


def test_budget_without_an_answer_leaves_only_the_lead():
    _, _, text = _apply_squad_overrides(transfer=_transfer(25), chip=None, final_text="  ",
                                        squad_context={"itb": 10})
    assert text == "No te alcanza el presupuesto: Haaland cuesta +£2.5m más y tienes £1.0m en el banco."


def test_affordable_transfer_is_unchanged():
    transfer, _, text = _apply_squad_overrides(transfer=_transfer(5), chip=None,
                                               final_text="Análisis.", squad_context={"itb": 10})
    assert transfer.budget_constraint is False and text == "Análisis."

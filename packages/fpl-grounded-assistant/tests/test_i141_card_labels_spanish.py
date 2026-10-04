"""i141 -- the last English texts that reached cards, now Spanish at the origin.

i139's sweep left three, and this card found a fourth on the way:

* TransferCard -- transfer reasons and the recommendation sentence around them
  (transfer_advisor.py); the set-piece helper loses its English mode.
* ChipCard -- ``signal_label`` («top captain score · Groß», «average FDR (top 10)»
  were in Leo's captures).
* TransferSuggestionCard -- ``difficulty_label`` (easy/moderate/hard) and the scope
  line's ``position_label`` («midfielders», «all positions»), both through the
  catalogue. The tool keeps its enums: the renderer and the model read them.

The final sweep drives every producer behind ChipCard, ComparisonCard,
TransferCard and TransferSuggestionCard through all their branches and fails
on any English word. No network.
"""
from __future__ import annotations

import re

import pytest

from fpl_grounded_assistant.comparison import _build_recommendation, _explain_comparison
from fpl_grounded_assistant.final_response import (
    _extract_chip_meta,
    _extract_transfer_suggestion_meta,
)
from fpl_grounded_assistant.transfer_advisor import _build_recommendation_text, _build_transfer_reasons

ENGLISH = re.compile(
    r"\b(stronger|easier|fixture|higher|output|better|security|advantage|advantages|edges|margin|tied|"
    r"recommendation|transfer in|consider|hold|score|net cost|net saving|captain|current|gameweek|"
    r"average|teams|mixed|normal gameweek|double|blank|easy|moderate|hard|goalkeepers|defenders|midfielders|"
    r"forwards|all positions|set-piece|pen|fk|fk2|pen2)\b",
    re.I,
)


def _p(form=5.0, fdr=3, xgi=0.3, risk=10.0, home=None, bonus=0.0, notes=()):
    return {"score_inputs": {"form": form, "fixture_difficulty": fdr, "effective_fdr": fdr,
                             "xgi_per_90": xgi, "minutes_risk": risk, "is_home": home},
            "role_signals": {"role_bonus": bonus, "set_piece_notes": list(notes)}}


STRONG = _p(form=8.5, fdr=2, home=True, xgi=0.7, risk=5.0, bonus=10.0, notes=["penalty_taker_1"])
WEAK = _p(form=6.0, fdr=4, home=False, xgi=0.3, risk=40.0, bonus=0.0, notes=["freekick_taker_2"])


# ---------------------------------------------------------------------------
# TransferCard
# ---------------------------------------------------------------------------

def test_transfer_reasons_are_spanish():
    assert _build_transfer_reasons(STRONG, WEAK) == [
        "mejor forma (8.5 vs 6.0)",
        "partido más fácil (FDR 2L vs 4V)",
        "más xGI por 90",
        "minutos más asegurados",
        "ventaja a balón parado (penales vs 2.º en tiros libres)",
    ]


@pytest.mark.parametrize("rec,price,expected", [
    ("transfer_in", 15, "Recomendación: incorpora a Haaland. Puntuación: 80 vs 70 de Salah (+10.0)."
                        "  Ventajas: mejor forma (8.5 vs 6.0).  Coste neto: +£1.5m."),
    ("marginal_transfer_in", -5, "Ajustado: valora a Haaland en lugar de Salah. Puntuación: 80 vs 70 (+10.0)."
                                 "  Ventajas: mejor forma (8.5 vs 6.0).  Ahorro neto: £0.5m."),
])
def test_transfer_recommendation_sentence(rec, price, expected):
    assert _build_recommendation_text("Haaland", "Salah", 80.0, 70.0, 10.0, price, rec,
                                      ["mejor forma (8.5 vs 6.0)"]) == expected


def test_transfer_hold_sentence():
    text = _build_recommendation_text("Haaland", "Salah", 65.0, 70.0, -5.0, 0, "hold", [])
    assert text == "Recomendación: mantén a Salah. Puntuación: 70 vs 65 de Haaland (-5.0)."


# ---------------------------------------------------------------------------
# ChipCard
# ---------------------------------------------------------------------------

def _chip(chip, **signals):
    return {"status": "ok", "chip": chip, "recommendation": "conditions_marginal",
            "evaluated_gameweek": 6, "signals": signals}


@pytest.mark.parametrize("raw,label", [
    (_chip("triple_captain", top_captain_score=82.0, top_player="Groß"), "mejor puntuación de capitán"),
    (_chip("triple_captain", evaluated_captain_score=70.0, evaluated_player="Saka"), "puntuación de capitán"),
    (_chip("wildcard", current_gameweek=6), "jornada actual"),
    (_chip("bench_boost", average_fdr_top10=2.4), "FDR medio (top 10)"),
    (_chip("free_hit", gameweek_type="double", dgw_count=4), "equipos con doble jornada"),
    (_chip("free_hit", gameweek_type="blank", bgw_count=6), "equipos sin partido"),
    (_chip("free_hit", gameweek_type="mixed", dgw_count=2, bgw_count=1), "jornada mixta (equipos con doble jornada)"),
    (_chip("free_hit", gameweek_type="normal"), "jornada normal"),
])
def test_chip_signal_label(raw, label):
    assert _extract_chip_meta(raw).signal_label == label


# ---------------------------------------------------------------------------
# TransferSuggestionCard
# ---------------------------------------------------------------------------

def _suggestion(position, *labels):
    return {"status": "ok", "position": position, "position_label": "whatever the tool said",
            "picks": [{"rank": i + 1, "web_name": f"P{i}", "team_short": "LIV", "position": "MID",
                       "now_cost": 80, "now_cost_m": 8.0, "form": 6.0, "avg_fdr": 2.5,
                       "difficulty_label": lab, "composite_score": 70.0, "ownership": 10.0}
                      for i, lab in enumerate(labels)]}


def test_difficulty_label_from_the_catalogue():
    meta = _extract_transfer_suggestion_meta(_suggestion("MID", "easy", "moderate", "hard", "weird"))
    assert [p.difficulty_label for p in meta.picks] == ["fácil", "moderado", "difícil", "weird"]


@pytest.mark.parametrize("code,noun", [("GKP", "porteros"), ("DEF", "defensas"), ("MID", "mediocampistas"),
                                       ("FWD", "delanteros"), ("ALL", "todas las posiciones")])
def test_position_label_from_the_catalogue(code, noun):
    assert _extract_transfer_suggestion_meta(_suggestion(code, "easy")).position_label == noun


def test_unknown_position_code_keeps_the_tool_label():
    assert _extract_transfer_suggestion_meta(_suggestion("XYZ", "easy")).position_label == "whatever the tool said"


# ---------------------------------------------------------------------------
# final sweep: every branch behind the four cards, no English word left
# ---------------------------------------------------------------------------

def _all_card_texts() -> list[str]:
    texts: list[str] = []
    # ComparisonCard + TransferCard reasons, every reason branch and set-piece shape
    for w, l in ((STRONG, WEAK), (_p(bonus=5.0), _p()), (_p(bonus=5.0, notes=["penalty_taker_2"]), _p()),
                 (_p(bonus=5.0, notes=["freekick_taker_1"]), _p(notes=["penalty_taker_1"]))):
        texts += _explain_comparison(w, l) + _build_transfer_reasons(w, l)
    # recommendation sentences (comparison + transfer), every branch
    reasons = _explain_comparison(STRONG, WEAK)
    texts.append(_build_recommendation("A", 80.0, "B", 70.0, "A", 12.0, reasons))
    texts.append(_build_recommendation("A", 60.0, "B", 59.0, "A", 1.0, []))
    texts.append(_build_recommendation("A", 60.0, "B", 60.0, None, 0.0, []))
    for rec, price in (("transfer_in", 10), ("marginal_transfer_in", -10), ("hold", 0)):
        texts.append(_build_recommendation_text("A", "B", 80.0, 70.0, 10.0, price, rec, reasons))
    # ChipCard signal labels, every branch
    for raw in (_chip("triple_captain", top_captain_score=82.0), _chip("triple_captain", evaluated_captain_score=1.0,
                evaluated_player="X"), _chip("wildcard", current_gameweek=6), _chip("bench_boost", average_fdr_top10=2.0),
                _chip("free_hit", gameweek_type="double", dgw_count=1), _chip("free_hit", gameweek_type="blank", bgw_count=1),
                _chip("free_hit", gameweek_type="mixed", dgw_count=1), _chip("free_hit", gameweek_type="normal")):
        texts.append(_extract_chip_meta(raw).signal_label or "")
    # TransferSuggestionCard labels
    for code in ("GKP", "DEF", "MID", "FWD", "ALL"):
        meta = _extract_transfer_suggestion_meta(_suggestion(code, "easy", "moderate", "hard"))
        texts.append(meta.position_label)
        texts += [p.difficulty_label for p in meta.picks]
    return texts


def test_no_english_reaches_the_four_cards():
    leaks = [t for t in _all_card_texts() if ENGLISH.search(t)]
    assert leaks == []

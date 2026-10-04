"""i137 -- a chip already played says when, in Spanish, and keeps the answer below.

Seen in prod 2026-10-04 (team 68643: bench boost GW2, triple captain GW3,
checked against FPL's entry history). ``_apply_squad_overrides`` replaced the
whole answer -- the i108/i112 composition and the model's body -- with the
English literal «Chip unavailable: triple_captain is not in your chips
remaining.». Now: «Ya usaste el Triple Capitán en la GW3. Vuelves a tenerlo
desde la GW20.» and the turn's answer below, as planning. The use comes from
``squad_context.chips_used`` (the UI's projection of the FPL history), the
return from the bootstrap's chip windows; neither is invented.

Read off what /ask serves (``to_ask_response``). No network.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from fpl_grounded_assistant import final_response as fr
from fpl_grounded_assistant.final_response import ChipAdviceMeta, _apply_squad_overrides

#: FPL 2026-27 bootstrap chips (live, 2026-10-04): every chip has two windows.
CHIP_WINDOWS = [
    {"name": "wildcard", "start_event": 2, "stop_event": 19},
    {"name": "wildcard", "start_event": 20, "stop_event": 38},
    {"name": "freehit", "start_event": 2, "stop_event": 19},
    {"name": "bboost", "start_event": 1, "stop_event": 19},
    {"name": "3xc", "start_event": 1, "stop_event": 19},
    {"name": "freehit", "start_event": 20, "stop_event": 38},
    {"name": "bboost", "start_event": 20, "stop_event": 38},
    {"name": "3xc", "start_event": 20, "stop_event": 38},
]
BOOTSTRAP = {"chips": CHIP_WINDOWS}
#: Team 68643's FPL history, as the UI projects it.
CHIPS_USED = [{"chip": "bench_boost", "event": 2}, {"chip": "triple_captain", "event": 3},
              {"chip": "wildcard", "event": 5}]
#: What the turn composed (i112 header + body + particular sentence).
COMPOSED = ("**Triple Captain — jornada 6.** Mejor candidato: Dasilva.\n\nEl contexto es favorable…\n\n"
            "Tu mejor candidato para el triple capitán no está en tu plantilla.")


def _chip(name: str = "triple_captain", gw: int = 6) -> ChipAdviceMeta:
    return ChipAdviceMeta(chip=name, recommendation="conditions_favorable", gw=gw,
                          signal_value=80.0, signal_label="captain_score", top_player="Dasilva",
                          evaluated_player=None)


def _apply(chip: ChipAdviceMeta, squad: dict, bootstrap=BOOTSTRAP, text: str = COMPOSED):
    return _apply_squad_overrides(transfer=None, chip=chip, final_text=text,
                                  squad_context=squad, bootstrap=bootstrap)


# ---------------------------------------------------------------------------
# the three cases of the gate
# ---------------------------------------------------------------------------

def test_used_in_the_first_half_says_when_and_when_it_comes_back():
    _, chip, text = _apply(_chip(), {"chips_remaining": ["wildcard", "free_hit"], "chips_used": CHIPS_USED})
    assert chip.chip_unavailable is True
    assert text.startswith("Ya usaste el Triple Capitán en la GW3. Vuelves a tenerlo desde la GW20.")
    assert fr._CHIP_UNAVAILABLE_PLANNING in text
    assert text.endswith(COMPOSED)                       # the composition survives, below
    assert "Chip unavailable" not in text and "chips remaining" not in text


def test_used_without_its_gameweek_says_it_without_a_number():
    _, chip, text = _apply(_chip(), {"chips_remaining": ["wildcard"]})      # no chips_used (old UI)
    assert chip.chip_unavailable is True
    lead = text.split("\n\n")[0]
    assert lead == "Ya usaste el Triple Capitán, así que ahora no lo tienes disponible."
    assert not re.search(r"\d", lead)
    assert text.endswith(COMPOSED)


def test_available_chip_is_unchanged():
    used = [{"chip": "bench_boost", "event": 2}, {"chip": "wildcard", "event": 5}]   # TC not played
    _, chip, text = _apply(_chip(), {"chips_remaining": ["triple_captain"], "chips_used": used})
    assert chip.chip_unavailable is False and text == COMPOSED


# ---------------------------------------------------------------------------
# one test per guard
# ---------------------------------------------------------------------------

def test_no_windows_keeps_the_used_gw_and_drops_the_return():
    _, _, text = _apply(_chip(), {"chips_remaining": [], "chips_used": CHIPS_USED}, bootstrap=None)
    assert text.split("\n\n")[0] == "Ya usaste el Triple Capitán en la GW3."


def test_used_in_the_last_window_has_no_return_sentence():
    used = [{"chip": "triple_captain", "event": 24}]
    # i140: asked about GW25, inside the window the chip was spent in
    _, _, text = _apply(_chip(gw=25), {"chips_remaining": [], "chips_used": used})
    assert text.split("\n\n")[0] == "Ya usaste el Triple Capitán en la GW24."


def test_the_latest_use_of_that_chip_is_the_one_named():
    used = [{"chip": "wildcard", "event": 5}, {"chip": "wildcard", "event": 21}]
    _, _, text = _apply(_chip("wildcard", gw=25), {"chips_remaining": [], "chips_used": used})
    assert text.split("\n\n")[0] == "Ya usaste el Comodín en la GW21."


@pytest.mark.parametrize("bad", [
    [{"chip": "triple_captain", "event": "x"}],
    [{"chip": "triple_captain", "event": 0}],
    [{"chip": "triple_captain"}],
    "triple_captain",
])
def test_a_malformed_or_foreign_use_reads_as_unknown(bad):
    _, _, text = _apply(_chip(), {"chips_remaining": [], "chips_used": bad})
    assert text.split("\n\n")[0] == "Ya usaste el Triple Capitán, así que ahora no lo tienes disponible."


def test_malformed_windows_give_no_return():
    boot = {"chips": [{"name": "3xc", "start_event": 1, "stop_event": 19}, {"name": "3xc", "start_event": "?"}]}
    _, _, text = _apply(_chip(), {"chips_remaining": [], "chips_used": CHIPS_USED}, bootstrap=boot)
    assert text.split("\n\n")[0] == "Ya usaste el Triple Capitán en la GW3."


def test_windows_are_read_for_that_chip_only():
    boot = {"chips": [{"name": "wildcard", "start_event": 2, "stop_event": 10},
                      {"name": "wildcard", "start_event": 11, "stop_event": 38},
                      {"name": "3xc", "start_event": 1, "stop_event": 19},
                      {"name": "3xc", "start_event": 20, "stop_event": 38}]}
    _, _, text = _apply(_chip(), {"chips_remaining": [], "chips_used": CHIPS_USED}, bootstrap=boot)
    assert text.split("\n\n")[0] == "Ya usaste el Triple Capitán en la GW3. Vuelves a tenerlo desde la GW20."


def test_one_malformed_window_voids_the_return_rather_than_skipping_it():
    boot = {"chips": [{"name": "3xc", "start_event": 1, "stop_event": 19},
                      {"name": "3xc", "start_event": "?", "stop_event": 25},
                      {"name": "3xc", "start_event": 20, "stop_event": 38}]}
    _, _, text = _apply(_chip(), {"chips_remaining": [], "chips_used": CHIPS_USED}, bootstrap=boot)
    assert text.split("\n\n")[0] == "Ya usaste el Triple Capitán en la GW3."


def test_feminine_chip_takes_its_article_and_pronoun():
    used = [{"chip": "free_hit", "event": 7}]
    _, _, text = _apply(_chip("free_hit"), {"chips_remaining": [], "chips_used": used})
    assert text.split("\n\n")[0] == "Ya usaste la Ficha Libre en la GW7. Vuelves a tenerla desde la GW20."
    _, _, text = _apply(_chip("free_hit"), {"chips_remaining": []})
    assert text.split("\n\n")[0] == "Ya usaste la Ficha Libre, así que ahora no la tienes disponible."


def test_empty_answer_leaves_only_the_lead():
    _, _, text = _apply(_chip(), {"chips_remaining": [], "chips_used": CHIPS_USED}, text="  ")
    assert text == "Ya usaste el Triple Capitán en la GW3. Vuelves a tenerlo desde la GW20."


def test_spanish_labels_match_the_chip_card():
    tsx = (Path(__file__).resolve().parents[2] / "fpl-ui" / "components" / "intents" / "ChipCard.tsx").read_text(encoding="utf-8")
    block = tsx[tsx.index("const CHIP_LABELS"):]
    block = block[:block.index("};")]
    card = dict(re.findall(r"(\w+):\s*'([^']+)'", block))
    assert card == {k: label for k, (_, label, _) in fr._CHIP_LABEL_ES.items()}


# ---------------------------------------------------------------------------
# what /ask serves
# ---------------------------------------------------------------------------

def _served(squad: dict, bootstrap=BOOTSTRAP):
    from fpl_grounded_assistant.harness_adapter import to_ask_response
    from fpl_server import AskRequest
    d = {"answer_text": COMPOSED, "chip": _chip(), "transfer": None, "selected_tool": "get_chip_advice",
         "outcome": "ok", "routing_trace": {"branch": "orchestrator", "grounded": True},
         "raw_output": {"status": "ok", "chip": "triple_captain"}}
    return to_ask_response(d, AskRequest(question="¿Uso el triple capitán esta jornada?", squad_context=squad),
                           bootstrap)


def test_served_text_for_team_68643():
    resp = _served({"chips_remaining": ["wildcard", "free_hit"], "chips_used": CHIPS_USED})
    assert resp.final_text.startswith("Ya usaste el Triple Capitán en la GW3. Vuelves a tenerlo desde la GW20.")
    assert "Mejor candidato: Dasilva" in resp.final_text
    assert resp.chip is not None and resp.chip.get("chip_unavailable") is True


def test_served_text_unchanged_when_the_chip_is_available():
    resp = _served({"chips_remaining": ["triple_captain"], "chips_used": []})
    assert resp.final_text == COMPOSED


def test_server_passes_its_bootstrap_to_the_adapter():
    src = (Path(__file__).resolve().parents[1] / "fpl_server.py").read_text(encoding="utf-8")
    assert "_to_ask_response(ask_v2_dict, req, _turn_bootstrap)" in src

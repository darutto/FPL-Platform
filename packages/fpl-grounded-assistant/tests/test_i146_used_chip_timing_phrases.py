"""i146 -- a used chip's advice has no timing / keep-it phrases about the spent window.

After i145 the window notice spoke of the next window, but 4/5 bodies still
said GW6 was «demasiado pronto / una fase temprana» for a Wildcard played in
GW5: the wildcard's own advice («It is early in the active wildcard window …
later in this window»). When ``chip_availability`` is ``used`` those sentences
are removed for all four chips (wildcard timing, triple captain «later
gameweek / worth saving», free hit «saving it / a larger double gameweek»).
With the chip available the advice text is byte-for-byte what it was. No network.
"""
from __future__ import annotations

import copy
from typing import Any

import pytest

from fpl_grounded_assistant import chip_advisor as ca
from fpl_grounded_assistant.chip_advisor import get_chip_advice

#: conftest's current GW is 28; windows chosen so 28 is early in its window.
WINDOWS = {
    "wildcard": [{"name": "wildcard", "start_event": 26, "stop_event": 38},
                 {"name": "wildcard", "start_event": 2, "stop_event": 25}],
    "triple_captain": [{"name": "3xc", "start_event": 1, "stop_event": 30},
                       {"name": "3xc", "start_event": 31, "stop_event": 38}],
    "free_hit": [{"name": "freehit", "start_event": 1, "stop_event": 30},
                 {"name": "freehit", "start_event": 31, "stop_event": 38}],
}
TIMING_TELLS = ("early in the active", "late in the active", "viable wildcard window", "later in this window",
                "later gameweek", "worth saving", "saving it", "larger double gameweek")


def _bs(bootstrap, chip: str, used_event: int | None) -> dict[str, Any]:
    bs = copy.deepcopy(bootstrap)
    bs["chips"] = WINDOWS[chip]
    bs["fixture_difficulty_map"] = {13: 2, 14: 2, 1: 4, 8: 2, 11: 2}
    used = [{"chip": chip, "event": used_event}] if used_event else []
    bs["_squad_context"] = {"chips_used": used}
    return bs


@pytest.mark.parametrize("chip,used_in_window", [("wildcard", 27), ("triple_captain", 20), ("free_hit", 20)])
def test_available_chip_keeps_its_timing_phrase(bootstrap, chip, used_in_window):
    out = get_chip_advice(chip, _bs(bootstrap, chip, None))
    assert out["chip_availability"]["status"] == "available"
    if chip == "triple_captain" and out["recommendation"] == "conditions_favorable":
        pytest.skip("favourable TC carries no timing phrase")
    assert any(t in out["advice_text"] for t in TIMING_TELLS), out["advice_text"]


@pytest.mark.parametrize("chip,used_in_window", [("wildcard", 27), ("triple_captain", 20), ("free_hit", 20)])
def test_used_chip_drops_every_timing_phrase(bootstrap, chip, used_in_window):
    available = get_chip_advice(chip, _bs(bootstrap, chip, None))
    used = get_chip_advice(chip, _bs(bootstrap, chip, used_in_window))
    assert used["chip_availability"]["status"] == "used"
    assert not any(t in used["advice_text"] for t in TIMING_TELLS), used["advice_text"]
    # everything that is not timing is still there: the conditions label and the facts
    label = available["advice_text"].split(".")[0]          # e.g. "Wildcard conditions: unfavorable"
    assert label in used["advice_text"]
    assert "  " not in used["advice_text"]


def test_wildcard_used_keeps_the_label_but_not_the_early_window_reasoning(bootstrap):
    out = get_chip_advice("wildcard", _bs(bootstrap, "wildcard", 27))
    assert "Wildcard conditions:" in out["advice_text"]
    assert "early" not in out["advice_text"] and "this early" not in out["advice_text"]


def test_free_hit_blank_keeps_its_fact_and_drops_the_save_clause():
    text = f"Free hit can help cover blanked players{ca._FH_SAVE_FOR_DGW}. Next."
    assert ca._strip_timing(text, [ca._FH_SAVE_FOR_DGW]) == "Free hit can help cover blanked players. Next."


def test_timing_phrases_never_reach_the_output(bootstrap):
    for chip in ("wildcard", "triple_captain", "free_hit", "bench_boost"):
        out = get_chip_advice(chip, _bs(bootstrap, chip if chip in WINDOWS else "free_hit", None))
        assert "timing_phrases" not in out


def _fh_bs(bootstrap, team_fixtures, used_event):
    bs = _bs(bootstrap, "free_hit", used_event)
    bs["team_fixtures"] = team_fixtures
    return bs


_FIX = {"gameweek": 28, "opponent_id": 2, "is_home": True, "difficulty": 3}


@pytest.mark.parametrize("team_fixtures,stem", [
    # every team plays once except team 5, which blanks -> blank gameweek
    ({1: [_FIX], 2: [_FIX], 3: [_FIX], 4: [_FIX], 5: []}, "saving it for an upcoming double gameweek"),
    # team 1 plays twice, the rest once -> small double gameweek
    ({1: [_FIX, _FIX], 2: [_FIX], 3: [_FIX], 4: [_FIX], 5: [_FIX]}, "a larger double gameweek"),
])
def test_free_hit_blank_and_double_phrases_drop_when_used(bootstrap, team_fixtures, stem):
    available = get_chip_advice("free_hit", _fh_bs(bootstrap, team_fixtures, None))
    assert stem in available["advice_text"], available["advice_text"]
    used = get_chip_advice("free_hit", _fh_bs(bootstrap, team_fixtures, 20))
    assert used["chip_availability"]["status"] == "used"
    assert stem not in used["advice_text"]
    assert not any(t in used["advice_text"] for t in TIMING_TELLS)

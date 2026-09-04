"""The factors behind a captain score, said out loud.

Slice 4's product claim is not "the ranking changed", it is "someone asking
about a player can now see why he sits where he does". These tests pin the
phrasing, the parity with the card, and the two things the copy must never do.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fpl_grounded_assistant.captain_factors import (
    TRIPLE_CAPTAIN_RISK_NOTE,
    contradiction_note,
    factor_phrases,
    minutes_phrase,
    penalties_phrase,
)

_FULL = {
    "minutes_played": 180,
    "minutes_available": 180,
    "starts": 2,
    "participation_percent": 100.0,
    "degraded": False,
}
_PARTIAL = {
    "minutes_played": 108,
    "minutes_available": 180,
    "starts": 1,
    "participation_percent": 60.0,
    "degraded": False,
}
_DEGRADED = {
    "minutes_played": 90,
    "minutes_available": None,
    "starts": 1,
    "participation_percent": None,
    "degraded": True,
    "degradation_reason": "missing_official_fixtures",
}


def test_minutes_are_named_in_plain_language():
    assert minutes_phrase(_PARTIAL) == "jugó 108 de 180 minutos posibles, 1 titularidad"
    assert minutes_phrase(_FULL) == "jugó 180 de 180 minutos posibles, 2 titularidades"


def test_a_derivation_that_degraded_says_nothing_rather_than_guessing():
    assert minutes_phrase(_DEGRADED) is None
    assert minutes_phrase(None) is None


def test_penalties_are_shown_and_absence_is_not_a_negative():
    assert penalties_phrase(1) == "lanza los penaltis"
    assert penalties_phrase(2) == "penaltis, 2º en la lista"
    # Not taking penalties produces no phrase at all, rather than a demerit.
    assert penalties_phrase(None) is None
    assert penalties_phrase(0) is None


def test_the_order_contradicting_the_factors_is_said_not_left_implied():
    haaland = {"minutes_context": _FULL, "penalties_order": 1, "rank": 5}
    above = [{"minutes_context": _PARTIAL, "penalties_order": None, "rank": 1}]

    note = contradiction_note(haaland, above)

    assert note is not None
    assert "aun así puntúa por debajo" in note


def test_no_note_when_the_order_and_the_factors_agree():
    haaland = {"minutes_context": _FULL, "penalties_order": 1, "rank": 1}
    below_but_also_full = [{"minutes_context": _FULL, "penalties_order": None, "rank": 0}]

    # A row without a note has to mean "no surprise here".
    assert contradiction_note(haaland, below_but_also_full) is None


@pytest.mark.parametrize("locale", ["es", "en"])
def test_no_user_visible_string_reveals_a_weight_or_a_threshold(locale):
    entry = {"minutes_context": _PARTIAL, "penalties_order": 1}
    everything = " ".join([
        *factor_phrases(entry, locale=locale),
        contradiction_note(
            {"minutes_context": _FULL, "penalties_order": 1},
            [{"minutes_context": _PARTIAL}],
            locale=locale,
        ) or "",
        TRIPLE_CAPTAIN_RISK_NOTE[locale],
    ])

    # Naming a factor informs. Naming its coefficient publishes the model.
    assert not re.search(r"\b(40|30|25|20|10|45)\s*%", everything)
    assert "peso" not in everything.lower()
    assert "weight" not in everything.lower()


def test_the_triple_captain_note_says_the_risk_multiplies_too():
    for locale in ("es", "en"):
        note = TRIPLE_CAPTAIN_RISK_NOTE[locale]
        assert note
        assert not re.search(r"\d+\s*%", note)


def test_card_and_prose_phrase_the_same_player_identically():
    """The Python and TypeScript helpers are deliberate mirrors.

    If they drift, the text above the card and the card itself describe the
    same player with two different figures — the failure this slice exists to
    stop.
    """
    ts = Path(__file__).resolve().parents[2] / "fpl-ui" / "lib" / "captain-factors.ts"
    source = ts.read_text(encoding="utf-8")

    assert "jugó ${minutes_played} de ${minutes_available} minutos posibles" in source
    assert "titularidad" in source and "titularidades" in source
    assert "lanza los penaltis" in source
    assert "aun así puntúa por debajo" in source


def test_asking_about_a_named_player_names_his_minutes_and_penalties(bootstrap):
    """Slice 4's acceptance criterion 1, end to end.

    "Do I triple-captain Haaland?" used to answer with two numbers and nothing
    else. It now has to say what he actually does on the pitch.
    """
    from fpl_grounded_assistant.chip_advisor import _advise_triple_captain

    import copy

    fixture = copy.deepcopy(bootstrap)
    named = fixture["elements"][0]
    named["penalties_order"] = 1
    result = _advise_triple_captain(fixture, player=named["web_name"])

    assert result["recommendation"] != "missing_context"
    text = result["advice_text"]
    signals = result["signals"]

    assert signals["evaluated_player"] == named["web_name"]
    assert "lanza los penaltis" in signals["evaluated_factors"] or any(
        "penalt" in phrase for phrase in signals["evaluated_factors"]
    )
    # And the chip's own risk is stated, not just its upside.
    assert signals["triple_captain_risk_note"] in text
    assert "three times" in signals["triple_captain_risk_note"]

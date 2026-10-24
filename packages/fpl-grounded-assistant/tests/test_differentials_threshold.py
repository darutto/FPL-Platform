"""
/differentials and /diferenciales read the ownership threshold from the text they are given.

Before this change the parser dropped all positional text, so "/differentials under 10%" used
the 15% default and gave the answer for the wrong threshold without saying so. The threshold
now comes from a percentage in the text, in either language. An explicit threshold=/umbral=/
max_owned= flag still wins, and a bare number with no % stays the top-N count, as before.
Deterministic: decide() and validate_and_parse() only, no provider, no network.
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.decision_router import decide
from fpl_grounded_assistant.prompt_registry import get_prompt_spec, validate_and_parse

EMPTY = {"elements": [], "teams": [], "events": []}


def _threshold(text: str) -> float:
    d = decide(text, EMPTY)
    assert d["kind"] == "prompt", d
    assert d["outcome"] in ("ok_prompt_dispatch", "ok_prompt_expansion"), d
    return d["args"]["threshold"]


# -- English command: the percentage is read ----------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("/differentials under 10%", 10.0),
    ("/differentials under 10", 10.0),
    ("/differentials under 7.5%", 7.5),
    ("/differentials below 12%", 12.0),
    ("/differentials less than 8%", 8.0),
    ("/differentials 10%", 10.0),
    ("/differentials under 10% top 3", 10.0),
])
def test_english_positional_percentage_is_the_threshold(text, expected):
    assert _threshold(text) == expected


# -- Spanish command: the same, in Spanish phrasing -----------------------------------

@pytest.mark.parametrize("text, expected", [
    ("/diferenciales menos del 10%", 10.0),
    ("/diferenciales menos del 10", 10.0),
    ("/diferenciales menos de 8%", 8.0),
    ("/diferenciales por debajo de 12%", 12.0),
    ("/diferenciales 7,5%", 7.5),
    ("/diferenciales menos del 10% propiedad", 10.0),
])
def test_spanish_positional_percentage_is_the_threshold(text, expected):
    assert _threshold(text) == expected


def test_the_english_and_spanish_phrasings_give_the_same_answer():
    assert _threshold("/differentials under 10%") == _threshold("/diferenciales menos del 10%")


# -- explicit flags still win; bare numbers are still the top-N count ---------------

@pytest.mark.parametrize("text, expected", [
    ("/differentials threshold=12", 12.0),
    ("/diferenciales umbral=8", 8.0),
    ("/differentials max_owned=8", 8.0),
    ("/differentials ownership=10", 10.0),
    ("/differentials threshold=12 under 5%", 12.0),   # the flag wins over the text
    ("/diferenciales umbral=6 menos del 10%", 6.0),
])
def test_explicit_threshold_flags_win_over_the_text(text, expected):
    assert _threshold(text) == expected


@pytest.mark.parametrize("text", ["/differentials 3", "/diferenciales 5", "/differentials top 3"])
def test_a_bare_number_without_percent_is_never_the_threshold(text):
    assert _threshold(text) == 15.0


def test_bare_number_stays_the_top_n_count():
    d = decide("/differentials under 10% count=3", EMPTY)
    assert d["args"] == {"threshold": 10.0, "top_n": 3}


# -- out of range is a visible error, not a silent default ---------------------------

@pytest.mark.parametrize("text", ["/differentials under 0.05%", "/differentials 0%", "/differentials 1000%"])
def test_an_out_of_range_percentage_is_refused_not_defaulted(text):
    d = decide(text, EMPTY)
    assert d["kind"] == "prompt"
    assert d["outcome"] == "needs_clarification", d


# -- the parser itself -------------------------------------------------------------

def test_validate_and_parse_reads_the_percentage_directly():
    spec = get_prompt_spec("diferenciales")
    r = validate_and_parse(spec, "menos del 10%")
    assert r["ok"] and r["args"]["threshold"] == 10.0


def test_no_text_keeps_the_default():
    spec = get_prompt_spec("diferenciales")
    r = validate_and_parse(spec, "")
    assert r["ok"] and r["args"]["threshold"] == 15.0

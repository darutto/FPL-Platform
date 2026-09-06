"""The captain score must fall smoothly and monotonically as minutes fall.

Minutes used to enter the score as a 10% additive term, which moved the whole
range from ever-present to never-played by about 10 points out of 55 -- almost
flat.  With the signal that weak, the ordering could not express rotation risk,
so the tier carried the entire judgement, and it carried it as a cliff: one
minute either side of 50% participation was the difference between the top of
the ranking and being held back entirely.

These tests pin the shape of the curve, not a set of numbers: monotone,
continuous, and never more generous than the additive formula it replaced.
"""

from __future__ import annotations

import pytest

from fpl_captain_engine.captain_score import calculate_captain_score, minutes_confidence

FORM, FDR, XGI = 6.0, 3, 0.30
AVAILABLE_MINUTES = 180.0


def _score_at(minutes_played: float) -> float:
    risk = 100.0 - (minutes_played / AVAILABLE_MINUTES * 100.0)
    return calculate_captain_score(FORM, FDR, XGI, risk)


def _additive_only_score(minutes_risk: float) -> float:
    """The pre-change formula: minutes as a flat 10% component."""
    form_score = min(max((FORM / 10) * 100, 0.0), 100.0)
    fixture_score = min(max((6 - FDR) * 20, 0.0), 100.0)
    xgi_score = min(max(XGI * 50, 0.0), 100.0)
    minutes_score = min(max(100 - minutes_risk, 0.0), 100.0)
    return (
        form_score * 0.4 + fixture_score * 0.3 + xgi_score * 0.2 + minutes_score * 0.1
    )


def test_score_decreases_at_every_minute_lost():
    """Strictly monotone: one minute less is never worth the same or more."""
    scores = [_score_at(m) for m in range(int(AVAILABLE_MINUTES), -1, -1)]
    for higher, lower in zip(scores, scores[1:]):
        assert lower < higher


def test_no_cliff_between_players_one_minute_apart():
    """A single minute may not move the score by more than a single minute's worth.

    The whole point of the change: neighbours must be neighbours.  The largest
    one-minute step is bounded by the average step across the full range, with
    slack for the curve, so a re-introduced threshold inside the score fails.
    """
    scores = [_score_at(m) for m in range(int(AVAILABLE_MINUTES), -1, -1)]
    steps = [higher - lower for higher, lower in zip(scores, scores[1:])]
    full_range = scores[0] - scores[-1]
    average_step = full_range / len(steps)
    assert max(steps) < average_step * 2


def test_never_more_generous_than_the_formula_it_replaced():
    """Softening the criterion is the one outcome this change must not have."""
    for risk in range(0, 101):
        assert calculate_captain_score(FORM, FDR, XGI, float(risk)) <= (
            _additive_only_score(float(risk)) + 1e-9
        )


def test_half_participation_scores_strictly_worse_than_before():
    """The player who plays half the minutes is the case that started this."""
    half = calculate_captain_score(FORM, FDR, XGI, 50.0)
    assert half < _additive_only_score(50.0)


def test_certain_starters_are_untouched():
    """Zero measured risk keeps the whole score: nobody is penalised for nothing."""
    assert minutes_confidence(0.0) == 1.0
    assert calculate_captain_score(FORM, FDR, XGI, 0.0) == _additive_only_score(0.0)


@pytest.mark.parametrize("risk,expected", [(0.0, 1.0), (50.0, 0.5), (100.0, 0.0)])
def test_confidence_is_the_share_of_minutes_played(risk, expected):
    """Captain points are earned on the pitch: the score scales with the share."""
    assert minutes_confidence(risk) == pytest.approx(expected)


@pytest.mark.parametrize("risk", [-25.0, 125.0])
def test_confidence_stays_inside_zero_and_one(risk):
    assert 0.0 <= minutes_confidence(risk) <= 1.0


def test_minutes_move_the_score_enough_to_be_visible_in_the_ranking():
    """The descent must be steep enough that the ordering itself carries it.

    This is the test that fails if the additive-only formula comes back.  With
    minutes worth ten points out of fifty-five, two players an hour of football
    apart sorted as near-equals and only the tier could separate them -- which
    is exactly how the cliff got there.  The full range has to dominate the
    score, not decorate it.
    """
    ever_present = _score_at(AVAILABLE_MINUTES)
    never_played = _score_at(0)
    assert never_played == 0.0
    assert (ever_present - never_played) > ever_present * 0.9

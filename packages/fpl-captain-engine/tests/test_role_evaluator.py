"""Set-piece role signal coverage.

Ported from `fpl-grounded-assistant/run_phase2h_tests.py` (Phase 2h), a
standalone runner in no CI list. Expected values are carried over verbatim.

Deliberately NOT ported: that runner's sections J-S, which asserted
`classify_captain_tier(..., role_bonus=...)` applied `effective_score =
captain_score + role_bonus`. `classify_captain_tier` has never accepted a
`role_bonus` argument in any recorded commit, so those sections could not have
passed -- porting them would mean implementing an unbuilt feature rather than
preserving coverage. See the tracking issue linked from the commit that
retired the runners.

What role_bonus *does* drive today: reason selection in the grounded
assistant. `transfer_advisor._set_piece_advantage` and comparison's equivalent
fire a set-piece phrase only when one player's role_bonus strictly exceeds the
other's. It does not influence tier.
"""

from __future__ import annotations

import pytest

from fpl_captain_engine import (
    ROLE_BONUS_MAP,
    compute_role_bonus,
    derive_role_signals,
)


# ---------------------------------------------------------------------------
# Penalty takers
# ---------------------------------------------------------------------------

def test_first_choice_penalty_taker():
    signals = derive_role_signals({"penalties_order": 1, "direct_freekicks_order": None})
    assert signals["penalties_order"] == 1
    assert "penalty_taker_1" in signals["set_piece_notes"]
    assert signals["set_piece_threat"] is True
    assert signals["role_bonus"] == 5.0


def test_second_choice_penalty_taker_is_worth_less():
    signals = derive_role_signals({"penalties_order": 2, "direct_freekicks_order": None})
    assert "penalty_taker_2" in signals["set_piece_notes"]
    assert signals["set_piece_threat"] is True
    assert signals["role_bonus"] == 1.0


def test_no_penalty_role():
    signals = derive_role_signals({"penalties_order": None})
    assert not any("penalty" in note for note in signals["set_piece_notes"])
    assert signals["role_bonus"] == 0.0
    assert signals["set_piece_threat"] is False


# ---------------------------------------------------------------------------
# Direct free-kick takers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("order", "note", "bonus"),
    [
        (1, "freekick_taker_1", 3.0),
        (2, "freekick_taker_2", 0.5),
    ],
)
def test_freekick_taker(order, note, bonus):
    signals = derive_role_signals({"direct_freekicks_order": order})
    assert note in signals["set_piece_notes"]
    assert signals["role_bonus"] == bonus
    assert signals["set_piece_threat"] is True


def test_no_freekick_role():
    signals = derive_role_signals({"direct_freekicks_order": None})
    assert not any("freekick" in note for note in signals["set_piece_notes"])
    assert signals["role_bonus"] == 0.0


# ---------------------------------------------------------------------------
# Combined roles -- bonuses are additive
# ---------------------------------------------------------------------------

def test_penalty_and_freekick_notes_both_present():
    signals = derive_role_signals({"penalties_order": 1, "direct_freekicks_order": 1})
    assert "penalty_taker_1" in signals["set_piece_notes"]
    assert "freekick_taker_1" in signals["set_piece_notes"]
    assert signals["set_piece_threat"] is True


@pytest.mark.parametrize(
    ("pen", "fk", "expected"),
    [
        (1, 1, 8.0),   # 5.0 + 3.0
        (1, 2, 5.5),   # 5.0 + 0.5
        (2, 1, 4.0),   # 1.0 + 3.0
    ],
)
def test_combined_bonuses_are_additive(pen, fk, expected):
    signals = derive_role_signals({"penalties_order": pen, "direct_freekicks_order": fk})
    assert signals["role_bonus"] == expected


# ---------------------------------------------------------------------------
# No role at all
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "element",
    [
        {},
        {"penalties_order": None, "direct_freekicks_order": None},
    ],
    ids=["empty-element", "all-none"],
)
def test_no_role_signals(element):
    signals = derive_role_signals(element)
    assert signals["role_bonus"] == 0.0
    assert signals["set_piece_notes"] == []
    assert signals["set_piece_threat"] is False
    assert signals["penalties_order"] is None
    assert signals["direct_freekicks_order"] is None


# ---------------------------------------------------------------------------
# Corners are reported but excluded from the v1 bonus
# ---------------------------------------------------------------------------

def test_corners_are_surfaced_without_earning_a_bonus():
    signals = derive_role_signals({"corners_and_indirect_freekicks_order": 1})
    assert signals["corners_and_indirect_freekicks_order"] == 1
    assert signals["role_bonus"] == 0.0
    assert signals["set_piece_threat"] is False
    assert signals["set_piece_notes"] == []


def test_corners_do_not_stack_onto_a_penalty_bonus():
    signals = derive_role_signals({
        "penalties_order": 1,
        "corners_and_indirect_freekicks_order": 1,
    })
    assert signals["role_bonus"] == 5.0
    assert signals["corners_and_indirect_freekicks_order"] == 1


# ---------------------------------------------------------------------------
# compute_role_bonus agrees with derive_role_signals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("element", "expected"),
    [
        ({"penalties_order": 1}, 5.0),
        ({"direct_freekicks_order": 1}, 3.0),
        ({"penalties_order": 1, "direct_freekicks_order": 1}, 8.0),
        ({}, 0.0),
    ],
)
def test_compute_role_bonus(element, expected):
    assert compute_role_bonus(element) == expected


def test_compute_role_bonus_matches_derive_role_signals():
    element = {"penalties_order": 1}
    assert compute_role_bonus(element) == derive_role_signals(element)["role_bonus"]


# ---------------------------------------------------------------------------
# ROLE_BONUS_MAP
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("role", "bonus"),
    [
        ("penalty_taker_1", 5.0),
        ("penalty_taker_2", 1.0),
        ("freekick_taker_1", 3.0),
        ("freekick_taker_2", 0.5),
    ],
)
def test_role_bonus_map_values(role, bonus):
    assert ROLE_BONUS_MAP[role] == bonus


def test_corner_takers_are_absent_from_the_bonus_map():
    assert "corner_taker_1" not in ROLE_BONUS_MAP


def test_role_bonus_map_values_are_positive_floats():
    assert isinstance(ROLE_BONUS_MAP, dict)
    assert all(isinstance(v, float) for v in ROLE_BONUS_MAP.values())
    assert all(v > 0.0 for v in ROLE_BONUS_MAP.values())


def test_a_penalty_is_worth_more_than_a_freekick():
    assert ROLE_BONUS_MAP["penalty_taker_1"] > ROLE_BONUS_MAP["freekick_taker_1"]

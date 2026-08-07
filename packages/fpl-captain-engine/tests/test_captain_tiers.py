"""Tier classification coverage.

Ported from `fpl-grounded-assistant/run_phase2g_tests.py` (Phase 2g), a
standalone runner that was in no CI list and had been dead at import since the
bare-`python` collision (see PR #68). The assertions and their expected values
are carried over verbatim; only the harness changed.

Deliberately NOT ported: that runner's shim-export section, which asserted
`fpl_captain_engine.classify_captain_tier is python.captain_tiers.classify_captain_tier`.
The shim no longer exists -- the modules live here directly -- so those
assertions compared an object with itself. Public-surface coverage is kept in
test_public_surface.py instead, which is the part that still means something.
"""

from __future__ import annotations

import pytest

from fpl_captain_engine import (
    ALL_TIERS,
    CAPTAIN_TIER_RULES,
    TIER_AVOID,
    TIER_DIFFERENTIAL,
    TIER_LOW_CONFIDENCE,
    TIER_SAFE,
    TIER_UPSIDE,
    classify_captain_tier,
)


# ---------------------------------------------------------------------------
# Canonical examples (GW28 reference values, already validated in Phase 2d)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("label", "score", "risk", "xgi", "expected"),
    [
        ("Salah-like",         60.58,   0.0, 0.058, TIER_SAFE),
        ("Haaland-like",       54.85,   0.0, 0.085, TIER_UPSIDE),
        ("Saka-like",          36.35,  25.0, 0.085, TIER_DIFFERENTIAL),
        ("De Bruyne injured",  14.00, 100.0, 0.200, TIER_AVOID),
        ("catch-all",          28.00,  35.0, 0.040, TIER_LOW_CONFIDENCE),
    ],
)
def test_canonical_examples(label, score, risk, xgi, expected):
    assert classify_captain_tier(score, risk, xgi) == expected, label


def test_returns_str_within_all_tiers():
    result = classify_captain_tier(60.58, 0.0, 0.058)
    assert isinstance(result, str)
    assert result in ALL_TIERS


# ---------------------------------------------------------------------------
# Threshold boundaries -- the rules are inclusive/exclusive in specific ways,
# so each boundary is pinned from both sides.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("label", "score", "risk", "xgi", "expected"),
    [
        # avoid: minutes_risk >= 50 OR captain_score < 20
        ("risk=50 exactly triggers avoid",      60.0,  50.0, 0.10, TIER_AVOID),
        ("score=19.9 triggers avoid",           19.9,   0.0, 0.10, TIER_AVOID),
        # avoid takes priority over an otherwise-safe score
        ("avoid beats safe",                    80.0, 100.0, 0.10, TIER_AVOID),
        # safe: score >= 55 AND risk <= 20
        ("safe boundary",                       55.0,  20.0, 0.01, TIER_SAFE),
        # upside: score >= 45 AND risk <= 25 AND xgi >= 0.07
        ("upside boundary",                     45.0,  25.0, 0.07, TIER_UPSIDE),
        # differential: score >= 30 AND risk <= 30
        ("differential boundary",               30.0,  30.0, 0.01, TIER_DIFFERENTIAL),
        # catch-all
        ("low_confidence catch-all",            25.0,  35.0, 0.01, TIER_LOW_CONFIDENCE),
    ],
)
def test_threshold_boundaries(label, score, risk, xgi, expected):
    assert classify_captain_tier(score, risk, xgi) == expected, label


@pytest.mark.parametrize(
    ("label", "score", "risk", "xgi", "not_expected"),
    [
        ("risk=49.9 does not avoid by risk alone",  60.0,  49.9, 0.10, TIER_AVOID),
        ("score=20.0 does not avoid by score alone", 20.0,  0.0, 0.01, TIER_AVOID),
        ("score=54.9 is not safe",                  54.9,  20.0, 0.01, TIER_SAFE),
        ("risk=20.1 is not safe",                   55.0,  20.1, 0.01, TIER_SAFE),
        ("xgi=0.069 is not upside",                 45.0,  25.0, 0.069, TIER_UPSIDE),
        ("score=44.9 is not upside",                44.9,  25.0, 0.10, TIER_UPSIDE),
        ("risk=25.1 is not upside",                 45.0,  25.1, 0.10, TIER_UPSIDE),
        ("score=29.9 is not differential",          29.9,  30.0, 0.01, TIER_DIFFERENTIAL),
        ("risk=30.1 is not differential",           30.0,  30.1, 0.01, TIER_DIFFERENTIAL),
    ],
)
def test_threshold_boundaries_negative(label, score, risk, xgi, not_expected):
    assert classify_captain_tier(score, risk, xgi) != not_expected, label


@pytest.mark.parametrize("fixture_difficulty", [None, 1, 5])
def test_fixture_difficulty_is_reserved_and_does_not_change_result(fixture_difficulty):
    """`fixture_difficulty` is accepted but unused in v1 logic."""
    baseline = classify_captain_tier(60.58, 0.0, 0.058)
    assert classify_captain_tier(60.58, 0.0, 0.058, fixture_difficulty) == baseline


# ---------------------------------------------------------------------------
# CAPTAIN_TIER_RULES -- structure, priority ordering, and documented thresholds
# ---------------------------------------------------------------------------

def test_rules_cover_exactly_the_five_tiers():
    assert isinstance(CAPTAIN_TIER_RULES, dict)
    assert set(CAPTAIN_TIER_RULES) == {
        TIER_AVOID, TIER_SAFE, TIER_UPSIDE, TIER_DIFFERENTIAL, TIER_LOW_CONFIDENCE,
    }


@pytest.mark.parametrize(
    ("tier", "priority"),
    [
        (TIER_AVOID, 1),
        (TIER_SAFE, 2),
        (TIER_UPSIDE, 3),
        (TIER_DIFFERENTIAL, 4),
        (TIER_LOW_CONFIDENCE, 5),
    ],
)
def test_rule_priority_ordering(tier, priority):
    """Priority order is load-bearing: rules are applied first-match-wins, so
    `avoid` must outrank `safe` for the injured-but-high-scoring case."""
    assert CAPTAIN_TIER_RULES[tier]["priority"] == priority


@pytest.mark.parametrize(
    ("tier", "key", "value"),
    [
        (TIER_AVOID,        "minutes_risk_min",  50),
        (TIER_AVOID,        "captain_score_max", 20),
        (TIER_SAFE,         "captain_score_min", 55),
        (TIER_SAFE,         "minutes_risk_max",  20),
        (TIER_UPSIDE,       "captain_score_min", 45),
        (TIER_UPSIDE,       "minutes_risk_max",  25),
        (TIER_UPSIDE,       "xgi_per_90_min",    0.07),
        (TIER_DIFFERENTIAL, "captain_score_min", 30),
        (TIER_DIFFERENTIAL, "minutes_risk_max",  30),
    ],
)
def test_documented_thresholds(tier, key, value):
    assert CAPTAIN_TIER_RULES[tier]["thresholds"][key] == value


def test_low_confidence_is_the_unconditional_catch_all():
    assert CAPTAIN_TIER_RULES[TIER_LOW_CONFIDENCE]["thresholds"] == {}


@pytest.mark.parametrize("tier", ["avoid", "safe", "upside", "differential", "low_confidence"])
def test_every_rule_has_a_description(tier):
    description = CAPTAIN_TIER_RULES[tier].get("description")
    assert isinstance(description, str) and description


# ---------------------------------------------------------------------------
# Tier vocabulary
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("constant", "value"),
    [
        (TIER_SAFE, "safe"),
        (TIER_UPSIDE, "upside"),
        (TIER_DIFFERENTIAL, "differential"),
        (TIER_AVOID, "avoid"),
        (TIER_LOW_CONFIDENCE, "low_confidence"),
    ],
)
def test_tier_constant_values(constant, value):
    assert constant == value


def test_all_tiers_is_a_deduplicated_tuple_of_five():
    assert isinstance(ALL_TIERS, tuple)
    assert len(ALL_TIERS) == 5
    assert len(set(ALL_TIERS)) == 5
    assert set(ALL_TIERS) == {
        TIER_SAFE, TIER_UPSIDE, TIER_DIFFERENTIAL, TIER_AVOID, TIER_LOW_CONFIDENCE,
    }


@pytest.mark.parametrize("not_a_tier", ["error", "not_found", "ok", "ambiguous"])
def test_status_values_are_not_tier_values(not_a_tier):
    """Tier and status are separate vocabularies -- a player can resolve fine
    (status=ok) and still be tier=avoid."""
    assert not_a_tier not in ALL_TIERS

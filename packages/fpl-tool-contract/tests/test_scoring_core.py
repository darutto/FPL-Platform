"""Regression: the canonical base scoring-input derivation is null-FDR safe.

Cluster B consolidation. The FPL ``fixture_difficulty_map`` ships a
present-but-null value per team at season launch, so ``int(fdr_map.get(team, 3))``
does not default — it evaluates ``int(None)`` and raises. ``scoring_core`` is the
single null-safe home; ``tools._derive_scoring_inputs_from_element`` is now a thin
wrapper over it.
"""
from __future__ import annotations

from fpl_tool_contract.scoring_core import (
    NEUTRAL_FDR,
    _derive_base_scoring_inputs,
    derive_minutes_context,
)
from fpl_tool_contract.tools import _derive_scoring_inputs_from_element

# form 5.0; 6.0 xGI over 900 min → 0.6 /90; status "a" → risk 0.0; FDR from map.
_ELEMENT = {
    "form": "5.0",
    "minutes": 900,
    "expected_goal_involvements": "6.0",
    "status": "a",
    "team": 7,
}


def test_null_fdr_value_defaults_to_neutral():
    """Present-but-null FDR (season launch) → NEUTRAL_FDR, no TypeError."""
    out = _derive_base_scoring_inputs(_ELEMENT, {7: None})
    assert out["fixture_difficulty"] == NEUTRAL_FDR == 3


def test_missing_fdr_key_defaults_to_neutral():
    """Missing team key → NEUTRAL_FDR (the case the old .get default covered)."""
    out = _derive_base_scoring_inputs(_ELEMENT, {})
    assert out["fixture_difficulty"] == 3


def test_real_fdr_passes_through():
    out = _derive_base_scoring_inputs(_ELEMENT, {7: 2})
    assert out["fixture_difficulty"] == 2


def test_base_frozen_parity_well_formed():
    """Byte-for-byte expected output on a well-formed element (guards the
    behaviour-preserving claim; values frozen from pre-consolidation code)."""
    out = _derive_base_scoring_inputs(_ELEMENT, {7: 2})
    assert out == {
        "form": 5.0,
        "xgi_per_90": 0.6,
        "minutes_risk": 0.0,
        "fixture_difficulty": 2,
    }


def test_doubtful_uses_chance_of_playing():
    """The status="d" + chance_of_playing branch is preserved."""
    el = {**_ELEMENT, "status": "d", "chance_of_playing_this_round": 75}
    out = _derive_base_scoring_inputs(el, {7: 2})
    assert out["minutes_risk"] == 25.0  # (1 - 75/100) * 100


def test_tools_wrapper_null_fdr_four_keys_no_crash():
    """tools wrapper preserves its 4-key contract and is now null-safe."""
    out = _derive_scoring_inputs_from_element(
        _ELEMENT, {"fixture_difficulty_map": {7: None}}
    )
    assert set(out.keys()) == {"form", "xgi_per_90", "minutes_risk", "fixture_difficulty"}
    assert out["fixture_difficulty"] == 3


def test_tools_wrapper_matches_base():
    """The wrapper is exactly the base derivation over the bootstrap's map."""
    bootstrap = {"fixture_difficulty_map": {7: 2}}
    assert _derive_scoring_inputs_from_element(_ELEMENT, bootstrap) == (
        _derive_base_scoring_inputs(_ELEMENT, {7: 2})
    )


def _official_team_fixtures(*rows):
    return {
        7: [
            {
                "gameweek": gameweek,
                "finished": finished,
                "kickoff_time": kickoff,
                "minutes": minutes,
                "official_fixture_context_complete": True,
            }
            for gameweek, finished, kickoff, minutes in rows
        ]
    }


def _minutes_element(**overrides):
    return {
        **_ELEMENT,
        "starts": 2,
        "team_join_date": "2026-07-01",
        **overrides,
    }


def test_real_minutes_distinguish_cherki_from_haaland():
    fixtures = _official_team_fixtures(
        (1, True, "2026-08-15T14:00:00Z", 90),
        (2, True, "2026-08-22T14:00:00Z", 90),
    )
    cherki = derive_minutes_context(
        _minutes_element(minutes=108, starts=1), fixtures
    )
    haaland = derive_minutes_context(
        _minutes_element(minutes=180, starts=2), fixtures
    )

    assert cherki["minutes_played"] == 108
    assert cherki["minutes_available"] == 180
    assert cherki["participation_percent"] == 60.0
    assert cherki["minutes_risk"] == 40.0
    assert haaland["participation_percent"] == 100.0
    assert haaland["minutes_risk"] == 0.0


def test_injured_or_suspended_status_wins_over_high_participation():
    fixtures = _official_team_fixtures(
        (1, True, "2026-08-15T14:00:00Z", 90),
        (2, True, "2026-08-22T14:00:00Z", 90),
    )
    for status in ("i", "s"):
        context = derive_minutes_context(
            _minutes_element(minutes=180, status=status), fixtures
        )
        assert context["participation_risk"] == 0.0
        assert context["availability_risk"] == 100.0
        assert context["minutes_risk"] == 100.0


def test_zero_completed_fixtures_does_not_divide_or_penalize():
    fixtures = _official_team_fixtures(
        (1, False, "2026-08-15T14:00:00Z", 0),
    )
    context = derive_minutes_context(_minutes_element(minutes=0, starts=0), fixtures)

    assert context["minutes_risk"] == 0.0
    assert context["participation_percent"] is None
    assert context["degraded"] is True
    assert context["degradation_reason"] == "no_completed_fixtures_since_join"


def test_recent_signing_uses_only_fixtures_since_team_join_date():
    fixtures = _official_team_fixtures(
        (1, True, "2026-08-10T14:00:00Z", 90),
        (2, True, "2026-08-20T14:00:00Z", 90),
    )
    context = derive_minutes_context(
        _minutes_element(
            minutes=90,
            starts=1,
            team_join_date="2026-08-15",
        ),
        fixtures,
    )

    assert context["minutes_available"] == 90
    assert context["fixtures_available"] == 1
    assert context["participation_percent"] == 100.0
    assert context["minutes_risk"] == 0.0


def test_denominator_counts_doubles_and_rescheduled_kickoffs_not_gw_numbers():
    fixtures = _official_team_fixtures(
        (1, True, "2026-08-10T14:00:00Z", 90),  # before signing: excluded
        (1, True, "2026-08-16T14:00:00Z", 90),  # same GW double: counted
        # no GW2 row: a blank contributes no invented minutes
        (1, True, "2026-08-20T14:00:00Z", 90),  # postponed GW1: actual date counts
    )
    context = derive_minutes_context(
        _minutes_element(
            minutes=90,
            starts=1,
            team_join_date="2026-08-15",
        ),
        fixtures,
    )

    assert context["minutes_available"] == 180
    assert context["fixtures_available"] == 2
    assert context["participation_percent"] == 50.0
    assert context["minutes_risk"] == 50.0


def test_incomplete_fixture_context_degrades_explicitly_to_status_risk():
    partial = {
        7: [{
            "gameweek": 2,
            "finished": True,
            "kickoff_time": "2026-08-20T14:00:00Z",
            "minutes": 90,
            "official_fixture_context_complete": False,
        }]
    }
    context = derive_minutes_context(
        _minutes_element(minutes=45, status="d", chance_of_playing_this_round=60),
        partial,
    )

    assert context["source"] == "availability_status"
    assert context["degraded"] is True
    assert context["degradation_reason"] == "incomplete_official_fixtures"
    assert context["participation_risk"] is None
    assert context["minutes_risk"] == 40.0

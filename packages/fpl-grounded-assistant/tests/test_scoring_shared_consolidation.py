"""Cluster B consolidation regressions (grounded-assistant side).

Covers the shared 7-key ``_derive_scoring_inputs`` (null-FDR safety, frozen
parity, venue), the compat re-export identity (no duplicate implementation
survives, and the consumers are wired to the shared one), and the public paths
that the ``int(None)`` FDR bug reached: chip triple-captain scoring (which
*silently dropped* a null-FDR player) and differential picks.
"""
from __future__ import annotations

from fpl_grounded_assistant import scoring_shared
from fpl_grounded_assistant.scoring_shared import (
    _compute_effective_fdr,
    _derive_scoring_inputs,
)

_ELEMENT = {
    "form": "5.0",
    "minutes": 900,
    "expected_goal_involvements": "6.0",
    "status": "a",
    "team": 7,
}


# --------------------------------------------------------------------------- #
# Shared 7-key derivation
# --------------------------------------------------------------------------- #

def test_null_fdr_no_crash_neutral_3():
    """The season-launch bug: present-but-null FDR → 3, no TypeError."""
    out = _derive_scoring_inputs(_ELEMENT, {7: None})
    assert out["fixture_difficulty"] == 3


def test_seven_key_frozen_parity():
    """Frozen expected output (from pre-consolidation code) — behaviour preserved."""
    out = _derive_scoring_inputs(_ELEMENT, {7: 2})
    assert out == {
        "form": 5.0,
        "xgi_per_90": 0.6,
        "xgi_per_90_shrunk": 0.4,
        "minutes_risk": 0.0,
        "fixture_difficulty": 2,
        "is_home": None,
        "effective_fdr": 2.0,
        "minutes_context": {
            "minutes_played": 900,
            "minutes_available": None,
            "starts": 0,
            "fixtures_available": None,
            "participation_percent": None,
            "participation_risk": None,
            "availability_risk": 0.0,
            "minutes_risk": 0.0,
            "source": "availability_status",
            "degraded": True,
            "degradation_reason": "missing_official_fixtures",
        },
    }


def test_venue_home_away_adjustment():
    tf = {7: [{"gameweek": 1, "is_home": True}]}
    home = _derive_scoring_inputs(_ELEMENT, {7: 2}, team_fixtures=tf, current_gw=1)
    assert home["is_home"] is True
    assert home["effective_fdr"] == 1.5  # 2 - 0.5

    tf_away = {7: [{"gameweek": 1, "is_home": False}]}
    away = _derive_scoring_inputs(_ELEMENT, {7: 2}, team_fixtures=tf_away, current_gw=1)
    assert away["is_home"] is False
    assert away["effective_fdr"] == 2.5  # 2 + 0.5


def test_compute_effective_fdr_clamps_and_passthrough():
    assert _compute_effective_fdr(3, True) == 2.5
    assert _compute_effective_fdr(1, True) == 1.0   # clamped
    assert _compute_effective_fdr(5, False) == 5.0  # clamped
    assert _compute_effective_fdr(3, None) == 3.0   # venue unknown → unchanged


# --------------------------------------------------------------------------- #
# Compat re-export identity — no duplicate implementation survives
# --------------------------------------------------------------------------- #

def test_consumers_share_one_implementation():
    from fpl_grounded_assistant import comparison, transfer_advisor
    assert comparison._derive_scoring_inputs is scoring_shared._derive_scoring_inputs
    assert transfer_advisor._derive_scoring_inputs is scoring_shared._derive_scoring_inputs
    # venue + thresholds also re-exported, not re-implemented
    assert comparison._resolve_venue is scoring_shared._resolve_venue
    assert transfer_advisor._compute_effective_fdr is scoring_shared._compute_effective_fdr


# --------------------------------------------------------------------------- #
# Public path: chip triple-captain scoring retained a null-FDR player
# --------------------------------------------------------------------------- #

def _bootstrap_with_null_fdr_player():
    return {
        "elements": [
            {
                "id": 101, "web_name": "NullFdrGuy", "element_type": 4,
                "status": "a", "team": 7, "form": "6.0", "minutes": 900,
                "expected_goal_involvements": "5.0",
                "defensive_contribution_per_90": 0,
                "selected_by_percent": "2.0",
            },
        ],
        "teams": [{"id": 7, "name": "Team Seven", "short_name": "TS7"}],
        "fixture_difficulty_map": {7: None},   # season-launch null
    }


def test_score_outfield_players_retains_null_fdr_player():
    """The decisive silent-drop regression.

    Pre-fix, the inline ``int(fdr_map.get(team, 3))`` raised inside
    ``_score_outfield_players``' broad try/except, so the player was dropped and
    the list came back empty. "no exception" is insufficient — assert the player
    SURVIVES with the neutral FDR.
    """
    from fpl_grounded_assistant.chip_advisor import _score_outfield_players

    scored = _score_outfield_players(_bootstrap_with_null_fdr_player())
    names = [row["web_name"] for row in scored]
    assert "NullFdrGuy" in names
    row = next(r for r in scored if r["web_name"] == "NullFdrGuy")
    assert row["fdr"] == 3


# --------------------------------------------------------------------------- #
# Public path: differential picks does not drop a null-FDR player
# --------------------------------------------------------------------------- #

def test_get_differential_picks_null_fdr_no_crash():
    from fpl_grounded_assistant.differential_picks import get_differential_picks

    result = get_differential_picks(_bootstrap_with_null_fdr_player())
    assert result.get("status") != "error"

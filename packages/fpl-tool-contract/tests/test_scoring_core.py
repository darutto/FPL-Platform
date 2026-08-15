"""Regression: the canonical base scoring-input derivation is null-FDR safe.

Cluster B consolidation. The FPL ``fixture_difficulty_map`` ships a
present-but-null value per team at season launch, so ``int(fdr_map.get(team, 3))``
does not default — it evaluates ``int(None)`` and raises. ``scoring_core`` is the
single null-safe home; ``tools._derive_scoring_inputs_from_element`` is now a thin
wrapper over it.
"""
from __future__ import annotations

from fpl_tool_contract.scoring_core import NEUTRAL_FDR, _derive_base_scoring_inputs
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

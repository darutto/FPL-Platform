"""Public surface guard for `fpl_captain_engine`.

Replaces the shim-export sections of the retired Phase 2g/2h runners. Those
asserted that symbols imported through `fpl_captain_engine` were the *same
objects* as those in the old sibling `python/` package. That shim is gone (see
PR #68), so the identity checks are meaningless -- but the underlying intent
(the package exposes a stable, complete public surface) is still worth pinning.
"""

from __future__ import annotations

import pytest

import fpl_captain_engine


_EXPECTED_SURFACE = {
    # captain_score
    "CaptainCandidate",
    "calculate_captain_score",
    "update_captain_scores",
    # tier_classifier
    "Tier",
    "TieredRecommendation",
    "TierClassifier",
    "TieredCaptainSelector",
    "TIER_CRITERIA",
    # captain_tiers (Phase 5m)
    "classify_captain_tier",
    "TIER_SAFE",
    "TIER_UPSIDE",
    "TIER_DIFFERENTIAL",
    "TIER_AVOID",
    "TIER_LOW_CONFIDENCE",
    "ALL_TIERS",
    "CAPTAIN_TIER_RULES",
    # role_evaluator (Phase 5m)
    "derive_role_signals",
    "compute_role_bonus",
    "ROLE_BONUS_MAP",
}


def test_all_matches_expected_surface():
    assert set(fpl_captain_engine.__all__) == _EXPECTED_SURFACE


@pytest.mark.parametrize("name", sorted(_EXPECTED_SURFACE))
def test_every_exported_name_is_importable(name):
    assert hasattr(fpl_captain_engine, name), f"missing export: {name}"


def test_package_does_not_depend_on_a_bare_python_module():
    """Regression guard for the collision fixed in PR #68.

    The package used to reach its implementation through the bare top-level
    name `python`, which three other packages also shipped -- so which one won
    was import-order luck. Importing the engine must not pull in any module
    named `python`.
    """
    import sys

    assert "python" not in sys.modules

    module_file = fpl_captain_engine.__file__ or ""
    assert "fpl_captain_engine" in module_file

"""
fpl_captain_engine
==================
Importable Python package for fpl-captain-engine.

The canonical importable name for the captain engine. Implementation modules
live directly in this package.

Previously the implementation sat in a sibling ``../python/`` directory that
this module re-exported via a ``sys.path`` insertion. That made the engine
depend on the bare top-level name ``python`` resolving to the right directory
-- but three other packages ship a ``python/`` directory too, so which one won
was import-order luck. The modules were moved here to remove that hazard.

Public surface
--------------
    from fpl_captain_engine import calculate_captain_score
    from fpl_captain_engine import CaptainCandidate, update_captain_scores
    from fpl_captain_engine import (
        Tier, TieredRecommendation, TierClassifier,
        TieredCaptainSelector, TIER_CRITERIA,
    )

Source of truth
---------------
    packages/fpl-captain-engine/fpl_captain_engine/captain_score.py
    packages/fpl-captain-engine/fpl_captain_engine/tier_classifier.py

Formula (captain_score.py)
--------------------------
    form_score    = min(max((form / 10) * 100, 0.0), 100.0)
    fixture_score = min(max((6 - fdr) * 20, 0.0), 100.0)   fdr clipped 1-5
    xgi_score     = min(max(xgi_per_90 * 50, 0.0), 100.0)
    minutes_score = min(max(100 - minutes_risk, 0.0), 100.0)
    total = form_score*0.4 + fixture_score*0.3 + xgi_score*0.2 + minutes_score*0.1
    → unrounded; callers apply round(..., 2) for display
"""

from __future__ import annotations

from .captain_score import (
    CaptainCandidate,
    calculate_captain_score,
    update_captain_scores,
)
from .tier_classifier import (
    Tier,
    TieredRecommendation,
    TierClassifier,
    TieredCaptainSelector,
    TIER_CRITERIA,
)
from .captain_tiers import (  # Phase 5m: tier classification
    classify_captain_tier,
    TIER_SAFE,
    TIER_UPSIDE,
    TIER_DIFFERENTIAL,
    TIER_AVOID,
    TIER_LOW_CONFIDENCE,
    ALL_TIERS,
    CAPTAIN_TIER_RULES,
)
from .role_evaluator import (  # Phase 5m: role signals
    derive_role_signals,
    compute_role_bonus,
    ROLE_BONUS_MAP,
)

__all__ = [
    "CaptainCandidate",
    "calculate_captain_score",
    "update_captain_scores",
    "Tier",
    "TieredRecommendation",
    "TierClassifier",
    "TieredCaptainSelector",
    "TIER_CRITERIA",
    # Phase 5m
    "classify_captain_tier",
    "TIER_SAFE",
    "TIER_UPSIDE",
    "TIER_DIFFERENTIAL",
    "TIER_AVOID",
    "TIER_LOW_CONFIDENCE",
    "ALL_TIERS",
    "CAPTAIN_TIER_RULES",
    "derive_role_signals",
    "compute_role_bonus",
    "ROLE_BONUS_MAP",
]
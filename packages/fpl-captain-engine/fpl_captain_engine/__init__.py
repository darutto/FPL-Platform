"""
fpl_captain_engine
==================
Importable Python package for fpl-captain-engine.

This is a thin re-export shim over the source modules in the sibling
``../python/`` directory.  The source modules remain at ``python/`` to
preserve the original layout of the repository; this directory provides
the canonical importable name ``fpl_captain_engine`` that the rest of the
fpl-platform stack expects.

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
    packages/fpl-captain-engine/python/captain_score.py
    packages/fpl-captain-engine/python/tier_classifier.py

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

import os as _os
import sys as _sys

# Ensure the sibling ``python/`` package is importable under the name
# ``python`` by putting this package's parent directory on sys.path.
_here   = _os.path.dirname(_os.path.abspath(__file__))
_parent = _os.path.dirname(_here)   # packages/fpl-captain-engine/
if _parent not in _sys.path:
    _sys.path.insert(0, _parent)

# Re-export the canonical captain-engine public surface
from python import (  # noqa: E402  (import not at top of file)
    CaptainCandidate,
    calculate_captain_score,
    update_captain_scores,
    Tier,
    TieredRecommendation,
    TierClassifier,
    TieredCaptainSelector,
    TIER_CRITERIA,
    # Phase 5m: tier classification
    classify_captain_tier,
    TIER_SAFE,
    TIER_UPSIDE,
    TIER_DIFFERENTIAL,
    TIER_AVOID,
    TIER_LOW_CONFIDENCE,
    ALL_TIERS,
    CAPTAIN_TIER_RULES,
    # Phase 5m: role signals
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
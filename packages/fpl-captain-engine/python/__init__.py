"""fpl-captain-engine Python package."""

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
from .captain_tiers import (  # Phase 5m
    classify_captain_tier,
    TIER_SAFE,
    TIER_UPSIDE,
    TIER_DIFFERENTIAL,
    TIER_AVOID,
    TIER_LOW_CONFIDENCE,
    ALL_TIERS,
    CAPTAIN_TIER_RULES,
)
from .role_evaluator import (  # Phase 5m
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
    # Phase 5m: tier classification
    "classify_captain_tier",
    "TIER_SAFE",
    "TIER_UPSIDE",
    "TIER_DIFFERENTIAL",
    "TIER_AVOID",
    "TIER_LOW_CONFIDENCE",
    "ALL_TIERS",
    "CAPTAIN_TIER_RULES",
    # Phase 5m: role signals
    "derive_role_signals",
    "compute_role_bonus",
    "ROLE_BONUS_MAP",
]



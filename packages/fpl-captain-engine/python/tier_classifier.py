"""
fpl-captain-engine · packages/fpl-captain-engine/python/tier_classifier.py
===========================================================================
Tier classification for captain candidates (Premium / Differential / Outlier).

SOURCE:  Promoted directly from:
  - captaincy-ml/phase4_tiered_recommendations.py
    • TierClassifier class    (lines ~50-120)
    • TieredRecommendation    (lines ~20-48)
    • TIER_CRITERIA constants

REPLACES (do NOT delete originals until migration is approved):
  - captaincy-ml/phase4_tiered_recommendations.py::TierClassifier

CONSUMERS AFTER MIGRATION:
  - captaincy-ml/phase4_tiered_recommendations.py → import from here
  - fpl-platform/apps/fpl-chat
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple

from .captain_score import CaptainCandidate

Tier = Literal["premium", "differential", "outlier"]

# ---------------------------------------------------------------------------
# TieredRecommendation  (SOURCE: phase4_tiered_recommendations.py lines 20-48)
# ---------------------------------------------------------------------------

@dataclass
class TieredRecommendation:
    """Captain recommendation with tier classification.

    SOURCE: captaincy-ml/phase4_tiered_recommendations.py::TieredRecommendation
    """
    player_id: int
    player_name: str
    position: str
    team: str
    predicted_points: float
    ownership_percentage: float
    tier: Tier
    tier_rank: int           # Rank within tier (1-5 premium, 1-3 differential, 1-2 outlier)
    differential_score: float
    risk_score: float
    ceiling_score: float
    floor_score: float
    strategy_rationale: str
    confidence_level: str    # HIGH | MEDIUM | LOW
    tier_justification: str


# ---------------------------------------------------------------------------
# Tier criteria  (SOURCE: phase4_tiered_recommendations.py::TierClassifier.__init__)
# ---------------------------------------------------------------------------

TIER_CRITERIA: Dict[str, Dict] = {
    "premium": {
        "ownership_min":   15.0,
        "risk_max":         1.2,
        "floor_min":        4.0,
        "description":      "Safe, reliable, high-ownership picks",
    },
    "differential": {
        "ownership_min":    5.0,
        "ownership_max":   25.0,
        "risk_min":         0.8,
        "risk_max":         2.0,
        "ceiling_min":     12.0,
        "description":      "Medium-risk, medium-ownership outperformers",
    },
    "outlier": {
        "ownership_max":    8.0,
        "ceiling_min":     15.0,
        "description":      "High-risk, low-ownership wildcard options",
    },
}

# ---------------------------------------------------------------------------
# TierClassifier  (SOURCE: phase4_tiered_recommendations.py::TierClassifier)
# ---------------------------------------------------------------------------

class TierClassifier:
    """Classify CaptainCandidates into premium / differential / outlier tiers.

    SOURCE: captaincy-ml/phase4_tiered_recommendations.py::TierClassifier
            Import path changes only.
    """

    def classify(self, candidate: CaptainCandidate) -> Tuple[Optional[Tier], str]:
        """Return (tier, justification) for a candidate, or (None, reason) if no tier fits.

        SOURCE: phase4_tiered_recommendations.py::TierClassifier.classify
        """
        ownership = candidate.ownership
        risk = candidate.minutes_risk / 100.0  # normalise to 0-2 scale proxy
        # Ceiling/floor proxy: use xGI × form as a rough ceiling
        ceiling = candidate.xgi_per_90 * candidate.form_score
        floor = candidate.captain_score * 0.4  # conservative floor estimate

        # Premium
        pc = TIER_CRITERIA["premium"]
        if (ownership >= pc["ownership_min"]
                and risk <= pc["risk_max"]
                and floor >= pc["floor_min"]):
            return "premium", (
                f"Owned by {ownership:.1f}% (≥{pc['ownership_min']}%), "
                f"risk {risk:.2f} (≤{pc['risk_max']}), "
                f"floor estimate {floor:.1f} (≥{pc['floor_min']})"
            )

        # Differential
        dc = TIER_CRITERIA["differential"]
        if (dc["ownership_min"] <= ownership <= dc["ownership_max"]
                and dc["risk_min"] <= risk <= dc["risk_max"]
                and ceiling >= dc["ceiling_min"]):
            return "differential", (
                f"Owned by {ownership:.1f}% (range {dc['ownership_min']}-{dc['ownership_max']}%), "
                f"ceiling {ceiling:.1f} (≥{dc['ceiling_min']})"
            )

        # Outlier
        oc = TIER_CRITERIA["outlier"]
        if ownership <= oc["ownership_max"] and ceiling >= oc["ceiling_min"]:
            return "outlier", (
                f"Owned by only {ownership:.1f}% (≤{oc['ownership_max']}%), "
                f"ceiling {ceiling:.1f} (≥{oc['ceiling_min']})"
            )

        return None, f"No tier: ownership={ownership:.1f}%, ceiling={ceiling:.1f}"


# ---------------------------------------------------------------------------
# TieredCaptainSelector
# ---------------------------------------------------------------------------

class TieredCaptainSelector:
    """Produce 10-player tiered captain recommendations.

    Output:  5 Premium + 3 Differential + 2 Outlier
    SOURCE:  captaincy-ml/phase4_tiered_recommendations.py::TieredCaptainSelector
    """

    TIER_SIZES: Dict[Tier, int] = {
        "premium":      5,
        "differential": 3,
        "outlier":      2,
    }

    def __init__(self) -> None:
        self.classifier = TierClassifier()

    def select(self, candidates: List[CaptainCandidate]) -> List[TieredRecommendation]:
        """Return up to 10 tiered recommendations sorted by tier then score.

        SOURCE: captaincy-ml/phase4_tiered_recommendations.py::TieredCaptainSelector.select
        """
        tiered: Dict[Tier, List[Tuple[CaptainCandidate, str]]] = {
            "premium": [], "differential": [], "outlier": [],
        }

        for c in sorted(candidates, key=lambda x: x.captain_score, reverse=True):
            tier, justification = self.classifier.classify(c)
            if tier is None:
                continue
            bucket = tiered[tier]
            if len(bucket) < self.TIER_SIZES[tier]:
                bucket.append((c, justification))

        results: List[TieredRecommendation] = []
        for tier_name, items in tiered.items():
            for rank, (c, justification) in enumerate(items, start=1):
                results.append(TieredRecommendation(
                    player_id=c.player_id,
                    player_name=c.name,
                    position=c.position,
                    team=c.team,
                    predicted_points=c.captain_score,
                    ownership_percentage=c.ownership,
                    tier=tier_name,
                    tier_rank=rank,
                    differential_score=c.ownership,
                    risk_score=c.minutes_risk / 100.0,
                    ceiling_score=c.xgi_per_90 * c.form_score,
                    floor_score=c.captain_score * 0.4,
                    strategy_rationale=TIER_CRITERIA[tier_name]["description"],
                    confidence_level=(
                        "HIGH" if c.captain_score >= 70
                        else "MEDIUM" if c.captain_score >= 45
                        else "LOW"
                    ),
                    tier_justification=justification,
                ))

        return results



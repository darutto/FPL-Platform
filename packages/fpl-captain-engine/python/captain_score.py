"""
fpl-captain-engine · packages/fpl-captain-engine/python/captain_score.py
=========================================================================
Python implementation of the canonical captain scoring formula.

SOURCE:  Python port of:
  - captaincy-showdown/src/engine/captainScore.ts (full file — lines 1-50)
    • calculateCaptainScore() function
    • updateCaptainScores() function
  Also referenced by:
  - captaincy-ml/phase4_tiered_recommendations.py  (TierClassifier uses separate scoring)

REPLACES (do NOT delete originals until migration is approved):
  - There is no Python equivalent yet; this is a NEW file porting the TS formula.
  - captaincy-ml should import this instead of reimplementing scoring locally.

CONSUMERS AFTER MIGRATION:
  - captaincy-ml/phase4_tiered_recommendations.py
  - fpl-platform/apps/fpl-chat (tool: rank_captain_candidates)
  - Any future Python captaincy scripts

SCORE WEIGHTS  (canonical — matches captainScore.ts exactly):
  form      40%
  fixture   30%
  xGI/90    20%
  minutes   10%
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Data model  (Python mirror of captaincy-showdown/src/types/index.ts)
# ---------------------------------------------------------------------------

@dataclass
class CaptainCandidate:
    """Python equivalent of TypeScript CaptainCandidate interface.

    SOURCE: captaincy-showdown/src/types/index.ts (lines 1-16)
    """
    player_id: int
    name: str
    team: str
    position: str            # GKP | DEF | MID | FWD
    price: float             # now_cost / 10
    ownership: float         # selected_by_percent as float
    expected_ownership: float
    form_score: float        # Last 4 GW average points
    fixture_difficulty: int  # 1-5 (opponent strength)
    minutes_risk: float      # 0-100 (higher = more risky)
    xgi_per_90: float        # Expected goal involvements per 90
    captain_score: float = field(default=0.0)
    opponent: str | None = None
    home: bool | None = None


# ---------------------------------------------------------------------------
# Scoring formula  (exact port of captainScore.ts)
# ---------------------------------------------------------------------------

def calculate_captain_score(
    form: float,
    fixture_difficulty: int,
    xgi_per_90: float,
    minutes_risk: float,
) -> float:
    """Calculate a composite captain score from 0 to 100.

    Weights:
        form          40%  (normalised to 0-100: form/10 × 100)
        fixture       30%  (normalised to 0-100: (6-diff) × 20)
        xGI/90        20%  (normalised to 0-100: xgi × 50, capped at 100)
        minutes risk  10%  (normalised to 0-100: 100 - risk)

    SOURCE: captaincy-showdown/src/engine/captainScore.ts::calculateCaptainScore (lines 19-35)
            — direct Python port, identical maths.
    """
    # Normalise each metric to 0-100
    form_score    = min(max((form / 10) * 100, 0.0), 100.0)
    diff          = min(max(fixture_difficulty, 1), 5)
    fixture_score = min(max((6 - diff) * 20, 0.0), 100.0)
    xgi_score     = min(max(xgi_per_90 * 50, 0.0), 100.0)
    minutes_score = min(max(100 - minutes_risk, 0.0), 100.0)

    total = (
        form_score    * 0.4
        + fixture_score * 0.3
        + xgi_score     * 0.2
        + minutes_score * 0.1
    )
    return min(max(total, 0.0), 100.0)


def update_captain_scores(candidates: List[CaptainCandidate]) -> List[CaptainCandidate]:
    """Set captain_score on each candidate. Returns the same list (mutated).

    SOURCE: captaincy-showdown/src/engine/captainScore.ts::updateCaptainScores (lines 40-50)
    """
    for c in candidates:
        c.captain_score = calculate_captain_score(
            form=c.form_score,
            fixture_difficulty=c.fixture_difficulty,
            xgi_per_90=c.xgi_per_90,
            minutes_risk=c.minutes_risk,
        )
    return candidates
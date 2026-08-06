"""
fpl-captain-engine · packages/fpl-captain-engine/python/captain_tiers.py
=========================================================================
Deterministic tier classification for captain candidates — v1 vocabulary.

This module provides Captain Score v1 tier framing.  It operates entirely
on the four scoring inputs already computed by the canonical
``calculate_captain_score`` formula — no ownership data, no external API
calls, no ML models.

Relationship to existing TierClassifier
----------------------------------------
The existing :class:`TierClassifier` in ``tier_classifier.py`` uses the
vocabulary  premium / differential / outlier  and requires
``ownership_percentage`` as an input.  That classifier is sourced from
``captaincy-ml/phase4_tiered_recommendations.py`` and is preserved
unchanged.

This module introduces a **parallel, simpler** vocabulary:
  safe · upside · differential · avoid · low_confidence

These tiers are:
  * FPL-oriented (intuitive to FPL players)
  * self-contained (no ownership required)
  * deterministic (same inputs → same tier, always)
  * testable (pure function, zero side-effects)

Phase 2g notes
--------------
* Tier labels are constants exported as module-level strings for safety
  (use the constants, not bare strings, in conditional logic).
* ``CAPTAIN_TIER_RULES`` documents every threshold so tests can verify
  correctness without hardcoding magic numbers.
* ``classify_captain_tier`` uses priority ordering (first match wins).

Tier vocabulary & rules
------------------------
Priority order is highest to lowest (first match wins):

``avoid``
    ``minutes_risk >= 50`` OR ``captain_score < 20``
    High rotation / injury risk, or too low a composite score to captain.

``safe``
    ``captain_score >= 55`` AND ``minutes_risk <= 20``
    High composite score + almost certain to start.  Reliable captain pick.
    (Does not require explosive xGI — pure score + availability.)

``upside``
    ``captain_score >= 45`` AND ``minutes_risk <= 25`` AND ``xgi_per_90 >= 0.07``
    Strong attacker who starts most weeks.  High ceiling relative to score.

``differential``
    ``captain_score >= 30`` AND ``minutes_risk <= 30``
    Reasonable pick; lower ceiling / expectation than safe/upside.
    Often a player with partial risk or a harder fixture.

``low_confidence``
    Catch-all — mixed signals, moderate risk, or insufficient score for
    a clear recommendation.

Examples from Phase 2d test data (GW28):
    Salah      (60.58, risk=0,   xgi=0.058) → safe          [high score + starter]
    Haaland    (54.85, risk=0,   xgi=0.085) → upside        [just below safe, but big xGI]
    Saka       (36.35, risk=25,  xgi=0.085) → differential  [decent score, doubtful start]
    De Bruyne  (14.0,  risk=100, xgi=0.200) → avoid         [injured, risk=100]
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Tier label constants
# ---------------------------------------------------------------------------

TIER_SAFE           = "safe"
TIER_UPSIDE         = "upside"
TIER_DIFFERENTIAL   = "differential"
TIER_AVOID          = "avoid"
TIER_LOW_CONFIDENCE = "low_confidence"

ALL_TIERS: tuple[str, ...] = (
    TIER_SAFE,
    TIER_UPSIDE,
    TIER_DIFFERENTIAL,
    TIER_AVOID,
    TIER_LOW_CONFIDENCE,
)

# ---------------------------------------------------------------------------
# Tier rule documentation
# ---------------------------------------------------------------------------

CAPTAIN_TIER_RULES: dict[str, dict[str, Any]] = {
    TIER_AVOID: {
        "priority":    1,
        "conditions":  "minutes_risk >= 50  OR  captain_score < 20",
        "description": (
            "Avoid captaining — high rotation/injury risk or very low "
            "expected return.  Do not captain this player."
        ),
        "thresholds": {
            "minutes_risk_min":   50.0,   # >= triggers avoid
            "captain_score_max":  20.0,   # <  triggers avoid
        },
    },
    TIER_SAFE: {
        "priority":    2,
        "conditions":  "captain_score >= 55  AND  minutes_risk <= 20",
        "description": (
            "Reliable captain pick — high composite score and almost certain "
            "to start.  Consistent, low-variance choice."
        ),
        "thresholds": {
            "captain_score_min":  55.0,   # >=
            "minutes_risk_max":   20.0,   # <=
        },
    },
    TIER_UPSIDE: {
        "priority":    3,
        "conditions":  (
            "captain_score >= 45  AND  minutes_risk <= 25  "
            "AND  xgi_per_90 >= 0.07"
        ),
        "description": (
            "Explosive ceiling — strong attacker who starts most weeks.  "
            "Good upside but may not be the 'safest' captain pick."
        ),
        "thresholds": {
            "captain_score_min":  45.0,   # >=
            "minutes_risk_max":   25.0,   # <=
            "xgi_per_90_min":      0.07,  # >=
        },
    },
    TIER_DIFFERENTIAL: {
        "priority":    4,
        "conditions":  "captain_score >= 30  AND  minutes_risk <= 30",
        "description": (
            "Reasonable differential — decent expected return with "
            "acceptable rotation/injury risk.  Lower expectation than "
            "safe or upside options."
        ),
        "thresholds": {
            "captain_score_min":  30.0,   # >=
            "minutes_risk_max":   30.0,   # <=
        },
    },
    TIER_LOW_CONFIDENCE: {
        "priority":    5,
        "conditions":  "catch-all",
        "description": (
            "Mixed signals — moderate risk, low score, or ambiguous context.  "
            "Does not fit any clear captain recommendation tier."
        ),
        "thresholds": {},
    },
}


# ---------------------------------------------------------------------------
# Classification function
# ---------------------------------------------------------------------------

def classify_captain_tier(
    captain_score: float,
    minutes_risk: float,
    xgi_per_90: float,
    fixture_difficulty: int | None = None,  # reserved for future rule expansion
) -> str:
    """Return a tier label for a captain candidate.

    Applies tier rules in priority order; returns the first match.

    Parameters
    ----------
    captain_score:
        Composite captain score (0–100), as returned by
        ``calculate_captain_score`` / ``tool_get_captain_score``.
    minutes_risk:
        Rotation / injury risk (0–100).  0 = certain starter; 100 = out.
    xgi_per_90:
        Expected goal involvements per 90 minutes.
    fixture_difficulty:
        FDR 1–5 (1 = easiest, 5 = hardest).  Currently reserved for
        future rule expansion — not used in v1 tier logic.

    Returns
    -------
    str
        One of: ``"safe"``, ``"upside"``, ``"differential"``,
        ``"avoid"``, ``"low_confidence"``.

    Examples
    --------
    >>> classify_captain_tier(60.58, 0.0, 0.058)   # Salah-like
    'safe'
    >>> classify_captain_tier(54.85, 0.0, 0.085)   # Haaland-like
    'upside'
    >>> classify_captain_tier(36.35, 25.0, 0.085)  # Saka-like
    'differential'
    >>> classify_captain_tier(14.0, 100.0, 0.200)  # De Bruyne injured
    'avoid'
    """
    rules = CAPTAIN_TIER_RULES

    # Priority 1 — avoid
    _avoid = rules[TIER_AVOID]["thresholds"]
    if minutes_risk >= _avoid["minutes_risk_min"] or captain_score < _avoid["captain_score_max"]:
        return TIER_AVOID

    # Priority 2 — safe
    _safe = rules[TIER_SAFE]["thresholds"]
    if captain_score >= _safe["captain_score_min"] and minutes_risk <= _safe["minutes_risk_max"]:
        return TIER_SAFE

    # Priority 3 — upside
    _up = rules[TIER_UPSIDE]["thresholds"]
    if (captain_score >= _up["captain_score_min"]
            and minutes_risk <= _up["minutes_risk_max"]
            and xgi_per_90 >= _up["xgi_per_90_min"]):
        return TIER_UPSIDE

    # Priority 4 — differential
    _diff = rules[TIER_DIFFERENTIAL]["thresholds"]
    if captain_score >= _diff["captain_score_min"] and minutes_risk <= _diff["minutes_risk_max"]:
        return TIER_DIFFERENTIAL

    # Priority 5 — low_confidence (catch-all)
    return TIER_LOW_CONFIDENCE
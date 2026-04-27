"""
fpl_grounded_assistant.position_score
======================================
Phase 8a1: Position-aware heuristic evaluation layer.

Replaces the Phase 8a additive ``position_bias`` with a cleaner architecture
that defines scoring components per position upfront.  Each position gets its
own weight profile over shared normalised components (all 0--100).

Three-layer scoring architecture
---------------------------------
Layer 1 — ``captain_score`` (canonical, frozen, in fpl-captain-engine).
Layer 2 — ``position_score`` (this module, heuristic, ``weights_override``-ready).
Layer 3 — future ML model (learned weights injected via ``weights_override``).

This module is Layer 2: an **operational heuristic**, not a validated
predictive model.  Cross-position scores are operationally comparable for
ranking and tooling, but equal numeric values across positions do NOT have
fully calibrated equivalent predictive meaning.  True predictive calibration
requires outcome backtesting (Layer 3).

Design rules
------------
* Canonical ``captain_score`` is NEVER modified.
* ``position_score`` is a weighted sum of normalised components (0--100).
* MID profile weights are identical to the canonical formula → zero drift.
* FWD = MID is a transitional simplification, not a final conclusion.
* ``dc_score`` is tracked at every surface but has zero default weight.
  Defensive contribution is an open modeling question requiring backtesting.
* ``weights_override`` enables future ML migration without pipeline changes.

Shared components (all normalised to 0--100)
---------------------------------------------
| Component      | Normalisation                               |
|----------------|---------------------------------------------|
| form_score     | clamp(form / 10 * 100, 0, 100)              |
| fixture_score  | clamp((6 - fdr) * 20, 0, 100)  (fdr=float)  |
| xgi_score      | clamp(xgi_per_90 * 50, 0, 100)              |
| minutes_score  | clamp(100 - minutes_risk, 0, 100)           |
| saves_score    | clamp(saves_per_90 / 4.0 * 100, 0, 100)    |
| cs_score       | clamp(cs_per_90 / 0.5 * 100, 0, 100)       |
| dc_score       | clamp(dc_per_90 / 12.0 * 100, 0, 100)      |

Default weight profiles
------------------------
| Component   | GKP  | DEF  | MID  | FWD  |
|-------------|------|------|------|------|
| form        | 0.30 | 0.30 | 0.40 | 0.40 |
| fixture     | 0.20 | 0.25 | 0.30 | 0.30 |
| xgi         | 0.00 | 0.15 | 0.20 | 0.20 |
| minutes     | 0.10 | 0.10 | 0.10 | 0.10 |
| saves       | 0.25 | 0.00 | 0.00 | 0.00 |
| clean_sheet | 0.15 | 0.20 | 0.00 | 0.00 |
| dc          | 0.00 | 0.00 | 0.00 | 0.00 |
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Position weight profiles
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PositionWeights:
    """Weight profile for a single position.  All weights must sum to 1.0."""

    form: float
    fixture: float
    xgi: float
    minutes: float
    saves: float
    clean_sheet: float
    dc: float  # defensive contribution — zero default, tracked for ablation

    def __post_init__(self) -> None:
        total = (
            self.form + self.fixture + self.xgi + self.minutes
            + self.saves + self.clean_sheet + self.dc
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"PositionWeights must sum to 1.0, got {total:.4f}"
            )

    def as_dict(self) -> dict[str, float]:
        return {
            "form": self.form,
            "fixture": self.fixture,
            "xgi": self.xgi,
            "minutes": self.minutes,
            "saves": self.saves,
            "clean_sheet": self.clean_sheet,
            "dc": self.dc,
        }


# Default profiles — MID matches canonical formula exactly (zero drift).
# FWD = MID is a transitional simplification, not a final conclusion.
POSITION_PROFILES: dict[str, PositionWeights] = {
    # 2026-03-28 calibration: saves weight reduced 0.25→0.15 (freed weight into form
    # 0.30→0.40) based on sensitivity analysis showing saves was the dominant
    # overpromotion driver for marginal GKPs.  clean_sheet, fixture, xgi, minutes
    # are unchanged.  Residual risk: high-saves GKPs (saves_per_90 >= 3.0 with
    # competitive form) may still rank in top-5 under this profile.  True
    # calibration for those cases requires outcome backtesting (Layer 3).
    "GKP": PositionWeights(
        form=0.40, fixture=0.20, xgi=0.00, minutes=0.10,
        saves=0.15, clean_sheet=0.15, dc=0.00,
    ),
    "DEF": PositionWeights(
        form=0.30, fixture=0.25, xgi=0.15, minutes=0.10,
        saves=0.00, clean_sheet=0.20, dc=0.00,
    ),
    "MID": PositionWeights(
        form=0.40, fixture=0.30, xgi=0.20, minutes=0.10,
        saves=0.00, clean_sheet=0.00, dc=0.00,
    ),
    "FWD": PositionWeights(
        form=0.40, fixture=0.30, xgi=0.20, minutes=0.10,
        saves=0.00, clean_sheet=0.00, dc=0.00,
    ),
}

# Experimental DEF profile with DC weight — for backtesting only.
# Activate via weights_override, not as default.
DEF_EXPERIMENTAL_PROFILES: dict[str, PositionWeights] = {
    "dc_included": PositionWeights(
        form=0.25, fixture=0.25, xgi=0.10, minutes=0.10,
        saves=0.00, clean_sheet=0.20, dc=0.10,
    ),
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PositionScoreResult:
    """Structured result from ``compute_position_score()``.

    Attributes
    ----------
    position_score:
        Final composite evaluation score (0--100).  Operationally comparable
        across positions for ranking.  Not a calibrated prediction — see
        module docstring.
    components:
        All 7 normalised component scores (0--100), keyed by component name.
        Always present regardless of weight profile, for auditability.
    weights:
        The weight profile that was used (dict form of ``PositionWeights``).
    weighted:
        Each component multiplied by its weight — shows contribution to
        the final score.  Sum equals ``position_score`` (before clamping).
    position_profile:
        Label identifying which profile was used (``"GKP"`` / ``"DEF"`` /
        ``"MID"`` / ``"FWD"`` for defaults, or ``"custom"`` for overrides).
    """

    position_score: float
    components: dict[str, float]
    weights: dict[str, float]
    weighted: dict[str, float]
    position_profile: str


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def compute_position_score(
    position: str,
    form: float,
    fixture_difficulty: float,
    xgi_per_90: float,
    minutes_risk: float,
    saves_per_90: float,
    clean_sheets_per_90: float,
    dc_per_90: float = 0.0,
    *,
    weights_override: PositionWeights | None = None,
) -> PositionScoreResult:
    """Compute a position-aware evaluation score.

    Parameters
    ----------
    position:
        Player position string: ``"GKP"``, ``"DEF"``, ``"MID"``, or ``"FWD"``.
    form:
        FPL form field (last-4-GW average points, 0--10 scale).
    fixture_difficulty:
        FDR rating for the player's next fixture (1.0--5.0, lower = easier).
        Accepts float for home/away adjusted values (Phase 8b ``effective_fdr``).
    xgi_per_90:
        Expected goal involvements per 90 minutes.
    minutes_risk:
        Minutes risk percentage (0 = certain starter, 100 = unavailable).
    saves_per_90:
        Saves per 90 minutes (GKP-exclusive; outfield = 0).
    clean_sheets_per_90:
        Clean sheets per 90 minutes.
    dc_per_90:
        Defensive contribution per 90 minutes.  Zero-weighted by default;
        included for auditability and future ablation.
    weights_override:
        Optional custom weight profile.  When provided, overrides the
        default profile for this position.  Enables Layer 3 (ML) migration
        and experimental profile testing (e.g. DEF with DC weight).

    Returns
    -------
    PositionScoreResult
        Composite score, component breakdown, weights used, and profile label.
    """
    # --- Normalise all components to 0--100 ---
    form_score    = _clamp(form / 10.0 * 100.0,              0.0, 100.0)
    fixture_score = _clamp((6 - fixture_difficulty) * 20.0,  0.0, 100.0)
    xgi_score     = _clamp(xgi_per_90 * 50.0,                0.0, 100.0)
    minutes_score = _clamp(100.0 - minutes_risk,              0.0, 100.0)
    saves_score   = _clamp(saves_per_90 / 4.0 * 100.0,       0.0, 100.0)
    cs_score      = _clamp(clean_sheets_per_90 / 0.5 * 100.0, 0.0, 100.0)
    dc_score_val  = _clamp(dc_per_90 / 12.0 * 100.0,         0.0, 100.0)

    components = {
        "form_score":    round(form_score, 4),
        "fixture_score": round(fixture_score, 4),
        "xgi_score":     round(xgi_score, 4),
        "minutes_score": round(minutes_score, 4),
        "saves_score":   round(saves_score, 4),
        "cs_score":      round(cs_score, 4),
        "dc_score":      round(dc_score_val, 4),
    }

    # --- Select weight profile ---
    pos = position.upper()
    if weights_override is not None:
        profile = weights_override
        profile_label = "custom"
    else:
        profile = POSITION_PROFILES.get(pos, POSITION_PROFILES["MID"])
        profile_label = pos if pos in POSITION_PROFILES else "MID"

    weights_dict = profile.as_dict()

    # --- Weighted sum ---
    weighted = {
        "form":        round(form_score * profile.form, 4),
        "fixture":     round(fixture_score * profile.fixture, 4),
        "xgi":         round(xgi_score * profile.xgi, 4),
        "minutes":     round(minutes_score * profile.minutes, 4),
        "saves":       round(saves_score * profile.saves, 4),
        "clean_sheet": round(cs_score * profile.clean_sheet, 4),
        "dc":          round(dc_score_val * profile.dc, 4),
    }

    raw_score = sum(weighted.values())
    position_score = round(_clamp(raw_score, 0.0, 100.0), 2)

    return PositionScoreResult(
        position_score=position_score,
        components=components,
        weights=weights_dict,
        weighted=weighted,
        position_profile=profile_label,
    )

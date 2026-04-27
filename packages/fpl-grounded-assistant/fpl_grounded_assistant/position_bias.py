"""
fpl_grounded_assistant.position_bias
=====================================
.. deprecated:: Phase 8a1
   Superseded by ``position_score.py`` (Phase 8a1 position-aware heuristic).
   Kept in the tree for side-by-side backtesting comparison against Phase 8a1.
   No active modules import from this file.

Phase 8a: Position-aware captain score adjustment (DEPRECATED).

Computes an additive `position_bias` on top of the canonical captain score.
The canonical formula (form 40% / fixture 30% / xGI/90 20% / minutes 10%)
was calibrated for MID/FWD captaincy.  It structurally suppresses GKP and
DEF scores because the xGI/90 component (20%) is near-zero for those positions.

Design rules
------------
* Canonical `captain_score` is NEVER modified.
* `adjusted_captain_score = clamp(captain_score + position_bias, 0, 100)`.
* All bias inputs are pre-computed by FPL and available directly in the
  bootstrap ``elements`` array — no per-player API calls.
* MID bias is always 0 (canonical formula is calibrated for MID).

Position bias rules (V1_5_ROADMAP.md §8a, verified against GW28 2025-26 live data)
------------------------------------------------------------------------------------

| Position | Bias formula |
|----------|--------------------------------------------------------------|
| GKP      | saves_score × 0.15 + cs_score × 0.10 − xgi_drag × 1.0      |
| DEF      | cs_score × 0.10 − xgi_drag × 0.5                           |
| MID      | 0                                                           |
| FWD      | xgi_score × 0.05                                           |

Normalisation:
    xgi_score   = clamp(xgi_per_90 × 50, 0, 100)     [canonical formula normalisation]
    xgi_drag    = xgi_score × 0.20                     [xGI component weight in canonical]
    saves_score = clamp(saves_per_90 / 4.0 × 100, 0, 100)
    cs_score    = clamp(clean_sheets_per_90 / 0.5 × 100, 0, 100)

Key data findings (GW28 2025-26, players >450 min):
    saves_per_90  — GKP range 1.6–3.6; all outfield = 0.0 (GKP-exclusive signal)
    dc_per_90     — MID median 8.3 > DEF median 7.5 (NOT a DEF bonus)
    cs_per_90     — uniform outfield median ~0.27–0.34 (player-level history signal)
"""
from __future__ import annotations

from typing import Any


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def compute_position_bias(
    position: str,
    element: dict[str, Any],
    xgi_per_90: float,
) -> tuple[float, dict[str, Any]]:
    """Compute an additive position bias for the given player.

    Parameters
    ----------
    position:
        Player position string: ``"GKP"``, ``"DEF"``, ``"MID"``, or ``"FWD"``.
    element:
        Raw FPL bootstrap element dict.  Used to read per-90 fields pre-computed
        by FPL (``saves_per_90``, ``clean_sheets_per_90``,
        ``defensive_contribution_per_90``).  Falls back to 0 when absent.
    xgi_per_90:
        Derived xGI per 90 minutes — the same value supplied to
        ``calculate_captain_score()``.

    Returns
    -------
    tuple[float, dict]
        bias
            Additive correction to add to ``captain_score``.  May be 0 or
            positive; clamping to [0, 100] happens in the caller after
            adding to ``captain_score``.
        bias_inputs
            Transparent signal dict surfaced in ``score_inputs``:
            ``{saves_per_90, clean_sheets_per_90, dc_per_90,
              xgi_score, saves_score, cs_score, xgi_drag}``.
            Exposed for auditability — not used for further calculations.
    """
    saves_per_90 = float(element.get("saves_per_90", 0) or 0)
    cs_per_90    = float(element.get("clean_sheets_per_90", 0) or 0)
    dc_per_90    = float(element.get("defensive_contribution_per_90", 0) or 0)

    # Normalise to 0-100 using the same ceiling as the canonical formula
    xgi_score   = _clamp(xgi_per_90 * 50,          0.0, 100.0)
    saves_score = _clamp(saves_per_90 / 4.0 * 100, 0.0, 100.0)
    cs_score    = _clamp(cs_per_90   / 0.5 * 100,  0.0, 100.0)
    xgi_drag    = xgi_score * 0.20

    pos = position.upper()

    if pos == "GKP":
        bias = saves_score * 0.15 + cs_score * 0.10 - xgi_drag * 1.0
    elif pos == "DEF":
        bias = cs_score * 0.10 - xgi_drag * 0.5
    elif pos == "FWD":
        bias = xgi_score * 0.05
    else:
        # MID (and any unknown position) — canonical formula already calibrated
        bias = 0.0

    return bias, {
        "saves_per_90":         round(saves_per_90, 4),
        "clean_sheets_per_90":  round(cs_per_90,    4),
        "dc_per_90":            round(dc_per_90,    4),
        "xgi_score":            round(xgi_score,    4),
        "saves_score":          round(saves_score,  4),
        "cs_score":             round(cs_score,     4),
        "xgi_drag":             round(xgi_drag,     4),
    }

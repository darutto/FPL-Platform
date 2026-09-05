"""Shared captain-scoring helpers for the grounded-assistant comparison family.

Single home for the helpers that ``comparison.py`` and ``transfer_advisor.py``
used to carry as byte-identical private copies (which had silently diverged on
one point — FDR null-safety). Consumers: ``comparison``, ``transfer_advisor``,
``differential_picks``, ``chip_advisor``.

Layering: the *base* four-value derivation lives one layer down in
``fpl_tool_contract.scoring_core`` (so ``tool_contract.tools`` can share it too).
This module composes on top of it the grounded-assistant-only parts — the
minutes-shrunk rate (``position_score.shrink_rate_by_minutes``) and the
home/away venue adjustment — plus the set-piece / venue / advantage-threshold
presentation helpers, which no lower layer consumes.
"""
from __future__ import annotations

from typing import Any, Mapping

from fpl_tool_contract.scoring_core import (
    _derive_base_scoring_inputs,
    derive_minutes_context,
)

from .position_score import shrink_rate_by_minutes

# ---------------------------------------------------------------------------
# Comparative explainability thresholds (Phase 5d)
# ---------------------------------------------------------------------------

#: Minimum form delta for "stronger form" advantage
_FORM_ADV_THRESHOLD: float = 1.5

#: Minimum FDR difference for "easier fixture" advantage (lower FDR = better)
_FDR_ADV_THRESHOLD: int = 1

#: Minimum xGI/90 delta for "higher xGI output" advantage
_XGI_ADV_THRESHOLD: float = 0.10

#: Minimum minutes_risk delta for "better minutes security" advantage
_RISK_ADV_THRESHOLD: float = 20.0


# ---------------------------------------------------------------------------
# Set-piece labels (Phase 5h) — kept out of renderer.py to avoid coupling
# ---------------------------------------------------------------------------

_SET_PIECE_SHORT: dict[str, str] = {
    "penalty_taker_1":  "pen",
    "penalty_taker_2":  "pen2",
    "freekick_taker_1": "fk",
    "freekick_taker_2": "fk2",
}


def _venue_tag(is_home: bool | None) -> str:
    """Return a short venue suffix for display: 'H', 'A', or ''."""
    if is_home is True:
        return "H"
    if is_home is False:
        return "A"
    return ""


def _set_piece_advantage_phrase(
    better_role: dict[str, Any],
    worse_role: dict[str, Any],
) -> str | None:
    """Return a specific set-piece advantage phrase, or ``None``.

    Fires when ``better_role``'s ``role_bonus`` strictly exceeds
    ``worse_role``'s. Uses ``set_piece_notes`` to label the specific roles
    rather than producing only a generic "set-piece advantage" string.
    ``better_role``/``worse_role`` are ``role_signals`` dicts — the comparison
    winner/loser, or transfer player_in/player_out.

    Examples
    --------
    better=penalty_taker_1, worse=freekick_taker_2 → "set-piece advantage (pen vs fk2)"
    better=penalty_taker_1, worse=[]               → "set-piece advantage (pen)"
    better.role_bonus == worse.role_bonus          → None
    """
    better_bonus = float(better_role.get("role_bonus", 0.0))
    worse_bonus = float(worse_role.get("role_bonus", 0.0))
    if better_bonus <= worse_bonus:
        return None

    better_notes = better_role.get("set_piece_notes", [])
    worse_notes = worse_role.get("set_piece_notes", [])

    if not better_notes:
        # role_bonus set but no notes — generic fallback
        return "set-piece advantage"

    better_label = _SET_PIECE_SHORT.get(better_notes[0], better_notes[0])

    if worse_notes:
        worse_label = _SET_PIECE_SHORT.get(worse_notes[0], worse_notes[0])
        return f"set-piece advantage ({better_label} vs {worse_label})"

    return f"set-piece advantage ({better_label})"


# ---------------------------------------------------------------------------
# Phase 8b: home/away fixture awareness
# ---------------------------------------------------------------------------

#: Home/away FDR adjustment magnitude.
#: Home team gets ``raw_fdr - HOME_FDR_ADJUSTMENT`` (easier at home).
#: Away team gets ``raw_fdr + HOME_FDR_ADJUSTMENT`` (harder away).
#: Net effect on fixture_score: ±10 points (via ``(6 - fdr) * 20``).
HOME_FDR_ADJUSTMENT: float = 0.5


def _resolve_venue(
    team_id: int | None,
    team_fixtures: dict | None,
    current_gw: int | None,
) -> bool | None:
    """Return ``True`` if the team plays at home this GW, ``False`` if away,
    or ``None`` if venue cannot be determined."""
    if team_id is None or team_fixtures is None or current_gw is None:
        return None
    fixtures = team_fixtures.get(team_id)
    if not fixtures:
        return None
    for fix in fixtures:
        if fix.get("gameweek") == current_gw:
            return fix.get("is_home")
    return None


def _compute_effective_fdr(
    raw_fdr: int,
    is_home: bool | None,
) -> float:
    """Apply home/away adjustment to raw FDR.

    Returns a float FDR clamped to [1.0, 5.0].  When ``is_home`` is
    ``None`` (venue unknown), returns ``raw_fdr`` unchanged.
    """
    if is_home is None:
        return float(raw_fdr)
    if is_home:
        return max(1.0, min(5.0, raw_fdr - HOME_FDR_ADJUSTMENT))
    return max(1.0, min(5.0, raw_fdr + HOME_FDR_ADJUSTMENT))


def _derive_scoring_inputs(
    element: dict[str, Any],
    fdr_map: Mapping[int, int | None],
    team_fixtures: dict | None = None,
    current_gw: int | None = None,
) -> dict[str, Any]:
    """Derive captain scoring inputs from a raw FPL bootstrap element.

    Composes the cross-layer base (:func:`scoring_core._derive_base_scoring_inputs`
    — form, xgi_per_90, minutes_risk, fixture_difficulty, null-safe FDR) with the
    grounded-assistant-only additions:

    * ``xgi_per_90_shrunk`` — the minutes-floor-shrunk rate, consumed only by the
      ``position_score`` (Layer 2) branch in ``_score_one``; captain_score / chip
      advice see the RAW ``xgi_per_90``, never the shrinkage.
    * ``is_home`` / ``effective_fdr`` (Phase 8b) — home/away venue resolution and
      adjusted FDR, when ``team_fixtures`` and ``current_gw`` are provided.

    Returns a dict with keys: form, xgi_per_90, xgi_per_90_shrunk, minutes_risk,
    fixture_difficulty, is_home, effective_fdr, minutes_context.
    """
    base = _derive_base_scoring_inputs(element, fdr_map, team_fixtures)
    minutes_context = derive_minutes_context(element, team_fixtures)

    # Recompute the raw (unrounded) per-90 for the shrink, so the shrunk value
    # is byte-identical to the pre-consolidation code (which shrank the unrounded
    # rate). base["xgi_per_90"] is the rounded value returned to callers.
    minutes = float(element.get("minutes", 0) or 0)
    xgi_raw = float(element.get("expected_goal_involvements", "0") or 0)
    xgi_per_90 = (xgi_raw / (minutes / 90.0)) if minutes > 0 else 0.0
    xgi_per_90_shrunk = shrink_rate_by_minutes(xgi_per_90, minutes)

    is_home = _resolve_venue(element.get("team"), team_fixtures, current_gw)
    effective_fdr = _compute_effective_fdr(base["fixture_difficulty"], is_home)

    return {
        "form":               base["form"],
        "xgi_per_90":         base["xgi_per_90"],
        "xgi_per_90_shrunk":  round(xgi_per_90_shrunk, 6),
        "minutes_risk":       base["minutes_risk"],
        "fixture_difficulty": base["fixture_difficulty"],
        "is_home":            is_home,
        "effective_fdr":      round(effective_fdr, 1),
        "minutes_context":    minutes_context,
    }

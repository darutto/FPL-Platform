"""
fpl_grounded_assistant.explainer
=================================
Deterministic captain explanation engine.

Converts structured captain ``raw_output`` dicts (as produced by
``fpl_tool_contract.tools`` after Phase 2h) into short, composable reason
strings.

Design rules
------------
* All logic is threshold-based — no freeform text generation, no LLM.
* Functions are pure (no side-effects, no I/O).
* Thresholds are named module-level constants — importable and testable.
* Reason strings are short noun phrases intended to be composed into
  sentences by the renderer, or passed directly to an LLM as structured
  context in a future phase.
* Non-ok outputs always return an empty list — safety is preserved.

Phase 2j additions
------------------
Threshold constants
    ``FORM_HIGH``, ``FORM_LOW`` — form signal boundaries.
    ``FDR_EASY``, ``FDR_HARD`` — fixture difficulty signal boundaries.
    ``XGI_HIGH``, ``XGI_LOW`` — xGI/90 signal boundaries.
    ``RISK_ROTATION``, ``RISK_HIGH`` — minutes risk signal boundaries.

Display maps
    ``_ROLE_REASON`` — set_piece_notes key → full reason string.
    ``_COMPACT_EXCLUDED`` — reason strings omitted in compact mode because
    they duplicate information already surfaced by the renderer (e.g.
    set-piece suffixes ``· pen``, tier brackets ``[safe]``).

Public functions
    ``explain_captain(raw_output) → list[str]``
        Full reason list for single-player responses.
    ``explain_captain_compact(raw_output, max_reasons=2) → list[str]``
        Filtered, capped reason list for ranked-candidate lines.

Reason ordering (most specific first)
--------------------------------------
1. Role signals (highest positional value — penalty adds 5 effective pts)
2. Form
3. Fixture difficulty
4. xGI/90
5. Minutes risk
6. Tier-level summary (only for differential and low_confidence)

This ordering ensures that when the list is truncated for compact display
the most actionable signals appear first.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Threshold constants — single source of truth, all exported
# ---------------------------------------------------------------------------

#: form >= FORM_HIGH → "Strong recent form"
FORM_HIGH: float = 7.0

#: form < FORM_LOW → "Weak recent form"
FORM_LOW: float = 3.0

#: fixture_difficulty <= FDR_EASY → "Favorable fixture"
FDR_EASY: int = 2

#: fixture_difficulty >= FDR_HARD → "Tough fixture"
FDR_HARD: int = 4

#: xgi_per_90 >= XGI_HIGH → "High attacking involvement"
XGI_HIGH: float = 0.50

#: xgi_per_90 < XGI_LOW → "Weak attacking process"
XGI_LOW: float = 0.15

#: minutes_risk >= RISK_ROTATION (and < RISK_HIGH) → "Rotation risk lowers confidence"
RISK_ROTATION: float = 30.0

#: minutes_risk >= RISK_HIGH → "Significant minutes risk"
RISK_HIGH: float = 50.0

# ---------------------------------------------------------------------------
# Role signal → reason string map (full labels)
# ---------------------------------------------------------------------------

_ROLE_REASON: dict[str, str] = {
    "penalty_taker_1":  "Penalty taker",
    "penalty_taker_2":  "2nd penalty taker",
    "freekick_taker_1": "Free-kick taker",
    "freekick_taker_2": "2nd free-kick taker",
}

# ---------------------------------------------------------------------------
# Compact-mode exclusion set
# ---------------------------------------------------------------------------

#: Reason strings excluded from compact (ranked-list) display because the
#: renderer already surfaces them via set-piece suffix (· pen, · FK) or tier
#: bracket ([safe], [diff]).  Keeping them in the compact list would be noisy.
_COMPACT_EXCLUDED: frozenset[str] = frozenset({
    # Role reasons — already shown as set-piece suffix
    "Penalty taker",
    "2nd penalty taker",
    "Free-kick taker",
    "2nd free-kick taker",
    # Tier-summary reasons — already shown as tier bracket
    "High-upside differential profile",
    "Low-confidence captaincy profile",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def explain_captain(raw_output: dict[str, Any]) -> list[str]:
    """Return deterministic reason strings for a captain ``ok`` output.

    Returns an empty list for non-ok outputs (ambiguous, not_found, error)
    — safe to call unconditionally.

    Reason ordering: role signals → form → fixture → xGI → minutes risk →
    tier-level summary.  See module docstring for full ordering rationale.

    Parameters
    ----------
    raw_output:
        A dict as returned by ``tool_get_captain_score`` or a single
        ``ranked_candidates`` entry from ``tool_rank_captain_candidates``
        (both share the same ok structure).

    Returns
    -------
    list[str]
        Ordered list of short reason phrases.  May be empty when all inputs
        are in the neutral range.  Never raises.
    """
    if raw_output.get("status") != "ok":
        return []

    reasons: list[str] = []

    inputs    = raw_output.get("score_inputs", {})
    tier      = raw_output.get("tier", "")
    role_sigs = raw_output.get("role_signals", {})

    form = inputs.get("form")
    fdr  = inputs.get("fixture_difficulty")
    xgi  = inputs.get("xgi_per_90")
    risk = inputs.get("minutes_risk")

    # ── 1. Role signals ──────────────────────────────────────────────────
    for note in role_sigs.get("set_piece_notes", []):
        label = _ROLE_REASON.get(note)
        if label:
            reasons.append(label)

    # ── 2. Form ──────────────────────────────────────────────────────────
    if isinstance(form, (int, float)):
        if form >= FORM_HIGH:
            reasons.append("Strong recent form")
        elif form < FORM_LOW:
            reasons.append("Weak recent form")

    # ── 3. Fixture difficulty ────────────────────────────────────────────
    if isinstance(fdr, (int, float)):
        if fdr <= FDR_EASY:
            reasons.append("Favorable fixture")
        elif fdr >= FDR_HARD:
            reasons.append("Tough fixture")

    # ── 4. xGI/90 ────────────────────────────────────────────────────────
    if isinstance(xgi, (int, float)):
        if xgi >= XGI_HIGH:
            reasons.append("High attacking involvement")
        elif xgi < XGI_LOW:
            reasons.append("Weak attacking process")

    # ── 5. Minutes risk ──────────────────────────────────────────────────
    if isinstance(risk, (int, float)):
        if risk == 0.0:
            reasons.append("Secure minutes")
        elif RISK_ROTATION <= risk < RISK_HIGH:
            reasons.append("Rotation risk lowers confidence")
        elif risk >= RISK_HIGH:
            reasons.append("Significant minutes risk")

    # ── 6. Tier-level summary (only for non-trivial / diagnostic tiers) ──
    if tier == "differential":
        reasons.append("High-upside differential profile")
    elif tier == "low_confidence":
        reasons.append("Low-confidence captaincy profile")

    return reasons


def explain_captain_compact(
    raw_output: dict[str, Any],
    max_reasons: int = 2,
) -> list[str]:
    """Compact variant of ``explain_captain`` for ranked-list display.

    Excludes reason strings that the renderer already surfaces via other
    mechanisms (set-piece suffix, tier bracket), then caps the result at
    ``max_reasons`` entries.

    Parameters
    ----------
    raw_output:
        Same input as :func:`explain_captain`.
    max_reasons:
        Maximum number of reasons to return (default 2, suitable for
        inline display on a ranked entry line).

    Returns
    -------
    list[str]
        Filtered, capped reason list.  Empty list when nothing to add.
    """
    all_reasons = explain_captain(raw_output)
    filtered = [r for r in all_reasons if r not in _COMPACT_EXCLUDED]
    return filtered[:max_reasons]
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
    ``_ROLE_REASON`` — set_piece_notes key → catalogue key.
    ``_COMPACT_EXCLUDED`` — catalogue keys omitted in compact mode because
    they duplicate information already surfaced by the renderer (e.g.
    set-piece suffixes, tier brackets ``[safe]``). Filtering happens on the
    catalogue *key*, not the localized string -- filtering on the already-
    translated text would silently stop working for any locale other than
    the one the set was written against.

Public functions
    ``explain_captain(raw_output, locale="en") → list[str]``
        Full reason list for single-player responses.
    ``explain_captain_compact(raw_output, locale="en", max_reasons=2) → list[str]``
        Filtered, capped reason list for ranked-candidate lines.

    Both default *locale* to ``"en"``, not the catalogue's ``DEFAULT_LOCALE``
    -- ``comparison.py`` and ``transfer_advisor.py`` call these without a
    locale argument and depend on English reason text for their own
    (tier-2b, out-of-scope) recommendation prose. Only the two F2 renderer
    call sites (``get_captain_score``, ``rank_captain_candidates``) pass
    *locale* explicitly.

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

try:
    from .locale_types import Locale
except ImportError:  # standalone load, mirrors renderer.py's own fallback
    from locale_types import Locale  # type: ignore[no-redef]

try:
    from .catalogue import t
except ImportError:  # standalone load, mirrors renderer.py's own fallback
    from catalogue import t  # type: ignore[no-redef]

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
# Role signal → catalogue key map (full labels)
# ---------------------------------------------------------------------------

_ROLE_REASON: dict[str, str] = {
    "penalty_taker_1":  "captain_reason.penalty_taker",
    "penalty_taker_2":  "captain_reason.penalty_taker_2nd",
    "freekick_taker_1": "captain_reason.freekick_taker",
    "freekick_taker_2": "captain_reason.freekick_taker_2nd",
}

# ---------------------------------------------------------------------------
# Compact-mode exclusion set
# ---------------------------------------------------------------------------

#: Catalogue keys excluded from compact (ranked-list) display because the
#: renderer already surfaces them via set-piece suffix or tier bracket
#: ([safe], [diff]).  Keeping them in the compact list would be noisy.
_COMPACT_EXCLUDED: frozenset[str] = frozenset({
    # Role reasons — already shown as set-piece suffix
    "captain_reason.penalty_taker",
    "captain_reason.penalty_taker_2nd",
    "captain_reason.freekick_taker",
    "captain_reason.freekick_taker_2nd",
    # Tier-summary reasons — already shown as tier bracket
    "captain_reason.tier_differential",
    "captain_reason.tier_low_confidence",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _captain_reason_keys(raw_output: dict[str, Any]) -> list[str]:
    """Return catalogue keys for a captain ``ok`` output, in display order.

    Locale-independent: this is the enumeration step, translation happens
    in the public functions below. Kept separate so compact filtering can
    exclude by key identity rather than by post-translation string match.
    """
    if raw_output.get("status") != "ok":
        return []

    keys: list[str] = []

    inputs    = raw_output.get("score_inputs", {})
    tier      = raw_output.get("tier", "")
    role_sigs = raw_output.get("role_signals", {})

    form = inputs.get("form")
    fdr  = inputs.get("fixture_difficulty")
    xgi  = inputs.get("xgi_per_90")
    risk = inputs.get("minutes_risk")

    # ── 1. Role signals ──────────────────────────────────────────────────
    for note in role_sigs.get("set_piece_notes", []):
        key = _ROLE_REASON.get(note)
        if key:
            keys.append(key)

    # ── 2. Form ──────────────────────────────────────────────────────────
    if isinstance(form, (int, float)):
        if form >= FORM_HIGH:
            keys.append("captain_reason.form_strong")
        elif form < FORM_LOW:
            keys.append("captain_reason.form_weak")

    # ── 3. Fixture difficulty ────────────────────────────────────────────
    if isinstance(fdr, (int, float)):
        if fdr <= FDR_EASY:
            keys.append("captain_reason.fixture_favorable")
        elif fdr >= FDR_HARD:
            keys.append("captain_reason.fixture_tough")

    # ── 4. xGI/90 ────────────────────────────────────────────────────────
    if isinstance(xgi, (int, float)):
        if xgi >= XGI_HIGH:
            keys.append("captain_reason.xgi_high")
        elif xgi < XGI_LOW:
            keys.append("captain_reason.xgi_low")

    # ── 5. Minutes risk ──────────────────────────────────────────────────
    if isinstance(risk, (int, float)):
        if risk == 0.0:
            keys.append("captain_reason.minutes_secure")
        elif RISK_ROTATION <= risk < RISK_HIGH:
            keys.append("captain_reason.minutes_rotation_risk")
        elif risk >= RISK_HIGH:
            keys.append("captain_reason.minutes_significant_risk")

    # ── 6. Tier-level summary (only for non-trivial / diagnostic tiers) ──
    if tier == "differential":
        keys.append("captain_reason.tier_differential")
    elif tier == "low_confidence":
        keys.append("captain_reason.tier_low_confidence")

    return keys


def explain_captain(raw_output: dict[str, Any], locale: Locale = "en") -> list[str]:
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
    locale:
        Defaults to ``"en"`` — see module docstring for why this default
        must not follow the catalogue's ``DEFAULT_LOCALE``.

    Returns
    -------
    list[str]
        Ordered list of short reason phrases.  May be empty when all inputs
        are in the neutral range.  Never raises.
    """
    return [t(key, locale) for key in _captain_reason_keys(raw_output)]


def explain_captain_compact(
    raw_output: dict[str, Any],
    locale: Locale = "en",
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
    locale:
        Defaults to ``"en"`` — same rationale as :func:`explain_captain`.
    max_reasons:
        Maximum number of reasons to return (default 2, suitable for
        inline display on a ranked entry line).

    Returns
    -------
    list[str]
        Filtered, capped reason list.  Empty list when nothing to add.
    """
    keys = [k for k in _captain_reason_keys(raw_output) if k not in _COMPACT_EXCLUDED]
    return [t(key, locale) for key in keys[:max_reasons]]
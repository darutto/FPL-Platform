"""
fpl-captain-engine · packages/fpl-captain-engine/python/role_evaluator.py
==========================================================================
Deterministic role-awareness layer for captain evaluation — Phase 2h.

This module derives **role signals** from the raw FPL bootstrap element dict
and computes a ``role_bonus`` float that can be passed to
``classify_captain_tier`` to produce role-aware tier recommendations.

What are role signals?
----------------------
FPL bootstrap elements include three set-piece order fields:

``penalties_order``
    Integer 1–N, or ``None``.  1 = designated penalty taker for the team.
    Penalty kicks convert at roughly 75–80 % and can significantly inflate a
    captain's haul; being the primary taker (order=1) is a genuine scoring
    uplift over an equivalent player who does not take penalties.

``direct_freekicks_order``
    Integer 1–N, or ``None``.  1 = primary direct free-kick taker.
    Direct FKs are lower-probability scoring events than penalties (≈10–20 %)
    but still represent additional scoring opportunities for the player.

``corners_and_indirect_freekicks_order``
    Integer 1–N, or ``None``.  Reflects delivery/assist involvement.
    Corners → likely assists rather than goals; corner order correlates with
    creativity metrics already captured by ``xgi_per_90``.  Included in
    signals for completeness but **not** used for the role_bonus in v1.

Why role_bonus, not score modification?
----------------------------------------
The canonical captain score formula (form · fixture · xGI/90 · minutes) is
deliberately frozen — it matches the upstream source of truth and is the
single-source formula for all scoring tools.  Changing it would require a
versioned formula bump.

Instead, role signals feed ``role_bonus`` into ``classify_captain_tier`` as an
additive correction applied to the **effective score used for tier
classification only**:

    effective_score = captain_score + role_bonus

The published ``captain_score`` in tool output is never modified.  The
``tier`` field reflects role awareness; ``captain_score`` does not.

This keeps the score formula stable while allowing the recommendation tier
to improve for players who hold high-value set-piece roles — an important
dimension not captured by historical xGI data alone.

Role bonus values — v1
-----------------------
Defined in ``ROLE_BONUS_MAP``.  Bonus is additive, capped by the calling
function not here.  Values were chosen so that:

* A primary penalty taker (+5.0) with a borderline-safe score (e.g. 52.0)
  crosses the ``safe`` threshold (55.0) after adjustment.
* A primary direct FK taker (+3.0) with a borderline-upside score (e.g. 43.0)
  crosses the ``upside`` threshold (45.0) after adjustment.
* Backup-role bonuses (+1.0 / +0.5) produce smaller nudges, suitable for
  borderline differential/low_confidence distinctions.
* Corner/indirect FK order is not included in the role_bonus in v1 (the
  assist signal is already present in xgi_per_90).

Derivation rules
----------------
``derive_role_signals(element)`` inspects the element once and returns:
    penalties_order               raw value (int or None)
    direct_freekicks_order        raw value (int or None)
    corners_and_indirect_freekicks_order   raw value (int or None)
    set_piece_notes               list[str] — active role identifiers
    set_piece_threat              bool — any scoring role bonus is active
    role_bonus                    float — total additive bonus for tier logic

Phase 2h notes
--------------
* ``compute_role_bonus(element)`` is a convenience wrapper that returns just
  the ``role_bonus`` float — useful in callers that don't need the full dict.
* Both functions are pure (no side-effects) and deterministic.
* If ``penalties_order`` or ``direct_freekicks_order`` is not present in the
  element dict (older data or partial elements), the field defaults to
  ``None`` (no bonus).
* The ``fixture_difficulty`` parameter in ``classify_captain_tier`` was
  previously reserved; role_bonus is a separate, more explicit mechanism.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Role bonus values
# ---------------------------------------------------------------------------

ROLE_BONUS_MAP: dict[str, float] = {
    "penalty_taker_1":   5.0,   # primary penalty taker — high scoring uplift
    "penalty_taker_2":   1.0,   # backup penalty taker — small uplift
    "freekick_taker_1":  3.0,   # primary direct FK taker — moderate uplift
    "freekick_taker_2":  0.5,   # backup FK taker — marginal uplift
    # corner/indirect FK order excluded from bonus in v1 (captured by xgi/90)
}

# ---------------------------------------------------------------------------
# Role signal derivation
# ---------------------------------------------------------------------------

def derive_role_signals(element: dict[str, Any]) -> dict[str, Any]:
    """Derive role signals from a raw FPL bootstrap element dict.

    Inspects ``penalties_order``, ``direct_freekicks_order``, and
    ``corners_and_indirect_freekicks_order`` fields.  All three fields are
    optional — missing or ``None`` values are treated as no role.

    Parameters
    ----------
    element:
        Raw FPL bootstrap element dict (a member of
        ``bootstrap["elements"]``).

    Returns
    -------
    dict with the following keys:

    ``penalties_order``
        int or None — raw FPL value (1 = primary taker)
    ``direct_freekicks_order``
        int or None — raw FPL value (1 = primary taker)
    ``corners_and_indirect_freekicks_order``
        int or None — raw FPL value (1 = primary delivery taker)
    ``set_piece_notes``
        list[str] — identifiers of active roles, e.g.
        ``["penalty_taker_1", "freekick_taker_2"]``
    ``set_piece_threat``
        bool — True if any bonus role is active (role_bonus > 0)
    ``role_bonus``
        float — total additive bonus for tier classification;
        0.0 when no relevant role is held.
    """
    pen_order = element.get("penalties_order")
    fk_order  = element.get("direct_freekicks_order")
    ci_order  = element.get("corners_and_indirect_freekicks_order")

    notes: list[str] = []

    # Penalty taker
    if pen_order == 1:
        notes.append("penalty_taker_1")
    elif pen_order == 2:
        notes.append("penalty_taker_2")

    # Direct free-kick taker
    if fk_order == 1:
        notes.append("freekick_taker_1")
    elif fk_order == 2:
        notes.append("freekick_taker_2")

    # Corner/indirect FK order — informational only, no bonus in v1
    # (included in the return dict for completeness / future phases)

    bonus: float = sum(ROLE_BONUS_MAP.get(n, 0.0) for n in notes)

    return {
        "penalties_order":                    pen_order,
        "direct_freekicks_order":             fk_order,
        "corners_and_indirect_freekicks_order": ci_order,
        "set_piece_notes":                    notes,
        "set_piece_threat":                   bonus > 0.0,
        "role_bonus":                         bonus,
    }


def compute_role_bonus(element: dict[str, Any]) -> float:
    """Return only the role_bonus float for *element*.

    Convenience wrapper over :func:`derive_role_signals` for callers that
    need just the bonus value.

    Parameters
    ----------
    element:
        Raw FPL bootstrap element dict.

    Returns
    -------
    float
        Additive role bonus (0.0 when no relevant role is held).
    """
    return derive_role_signals(element)["role_bonus"]
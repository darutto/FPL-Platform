"""
fpl_grounded_assistant.multi_intent
=====================================
Phase 6c: Multi-intent detection and splitting.

Detects conjunctive multi-intent questions and splits them into
independently-routable sub-questions.

Only fires when BOTH halves of a " and " split independently route to
known tools via the deterministic router.  When either half fails to
route, ``detect_multi_intent`` returns ``None`` and the caller falls
through to single-intent processing.

Supported conjunction (Phase 6c): " and " only.
Other conjunctions ("also", "plus", "as well as") are deferred.

False-split guards (by design)
-------------------------------
- ``"compare Salah and Haaland"`` — ``"compare Salah"`` alone does not
  route (comparison routing requires a two-player connector); falls
  through correctly to single comparison intent.
- ``"sell Saka and bring in Salah"`` — ``"sell Saka"`` alone has no
  transfer connector; falls through to single-intent which handles it
  correctly as ``get_transfer_advice``.
- ``"Haaland vs Salah"`` — contains no " and "; falls through unchanged.

Scope limitations
-----------------
- Two sub-intents maximum (Phase 6c).
- Splits on the *first* occurrence of " and " only.
- Both halves must independently produce a ``RouteResult`` from the
  deterministic router; LLM-assisted classification is not used here.
- Session state (last_player, last_comparison, last_resolver_source) is
  not updated from multi-intent turns in Phase 6c.
"""
from __future__ import annotations

from .router import route


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The only conjunction supported in Phase 6c.  Checked as a lowercase
#: substring so case-insensitive questions like "Who is Salah AND what
#: gameweek is it?" also split correctly.
_MULTI_CONJUNCTION: str = " and "


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_multi_intent(question: str) -> list[str] | None:
    """Attempt to split *question* into two independently-routable sub-questions.

    Splits on the first occurrence of ``" and "`` (case-insensitive) and
    validates that both halves route to distinct tools via the deterministic
    ``route()`` function.

    Returns a list of two sub-question strings when a valid split is found,
    or ``None`` when the question should be treated as a single-intent query.

    Parameters
    ----------
    question:
        The raw user question.  Original casing is preserved so that player
        names (e.g. ``"KDB"``) reach the router correctly.

    Returns
    -------
    list[str] | None
        ``[part_a, part_b]`` when a valid two-intent split is detected,
        otherwise ``None``.

    Examples
    --------
    Detected — both halves route independently::

        detect_multi_intent("who is Salah and what gameweek is it?")
        # → ["who is Salah", "what gameweek is it"]

        detect_multi_intent("captain score for Haaland and who is Saka")
        # → ["captain score for Haaland", "who is Saka"]

    Not detected — comparison routing requires both players::

        detect_multi_intent("compare Salah and Haaland")
        # → None  (correct — "compare Salah" alone does not route)

    Not detected — transfer routing requires a connector between players::

        detect_multi_intent("sell Saka and bring in Salah")
        # → None  (correct — "sell Saka" alone has no transfer connector)
    """
    # Normalise for detection only; preserve original casing for the split.
    q_stripped = question.strip().rstrip("?!.")
    q_lower = q_stripped.lower()

    if _MULTI_CONJUNCTION not in q_lower:
        return None

    idx = q_lower.find(_MULTI_CONJUNCTION)
    part_a = q_stripped[:idx].strip()
    part_b = q_stripped[idx + len(_MULTI_CONJUNCTION):].strip()

    if not part_a or not part_b:
        return None

    if route(part_a) is None or route(part_b) is None:
        return None

    return [part_a, part_b]

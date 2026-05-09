"""
fpl_grounded_assistant.telemetry
=================================
In-process telemetry for routing and clarification outcomes.

Phase 2.7g: Telemetry-Driven Hardening Loop.

All state is module-level; counters are additive and never affect routing.
All public functions are wrapped in try/except so telemetry can never raise
into the caller.

Counter vocabulary
------------------
route_source_counts
    Keyed by route_source value (or "none" if None).  Tracks which routing
    stage decided the intent: "deterministic", "llm_classifier_high",
    "llm_classifier_medium", etc.

outcome_counts
    Keyed by outcome value (or "none" if None).  Tracks ok, not_found,
    needs_clarification, unsupported_intent, etc.

classifier_confidence_bucket_counts
    Keyed by confidence bucket string:
      "high"   — confidence >= 0.9
      "medium" — 0.7 <= confidence < 0.9
      "low"    — confidence < 0.7
      "none"   — classifier not attempted (confidence is None)

clarification_asked_counts
    Counter with a single key "total" — incremented on every turn where
    clarification_asked=True (i.e. outcome==needs_clarification from the
    medium-confidence gate).

intent_route_counts
    Keyed by (intent, route_source) tuple.  Lets operators ask "how many
    captain_score turns were routed by the LLM classifier vs deterministic?"
"""
from __future__ import annotations

from collections import Counter


# ---------------------------------------------------------------------------
# Module-level counters (never reset in production; use reset() in tests only)
# ---------------------------------------------------------------------------

route_source_counts:                Counter = Counter()
outcome_counts:                     Counter = Counter()
classifier_confidence_bucket_counts: Counter = Counter()
clarification_asked_counts:         Counter = Counter()
intent_route_counts:                Counter = Counter()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _confidence_bucket(confidence: "float | None") -> str:
    """Map a raw confidence float (or None) to a bucketed string label.

    Parameters
    ----------
    confidence:
        LLM classifier confidence in [0.0, 1.0], or ``None`` when the
        classifier was not attempted for this turn.

    Returns
    -------
    str
        ``"high"``   when confidence >= 0.9
        ``"medium"`` when 0.7 <= confidence < 0.9
        ``"low"``    when confidence < 0.7
        ``"none"``   when confidence is None
    """
    if confidence is None:
        return "none"
    if confidence >= 0.9:
        return "high"
    if confidence >= 0.7:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_response(
    intent: "str | None",
    outcome: "str | None",
    route_source: "str | None",
    classifier_confidence: "float | None",
    supported: bool,
    clarification_asked: bool,
) -> None:
    """Record one response event.

    Increments all relevant counters for a single ``respond()`` call.
    Never raises — all counter operations are wrapped in a broad except so
    a telemetry bug can never surface into the caller.

    Parameters
    ----------
    intent:
        INTENT_* constant from ``FinalResponse.intent``.  ``None`` is safe.
    outcome:
        OUTCOME_* constant from ``FinalResponse.outcome``.  ``None`` is safe.
    route_source:
        Routing stage that decided the intent (e.g. ``"deterministic"``,
        ``"llm_classifier_high"``, ``"llm_classifier_medium"``).  ``None``
        when the deterministic path ran with no classifier attempt.
    classifier_confidence:
        LLM classifier confidence in [0.0, 1.0], or ``None`` when the
        classifier was not attempted.
    supported:
        ``True`` when intent is within scope; mirrors ``FinalResponse.supported``.
        Not currently used for counters but kept in the signature for future use.
    clarification_asked:
        ``True`` when the medium-confidence gate fired and a clarification
        prompt was returned instead of a grounded answer.
    """
    try:
        route_source_counts[route_source or "none"] += 1
        outcome_counts[outcome or "none"] += 1
        bucket = _confidence_bucket(classifier_confidence)
        classifier_confidence_bucket_counts[bucket] += 1
        if clarification_asked:
            clarification_asked_counts["total"] += 1
        intent_route_counts[(intent or "none", route_source or "none")] += 1
    except Exception:  # noqa: BLE001 — telemetry must never raise into caller
        pass


def get_snapshot() -> dict:
    """Return a JSON-serializable snapshot of current counters.

    The returned dict is a shallow copy of each counter at the moment of
    the call — it is not a live view.  All keys are strings; all values
    are ints.

    Returns
    -------
    dict
        Keys:
        ``route_source_counts``            — dict[str, int]
        ``outcome_counts``                 — dict[str, int]
        ``classifier_confidence_bucket_counts`` — dict[str, int]
        ``clarification_asked_total``      — int
        ``intent_route_counts``            — dict[str, int] with keys
                                             formatted as "intent|route_source"
    """
    try:
        return {
            "route_source_counts": dict(route_source_counts),
            "outcome_counts": dict(outcome_counts),
            "classifier_confidence_bucket_counts": dict(
                classifier_confidence_bucket_counts
            ),
            "clarification_asked_total": clarification_asked_counts["total"],
            "intent_route_counts": {
                f"{intent}|{rs}": count
                for (intent, rs), count in intent_route_counts.items()
            },
        }
    except Exception:  # noqa: BLE001
        return {}


def reset() -> None:
    """Reset all counters.

    Use in tests only.  Not safe to call in production — any in-flight
    request may observe partial counter state during or after reset.
    """
    try:
        route_source_counts.clear()
        outcome_counts.clear()
        classifier_confidence_bucket_counts.clear()
        clarification_asked_counts.clear()
        intent_route_counts.clear()
    except Exception:  # noqa: BLE001
        pass

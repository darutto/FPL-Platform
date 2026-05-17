"""
fpl_grounded_assistant.telemetry
=================================
In-process telemetry for routing and clarification outcomes.

Phase 2.7g: Telemetry-Driven Hardening Loop.
Phase M5: Decision-Tree Telemetry (routing-branch counters + graduation math).

All state is module-level; counters are additive and never affect routing.
All public functions are wrapped in try/except so telemetry can never raise
into the caller.

Phase 2.7g counter vocabulary
------------------------------
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

Phase M5 routing-branch counter vocabulary
------------------------------------------
M5 counters track which branch of the ask_v2() decision ladder fired.
They are populated by ``record(routing_trace)`` called from ``ask_v2()``
and from ``POST /ask-orchestrated`` after each response is built.

routing_branch_counts["resource"]
    Inputs matched a registered @resource.  These are fully deterministic.

routing_branch_counts["prompt"]
    Inputs matched a /prompt (expansion or dispatch mode).  May involve a
    classify_intent_llm call for the canonical-text path, but the downstream
    tool is deterministic once the canonical text is produced.

routing_branch_counts["route"]
    Plain-text inputs where route() succeeded on the first try.  Fully
    deterministic.

routing_branch_counts["classifier_rewrite"]
    Plain-text inputs where route() missed, classify_intent_llm() produced a
    canonical question, and route() succeeded on the rewrite.  The LLM
    classifier is used, but the downstream tool is still deterministic.
    Counted as deterministic share for graduation-criteria purposes because
    the answer grounds in a deterministic tool — the classifier only rewrites
    the question, it does not generate the answer.

routing_branch_counts["orchestrator_attempted"]
    Inputs where the orchestrator was invoked (routing_trace.orchestrator_called
    == True), regardless of whether it returned a grounded answer.  Includes
    both successful and failed orchestrator calls.

routing_branch_counts["orchestrator_grounded"]
    Subset of orchestrator_attempted where the orchestrator actually ran a
    deterministic tool to completion (routing_trace.branch == "orchestrator"
    AND routing_trace.grounded == True).  This is the "long tail handled" metric.

routing_branch_counts["unsupported"]
    Inputs that fell through every ladder rung without a grounded answer.
    Used to compute the reject rate: unsupported / total_primary.

The graduation criterion reject_rate < 5% is computed over total_primary
(sum of resource + prompt + route + classifier_rewrite + unsupported),
which excludes the orchestrator_attempted / orchestrator_grounded derived
counters (those are informational, not primary branch counters).
"""
from __future__ import annotations

from collections import Counter
from typing import Any


# ---------------------------------------------------------------------------
# Module-level counters (never reset in production; use reset() in tests only)
# ---------------------------------------------------------------------------

# Phase 2.7g counters
route_source_counts:                Counter = Counter()
outcome_counts:                     Counter = Counter()
classifier_confidence_bucket_counts: Counter = Counter()
clarification_asked_counts:         Counter = Counter()
intent_route_counts:                Counter = Counter()

# Phase M5 routing-branch counters (populated by record(routing_trace))
routing_branch_counts: Counter = Counter()


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
    """Reset all counters (Phase 2.7g and M5).

    Use in tests only.  Not safe to call in production — any in-flight
    request may observe partial counter state during or after reset.
    """
    try:
        route_source_counts.clear()
        outcome_counts.clear()
        classifier_confidence_bucket_counts.clear()
        clarification_asked_counts.clear()
        intent_route_counts.clear()
        routing_branch_counts.clear()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Phase M5: routing-branch recording and graduation math
# ---------------------------------------------------------------------------

# Primary branch labels — the six exclusive branch outcomes from ask_v2().
# orchestrator_attempted and orchestrator_grounded are derived from the
# orchestrator_called / grounded fields and are NOT primary branch keys.
_PRIMARY_BRANCHES: tuple[str, ...] = (
    "resource",
    "prompt",
    "route",
    "classifier_rewrite",
    "orchestrator",   # primary branch when orch is grounded
    "unsupported",
)


def record(routing_trace: "dict[str, Any]") -> None:
    """Record one routing event from a routing_trace dict produced by ask_v2().

    Increments the appropriate M5 routing-branch counters.  Never raises —
    all counter operations are wrapped in a broad except so a telemetry bug
    can never surface into the caller.

    Designed to be called from ``ask_v2()`` immediately before each return
    that carries a routing_trace, and from ``POST /ask-orchestrated`` after
    the orchestrator returns.

    Per-counter semantics
    ---------------------
    Primary branch counter (routing_branch_counts[branch]):
        Incremented once per call, using routing_trace["branch"] as the key.
        Possible values: "resource", "prompt", "route", "classifier_rewrite",
        "orchestrator", "unsupported".

    orchestrator_attempted:
        Incremented when routing_trace["orchestrator_called"] is True,
        regardless of grounding status.  This captures every invocation of
        the orchestrator loop, even when it fails to produce a grounded answer.

    orchestrator_grounded:
        Incremented only when the primary branch is "orchestrator" AND
        routing_trace["grounded"] is True.  This is the subset of orchestrator
        calls that yielded a usable tool-grounded answer.

    The split between orchestrator_attempted and orchestrator_grounded
    satisfies Adversarial Reviewer finding R5: these two counters are always
    distinct, never conflated into a single "orchestrator" bucket.
    """
    try:
        branch = routing_trace.get("branch", "unsupported")
        routing_branch_counts[branch] += 1

        # Orchestrator attempted — any call regardless of outcome
        if routing_trace.get("orchestrator_called"):
            routing_branch_counts["orchestrator_attempted"] += 1

        # Orchestrator grounded — successful tool-grounded answer
        if branch == "orchestrator" and routing_trace.get("grounded"):
            routing_branch_counts["orchestrator_grounded"] += 1
    except Exception:  # noqa: BLE001 — telemetry must never raise into caller
        pass


def snapshot() -> "dict[str, Any]":
    """Return a JSON-serialisable snapshot of M5 routing-branch counters.

    Returns a dict suitable for embedding in /healthz.  The snapshot is a
    point-in-time copy; it is not a live view.

    Shape
    -----
    ::

        {
          "resource":               int,   # @resource branch hits
          "prompt":                 int,   # /prompt branch hits
          "route":                  int,   # deterministic route() hits
          "classifier_rewrite":     int,   # LLM rewrite -> route() hits
          "orchestrator":           int,   # orchestrator grounded (primary branch)
          "unsupported":            int,   # reject count
          "orchestrator_attempted": int,   # all orch invocations (R5 split)
          "orchestrator_grounded":  int,   # orch invocations that grounded (R5 split)
          "total_primary":          int,   # sum of the 5 exclusive primary branches
                                          #   (resource+prompt+route+classifier_rewrite
                                          #    +unsupported); excludes orch
          "reject_rate":            float, # unsupported / total_primary, or 0.0
        }

    Note: ``total_primary`` counts are defined over the five branches that
    directly map to user intents.  The ``orchestrator`` primary-branch counter
    is NOT included in total_primary to avoid double-counting — when an
    orchestrator call succeeds the branch IS "orchestrator", but when it fails
    the branch IS "unsupported".  total_primary is therefore a clean count of
    distinct user requests processed, one per call to ask_v2().
    """
    try:
        resource           = routing_branch_counts["resource"]
        prompt             = routing_branch_counts["prompt"]
        route_             = routing_branch_counts["route"]
        classifier_rewrite = routing_branch_counts["classifier_rewrite"]
        orchestrator       = routing_branch_counts["orchestrator"]
        unsupported        = routing_branch_counts["unsupported"]
        orch_attempted     = routing_branch_counts["orchestrator_attempted"]
        orch_grounded      = routing_branch_counts["orchestrator_grounded"]

        # total_primary: every exclusive primary-branch outcome (one per request)
        total_primary = (
            resource + prompt + route_ + classifier_rewrite
            + orchestrator + unsupported
        )
        reject_rate = unsupported / total_primary if total_primary > 0 else 0.0

        return {
            "resource":               resource,
            "prompt":                 prompt,
            "route":                  route_,
            "classifier_rewrite":     classifier_rewrite,
            "orchestrator":           orchestrator,
            "unsupported":            unsupported,
            "orchestrator_attempted": orch_attempted,
            "orchestrator_grounded":  orch_grounded,
            "total_primary":          total_primary,
            "reject_rate":            reject_rate,
        }
    except Exception:  # noqa: BLE001
        return {}


def graduation_status(snap: "dict[str, Any] | None" = None) -> "dict[str, Any]":
    """Evaluate whether the branch is ready to graduate to main.

    Computes the graduation criteria from plan §M5 (decision rule, line 322):
      - >= 80% of inputs land on router or resources/prompts (deterministic share)
      - orchestrator handles the long tail (informational, not gating)
      - reject rate < 5%

    All three quantities are derived from the routing-branch counters.

    Parameters
    ----------
    snap:
        Optional pre-computed snapshot dict (from ``snapshot()``).  When
        ``None``, ``snapshot()`` is called internally.  Pass an explicit
        snapshot in tests to exercise the math without touching live counters.

    Returns
    -------
    dict with keys:

    ``deterministic_share``
        (resource + prompt + route + classifier_rewrite) / total_primary.

        ``classifier_rewrite`` is included as deterministic because the LLM
        classifier only rewrites the question to a canonical form that
        re-enters ``route()``.  The downstream tool is still a deterministic
        function of the rewritten question — the LLM does not generate the
        answer.  This is the correct interpretation of "lands on the router"
        from the plan's graduation rule.

    ``orchestrator_grounded_share``
        orchestrator_grounded / total_primary.  Informational only — not a
        gating criterion.  The plan says "orchestrator handles the long tail";
        this metric lets operators confirm the orchestrator is active but not
        dominant.  It is NOT tested in ``criteria`` or ``ready_to_graduate``.

    ``reject_rate``
        unsupported / total_primary.  Gating criterion: must be < 0.05.

    ``criteria``
        dict of gating booleans:
          ``deterministic_share_ge_80``: deterministic_share >= 0.80
          ``reject_rate_lt_5``:          reject_rate < 0.05

    ``ready_to_graduate``
        True iff all criteria are True AND total_primary > 0.
        (Zero observations means the system has not been exercised —
        that is not a passing state.)

    ``total_observations``
        Same as ``total_primary`` — total distinct requests observed.
    """
    try:
        s = snap if snap is not None else snapshot()
        if not s:
            return {
                "deterministic_share": 0.0,
                "orchestrator_grounded_share": 0.0,
                "reject_rate": 0.0,
                "criteria": {
                    "deterministic_share_ge_80": False,
                    "reject_rate_lt_5": False,
                },
                "ready_to_graduate": False,
                "total_observations": 0,
            }

        total = s.get("total_primary", 0)
        deterministic = (
            s.get("resource", 0)
            + s.get("prompt", 0)
            + s.get("route", 0)
            + s.get("classifier_rewrite", 0)
        )
        orch_grounded = s.get("orchestrator_grounded", 0)
        unsupported   = s.get("unsupported", 0)

        det_share  = deterministic / total if total > 0 else 0.0
        orch_share = orch_grounded  / total if total > 0 else 0.0
        rej_rate   = unsupported    / total if total > 0 else 0.0

        criteria = {
            "deterministic_share_ge_80": det_share >= 0.80,
            "reject_rate_lt_5":          rej_rate  < 0.05,
        }
        ready = total > 0 and all(criteria.values())

        return {
            "deterministic_share":       det_share,
            "orchestrator_grounded_share": orch_share,
            "reject_rate":               rej_rate,
            "criteria":                  criteria,
            "ready_to_graduate":         ready,
            "total_observations":        total,
        }
    except Exception:  # noqa: BLE001
        return {
            "deterministic_share": 0.0,
            "orchestrator_grounded_share": 0.0,
            "reject_rate": 0.0,
            "criteria": {
                "deterministic_share_ge_80": False,
                "reject_rate_lt_5": False,
            },
            "ready_to_graduate": False,
            "total_observations": 0,
        }

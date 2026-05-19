"""harness_adapter.py — Pure mapping from ask_v2() dict to AskResponse.

**Module contract (read before editing):**

This module is a PURE MAPPING LAYER.  It has ZERO LLM calls, ZERO decision
logic, and ZERO I/O.  Every line in this file is a data-transformation or a
field projection.  If you find yourself adding a conditional that invokes a
network resource, spawns a thread, or calls ``anthropic.*``, you are violating
the module contract.

Routing concerns (which ladder rung fires, which tool runs) live in
``harness.ask_v2()``.  UI-contract concerns (squad_context overrides,
AskResponse field projection, debug-only routing_trace surfacing) live here.

The two Adversarial-Reviewer-blessed semantic shifts (documented below):

1. **``orch_outcome`` semantics change.**
   Pre-graduation: ``orch_outcome`` marked "non-OK orchestrator fallback inside
   ``respond()``" — it was populated only when the orchestrator was attempted
   BUT returned a non-OK outcome, and the deterministic path then ran.
   Post-graduation (this adapter): ``orch_outcome`` marks the orchestrator
   branch outcome from ``routing_trace["orchestrator_outcome"]`` — populated
   whenever ``routing_trace["branch"] == "orchestrator"`` (success and
   no-grounded-tool paths), ``None`` on all other branches.  Operators
   observing this field must account for this semantic shift.

2. **``review_passed`` and ``llm_used`` lose LLM-review semantics on
   deterministic and ladder paths.**
   ``ask_v2()`` has no LLM-review step.  Post-graduation these fields reflect
   orchestrator-LLM use only:
   - ``llm_used = True`` only when ``branch in ("orchestrator", "classifier_rewrite")``.
   - ``review_passed = True`` when the answer is grounded (tool ran end-to-end)
     OR when outcome is not "unsupported"; ``False`` only on full-ladder misses.
   Session paths (``POST /session/{id}/ask``) still call ``respond()`` and
   retain the original LLM-review semantics.
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fpl_server import AskRequest, AskResponse


def _to_dict(value: Any) -> Any:
    """Convert a dataclass instance to a plain dict; pass through everything else.

    ``AskResponse`` fields typed as ``dict[str, Any] | None`` do not accept
    dataclass instances.  ``_extract_structured_meta()`` returns typed
    dataclasses (TransferMeta, ChipAdviceMeta, etc.); this helper converts them
    so the pydantic validator accepts the value.

    For list values (captain_ranking is a tuple of dataclasses), each element
    is converted recursively.
    """
    if value is None:
        return None
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, (list, tuple)):
        return [_to_dict(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Branch → semantic helpers (pure constants)
# ---------------------------------------------------------------------------

# Branches where an LLM ran somewhere in the pipeline.
_LLM_BRANCHES: frozenset[str] = frozenset({"orchestrator", "classifier_rewrite"})

# Branches where the question was grounded (a deterministic tool ran end-to-end).
_GROUNDED_BRANCHES: frozenset[str] = frozenset(
    {"route", "classifier_rewrite", "orchestrator", "prompt"}
)


def to_ask_response(
    ask_v2_dict: dict[str, Any],
    ask_request: "AskRequest",
) -> "AskResponse":
    """Project an ask_v2() return dict into the AskResponse contract.

    Pure mapping — no side effects, no LLM, no decisions.
    UI-contract concerns (squad_context overrides, AskResponse field
    projection, debug-only routing_trace surfacing) live here.
    Routing concerns stay in ask_v2().

    Parameters
    ----------
    ask_v2_dict:
        The dict returned by ``harness.ask_v2()``.  Not mutated.
    ask_request:
        The original ``AskRequest`` from the HTTP layer.  Used for
        ``squad_context`` (override application) and ``debug`` (routing_trace
        gating).

    Returns
    -------
    AskResponse
        Fully-populated pydantic response model ready for FastAPI serialisation.

    Notes on field mapping
    ----------------------
    ``intent``
        Derived from ``selected_tool`` via ``_TOOL_TO_INTENT``.  Defaults to
        ``"unsupported"`` when no tool ran (resource, prompt-expansion-miss,
        unsupported branches).

    ``supported``
        ``True`` iff ``outcome != "unsupported"``.  Resource and
        needs_clarification turns are considered *supported* (the question was
        understood; the answer was limited by scope or prompt state).

    ``review_passed`` — SEMANTIC SHIFT documented in module docstring.

    ``llm_used`` — SEMANTIC SHIFT documented in module docstring.

    ``orch_outcome`` — SEMANTIC SHIFT documented in module docstring.

    ``route_source``
        ``"intent_hint"`` when the routing_trace indicates the hint path fired
        (classification_source == "intent_hint").
        ``"llm_classifier_high"`` / ``"llm_classifier_medium"`` / ``"llm_classifier"``
        when branch == "classifier_rewrite" (band derived from classifier_confidence,
        threshold 0.9 mirrors dispatcher._CLASSIFIER_HIGH_CONFIDENCE — pure numeric
        mapping, not a routing decision).
        ``"deterministic"`` when branch == "route" (no LLM involved).
        ``None`` for all other branches (prompt, resource, orchestrator, unsupported).

    ``routing_trace``
        NEVER surfaced as a top-level field.  Only included inside the ``debug``
        blob when ``ask_request.debug == True``.
    """
    # Deferred import — avoids circular at module-load time (fpl_server imports
    # fpl_grounded_assistant which imports harness_adapter at wire-up time).
    from fpl_server import AskResponse as _AskResponse
    from fpl_grounded_assistant.dispatcher import _TOOL_TO_INTENT, INTENT_UNSUPPORTED
    from fpl_grounded_assistant.final_response import (
        _apply_squad_overrides,
        _clarification_text_for_intent,
    )

    # Work on a shallow copy so we never mutate the caller's dict.
    d: dict[str, Any] = dict(ask_v2_dict)

    routing_trace: dict[str, Any] = d.get("routing_trace") or {}
    branch: str = routing_trace.get("branch", "unsupported")

    # ------------------------------------------------------------------
    # 1. Squad overrides — applied BEFORE structured-metadata projection.
    #    squad_context is dict[str, Any] | None (already the right type
    #    for _apply_squad_overrides; no .model_dump() needed).
    # ------------------------------------------------------------------
    squad_context: dict[str, Any] | None = ask_request.squad_context

    transfer = d.get("transfer")
    chip     = d.get("chip")
    answer_text: str = d.get("answer_text", "")

    if squad_context is not None and (transfer is not None or chip is not None):
        transfer, chip, answer_text = _apply_squad_overrides(
            transfer=transfer,
            chip=chip,
            final_text=answer_text,
            squad_context=squad_context,
        )
        d["transfer"]     = transfer
        d["chip"]         = chip
        d["answer_text"]  = answer_text

    # ------------------------------------------------------------------
    # 2. Derive intent from selected_tool (no top-level "intent" key in
    #    ask_v2 dict).
    #    Exception: when the medium-confidence gate fires, selected_tool=None
    #    but ask_v2() injects "medium_gate_intent" with the classifier-resolved
    #    intent so callers see the correct intent (matching dispatcher.py line 660).
    # ------------------------------------------------------------------
    selected_tool: str | None = d.get("selected_tool")
    if selected_tool is not None:
        intent: str = _TOOL_TO_INTENT.get(selected_tool, INTENT_UNSUPPORTED)
    elif d.get("medium_gate_intent") is not None:
        intent = d["medium_gate_intent"]
    else:
        intent = INTENT_UNSUPPORTED

    # ------------------------------------------------------------------
    # 3. Outcome and supported.
    # ------------------------------------------------------------------
    _raw_outcome: str = d.get("outcome", "unsupported")
    # Parity fix (mcp-graduation G1.4): ask_v2() step 4 (full text-ladder miss)
    # returns outcome="unsupported" with kind="text" and branch="unsupported".
    # dispatcher.dispatch() returns OUTCOME_UNSUPPORTED_INTENT ("unsupported_intent")
    # for the same case.  Map here to preserve parity without altering ask_v2().
    # Other "unsupported" cases (rejected, resource-miss, prompt-miss) keep "unsupported"
    # because they have kind != "text".
    _kind: str = d.get("kind", "")
    if _raw_outcome == "unsupported" and branch == "unsupported" and _kind == "text":
        outcome: str = "unsupported_intent"
    else:
        outcome = _raw_outcome
    # supported=False for unsupported_intent AND needs_clarification,
    # matching adapter.py line 143:
    #   supported = dr.outcome not in (OUTCOME_UNSUPPORTED_INTENT, OUTCOME_NEEDS_CLARIFICATION)
    # All other outcomes (ok, not_found, ambiguous, error, missing_arguments) are "supported"
    # (the intent was within scope; the answer was limited by data or routing state).
    supported: bool = outcome not in ("unsupported", "unsupported_intent", "needs_clarification")

    # ------------------------------------------------------------------
    # 3b. Phase 2.7f parity: when outcome == needs_clarification, replace the
    #     generic harness answer_text with an intent-shaped clarification prompt,
    #     matching final_response.py line 2084 (_clarification_text_for_intent).
    # ------------------------------------------------------------------
    if outcome == "needs_clarification":
        answer_text = _clarification_text_for_intent(intent)

    # ------------------------------------------------------------------
    # 4. Semantic-shift fields (documented in module docstring).
    # ------------------------------------------------------------------
    llm_used: bool = branch in _LLM_BRANCHES
    # review_passed: True whenever the answer is grounded OR the outcome is
    # not a full ladder miss.  False on unsupported / unsupported_intent branches.
    # "unsupported_intent" is the adapter-mapped value of step-4 "unsupported" text misses.
    review_passed: bool = routing_trace.get("grounded", False) or (
        outcome not in ("unsupported", "unsupported_intent")
    )

    # ------------------------------------------------------------------
    # 5. Routing audit fields from routing_trace.
    # ------------------------------------------------------------------
    # route_source: mirrors dispatcher.py semantics exactly.
    #
    #   "intent_hint"          — routing_trace classification_source == "intent_hint"
    #                            (injected by fpl_server POST /ask pre-processing)
    #   "llm_classifier_high"  — classifier_rewrite branch, confidence >= 0.9
    #                            (matches dispatcher._CLASSIFIER_HIGH_CONFIDENCE)
    #   "llm_classifier_medium"— classifier_rewrite branch, 0 <= confidence < 0.9
    #   "llm_classifier"       — classifier_rewrite branch, confidence absent
    #   "deterministic"        — route branch (no LLM involved)
    #   None                   — all other branches (prompt, resource, orchestrator,
    #                            unsupported)
    #
    # The confidence-band thresholds are read from the same constants used by
    # dispatcher.py at lines 652-655 (_CLASSIFIER_HIGH_CONFIDENCE = 0.9).
    # Adapter computes the band from classifier_confidence — pure numeric mapping,
    # NOT a routing decision (routing decisions live in ask_v2 / dispatcher).
    _ADAPTER_HIGH_CONFIDENCE: float = 0.9  # mirrors dispatcher._CLASSIFIER_HIGH_CONFIDENCE
    classification_source: str | None = routing_trace.get("classification_source")
    if classification_source == "intent_hint":
        route_source: str | None = "intent_hint"
    elif branch == "classifier_rewrite":
        # Derive confidence band to match dispatcher semantics (Fix A, G1.4).
        conf = routing_trace.get("classifier_confidence")
        if conf is not None and conf >= _ADAPTER_HIGH_CONFIDENCE:
            route_source = "llm_classifier_high"
        elif conf is not None:
            route_source = "llm_classifier_medium"
        else:
            # classifier_confidence absent — shouldn't happen on classifier_rewrite branch,
            # but fall back gracefully.
            route_source = "llm_classifier"
    elif branch == "route":
        # Deterministic path: route() succeeded on the first try, no LLM involved.
        route_source = "deterministic"
    else:
        route_source = None

    classifier_confidence: float | None = routing_trace.get("classifier_confidence")

    # route_conflict: always False — M3 ladder is strict-order; conflicts cannot
    # arise post-graduation.
    route_conflict: bool = False

    # ------------------------------------------------------------------
    # 6. Clarification gate.
    # ------------------------------------------------------------------
    clarification_asked: bool = outcome == "needs_clarification"

    # ------------------------------------------------------------------
    # 7. orch_outcome — SEMANTIC SHIFT (see module docstring).
    #    Populated only when branch == "orchestrator".
    # ------------------------------------------------------------------
    if branch == "orchestrator":
        orch_outcome: str | None = routing_trace.get("orchestrator_outcome")
    else:
        orch_outcome = None

    # ------------------------------------------------------------------
    # 8. degraded — no degraded signal in ask_v2 dict; False by default.
    #    ask_v2() never calls ask_llm_safe() so provider-failed tracking
    #    is inapplicable on this path.
    # ------------------------------------------------------------------
    degraded: bool = False

    # ------------------------------------------------------------------
    # 9. debug blob — routing_trace ONLY when ask_request.debug == True.
    # ------------------------------------------------------------------
    debug_blob: dict[str, Any] | None = None
    if ask_request.debug:
        debug_blob = {"routing_trace": routing_trace}

    # ------------------------------------------------------------------
    # 10. context_meta passthrough.
    # ------------------------------------------------------------------
    # (AskResponse has no context_meta field; kept as internal metadata only.)
    # context_meta = d.get("context_meta")

    # ------------------------------------------------------------------
    # 11. Build AskResponse.
    #     AskResponse fields typed dict[str,Any] | None cannot accept raw
    #     dataclass instances; _to_dict() converts them via dataclasses.asdict().
    # ------------------------------------------------------------------
    return _AskResponse(
        final_text=answer_text,
        outcome=outcome,
        supported=supported,
        intent=intent,
        review_passed=review_passed,
        llm_used=llm_used,
        debug=debug_blob,
        # 14 structured-metadata fields — convert dataclasses to plain dicts.
        comparison=_to_dict(d.get("comparison")),
        captain=_to_dict(d.get("captain")),
        captain_ranking=_to_dict(d.get("captain_ranking")),
        transfer=_to_dict(d.get("transfer")),
        chip=_to_dict(d.get("chip")),
        fixture_run=_to_dict(d.get("fixture_run")),
        differential=_to_dict(d.get("differential")),
        player_form=_to_dict(d.get("player_form")),
        injury_list=_to_dict(d.get("injury_list")),
        price_changes=_to_dict(d.get("price_changes")),
        team_calendar=_to_dict(d.get("team_calendar")),
        team_schedule=_to_dict(d.get("team_schedule")),
        position_fixture_run=_to_dict(d.get("position_fixture_run")),
        transfer_suggestion=_to_dict(d.get("transfer_suggestion")),
        # routing audit
        orch_outcome=orch_outcome,
        degraded=degraded,
        route_source=route_source,
        classifier_confidence=classifier_confidence,
        route_conflict=route_conflict,
        clarification_asked=clarification_asked,
    )

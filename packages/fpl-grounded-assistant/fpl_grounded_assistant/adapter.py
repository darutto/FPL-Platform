"""
fpl_grounded_assistant.adapter
==============================
Thin model-facing adapter over the deterministic dispatcher.

Phase 2m: Minimal LLM adapter.

This module is the boundary layer intended for model / LLM integration.
It accepts a user message, delegates all execution to ``dispatch()``, and
returns a clean ``AdapterResponse`` object that packages the key fields a
model-facing caller needs without exposing raw tool internals.

Design principles
-----------------
* **Deterministic** — no LLM calls, no freeform reasoning, no fuzzy matching.
  All routing and execution is delegated to the existing grounded backend.
* **Thin** — the adapter adds no new logic beyond what ``dispatch()`` already
  provides.  Its sole job is to package the result into a caller-friendly shape.
* **Explicit outcomes** — ``supported`` and ``response_text`` make the key
  facts accessible without requiring callers to inspect ``DispatchResult``
  internals.
* **Safe** — unsupported, error, not_found, and ambiguous outcomes all return
  a complete ``AdapterResponse`` with human-readable ``response_text``.

``supported`` flag semantics
-----------------------------
``supported=True`` means the dispatcher *recognised* the intent — even if
execution could not complete (e.g. player not found, ambiguous name, missing
candidates list).  Callers that need finer granularity should inspect
``dispatch_result.outcome`` against the ``OUTCOME_*`` constants.

``supported=False`` means the question fell outside the dispatcher's supported
scope (``outcome == OUTCOME_UNSUPPORTED_INTENT``).

Intentionally deferred
-----------------------
* LLM-based intent classification
* Multi-turn conversation memory
* Pronoun resolution ("What about his form?")
* Combined intents ("Who is Salah and what gameweek is it?")
* Freeform response generation
* UI integration
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .dispatcher import (
    dispatch,
    DispatchResult,
    OUTCOME_UNSUPPORTED_INTENT,
)


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdapterResponse:
    """The output of a single ``adapt()`` call.

    Attributes
    ----------
    user_message:
        The original user message, preserved verbatim.
    dispatch_result:
        The full ``DispatchResult`` from the grounded dispatcher.
        Exposes intent, outcome, selected_tool, raw_output, answer_text,
        and context_meta.
    supported:
        ``True`` if the intent was recognised by the dispatcher (even if
        execution produced a not_found, ambiguous, or error outcome).
        ``False`` only when ``outcome == OUTCOME_UNSUPPORTED_INTENT``.
    response_text:
        The human-readable response string.  Mirrors
        ``dispatch_result.answer_text`` — callers do not need to reach
        into ``dispatch_result`` just to get the text.
    """
    user_message:    str
    dispatch_result: DispatchResult
    supported:       bool
    response_text:   str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def adapt(
    user_message: str,
    bootstrap: dict[str, Any],
    *,
    candidate_inputs: dict[str, Any] | None = None,
    candidates_list: list[dict[str, Any]] | None = None,
) -> AdapterResponse:
    """Adapt a user message into a safe ``AdapterResponse``.

    This is the intended entrypoint for model / LLM integration.  It wraps
    ``dispatch()`` and returns a clean result object without exposing raw
    tool internals.

    Parameters
    ----------
    user_message:
        The raw message from the user (or model).
    bootstrap:
        FPL bootstrap dict (or assembled context from
        ``assemble_captain_context()``).
    candidate_inputs:
        Optional scoring override dict for ``get_captain_score``.
    candidates_list:
        Optional list of candidate dicts for ``rank_captain_candidates``.

    Returns
    -------
    AdapterResponse
        Always returns — never raises.

    Notes
    -----
    ``supported`` is derived from the outcome: ``True`` for all outcomes
    except ``OUTCOME_UNSUPPORTED_INTENT``.  Callers that need finer
    distinctions (not_found vs. ambiguous vs. error) should inspect
    ``dispatch_result.outcome`` directly.
    """
    dr = dispatch(
        user_message,
        bootstrap,
        candidate_inputs=candidate_inputs,
        candidates_list=candidates_list,
    )
    supported = dr.outcome != OUTCOME_UNSUPPORTED_INTENT
    return AdapterResponse(
        user_message=user_message,
        dispatch_result=dr,
        supported=supported,
        response_text=dr.answer_text,
    )
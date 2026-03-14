"""
fpl_grounded_assistant.final_response
======================================
Unified final-response policy layer.

Phase 3c: Unified final response policy.

This module is the outermost caller-facing surface of the fpl-grounded-assistant
stack.  It encapsulates the full pipeline and exposes a single ``FinalResponse``
object that makes the final-response policy explicit and unambiguous.

Stack layers (innermost to outermost)
--------------------------------------
::

    respond()
      └── ask_llm_safe()           ← review gate (Phase 3b)
            └── ask_llm()          ← LLM presentation (Phase 3a)
                  └── adapt()      ← deterministic adapter (Phase 2m)
                        └── dispatch()   ← typed dispatcher (Phase 2k/2l)
                              └── ask()  ← grounded harness (Phase 1h)

Final-response policy
---------------------
``final_text`` is always ``review.safe_text``:

* LLM called, review passed → ``final_text = llm_text``   (``llm_used=True``)
* LLM not called (fallback) → ``final_text = response_text``  (``llm_used=False``)
* LLM called, review failed → ``final_text = response_text``  (``llm_used=False``)

This single rule eliminates ambiguity for callers — they always get the safest
available text without inspecting internal review state.

Caller-facing vs debug-facing
------------------------------
``FinalResponse`` exposes six caller-facing fields::

    final_text    — the text to show the user
    outcome       — OUTCOME_* constant for routing decisions
    supported     — intent within scope (True) or not (False)
    intent        — INTENT_* constant for logging and analytics
    review_passed — did LLM text pass parity checks?
    llm_used      — is final_text LLM-generated (and accepted)?

And one optional debug bundle::

    debug — FinalResponseDebug | None

The debug bundle is ``None`` by default.  Callers may opt in with
``include_debug=True`` to get internal fields (``llm_text``, ``response_text``,
``violations``, ``prompt_used``, ``model``) for diagnostics and regression
testing.  These fields are explicitly **not** part of the caller-facing contract.

``llm_used`` semantics
-----------------------
``llm_used=True`` means exactly: an actual Anthropic API call was made AND the
returned text passed the deterministic parity review.  When ``llm_used=False``
the deterministic ``response_text`` is surfaced, which is always safe regardless
of reason (no API key, API error, review failure, etc.).

Intentionally deferred
-----------------------
* Multi-turn conversation memory
* Pronoun resolution
* Combined intents
* UI integration
* Model-based review (Phase 3b established deterministic-only review)
* Streaming responses
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .dispatcher import OUTCOME_OK  # noqa: F401 — re-exported for convenience
from .llm_layer import DEFAULT_MODEL
from .llm_review import ask_llm_safe


# ---------------------------------------------------------------------------
# Debug bundle
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FinalResponseDebug:
    """Internal fields for debugging and regression testing.

    Only populated when ``respond()`` is called with ``include_debug=True``.
    Not intended for production caller consumption.

    Attributes
    ----------
    llm_text:
        The raw text returned by the LLM (or the deterministic fallback when
        ``llm_called=False``).  May differ from ``FinalResponse.final_text``
        when the review rejected it.
    response_text:
        The deterministic backend text (``adapter_response.response_text``).
        Always the ultimate safety net — identical to ``final_text`` whenever
        ``FinalResponse.llm_used=False``.
    violations:
        Tuple of violation strings from the review layer.  Empty when the
        review passed.
    prompt_used:
        The user-turn prompt that was (or would have been) sent to the LLM.
        Useful for diagnosing unexpected LLM behaviour.
    model:
        The Anthropic model identifier, or ``"none"`` when the deterministic
        fallback was used.
    """
    llm_text:      str
    response_text: str
    violations:    tuple[str, ...]
    prompt_used:   str
    model:         str


# ---------------------------------------------------------------------------
# Caller-facing response
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FinalResponse:
    """The canonical caller-facing output of a single ``respond()`` call.

    Attributes
    ----------
    final_text:
        The text to surface to the user.  Guaranteed non-empty.  Policy:
        equals ``llm_text`` when ``llm_used=True``; equals ``response_text``
        (deterministic ground truth) when ``llm_used=False``.
    outcome:
        The ``OUTCOME_*`` constant from the grounded backend.  Use for
        routing decisions: e.g. distinguish ``OUTCOME_OK`` vs.
        ``OUTCOME_NOT_FOUND`` vs. ``OUTCOME_UNSUPPORTED_INTENT``.
    supported:
        Whether the intent was within the supported scope of the dispatcher.
        ``True`` for all outcomes except ``OUTCOME_UNSUPPORTED_INTENT``.
    intent:
        The ``INTENT_*`` constant from the grounded backend.  Useful for
        logging, analytics, and debugging routing decisions.
    review_passed:
        Whether the LLM text passed the deterministic parity review.  When
        ``False``, ``final_text`` contains the deterministic fallback.
    llm_used:
        Whether LLM-generated text appears in ``final_text``.
        ``True`` iff ``llm_called=True`` AND ``review_passed=True``.
        When ``False``, ``final_text`` is purely deterministic.
    debug:
        Optional internal debug bundle.  ``None`` by default; populated when
        ``respond()`` is called with ``include_debug=True``.
    """
    final_text:    str
    outcome:       str
    supported:     bool
    intent:        str
    review_passed: bool
    llm_used:      bool
    debug:         FinalResponseDebug | None


# ---------------------------------------------------------------------------
# Final-response policy constant
# ---------------------------------------------------------------------------

#: Human-readable summary of the ``final_text`` selection policy.
FINAL_TEXT_POLICY: str = (
    "final_text = review.safe_text: "
    "llm_text when (llm_called AND review_passed), "
    "response_text otherwise"
)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def respond(
    user_message: str,
    bootstrap: dict[str, Any],
    *,
    client: Any = None,
    model: str = DEFAULT_MODEL,
    candidate_inputs: dict[str, Any] | None = None,
    candidates_list: list[dict[str, Any]] | None = None,
    api_key: str | None = None,
    include_debug: bool = False,
) -> FinalResponse:
    """Run the full pipeline and return a single caller-facing ``FinalResponse``.

    This is the recommended entrypoint for external callers.  It orchestrates
    the complete stack — ``adapt()`` → ``ask_llm()`` → ``review_llm_response()``
    — and applies the unified final-response policy to produce a single clean
    object without exposing internal ambiguity.

    Parameters
    ----------
    user_message:
        Raw user question.
    bootstrap:
        FPL bootstrap dict (or assembled context from
        ``assemble_captain_context()``).
    client:
        Optional pre-built ``anthropic.Anthropic`` instance.  When ``None``,
        ``ask_llm()`` uses ``api_key`` or ``ANTHROPIC_API_KEY`` env var.
    model:
        Anthropic model identifier.  Defaults to ``DEFAULT_MODEL``.
    candidate_inputs:
        Optional scoring overrides forwarded to ``adapt()``.
    candidates_list:
        Optional list of candidate dicts forwarded to ``adapt()``.
    api_key:
        Explicit API key (only used when ``client`` is ``None``).
    include_debug:
        When ``True``, populate ``FinalResponse.debug`` with internal fields
        (``llm_text``, ``response_text``, ``violations``, ``prompt_used``,
        ``model``).  Defaults to ``False``.

    Returns
    -------
    FinalResponse
        Always returns — never raises.

    Notes
    -----
    ``FinalResponse.final_text`` policy (authoritative):

    * LLM called + review passed  →  ``final_text = llm_text``
    * LLM not called (fallback)   →  ``final_text = response_text``
    * LLM called + review failed  →  ``final_text = response_text``

    ``llm_used`` captures whether LLM text is actually in ``final_text``:
    ``llm_used = lr.llm_called and review.passed``.
    """
    lr, review = ask_llm_safe(
        user_message,
        bootstrap,
        client=client,
        model=model,
        candidate_inputs=candidate_inputs,
        candidates_list=candidates_list,
        api_key=api_key,
    )

    ar = lr.adapter_response
    dr = ar.dispatch_result

    # -----------------------------------------------------------------------
    # Final-response policy — single explicit rule
    # -----------------------------------------------------------------------
    final_text    = review.safe_text                   # encodes the full fallback logic
    review_passed = review.passed
    llm_used      = lr.llm_called and review.passed    # LLM text generated AND accepted

    # -----------------------------------------------------------------------
    # Debug bundle (opt-in only)
    # -----------------------------------------------------------------------
    debug: FinalResponseDebug | None = None
    if include_debug:
        debug = FinalResponseDebug(
            llm_text=lr.llm_text,
            response_text=ar.response_text,
            violations=review.violations,
            prompt_used=lr.prompt_used,
            model=lr.model,
        )

    return FinalResponse(
        final_text=final_text,
        outcome=dr.outcome,
        supported=ar.supported,
        intent=dr.intent,
        review_passed=review_passed,
        llm_used=llm_used,
        debug=debug,
    )
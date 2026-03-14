"""
fpl_grounded_assistant.llm_review
==================================
Deterministic safety and parity review for LLM-generated responses.

Phase 3b: LLM behavior hardening and parity checks.

This module provides a lightweight, entirely deterministic review layer that
runs *after* ``ask_llm()`` returns.  It checks whether ``llm_text`` is
semantically aligned with the grounded backend result and flags known
categories of unsafe drift without making any further LLM calls.

Design principles
-----------------
* **No LLM calls** — all checks are string / regex operations.
* **Single responsibility** — this module only inspects; it does not modify
  the LLM response.  Callers decide what to do with violations.
* **Safe fallback** — ``ReviewResult.safe_text`` is ``llm_text`` when the
  review passes; it falls back to ``adapter_response.response_text`` (the
  deterministic ground truth) when violations are found.
* **Conservative checks** — checks target well-defined categories of harm
  (invented numbers, overconfidence on failure outcomes, false ambiguity
  resolution) rather than open-ended semantic similarity.

Violation taxonomy
------------------
``VIOLATION_OVERCONFIDENT_NON_OK``
    An overconfident phrase ("definitely", "certainly", etc.) appeared in
    ``llm_text`` for a non-ok outcome.  The grounded backend communicated
    a failure (not_found, ambiguous, missing_arguments, error, or
    unsupported_intent); the LLM must not paper over that.

``VIOLATION_INVENTED_NUMBERS``
    A number appeared in ``llm_text`` that is not present in
    ``response_text`` for a non-ok outcome.  Invented scores, percentages,
    or stats are the primary form of factual hallucination risk.

``VIOLATION_AMBIGUOUS_FALSE_RESOLUTION``
    A phrase that claims or implies a single player was identified appeared
    in ``llm_text`` when the outcome was ``OUTCOME_AMBIGUOUS``.  The LLM
    must not silently resolve an ambiguous lookup.

``VIOLATION_EMPTY_LLM_TEXT``
    The LLM was called (``llm_called=True``) but returned an empty string.
    An empty response cannot safely be surfaced to a user.

Safe fallback invariant
-----------------------
When ``llm_called=False`` (deterministic fallback used), ``llm_text`` is
identical to ``response_text``.  The ``_check_numeric_invention`` function
always passes in that case because the two strings are the same.  The
other checks may still trigger if the underlying deterministic response
itself contains overconfident or resolution-implying phrases, but the
controlled phrasing of the backend makes this extremely unlikely.

Intentionally deferred
-----------------------
* Semantic similarity scoring between ``llm_text`` and ``response_text``
* Embedding-based drift detection
* Multi-turn coherence checks
* LLM-assisted review (would defeat the deterministic guarantee)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .dispatcher import (
    OUTCOME_OK,
    OUTCOME_UNSUPPORTED_INTENT,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
    OUTCOME_ERROR,
)

if TYPE_CHECKING:
    from .llm_layer import LLMResponse


# ---------------------------------------------------------------------------
# Violation type constants
# ---------------------------------------------------------------------------

VIOLATION_OVERCONFIDENT_NON_OK: str = "overconfident_non_ok"
"""Overconfident phrase found in llm_text for a non-ok outcome."""

VIOLATION_INVENTED_NUMBERS: str = "invented_numbers"
"""Numbers in llm_text not present in response_text for non-ok outcomes."""

VIOLATION_AMBIGUOUS_FALSE_RESOLUTION: str = "ambiguous_false_resolution"
"""Resolution phrase found in llm_text when outcome is ambiguous."""

VIOLATION_EMPTY_LLM_TEXT: str = "empty_llm_text"
"""LLM was called but returned empty text."""


# ---------------------------------------------------------------------------
# Non-ok outcomes set (used by multiple checks)
# ---------------------------------------------------------------------------

_NON_OK_OUTCOMES: frozenset[str] = frozenset([
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
    OUTCOME_ERROR,
    OUTCOME_UNSUPPORTED_INTENT,
])


# ---------------------------------------------------------------------------
# Phrase lists (all lowercase for case-insensitive matching)
# ---------------------------------------------------------------------------

_OVERCONFIDENT_PHRASES: frozenset[str] = frozenset([
    "definitely",
    "certainly",
    "guaranteed",
    "i can confirm",
    "without doubt",
    "without a doubt",
    "for certain",
    "i guarantee",
    "no question about it",
    "absolutely certain",
    "100% sure",
    "i'm positive",
])

_AMBIGUOUS_RESOLUTION_PHRASES: frozenset[str] = frozenset([
    "that would be",
    "the player you're looking for is",
    "the player you are looking for is",
    "i recommend going with",
    "you should go with",
    "they are",
    "he is definitely",
    "she is definitely",
    "must be",
    "it's clearly",
    "it is clearly",
    "based on context, that's",
    "based on context, that is",
    "clearly referring to",
])


# ---------------------------------------------------------------------------
# Individual check functions (private, exported for testing)
# ---------------------------------------------------------------------------

def _check_overconfidence(llm_text: str, outcome: str) -> list[str]:
    """Return violations for overconfident phrases in non-ok outcomes.

    Parameters
    ----------
    llm_text:
        The text produced by the LLM (or deterministic fallback).
    outcome:
        The ``OUTCOME_*`` constant from the grounded backend.

    Returns
    -------
    list[str]
        Zero or more violation strings.  Each string begins with
        ``VIOLATION_OVERCONFIDENT_NON_OK``.
    """
    if outcome not in _NON_OK_OUTCOMES:
        return []
    lower = llm_text.lower()
    violations: list[str] = []
    for phrase in sorted(_OVERCONFIDENT_PHRASES):
        if phrase in lower:
            violations.append(
                f"{VIOLATION_OVERCONFIDENT_NON_OK}: "
                f"phrase {phrase!r} in llm_text for outcome={outcome!r}"
            )
    return violations


def _check_numeric_invention(
    llm_text: str,
    response_text: str,
    outcome: str,
) -> list[str]:
    """Return violations for numbers in llm_text not present in response_text.

    Only checked for non-ok outcomes.  For ok outcomes the LLM is allowed to
    reformulate grounded numbers freely (e.g. "72/100" → "72 out of 100").

    Parameters
    ----------
    llm_text:
        The text produced by the LLM (or deterministic fallback).
    response_text:
        The deterministic response text from the grounded backend.
    outcome:
        The ``OUTCOME_*`` constant from the grounded backend.

    Returns
    -------
    list[str]
        Zero or more violation strings beginning with
        ``VIOLATION_INVENTED_NUMBERS``.
    """
    if outcome not in _NON_OK_OUTCOMES:
        return []

    _NUMBER_RE = re.compile(r'\b\d+(?:\.\d+)?\b')
    response_numbers: frozenset[str] = frozenset(
        _NUMBER_RE.findall(response_text)
    )
    llm_numbers: frozenset[str] = frozenset(
        _NUMBER_RE.findall(llm_text)
    )
    invented = llm_numbers - response_numbers

    violations: list[str] = []
    for n in sorted(invented, key=lambda x: float(x)):
        violations.append(
            f"{VIOLATION_INVENTED_NUMBERS}: "
            f"number {n!r} in llm_text not found in response_text "
            f"for outcome={outcome!r}"
        )
    return violations


def _check_ambiguous_false_resolution(
    llm_text: str,
    outcome: str,
) -> list[str]:
    """Return violations for resolution phrases when outcome is ambiguous.

    The LLM must not silently resolve an ambiguous player lookup by naming
    a specific player as the answer.

    Parameters
    ----------
    llm_text:
        The text produced by the LLM (or deterministic fallback).
    outcome:
        The ``OUTCOME_*`` constant from the grounded backend.

    Returns
    -------
    list[str]
        Zero or more violation strings beginning with
        ``VIOLATION_AMBIGUOUS_FALSE_RESOLUTION``.
    """
    if outcome != OUTCOME_AMBIGUOUS:
        return []
    lower = llm_text.lower()
    violations: list[str] = []
    for phrase in sorted(_AMBIGUOUS_RESOLUTION_PHRASES):
        if phrase in lower:
            violations.append(
                f"{VIOLATION_AMBIGUOUS_FALSE_RESOLUTION}: "
                f"resolution phrase {phrase!r} in llm_text "
                f"for outcome=ambiguous"
            )
    return violations


def _check_empty_llm_text(llm_text: str, llm_called: bool) -> list[str]:
    """Return a violation when the LLM was called but returned empty text.

    Parameters
    ----------
    llm_text:
        The (possibly empty) text produced by the LLM.
    llm_called:
        Whether an actual API call was made.

    Returns
    -------
    list[str]
        Zero or one violation strings beginning with
        ``VIOLATION_EMPTY_LLM_TEXT``.
    """
    if llm_called and llm_text == "":
        return [f"{VIOLATION_EMPTY_LLM_TEXT}: LLM was called but returned empty text"]
    return []


# ---------------------------------------------------------------------------
# ReviewResult dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReviewResult:
    """The output of a single ``review_llm_response()`` call.

    Attributes
    ----------
    passed:
        ``True`` if no violations were found; ``False`` otherwise.
    violations:
        Tuple of violation strings.  Empty when ``passed=True``.
        Each string begins with a ``VIOLATION_*`` constant.
    llm_response:
        The ``LLMResponse`` that was reviewed.  Preserved for
        debugging and regression tests.
    safe_text:
        The text safe to surface to the user.  Equals
        ``llm_response.llm_text`` when ``passed=True``;
        falls back to ``llm_response.adapter_response.response_text``
        when ``passed=False``.
    """
    passed:       bool
    violations:   tuple[str, ...]
    llm_response: Any   # LLMResponse — Any avoids circular import at runtime
    safe_text:    str


# ---------------------------------------------------------------------------
# Main review function
# ---------------------------------------------------------------------------

def review_llm_response(llm_response: "LLMResponse") -> ReviewResult:
    """Deterministically review an ``LLMResponse`` for safety and parity.

    Runs all four violation checks and assembles a ``ReviewResult``.

    Parameters
    ----------
    llm_response:
        The response to review, as returned by ``ask_llm()``.

    Returns
    -------
    ReviewResult
        Always returns — never raises.  When ``passed=False``,
        ``safe_text`` is the deterministic fallback.
    """
    ar = llm_response.adapter_response
    outcome = ar.dispatch_result.outcome
    llm_text = llm_response.llm_text
    response_text = ar.response_text

    all_violations: list[str] = []
    all_violations += _check_overconfidence(llm_text, outcome)
    all_violations += _check_numeric_invention(llm_text, response_text, outcome)
    all_violations += _check_ambiguous_false_resolution(llm_text, outcome)
    all_violations += _check_empty_llm_text(llm_text, llm_response.llm_called)

    passed = len(all_violations) == 0
    safe_text = llm_text if passed else response_text

    return ReviewResult(
        passed=passed,
        violations=tuple(all_violations),
        llm_response=llm_response,
        safe_text=safe_text,
    )


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def ask_llm_safe(
    user_message: str,
    bootstrap: dict[str, Any],
    *,
    client: Any = None,
    model: str | None = None,
    candidate_inputs: dict[str, Any] | None = None,
    candidates_list: list[dict[str, Any]] | None = None,
    api_key: str | None = None,
) -> tuple["LLMResponse", ReviewResult]:
    """Run ``ask_llm()`` then immediately review the response.

    This is the recommended outer entrypoint when the caller wants both
    the LLM presentation and a safety/parity guarantee.  The caller can
    use ``review.safe_text`` to get text that has been validated against
    the grounded backend, or inspect ``review.violations`` for diagnostics.

    Parameters
    ----------
    user_message:
        Raw user question.
    bootstrap:
        FPL bootstrap dict (or assembled context).
    client:
        Optional pre-built ``anthropic.Anthropic`` instance.
    model:
        Anthropic model identifier.  Defaults to ``DEFAULT_MODEL``.
    candidate_inputs:
        Optional scoring overrides forwarded to ``adapt()``.
    candidates_list:
        Optional candidate list forwarded to ``adapt()``.
    api_key:
        Explicit API key (only used when ``client`` is ``None``).

    Returns
    -------
    tuple[LLMResponse, ReviewResult]
        Always returns — never raises.
    """
    from .llm_layer import ask_llm, DEFAULT_MODEL as _DEFAULT_MODEL
    resolved_model = model if model is not None else _DEFAULT_MODEL

    llm_response = ask_llm(
        user_message,
        bootstrap,
        client=client,
        model=resolved_model,
        candidate_inputs=candidate_inputs,
        candidates_list=candidates_list,
        api_key=api_key,
    )
    review = review_llm_response(llm_response)
    return llm_response, review
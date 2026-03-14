"""
fpl_grounded_assistant.llm_layer
=================================
Minimal LLM integration layer over the deterministic adapter.

Phase 3a: Minimal real LLM integration.

This module is the outermost layer of the fpl-grounded-assistant stack.
It accepts a user message, runs the deterministic adapter pipeline, then
optionally passes the result to an LLM for natural-language presentation.

Architecture
------------
::

    ask_llm()
      └── adapt()          ← deterministic adapter  (Phase 2m)
            └── dispatch() ← typed dispatcher        (Phase 2k/2l)
                  └── ask()  ← grounded harness      (Phase 1h)

The LLM's role is strictly **presentation**:

* It receives the grounded result (intent, outcome, answer_text) and formats
  a natural, helpful response for the user.
* It may NOT alter the outcome, re-route the question, or fabricate data.
* If the LLM is unavailable or raises, ``ask_llm()`` falls back to
  ``adapter_response.response_text`` and sets ``llm_called=False``.

Fallback behaviour
------------------
When no Anthropic client is available (missing API key or missing
``anthropic`` package), ``ask_llm()`` returns an ``LLMResponse`` with:

* ``llm_text``   = ``adapter_response.response_text``  (deterministic fallback)
* ``llm_called`` = ``False``
* ``model``      = ``"none"``

This means the full test suite passes without any API key or network access.
The conditional LLM-call section in ``run_phase3a_tests.py`` is skipped when
``ANTHROPIC_API_KEY`` is not set.

Intentionally deferred
-----------------------
* Multi-turn conversation memory
* Pronoun resolution (\"What about his form?\")
* Combined intents (\"Who is Salah and what gameweek is it?\")
* UI integration
* LLM-based intent classification (routing stays deterministic)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .adapter import adapt, AdapterResponse
from .dispatcher import (
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
    OUTCOME_ERROR,
    OUTCOME_UNSUPPORTED_INTENT,
)

# ---------------------------------------------------------------------------
# Optional anthropic import — gracefully absent
# ---------------------------------------------------------------------------

try:
    import anthropic as _anthropic_module  # type: ignore[import-untyped]
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _anthropic_module = None  # type: ignore[assignment]
    _ANTHROPIC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL: str = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT: str = (
    "You are a Fantasy Premier League (FPL) assistant. "
    "You have been given the output of a deterministic grounded backend "
    "that has already fetched and computed the correct factual answer. "
    "Your job is to present that answer to the user in a natural, concise, "
    "and helpful way. "
    "\n\n"
    "RULES — follow these strictly:\n"
    "1. Do NOT contradict the grounded result provided in the user turn.\n"
    "2. Do NOT fabricate statistics, player names, scores, or rankings.\n"
    "3. Do NOT attempt to answer questions outside the provided grounded result.\n"
    "4. Keep responses brief (1-3 sentences unless the result is a ranked list).\n"
    "5. If the result is an error or unsupported outcome, communicate it "
    "   clearly and politely without guessing at an answer.\n"
    "6. The grounded result is authoritative — trust it completely.\n"
)

# Per-outcome instruction appended to the user turn so the LLM understands
# what to do with each result type.
_OUTCOME_INSTRUCTION: dict[str, str] = {
    OUTCOME_OK: (
        "The request succeeded. Present the grounded answer to the user "
        "in a friendly, natural way. Do not add information not present "
        "in the grounded answer."
    ),
    OUTCOME_NOT_FOUND: (
        "The player was not found in the FPL registry. Politely inform the "
        "user that no matching player was found and suggest they check the "
        "spelling or use a different name."
    ),
    OUTCOME_AMBIGUOUS: (
        "Multiple players matched the query. Inform the user of the ambiguity "
        "and ask them to be more specific (e.g. use first name or full name)."
    ),
    OUTCOME_MISSING_ARGUMENTS: (
        "A required input was missing. Inform the user what additional "
        "information is needed to complete the request."
    ),
    OUTCOME_ERROR: (
        "An unexpected backend error occurred. Apologise briefly and suggest "
        "the user try again. Do not speculate on the cause."
    ),
    OUTCOME_UNSUPPORTED_INTENT: (
        "This question is outside the scope of the FPL assistant. Politely "
        "explain that you can help with captain picks, player summaries, "
        "gameweek information, and player identity — and that this question "
        "falls outside those areas."
    ),
}


# ---------------------------------------------------------------------------
# LLMResponse dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LLMResponse:
    """The output of a single ``ask_llm()`` call.

    Attributes
    ----------
    user_message:
        The original user message, preserved verbatim.
    adapter_response:
        The full ``AdapterResponse`` from the deterministic backend.
        Contains the ground truth — intent, outcome, raw_output, etc.
    llm_text:
        The final text to surface to the user.  Either the LLM-generated
        presentation (when ``llm_called=True``) or the deterministic
        fallback ``adapter_response.response_text`` (when ``llm_called=False``).
    prompt_used:
        The user-turn prompt that was (or would have been) sent to the LLM.
        Always populated — useful for debugging and regression tests.
    model:
        The model identifier used for the LLM call, or ``"none"`` when
        the deterministic fallback was used.
    llm_called:
        ``True`` if an actual Anthropic API call was made; ``False`` if
        the deterministic fallback was used (no API key, no client, or error).
    """
    user_message:     str
    adapter_response: AdapterResponse
    llm_text:         str
    prompt_used:      str
    model:            str
    llm_called:       bool


# ---------------------------------------------------------------------------
# Prompt builder — pure function, fully testable without API
# ---------------------------------------------------------------------------

def build_user_prompt(adapter_response: AdapterResponse) -> str:
    """Build the user-turn prompt for the LLM from an ``AdapterResponse``.

    This is a pure function — no side effects, fully deterministic, and
    testable without any API key or network access.

    The prompt packages:
    * The original user question
    * The grounded outcome and intent
    * The deterministic response text
    * A per-outcome instruction telling the LLM what to do

    Parameters
    ----------
    adapter_response:
        The ``AdapterResponse`` produced by ``adapt()``.

    Returns
    -------
    str
        The user-turn prompt ready to send to the LLM.
    """
    dr = adapter_response.dispatch_result
    outcome = dr.outcome
    instruction = _OUTCOME_INSTRUCTION.get(outcome, _OUTCOME_INSTRUCTION[OUTCOME_ERROR])

    lines = [
        f"User question: {adapter_response.user_message}",
        "",
        "--- Grounded backend result ---",
        f"Intent:   {dr.intent}",
        f"Outcome:  {outcome}",
        f"Grounded answer: {adapter_response.response_text}",
        "-------------------------------",
        "",
        f"Instruction: {instruction}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_anthropic_client(api_key: str | None = None):  # type: ignore[return]
    """Return an Anthropic client or ``None`` if unavailable.

    Parameters
    ----------
    api_key:
        Explicit API key.  If ``None``, falls back to the
        ``ANTHROPIC_API_KEY`` environment variable.

    Returns
    -------
    anthropic.Anthropic | None
    """
    if not _ANTHROPIC_AVAILABLE:
        return None
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        return _anthropic_module.Anthropic(api_key=key)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def ask_llm(
    user_message: str,
    bootstrap: dict[str, Any],
    *,
    client: Any = None,
    model: str = DEFAULT_MODEL,
    candidate_inputs: dict[str, Any] | None = None,
    candidates_list: list[dict[str, Any]] | None = None,
    api_key: str | None = None,
) -> LLMResponse:
    """Run the full grounded + LLM pipeline for a user message.

    Steps
    -----
    1. Run ``adapt()`` — deterministic grounded backend.
    2. Build the user-turn prompt via ``build_user_prompt()``.
    3. If a client is available, call the Anthropic API and use the result.
    4. On any error or when no client is available, fall back to
       ``adapter_response.response_text``.

    Parameters
    ----------
    user_message:
        Raw user question.
    bootstrap:
        FPL bootstrap dict (or assembled context).
    client:
        Optional pre-built ``anthropic.Anthropic`` instance.  Useful for
        testing with a mock client.  If ``None``, the function attempts to
        build one from ``api_key`` or ``ANTHROPIC_API_KEY``.
    model:
        Anthropic model identifier to use for the LLM call.
    candidate_inputs:
        Optional scoring overrides forwarded to ``adapt()``.
    candidates_list:
        Optional candidate list forwarded to ``adapt()``.
    api_key:
        Explicit API key (only used when ``client`` is ``None``).

    Returns
    -------
    LLMResponse
        Always returns — never raises.  When the LLM is unavailable or
        fails, ``llm_called=False`` and ``llm_text`` is the deterministic
        fallback.
    """
    # Step 1: deterministic backend — always runs
    adapter_response = adapt(
        user_message,
        bootstrap,
        candidate_inputs=candidate_inputs,
        candidates_list=candidates_list,
    )

    # Step 2: build prompt — always built (for debugging even in fallback mode)
    prompt_used = build_user_prompt(adapter_response)

    # Step 3: resolve client
    resolved_client = client or _get_anthropic_client(api_key=api_key)

    if resolved_client is None:
        # Deterministic fallback — no LLM available
        return LLMResponse(
            user_message=user_message,
            adapter_response=adapter_response,
            llm_text=adapter_response.response_text,
            prompt_used=prompt_used,
            model="none",
            llm_called=False,
        )

    # Step 4: LLM call — wrapped in try/except so errors always fall back
    try:
        message = resolved_client.messages.create(
            model=model,
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt_used}],
        )
        llm_text = message.content[0].text.strip()
        return LLMResponse(
            user_message=user_message,
            adapter_response=adapter_response,
            llm_text=llm_text,
            prompt_used=prompt_used,
            model=model,
            llm_called=True,
        )
    except Exception:  # noqa: BLE001
        # Any API error → deterministic fallback
        return LLMResponse(
            user_message=user_message,
            adapter_response=adapter_response,
            llm_text=adapter_response.response_text,
            prompt_used=prompt_used,
            model="none",
            llm_called=False,
        )
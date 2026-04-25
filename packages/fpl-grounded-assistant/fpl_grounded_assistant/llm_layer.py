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

import logging
import os
from dataclasses import dataclass
from typing import Any

from .adapter import adapt, AdapterResponse
from .orch_config import get_orch_max_retries, get_orch_timeout
from .provider_client import (
    get_provider,
    ProviderNotAvailableError,
)
from .dispatcher import (
    OUTCOME_OK,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
    OUTCOME_ERROR,
    OUTCOME_UNSUPPORTED_INTENT,
)

# ---------------------------------------------------------------------------
# Anthropic import — kept for _get_anthropic_client() backwards compat
# (orchestrator.py and reference_resolver.py import that helper from here)
# ---------------------------------------------------------------------------

try:
    import anthropic as _anthropic_module  # type: ignore[import-untyped]
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _anthropic_module = None  # type: ignore[assignment]
    _ANTHROPIC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Provider constants — canonical definitions live in provider_client; re-export
# here so existing callers (orchestrator.py, reference_resolver.py) still work.
# ---------------------------------------------------------------------------

from .provider_client import (  # noqa: E402  (import after stdlib block)
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    PROVIDER_GEMINI,
)

# Per-provider default model identifiers.
_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    PROVIDER_GEMINI:    "gemini-2.5-flash",
    PROVIDER_ANTHROPIC: "claude-haiku-4-5-20251001",
    PROVIDER_OPENAI:    "gpt-4o-mini",
}

# Active provider — read once at module load from DEFAULT_PROVIDER env var.
# Defaults to Gemini. Falls back to "gemini" for any unrecognised value.
_PROVIDER: str = os.environ.get("DEFAULT_PROVIDER", PROVIDER_GEMINI).lower()

DEFAULT_MODEL: str = _PROVIDER_DEFAULT_MODELS.get(_PROVIDER, "gemini-1.5-flash")

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

# ---------------------------------------------------------------------------
# Context injection (Phase 9b)
# ---------------------------------------------------------------------------

#: Maximum characters of FPL data context to inject into the system prompt.
#: Content beyond this limit is truncated with an explicit marker so the LLM
#: knows the data was cut, rather than silently receiving a partial block.
_MAX_CONTEXT_CHARS: int = 6000

_CONTEXT_SECTION_HEADER: str = (
    "\n\n"
    "--- FPL DATA CONTEXT (deterministic, from live bootstrap) ---\n"
    "The following is real-time FPL data computed from the live API. "
    "You may reference this data when presenting answers. "
    "Do NOT invent facts not present here or in the grounded result below.\n"
)

_CONTEXT_SECTION_FOOTER: str = (
    "\n--- END FPL DATA CONTEXT ---"
)

_CONTEXT_TRUNCATION_MARKER: str = (
    "\n[... context truncated to fit prompt budget ...]"
)

_LOG = logging.getLogger(__name__)


def build_system_prompt(bootstrap: dict) -> str:
    """Build the LLM system prompt with injected FPL data context.

    Combines the static ``SYSTEM_PROMPT`` with a deterministic FPL data
    context block produced by ``build_orchestration_context(bootstrap)``.
    The context is clearly delimited so the LLM knows where live data
    starts and ends.

    If context generation raises for any reason, the function degrades
    silently and returns the base ``SYSTEM_PROMPT`` without crashing.

    If the generated context exceeds ``_MAX_CONTEXT_CHARS`` characters, the
    tail is truncated and a marker is appended so the LLM is aware data was
    cut, rather than receiving a silently incomplete block.

    Parameters
    ----------
    bootstrap:
        FPL bootstrap dict (with or without fixture fields injected by
        ``assemble_captain_context()``).  Passed directly to
        ``build_orchestration_context()``.

    Returns
    -------
    str
        System prompt ready to pass to the LLM API.  Always returns at
        least ``SYSTEM_PROMPT`` — never raises.
    """
    try:
        from .context_builder import build_orchestration_context  # noqa: PLC0415
        context_text = build_orchestration_context(bootstrap)
    except Exception:  # noqa: BLE001
        # Context unavailable — return base prompt unchanged.
        return SYSTEM_PROMPT

    # Cap context length to protect against very large bootstraps
    if len(context_text) > _MAX_CONTEXT_CHARS:
        context_text = context_text[:_MAX_CONTEXT_CHARS] + _CONTEXT_TRUNCATION_MARKER

    return (
        SYSTEM_PROMPT
        + _CONTEXT_SECTION_HEADER
        + context_text
        + _CONTEXT_SECTION_FOOTER
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


def _fallback_llm_response(
    *,
    user_message: str,
    adapter_response: AdapterResponse,
    prompt_used: str,
) -> LLMResponse:
    """Return deterministic fallback response preserving contract semantics."""
    return LLMResponse(
        user_message=user_message,
        adapter_response=adapter_response,
        llm_text=adapter_response.response_text,
        prompt_used=prompt_used,
        model="none",
        llm_called=False,
    )


def _log_provider_failure(provider: str, error_code: str | None, error_msg: str | None, attempts: int) -> None:
    """Emit traceable provider failure logs without exposing credentials."""
    _LOG.warning(
        "ask_llm provider failure provider=%s code=%s attempts=%s msg=%s",
        provider,
        error_code or "unknown",
        attempts,
        error_msg or "",
    )


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
    classifier_client: Any = None,
    intent_hint: str | None = None,
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
        classifier_client=classifier_client,
        intent_hint=intent_hint,
    )

    # Step 2: build prompt — always built (for debugging even in fallback mode)
    prompt_used = build_user_prompt(adapter_response)

    timeout_s = get_orch_timeout()
    max_retries = get_orch_max_retries()
    system_prompt = build_system_prompt(bootstrap)

    # Step 3: dispatch through unified provider factory.
    # An explicit ``client`` argument always routes to AnthropicProvider for
    # backwards compatibility (test mocks pass Anthropic instances here).
    # Otherwise the active provider is read from _PROVIDER.
    try:
        provider = get_provider(_PROVIDER, client=client, api_key=api_key)
    except ProviderNotAvailableError:
        return _fallback_llm_response(
            user_message=user_message,
            adapter_response=adapter_response,
            prompt_used=prompt_used,
        )

    result = provider.call(
        model=model,
        system_prompt=system_prompt,
        user_message=prompt_used,
        max_tokens=256,
        timeout_s=timeout_s,
        max_retries=max_retries,
    )

    if result.error_code is not None:
        _log_provider_failure(
            _PROVIDER,
            result.error_code,
            result.error_msg,
            result.attempts,
        )
        return _fallback_llm_response(
            user_message=user_message,
            adapter_response=adapter_response,
            prompt_used=prompt_used,
        )

    return LLMResponse(
        user_message=user_message,
        adapter_response=adapter_response,
        llm_text=result.text or "",
        prompt_used=prompt_used,
        model=result.model,
        llm_called=True,
    )
"""
fpl_grounded_assistant.orchestrator
=====================================
Phase Orch-3b: ask_orchestrated() — provider-dispatch parity.

Extends the Orch-3a single-tool-call skeleton to support three LLM provider
response shapes: Anthropic tool_use, OpenAI function-calling, and Gemini
function-call.  The existing deterministic ``respond()`` / ``dispatch()`` /
``ask_llm()`` paths are **not modified**.

Architecture
------------
::

    ask_orchestrated()
      ├── build_system_prompt(bootstrap)     <- Phase 9b context injection
      ├── _build_tools(provider)             <- provider-appropriate tool list
      ├── client.messages.create(tools=...)  <- single LLM tool-use call
      ├── _parse_tool_call(response, prov)   <- provider-aware response parsing
      ├── run_tool(tool_name, tool_args, bs) <- deterministic execution
      └── render(tool_name, raw_output)      <- existing renderer

Provider shapes supported (Orch-3b)
------------------------------------
* Anthropic: ``response.content[i].type == "tool_use"``, ``.name``, ``.input``
  (dict).  Tool list format: ``[{"name", "description", "input_schema"}, ...]``.
* OpenAI: ``response.choices[0].message.tool_calls[0].function.name``,
  ``.function.arguments`` (JSON **string** — must be ``json.loads()``'d).
  Tool list format: ``[{"type": "function", "function": {...}}, ...]``.
* Gemini: ``response.candidates[0].content.parts[0].function_call.name``,
  ``.function_call.args`` (dict-like).
  Tool list format: ``[{"function_declarations": [...]}]``.

Auto-detection (provider=None)
-------------------------------
When no explicit provider is given the orchestrator defaults to Anthropic tool
list format (backward-compatible with Orch-3a) and tries all three response
parsers in Anthropic -> OpenAI -> Gemini order.

Outcome constants (Orch-3b additions)
--------------------------------------
* ``OUTCOME_TOOL_RESULT_ERROR``: tool ran and returned ``status != "ok"``.
  Distinguishes from ``OUTCOME_TOOL_ERROR`` (``run_tool()`` raised) and
  ``OUTCOME_OK`` (``status == "ok"``).
* Total outcomes: 7 (OUTCOME_OK, OUTCOME_NO_CLIENT, OUTCOME_LLM_ERROR,
  OUTCOME_NO_TOOL, OUTCOME_UNKNOWN_TOOL, OUTCOME_TOOL_ERROR,
  OUTCOME_TOOL_RESULT_ERROR).

Design invariants
-----------------
* Schema registry is the **only** source of tool definitions.
* Tool execution is **always** deterministic (run_tool / TOOL_REGISTRY).
* The LLM may choose a tool, but it cannot alter the grounded answer.
* Every failure path returns a safe, structured ``OrchestratorResult``
  — no exceptions are allowed to escape ask_orchestrated().

Wiring status
-------------
* ask_orchestrated() is NOT wired into respond(), adapt(), dispatch(),
  CLI, HTTP, or session endpoints.  It is additive and isolated.
* Future Orch-4 will wire it into endpoints behind a feature flag.

TOOL_REGISTRY population note
------------------------------
When this module is imported as part of the ``fpl_grounded_assistant``
package (which is the normal usage), ``__init__.py`` imports all tool
submodules (comparison, chip_advisor, etc.) which register themselves in
``TOOL_REGISTRY`` as side-effects.  After package import, run_tool() handles
all 10 grounded tools.  Importing this module in isolation (without the full
package __init__) will leave TOOL_REGISTRY with only 5 tools (the fpl-tool-
runner originals); in that case tools like compare_players will return a
graceful ``status='error'`` unknown-tool result.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from fpl_tool_runner import run_tool

from .llm_layer import (
    _get_anthropic_client,
    _CONTEXT_SECTION_HEADER,
    _CONTEXT_SECTION_FOOTER,
    _CONTEXT_TRUNCATION_MARKER,
    _MAX_CONTEXT_CHARS,
)
from .orch_config import get_orch_max_retries, get_orch_timeout
from .provider_client import (
    PERR_AUTH,
    PERR_NETWORK,
    PERR_RATE_LIMIT,
    PERR_TIMEOUT,
    OrchCallResult,
    ProviderResult,
    call_orch_provider,
)
from .renderer import render
from .tool_schema_registry import _ALL_SCHEMAS, TOOL_NAMES

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider constants
# ---------------------------------------------------------------------------

#: Anthropic tool_use response shape.
PROVIDER_ANTHROPIC: str = "anthropic"

#: OpenAI function-calling response shape.
PROVIDER_OPENAI: str = "openai"

#: Gemini function-call response shape.
PROVIDER_GEMINI: str = "gemini"

_ALL_PROVIDERS: frozenset[str] = frozenset({
    PROVIDER_ANTHROPIC, PROVIDER_OPENAI, PROVIDER_GEMINI,
})


# ---------------------------------------------------------------------------
# Outcome constants
# ---------------------------------------------------------------------------

#: Tool executed successfully and returned status == "ok".
OUTCOME_OK:                str = "ok"
#: No LLM client was available (no API key, no explicit client).
OUTCOME_NO_CLIENT:         str = "no_client"
#: The LLM API call raised an exception.
OUTCOME_LLM_ERROR:         str = "llm_error"
#: The LLM responded without a tool-call block (plain text or stop).
OUTCOME_NO_TOOL:           str = "no_tool"
#: The LLM chose a tool name not in the registry.
OUTCOME_UNKNOWN_TOOL:      str = "unknown_tool"
#: run_tool() raised an unexpected exception.
OUTCOME_TOOL_ERROR:        str = "tool_error"
#: run_tool() succeeded but returned status != "ok" (e.g. missing_argument).
OUTCOME_TOOL_RESULT_ERROR: str = "tool_result_error"
#: Provider call skipped because the degradation gate is open (cooldown active).
OUTCOME_COOLDOWN: str = "cooldown"

_ALL_OUTCOMES: frozenset[str] = frozenset({
    OUTCOME_OK, OUTCOME_NO_CLIENT, OUTCOME_COOLDOWN, OUTCOME_LLM_ERROR,
    OUTCOME_NO_TOOL, OUTCOME_UNKNOWN_TOOL, OUTCOME_TOOL_ERROR,
    OUTCOME_TOOL_RESULT_ERROR,
})


# ---------------------------------------------------------------------------
# Degradation gate (Phase 2.5d1)
# ---------------------------------------------------------------------------

#: Error codes that count toward transient-failure accumulation.
#: Auth errors and hard provider errors are intentionally excluded —
#: they are non-transient and retrying immediately will not help.
_TRANSIENT_PERR: frozenset[str] = frozenset({PERR_TIMEOUT, PERR_RATE_LIMIT, PERR_NETWORK})

# Env var names for gate configuration (all optional; safe defaults apply).
_GATE_THRESHOLD_ENV: str  = "FPL_ORCH_FAILURE_THRESHOLD"
_GATE_WINDOW_ENV:    str  = "FPL_ORCH_FAILURE_WINDOW_S"
_GATE_COOLDOWN_ENV:  str  = "FPL_ORCH_COOLDOWN_S"

_DEFAULT_THRESHOLD:  int   = 3
_DEFAULT_WINDOW_S:   float = 60.0
_DEFAULT_COOLDOWN_S: float = 30.0


class _FailureGate:
    """In-process degradation gate for transient provider failures.

    Tracks transient failures within a rolling time window.  When ``threshold``
    failures accumulate within ``window_s`` seconds the gate opens for
    ``cooldown_s`` seconds.  During cooldown ``is_open()`` returns ``True``
    and callers skip the provider call, returning the deterministic fallback.

    Only transient errors (timeout, rate-limit, network) advance the counter.
    Auth errors and hard ``PERR_PROVIDER`` errors do not — they are not
    self-healing and should not suppress future calls.

    Not thread-safe — designed for single-process, single-threaded contexts.
    """

    def __init__(self, threshold: int, window_s: float, cooldown_s: float) -> None:
        self._threshold  = max(1, threshold)
        self._window_s   = max(0.0, window_s)
        self._cooldown_s = max(0.0, cooldown_s)
        self._failure_times: list[float] = []
        self._cooldown_until: float = 0.0

    def is_open(self) -> bool:
        """Return ``True`` while an active cooldown is in effect."""
        return time.monotonic() < self._cooldown_until

    def record_failure(self, error_code: str | None) -> None:
        """Record a transient failure; open the gate if threshold is reached."""
        if error_code not in _TRANSIENT_PERR:
            return
        now = time.monotonic()
        cutoff = now - self._window_s
        self._failure_times = [t for t in self._failure_times if t > cutoff]
        self._failure_times.append(now)
        if len(self._failure_times) >= self._threshold:
            self._cooldown_until = now + self._cooldown_s
            self._failure_times = []

    def reset_on_success(self) -> None:
        """Clear accumulated failure list after a successful provider call."""
        self._failure_times = []

    def reset_all(self) -> None:
        """Full reset — clears failures AND cancels active cooldown.  For tests."""
        self._failure_times = []
        self._cooldown_until = 0.0


def _load_gate() -> _FailureGate:
    """Build a ``_FailureGate`` from env vars with safe fallback defaults."""
    def _int(env: str, default: int) -> int:
        try:
            return max(1, int(os.environ.get(env, "")))
        except (ValueError, TypeError):
            return default

    def _flt(env: str, default: float) -> float:
        try:
            return max(0.0, float(os.environ.get(env, "")))
        except (ValueError, TypeError):
            return default

    return _FailureGate(
        threshold  = _int(_GATE_THRESHOLD_ENV,  _DEFAULT_THRESHOLD),
        window_s   = _flt(_GATE_WINDOW_ENV,     _DEFAULT_WINDOW_S),
        cooldown_s = _flt(_GATE_COOLDOWN_ENV,   _DEFAULT_COOLDOWN_S),
    )


#: Module-level gate singleton.  Reset with ``_GATE.reset_all()`` in tests.
_GATE: _FailureGate = _load_gate()


# ---------------------------------------------------------------------------
# Test-mode guard for _orch_request_fn injection
# ---------------------------------------------------------------------------

#: Env var that enables ``_orch_request_fn`` injection in ``ask_orchestrated()``.
#: Scoped specifically to orchestrator test injection — narrower blast radius
#: than a generic ``FPL_ORCH_TEST_INJECTION`` flag.  Must NOT be set in production.
_ORCH_TEST_INJECTION_ENV: str = "FPL_ORCH_TEST_INJECTION"

_TEST_MODE_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})


def _test_mode_active() -> bool:
    """Return ``True`` when ``FPL_ORCH_TEST_INJECTION`` is set to a truthy value.

    Read fresh on each call so test runners can set/unset it between assertions
    without restarting the process.
    """
    return os.environ.get(_ORCH_TEST_INJECTION_ENV, "").strip().lower() in _TEST_MODE_TRUTHY


def _log_orch_provider_event(provider_name: str, result: ProviderResult) -> None:
    """Emit a structured provider event from the orchestrator call path.

    Identical schema to ``llm_layer._log_provider_event``:

    * Success: ``{event, provider, model, latency_ms, attempts}``
    * Failure: ``{event, provider, model, error_code, latency_ms, attempts}``

    ``error_msg`` is deliberately excluded from the event payload — it may
    contain sanitised-but-sensitive strings and is not needed by log processors.
    """
    if result.error_code is None:
        event: dict[str, Any] = {
            "event":      "provider_call_success",
            "provider":   provider_name,
            "model":      result.model,
            "latency_ms": round(result.latency_ms, 2),
            "attempts":   result.attempts,
        }
        _LOG.info("fpl_provider_event %s", json.dumps(event), extra={"fpl_event": event})
    else:
        event = {
            "event":      "provider_call_failure",
            "provider":   provider_name,
            "model":      result.model,
            "error_code": result.error_code,
            "latency_ms": round(result.latency_ms, 2),
            "attempts":   result.attempts,
        }
        _LOG.warning("fpl_provider_event %s", json.dumps(event), extra={"fpl_event": event})


# ---------------------------------------------------------------------------
# Orchestration defaults
# ---------------------------------------------------------------------------

#: Default model for orchestration.  Anthropic Haiku has strong tool-use
#: support and is cost-efficient for single-call cycles.
DEFAULT_ORCH_MODEL: str = "claude-haiku-4-5-20251001"

# P1.b source-discipline prompt: agent-friendly compressed format, ~200 tokens.
# Port of MPC_learning SOURCE_SELECTION_PROMPT pattern adapted for our sources
# (FPL_DATA / FPL_RECO / FOOTBALL_NEWS / OFF_TOPIC).
# Targets: source classification before tool use; grounding constraints
# (minutes/status/news); OFF_TOPIC refusal; Spanish-first output.
_SYSTEM_PROMPT: str = (
    "ROLE: FPL assistant. PRIORITY: ground every claim in tool output.\n"
    "\n"
    "CLASSIFY query → ONE source:\n"
    "  FPL_DATA      (players/teams/fixtures/GWs/points/price/minutes/status/news)\n"
    "  FPL_RECO      (captain/transfer/chip/bench_boost recommendation)\n"
    "  FOOTBALL_NEWS (recent events: results, rumors, rotation)\n"
    "  OFF_TOPIC     (anything not FPL/football) → REFUSE in user_lang, no tool calls\n"
    "\n"
    "CONSTRAINTS:\n"
    "  - single_source_per_turn (no cross-source unless user explicit)\n"
    "  - never_recommend if minutes_played_season==0 (silent skip)\n"
    "  - every player_reco MUST cite: minutes_played_season + status + news (tool-sourced)\n"
    "  - ungroundable claim → \"no tengo datos suficientes\" / \"insufficient data\"\n"
    "  - respond_lang = user_lang (default ES if ambiguous)\n"
    "  - web_fetch only for whitelisted football/FPL domains; OFF_TOPIC URLs → refuse\n"
    "\n"
    "OUTPUT: terse, structured, action-oriented. Spanish-first."
)

#: Retained for backwards compatibility with tests that import this name.
#: Value now matches _SYSTEM_PROMPT (the P1.b compressed prompt).
_ORCH_SYSTEM_SUFFIX: str = _SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# OrchestratorResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OrchestratorResult:
    """Structured result from a single ask_orchestrated() call.

    Attributes
    ----------
    question:
        The original user question, preserved verbatim.
    tool_chosen:
        The tool name selected by the LLM, or ``None`` when no tool was
        selected (outcomes: ``no_client``, ``llm_error``, ``no_tool``).
    tool_args:
        Arguments dict passed to ``run_tool()``.  Empty dict when no tool
        was executed.
    tool_output:
        Raw dict returned by ``run_tool()``.  Empty dict when no tool was
        executed.
    answer_text:
        Human-readable answer from ``render()``, or a safe fallback message
        on failure.  Always a non-empty string.
    llm_used:
        ``True`` when the LLM API call succeeded.  ``False`` for
        ``no_client`` and ``llm_error`` outcomes.
    model:
        Model identifier used for the LLM call, or ``"none"`` when
        ``llm_used=False``.
    outcome:
        One of the ``OUTCOME_*`` constants.  Use this to distinguish the
        result type without inspecting ``error``.
    error:
        Human-readable error message when ``outcome != OUTCOME_OK``,
        else ``None``.
    """

    question:    str
    tool_chosen: str | None
    tool_args:   dict[str, Any]
    tool_output: dict[str, Any]
    answer_text: str
    llm_used:    bool
    model:       str
    outcome:     str
    error:       str | None = None


# ---------------------------------------------------------------------------
# Provider-aware tool list builder
# ---------------------------------------------------------------------------

def _build_tools(provider: str | None) -> list[dict[str, Any]]:
    """Return a tool list in the appropriate wire format for *provider*.

    Parameters
    ----------
    provider:
        One of ``PROVIDER_ANTHROPIC``, ``PROVIDER_OPENAI``, ``PROVIDER_GEMINI``,
        or ``None``.  When ``None``, defaults to Anthropic format (Orch-3a
        backward compatibility).

    Returns
    -------
    list[dict[str, Any]]
        Tool list ready to be passed to the LLM API's ``tools=`` parameter.
    """
    if provider == PROVIDER_OPENAI:
        return [s.to_openai() for s in _ALL_SCHEMAS]
    if provider == PROVIDER_GEMINI:
        return [{"function_declarations": [s.to_gemini() for s in _ALL_SCHEMAS]}]
    # Anthropic (default) and None
    return [s.to_anthropic() for s in _ALL_SCHEMAS]


# ---------------------------------------------------------------------------
# Provider-specific response parsers
# ---------------------------------------------------------------------------

def _parse_anthropic_tool_call(
    response: Any,
) -> tuple[str | None, dict[str, Any]] | None:
    """Parse an Anthropic tool_use response block.

    Returns ``(tool_name, tool_args)`` on success, or ``None`` when the
    response does not contain a tool_use block.

    Note: returns the FIRST tool_use block only.  Use ``_parse_all_anthropic_tool_calls``
    when the response may contain multiple tool_use blocks (multi-tool batching).
    """
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use":
            name = getattr(block, "name", None)
            raw_input = getattr(block, "input", None)
            args = raw_input if isinstance(raw_input, dict) else {}
            return name, args
    return None


def _parse_all_anthropic_tool_calls(
    response: Any,
) -> list[tuple[str, str | None, dict[str, Any]]]:
    """Parse ALL Anthropic tool_use blocks from a single response.

    Multi-tool batching: the Anthropic API may return multiple ``tool_use``
    blocks in a single response content list.  Each block MUST be executed and
    ALL results MUST be returned in a single ``role=user`` message before the
    next model invocation.  Dropping any block breaks the tool_use_id
    correspondence and triggers a 400-error or silent result loss.

    Returns
    -------
    list of ``(tool_use_id, tool_name, tool_args)`` — one entry per tool_use
    block in the response, preserving original order.  Empty list when no
    tool_use blocks are present.
    """
    results = []
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use":
            tool_id = getattr(block, "id", None)
            name = getattr(block, "name", None)
            raw_input = getattr(block, "input", None)
            args = raw_input if isinstance(raw_input, dict) else {}
            results.append((tool_id, name, args))
    return results


def _parse_all_openai_tool_calls(
    response: Any,
) -> list[tuple[str, str | None, dict[str, Any]]]:
    """Parse ALL OpenAI tool_calls from a single chat-completions response.

    Returns list of ``(tool_call_id, function_name, function_args)`` tuples.
    Empty list when no tool calls are present or parsing fails.
    """
    try:
        choices = getattr(response, "choices", None) or []
        message = choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        results = []
        for tc in tool_calls:
            tc_id = getattr(tc, "id", None)
            func = tc.function
            name = getattr(func, "name", None)
            raw_args = getattr(func, "arguments", "{}")
            if isinstance(raw_args, str):
                args = json.loads(raw_args)
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
            if not isinstance(args, dict):
                args = {}
            results.append((tc_id, name, args))
        return results
    except Exception:  # noqa: BLE001
        return []


def _parse_all_gemini_tool_calls(
    response: Any,
) -> list[tuple[str, str | None, dict[str, Any]]]:
    """Parse ALL Gemini function_call parts from a single response.

    Returns list of ``(call_id, function_name, function_args)`` tuples.
    Gemini does not use explicit call IDs, so ``call_id`` is a synthetic
    positional identifier (``"gemini_call_0"``, ``"gemini_call_1"``, …) to
    satisfy the tool_use_id pairing contract.
    Empty list when no function calls are present or parsing fails.
    """
    try:
        candidates = getattr(response, "candidates", None) or []
        content = candidates[0].content
        parts = getattr(content, "parts", None) or []
        results = []
        for idx, part in enumerate(parts):
            fc = getattr(part, "function_call", None)
            if fc is None:
                continue
            name = getattr(fc, "name", None)
            raw_args = getattr(fc, "args", None)
            args = dict(raw_args) if raw_args is not None else {}
            call_id = f"gemini_call_{idx}"
            results.append((call_id, name, args))
        return results
    except Exception:  # noqa: BLE001
        return []


def _parse_all_tool_calls(
    response: Any,
    provider: str | None,
) -> list[tuple[str, str | None, dict[str, Any]]]:
    """Parse ALL tool-call blocks from *response*, returning one entry per block.

    Multi-tool batching invariant: when the LLM returns N tool_use blocks in a
    single response, this function returns ALL N entries.  The caller MUST
    execute every entry and send ALL results back in a single ``role=user``
    message before the next model invocation.

    Parameters
    ----------
    response:
        Raw LLM response object.
    provider:
        Explicit provider string or ``None`` for auto-detection (Anthropic-first).

    Returns
    -------
    list of ``(tool_use_id, tool_name, tool_args)`` — empty list means no tool
    calls were present (equivalent to ``OUTCOME_NO_TOOL``).
    """
    if provider == PROVIDER_OPENAI:
        return _parse_all_openai_tool_calls(response)
    if provider == PROVIDER_GEMINI:
        return _parse_all_gemini_tool_calls(response)
    if provider == PROVIDER_ANTHROPIC:
        return _parse_all_anthropic_tool_calls(response)
    # Auto-detection: try Anthropic first (most common), then OpenAI, then Gemini
    anthropic_calls = _parse_all_anthropic_tool_calls(response)
    if anthropic_calls:
        return anthropic_calls
    openai_calls = _parse_all_openai_tool_calls(response)
    if openai_calls:
        return openai_calls
    return _parse_all_gemini_tool_calls(response)


def _parse_openai_tool_call(
    response: Any,
) -> tuple[str | None, dict[str, Any]] | None:
    """Parse an OpenAI function-calling (chat completions) response.

    Handles ``response.choices[0].message.tool_calls[0].function.{name, arguments}``.
    ``arguments`` is a JSON string; this function deserialises it.

    Returns ``(tool_name, tool_args)`` on success, or ``None`` when no
    tool call is present or parsing fails.

    Note: returns the FIRST tool_call only.  Use ``_parse_all_openai_tool_calls``
    for multi-tool responses.
    """
    try:
        choices = getattr(response, "choices", None) or []
        message = choices[0].message
        tc = (getattr(message, "tool_calls", None) or [])[0]
        func = tc.function
        name = getattr(func, "name", None)
        raw_args = getattr(func, "arguments", "{}")
        if isinstance(raw_args, str):
            args = json.loads(raw_args)
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            args = {}
        if not isinstance(args, dict):
            args = {}
        return name, args
    except Exception:  # noqa: BLE001
        return None


def _parse_gemini_tool_call(
    response: Any,
) -> tuple[str | None, dict[str, Any]] | None:
    """Parse a Gemini function-call response.

    Handles ``response.candidates[0].content.parts[0].function_call.{name, args}``.

    Returns ``(tool_name, tool_args)`` on success, or ``None`` when no
    function call is present or parsing fails.

    Note: returns the FIRST function_call only.  Use ``_parse_all_gemini_tool_calls``
    for multi-tool responses.
    """
    try:
        candidates = getattr(response, "candidates", None) or []
        content = candidates[0].content
        part = (getattr(content, "parts", None) or [])[0]
        fc = part.function_call
        name = getattr(fc, "name", None)
        raw_args = getattr(fc, "args", None)
        args = dict(raw_args) if raw_args is not None else {}
        return name, args
    except Exception:  # noqa: BLE001
        return None


def _parse_tool_call(
    response: Any,
    provider: str | None,
) -> tuple[str | None, dict[str, Any]] | None:
    """Dispatch to the correct parser for *provider*, or try all on ``None``.

    Parameters
    ----------
    response:
        Raw LLM response object.
    provider:
        Explicit provider string or ``None`` for auto-detection.

    Returns
    -------
    ``(tool_name, tool_args)`` tuple, or ``None`` when no tool call was found.

    Note: returns FIRST tool call only (single-tool path, preserved for
    backward compatibility).  The multi-tool batching path uses
    ``_parse_all_tool_calls`` instead.
    """
    if provider == PROVIDER_OPENAI:
        return _parse_openai_tool_call(response)
    if provider == PROVIDER_GEMINI:
        return _parse_gemini_tool_call(response)
    if provider == PROVIDER_ANTHROPIC:
        return _parse_anthropic_tool_call(response)
    # Auto-detection: try Anthropic first (Orch-3a compat), then OpenAI, Gemini
    return (
        _parse_anthropic_tool_call(response)
        or _parse_openai_tool_call(response)
        or _parse_gemini_tool_call(response)
    )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def ask_orchestrated(
    question: str,
    bootstrap: dict[str, Any],
    *,
    client: Any = None,
    model: str = DEFAULT_ORCH_MODEL,
    api_key: str | None = None,
    provider: str | None = None,
    _gate: _FailureGate | None = None,
    _orch_request_fn: Any = None,
) -> OrchestratorResult:
    """Run a single LLM tool-use cycle and return a grounded result.

    Steps
    -----
    1. Resolve bootstrap (handles assembled context from assemble_captain_context).
    2. Resolve client — uses explicit ``client``, then tries Anthropic from env.
       Returns ``OUTCOME_NO_CLIENT`` immediately when no client is available.
    3. Build tool list from the Orch-2a schema registry (provider-appropriate format).
    4. Build system prompt with Phase 9b context injection + orchestration suffix.
    5. Call the LLM with tool schemas (one round-trip, no loop).
    6. Parse one tool-call block from the response (provider-aware).
    7. Validate the tool name against the registry.
    8. Execute the tool deterministically via ``run_tool()``.
    9. Render the answer via the existing ``render()`` function.
       Returns OUTCOME_OK when tool status == "ok", else OUTCOME_TOOL_RESULT_ERROR.

    Parameters
    ----------
    question:
        User question in natural language.
    bootstrap:
        FPL bootstrap dict, or a full assembled context from
        ``assemble_captain_context()`` (bootstrap is auto-extracted).
    client:
        Optional LLM-compatible client.  If ``None``, the function
        attempts to build one from ``ANTHROPIC_API_KEY`` or ``api_key``.
    model:
        LLM model identifier.  Defaults to ``DEFAULT_ORCH_MODEL``.
    api_key:
        Explicit Anthropic API key.  Used only when ``client is None``.
    provider:
        Explicit provider for response parsing and tool-list format.
        One of ``PROVIDER_ANTHROPIC``, ``PROVIDER_OPENAI``, ``PROVIDER_GEMINI``,
        or ``None`` (auto-detect; defaults to Anthropic-first for Orch-3a compat).

    Returns
    -------
    OrchestratorResult
        Always returns — never raises.  Check ``result.outcome`` for status.

    Examples
    --------
    With a mock Anthropic client::

        result = ask_orchestrated(
            "should I captain Haaland",
            bootstrap,
            client=mock_client,
        )
        assert result.outcome == OUTCOME_OK
        assert result.tool_chosen == "get_captain_score"

    With an explicit provider::

        result = ask_orchestrated(
            "should I captain Haaland",
            bootstrap,
            client=openai_mock,
            provider=PROVIDER_OPENAI,
        )
        assert result.outcome == OUTCOME_OK

    No client available::

        result = ask_orchestrated("should I captain Haaland", bootstrap)
        assert result.outcome == OUTCOME_NO_CLIENT
        assert not result.llm_used
    """
    # ------------------------------------------------------------------
    # 1. Resolve bootstrap (assembled context -> raw bootstrap)
    # ------------------------------------------------------------------
    if isinstance(bootstrap.get("bootstrap"), dict):
        actual_bootstrap: dict[str, Any] = bootstrap["bootstrap"]
    else:
        actual_bootstrap = bootstrap

    # ------------------------------------------------------------------
    # 2. Resolve client / credential pre-check
    # ------------------------------------------------------------------
    # _orch_request_fn injection (tests) bypasses all client resolution.
    # Guard: only permitted when FPL_ORCH_TEST_INJECTION is active.  In production,
    # reject immediately rather than silently bypassing credential validation.
    if _orch_request_fn is not None:
        if not _test_mode_active():
            return OrchestratorResult(
                question=question,
                tool_chosen=None, tool_args={}, tool_output={},
                answer_text="LLM call failed during orchestration.",
                llm_used=False, model="none",
                outcome=OUTCOME_LLM_ERROR,
                error="_orch_request_fn requires FPL_ORCH_TEST_INJECTION to be set",
            )
        resolved_client = None  # call_orch_provider uses _orch_request_fn directly
    elif client is not None:
        resolved_client = client  # pre-built client (backwards compat)
    elif provider == PROVIDER_OPENAI:
        if not (api_key or os.environ.get("OPENAI_API_KEY")):
            return OrchestratorResult(
                question=question,
                tool_chosen=None, tool_args={}, tool_output={},
                answer_text="No LLM client available for orchestration.",
                llm_used=False, model="none",
                outcome=OUTCOME_NO_CLIENT,
                error="OPENAI_API_KEY not configured",
            )
        resolved_client = None  # built inside call_orch_provider
    elif provider == PROVIDER_GEMINI:
        if not (api_key or os.environ.get("GOOGLE_API_KEY")):
            return OrchestratorResult(
                question=question,
                tool_chosen=None, tool_args={}, tool_output={},
                answer_text="No LLM client available for orchestration.",
                llm_used=False, model="none",
                outcome=OUTCOME_NO_CLIENT,
                error="GOOGLE_API_KEY not configured",
            )
        resolved_client = None  # built inside call_orch_provider
    else:
        # Default: Anthropic
        resolved_client = _get_anthropic_client(api_key=api_key)
        if resolved_client is None:
            return OrchestratorResult(
                question=question,
                tool_chosen=None, tool_args={}, tool_output={},
                answer_text="No LLM client available for orchestration.",
                llm_used=False, model="none",
                outcome=OUTCOME_NO_CLIENT,
                error="no LLM client available",
            )

    # ------------------------------------------------------------------
    # 3. Build tool list from schema registry (provider-appropriate format)
    # ------------------------------------------------------------------
    tools: list[dict[str, Any]] = _build_tools(provider)

    # ------------------------------------------------------------------
    # 4. Build system prompt (P1.b source-discipline prompt + bootstrap context)
    # ------------------------------------------------------------------
    try:
        from .context_builder import build_orchestration_context  # noqa: PLC0415
        _ctx = build_orchestration_context(actual_bootstrap)
        if len(_ctx) > _MAX_CONTEXT_CHARS:
            _ctx = _ctx[:_MAX_CONTEXT_CHARS] + _CONTEXT_TRUNCATION_MARKER
        system: str = (
            _SYSTEM_PROMPT
            + _CONTEXT_SECTION_HEADER
            + _ctx
            + _CONTEXT_SECTION_FOOTER
        )
    except Exception:  # noqa: BLE001
        system = _SYSTEM_PROMPT

    # ------------------------------------------------------------------
    # 5. Call LLM — ProviderResult envelope + degradation gate
    # ------------------------------------------------------------------
    _active_gate = _gate if _gate is not None else _GATE

    # 5a: Check cooldown — skip provider entirely if gate is open
    if _active_gate.is_open():
        return OrchestratorResult(
            question=question,
            tool_chosen=None,
            tool_args={},
            tool_output={},
            answer_text="LLM provider temporarily unavailable (cooldown active).",
            llm_used=False,
            model="none",
            outcome=OUTCOME_COOLDOWN,
            error="provider_cooldown_active",
        )

    # 5b: Unified multi-provider tool-use call (timing measured inside)
    _provider_label = provider if provider in _ALL_PROVIDERS else PROVIDER_ANTHROPIC
    _timeout_s   = get_orch_timeout()
    _max_retries = get_orch_max_retries()
    orch_call: OrchCallResult = call_orch_provider(
        _provider_label,
        model=model,
        system=system,
        tools=tools,
        messages=[{"role": "user", "content": question}],
        timeout_s=_timeout_s,
        max_retries=_max_retries,
        client=resolved_client,
        api_key=api_key,
        _request_fn=_orch_request_fn,
    )

    # 5c: ProviderResult envelope for structured event emission
    #     (identical schema to llm_layer._log_provider_event)
    _orch_pr = ProviderResult(
        text=None,   # raw response retained below for tool-call parsing
        model=model,
        error_code=orch_call.error_code,
        error_msg=orch_call.error_msg,
        attempts=orch_call.attempts,
        latency_ms=orch_call.latency_ms,
    )
    _log_orch_provider_event(_provider_label, _orch_pr)

    # 5d: Handle failure — record transient errors against the gate
    if orch_call.error_code is not None:
        _active_gate.record_failure(orch_call.error_code)
        if orch_call.error_code == PERR_AUTH:
            answer_text = "LLM authentication failed during orchestration."
        else:
            answer_text = "LLM call failed during orchestration."
        return OrchestratorResult(
            question=question,
            tool_chosen=None, tool_args={}, tool_output={},
            answer_text=answer_text,
            llm_used=False, model="none",
            outcome=OUTCOME_LLM_ERROR,
            error=f"[{orch_call.error_code}] {orch_call.error_msg}",
        )

    _active_gate.reset_on_success()
    response = orch_call.response

    # ------------------------------------------------------------------
    # 6. Parse ALL tool-call blocks from response (multi-tool batching, P1.c).
    #
    # INVARIANT: when the LLM returns N >= 2 tool_use blocks in a single
    # response, ALL N must be executed and ALL results sent back in a single
    # role=user message before the next model invocation.  Executing only the
    # first block (the pre-P1.c behaviour) loses subsequent tool_use blocks,
    # breaking the tool_use_id correspondence and causing silent result loss or
    # 400-errors on the follow-up call.
    #
    # Single-tool path (N == 1): the logic below is byte-equivalent to the
    # prior implementation — no behavioural change for the common case.
    # ------------------------------------------------------------------
    all_tool_calls: list[tuple[str, str | None, dict[str, Any]]] = (
        _parse_all_tool_calls(response, provider)
    )

    if not all_tool_calls:
        return OrchestratorResult(
            question=question,
            tool_chosen=None,
            tool_args={},
            tool_output={},
            answer_text="The model did not select a tool.",
            llm_used=True,
            model=model,
            outcome=OUTCOME_NO_TOOL,
            error="no tool-call block in response",
        )

    # ------------------------------------------------------------------
    # 7. Validate ALL tool names against registry before executing any.
    # ------------------------------------------------------------------
    for _tool_id, _tool_name, _tool_args in all_tool_calls:
        if not _tool_name or _tool_name not in TOOL_NAMES:
            return OrchestratorResult(
                question=question,
                tool_chosen=_tool_name,
                tool_args={},
                tool_output={},
                answer_text=f"Model selected an unknown tool: {_tool_name!r}.",
                llm_used=True,
                model=model,
                outcome=OUTCOME_UNKNOWN_TOOL,
                error=f"unknown tool: {_tool_name!r}",
            )

    # ------------------------------------------------------------------
    # 8. Execute ALL tools deterministically; collect (tool_use_id, result)
    #    pairs for the follow-up message.
    # ------------------------------------------------------------------
    executed: list[tuple[str, str | None, dict[str, Any], dict[str, Any]]] = []
    # Each entry: (tool_use_id, tool_name, tool_args, raw_output)

    for _tool_id, _tool_name, _tool_args in all_tool_calls:
        assert _tool_name is not None  # validated above
        try:
            _raw_output: dict[str, Any] = run_tool(_tool_name, _tool_args, actual_bootstrap)
        except Exception as exc:  # noqa: BLE001
            return OrchestratorResult(
                question=question,
                tool_chosen=_tool_name,
                tool_args=_tool_args,
                tool_output={},
                answer_text=f"Tool execution raised an error for {_tool_name!r}.",
                llm_used=True,
                model=model,
                outcome=OUTCOME_TOOL_ERROR,
                error=str(exc),
            )
        executed.append((_tool_id, _tool_name, _tool_args, _raw_output))

    # ------------------------------------------------------------------
    # 8b. Multi-tool batching: if the LLM issued 2+ tool_use blocks, send
    #     ALL tool_result blocks in a SINGLE role=user message and make a
    #     second model invocation to get the synthesised answer.
    #
    #     Single-tool path (N == 1): skip the second LLM call entirely —
    #     behaviour is identical to the pre-P1.c implementation.
    # ------------------------------------------------------------------
    # Unpack the first (and for single-tool path: only) result for use below.
    first_tool_id, tool_name, tool_args, raw_output = executed[0]

    if len(executed) > 1:
        # Build a single role=user message containing ALL tool_result blocks.
        # tool_use_id MUST match the block's id from the model's prior response.
        tool_result_blocks: list[dict[str, Any]] = [
            {
                "type": "tool_result",
                "tool_use_id": _tid if _tid is not None else f"synthetic_{_idx}",
                "content": json.dumps(_rout),
            }
            for _idx, (_tid, _tname, _targs, _rout) in enumerate(executed)
        ]
        # The assistant turn that triggered the tool calls must also be echoed
        # back in the conversation so the second call has full context.
        assistant_content: list[dict[str, Any]] = []
        for _tid, _tname, _targs, _rout in executed:
            assistant_content.append({
                "type": "tool_use",
                "id": _tid if _tid is not None else f"synthetic_0",
                "name": _tname,
                "input": _targs,
            })
        follow_up_messages: list[dict[str, Any]] = [
            {"role": "user", "content": question},
            {"role": "assistant", "content": assistant_content},
            {"role": "user", "content": tool_result_blocks},
        ]
        _second_call: OrchCallResult = call_orch_provider(
            _provider_label,
            model=model,
            system=system,
            tools=tools,
            messages=follow_up_messages,
            timeout_s=_timeout_s,
            max_retries=_max_retries,
            client=resolved_client,
            api_key=api_key,
            _request_fn=_orch_request_fn,
        )
        if _second_call.error_code is not None:
            # Second call failed — fall through to render the first tool's
            # output as a graceful degradation rather than returning an error.
            _LOG.warning(
                "multi-tool second LLM call failed: [%s] %s; rendering first tool only",
                _second_call.error_code, _second_call.error_msg,
            )
        else:
            # Second call succeeded; surface its synthesised answer text.
            _second_response = _second_call.response
            _second_text: str | None = None
            for _block in getattr(_second_response, "content", []):
                if getattr(_block, "type", None) == "text":
                    _second_text = getattr(_block, "text", None)
                    break
            if _second_text:
                tool_status = raw_output.get("status")
                outcome = OUTCOME_OK if tool_status == "ok" else OUTCOME_TOOL_RESULT_ERROR
                return OrchestratorResult(
                    question=question,
                    tool_chosen=tool_name,
                    tool_args=tool_args,
                    tool_output=raw_output,
                    answer_text=_second_text,
                    llm_used=True,
                    model=model,
                    outcome=outcome,
                    error=None if outcome == OUTCOME_OK else f"tool returned status={tool_status!r}",
                )

    # ------------------------------------------------------------------
    # 9. Render answer; determine outcome from first tool's status.
    #    (Single-tool path, or multi-tool fallback when second call failed.)
    # ------------------------------------------------------------------
    tool_status = raw_output.get("status")
    outcome = OUTCOME_OK if tool_status == "ok" else OUTCOME_TOOL_RESULT_ERROR

    try:
        answer_text: str = render(tool_name, raw_output)
    except Exception:  # noqa: BLE001
        # Renderer failed; surface status as minimal fallback
        answer_text = f"[{tool_status or 'unknown'}]"

    return OrchestratorResult(
        question=question,
        tool_chosen=tool_name,
        tool_args=tool_args,
        tool_output=raw_output,
        answer_text=answer_text,
        llm_used=True,
        model=model,
        outcome=outcome,
        error=None if outcome == OUTCOME_OK else f"tool returned status={tool_status!r}",
    )

"""
llm_orchestrator_core.tool_loop
================================
Generic bounded LLM tool-use loop (the domain-neutral skeleton of
``fpl_grounded_assistant.orchestrator.ask_orchestrated``).

The loop:

1. Calls the provider with a system prompt, conversation messages, and a
   tool list (built from ``ToolSpec``s).
2. Parses ALL tool-call blocks from the response (multi-tool batching:
   every block is executed and every result is returned in a single
   follow-up message — dropping a block breaks the tool_use_id pairing).
3. Executes each tool through a caller-supplied ``execute_tool(name, args)``
   callable.  Tool execution is always deterministic; the LLM selects tools
   and phrases the answer but cannot alter grounded data.
4. Feeds results back and repeats, bounded by ``max_iterations``.
5. Returns the final text answer plus a full tool trace and token counts.

Provider support
----------------
* Anthropic — native multi-turn tool use (assistant content blocks +
  ``tool_result`` user blocks).
* OpenAI — native multi-turn function calling (assistant ``tool_calls`` +
  ``role="tool"`` messages).
* Gemini — single tool round: after executing the first round of calls, the
  results are serialised into a follow-up user prompt for a final text turn
  (``call_orch_provider`` only forwards ``messages[0]["content"]`` to Gemini).

Every failure path returns a structured ``ToolLoopResult`` — no exceptions
escape ``run_tool_loop()``.

Contamination rule: no domain imports.  Domain behaviour arrives exclusively
through ``system_prompt``, ``tool_specs``, and ``execute_tool``.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .provider_client import (
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
    PROVIDER_OPENAI,
    OrchCallResult,
    call_orch_provider,
)
from .tool_schema import ToolSpec, build_tools

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Outcome constants
# ---------------------------------------------------------------------------

#: Loop completed with a final text answer.
LOOP_OK: str = "ok"
#: No client / credentials available (provider call attempts == 0).
LOOP_NO_CLIENT: str = "no_client"
#: The provider call failed (after retries).
LOOP_LLM_ERROR: str = "llm_error"
#: The model stopped without producing text (and without tool calls).
LOOP_NO_ANSWER: str = "no_answer"
#: The iteration bound was reached before a final text answer.
LOOP_MAX_ITERATIONS: str = "max_iterations"

_ALL_LOOP_OUTCOMES: frozenset[str] = frozenset({
    LOOP_OK, LOOP_NO_CLIENT, LOOP_LLM_ERROR, LOOP_NO_ANSWER, LOOP_MAX_ITERATIONS,
})


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolCallRecord:
    """One executed tool call (deterministic execution trace entry)."""

    tool_name: str
    tool_args: dict[str, Any]
    tool_output: dict[str, Any]
    error: str | None = None


@dataclass(frozen=True)
class ToolLoopResult:
    """Structured result of a single ``run_tool_loop()`` invocation.

    ``final_text`` is always a non-empty string (a safe fallback message on
    failure paths).  ``tool_trace`` records every executed tool call in
    order, across all iterations.
    """

    question:      str
    final_text:    str
    outcome:       str
    llm_used:      bool
    model:         str
    iterations:    int
    tool_trace:    list[ToolCallRecord] = field(default_factory=list)
    error:         str | None = None
    input_tokens:  int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens


# ---------------------------------------------------------------------------
# Prompt-caching helpers (Anthropic)
# ---------------------------------------------------------------------------

def build_cached_system_blocks(
    static_text: str,
    *,
    dynamic_suffix: str = "",
) -> list[dict[str, Any]]:
    """Anthropic content blocks with cache_control on the STATIC prefix only.

    Block 1 (static prompt) carries ``cache_control: ephemeral``; block 2
    (dynamic context) carries none, so per-request context changes do not
    invalidate the cached prefix.
    """
    blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": static_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    if dynamic_suffix:
        blocks.append({"type": "text", "text": dynamic_suffix})
    return blocks


def apply_tools_cache_control(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy of *tools* with cache_control on the LAST Anthropic tool entry.

    Non-Anthropic tool lists (OpenAI ``function`` entries, Gemini
    ``function_declarations``) are returned unchanged.
    """
    if not tools:
        return tools
    last = tools[-1]
    if "input_schema" not in last:
        return tools
    result = list(tools)
    last_with_cache = dict(last)
    last_with_cache["cache_control"] = {"type": "ephemeral"}
    result[-1] = last_with_cache
    return result


# ---------------------------------------------------------------------------
# Tool-output truncation (token-budget guard)
# ---------------------------------------------------------------------------

def truncate_list_fields(
    raw_output: dict[str, Any],
    truncatable_fields: frozenset[str],
    max_items: int = 10,
) -> dict[str, Any]:
    """Cap list-valued fields in *raw_output* to *max_items* (additive).

    Fields not in *truncatable_fields*, non-list fields, and lists within
    the cap are forwarded unchanged.  A ``_truncation_note`` key is added
    when truncation fires.  Never mutates the input dict.
    """
    truncated_fields: list[str] = []
    modified: dict[str, Any] = {}

    for key, value in raw_output.items():
        if key in truncatable_fields and isinstance(value, list) and len(value) > max_items:
            modified[key] = value[:max_items]
            truncated_fields.append(f"{key}: showing top {max_items} of {len(value)} total")
        else:
            modified[key] = value

    if truncated_fields:
        modified["_truncation_note"] = (
            "showing top " + str(max_items) + " of available results; "
            "ask for more if needed. Truncated: " + "; ".join(truncated_fields) + "."
        )

    return modified


# ---------------------------------------------------------------------------
# Provider-specific response parsers (multi-tool batching aware)
# ---------------------------------------------------------------------------

def _parse_all_anthropic_tool_calls(response: Any) -> list[tuple[str, str | None, dict[str, Any]]]:
    results = []
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use":
            tool_id = getattr(block, "id", None)
            name = getattr(block, "name", None)
            raw_input = getattr(block, "input", None)
            args = raw_input if isinstance(raw_input, dict) else {}
            results.append((tool_id, name, args))
    return results


def _parse_all_openai_tool_calls(response: Any) -> list[tuple[str, str | None, dict[str, Any]]]:
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


def _parse_all_gemini_tool_calls(response: Any) -> list[tuple[str, str | None, dict[str, Any]]]:
    try:
        candidates = getattr(response, "candidates", None) or []
        content = candidates[0].content
        parts = getattr(content, "parts", None) or []
        results = []
        for idx, part in enumerate(parts):
            fc = getattr(part, "function_call", None)
            # Protobuf ``Part`` always exposes ``function_call`` as a
            # default-instance, even for text-only parts — a non-empty
            # ``name`` is the only reliable signal that this part IS a call.
            name = getattr(fc, "name", None) if fc is not None else None
            if not name:
                continue
            raw_args = getattr(fc, "args", None)
            args = dict(raw_args) if raw_args is not None else {}
            results.append((f"gemini_call_{idx}", name, args))
        return results
    except Exception:  # noqa: BLE001
        return []


def parse_all_tool_calls(
    response: Any,
    provider: str | None,
) -> list[tuple[str, str | None, dict[str, Any]]]:
    """Parse ALL tool-call blocks from *response* (provider-aware).

    Returns ``(tool_use_id, tool_name, tool_args)`` per block; empty list
    means no tool calls.  ``None`` provider auto-detects Anthropic → OpenAI
    → Gemini.
    """
    if provider == PROVIDER_OPENAI:
        return _parse_all_openai_tool_calls(response)
    if provider == PROVIDER_GEMINI:
        return _parse_all_gemini_tool_calls(response)
    if provider == PROVIDER_ANTHROPIC:
        return _parse_all_anthropic_tool_calls(response)
    anthropic_calls = _parse_all_anthropic_tool_calls(response)
    if anthropic_calls:
        return anthropic_calls
    openai_calls = _parse_all_openai_tool_calls(response)
    if openai_calls:
        return openai_calls
    return _parse_all_gemini_tool_calls(response)


def extract_text_from_response(response: Any, provider: str | None) -> str | None:
    """Extract the first plain-text block from a provider response."""
    try:
        if provider == PROVIDER_OPENAI:
            choices = getattr(response, "choices", None) or []
            if choices:
                msg = choices[0].message
                text = getattr(msg, "content", None)
                if isinstance(text, str) and text.strip():
                    return text
            return None
        if provider == PROVIDER_GEMINI:
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                content = getattr(candidates[0], "content", None)
                parts = getattr(content, "parts", None) or []
                for part in parts:
                    t = getattr(part, "text", None)
                    if t and isinstance(t, str) and t.strip():
                        return t
            t2 = getattr(response, "text", None)
            if t2 and isinstance(t2, str) and t2.strip():
                return t2
            return None
        # Anthropic (default / auto-detect)
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) == "text":
                t = getattr(block, "text", None)
                if t and isinstance(t, str) and t.strip():
                    return t
        return None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Conversation-format dialect helpers
# ---------------------------------------------------------------------------

def _anthropic_assistant_turn(response: Any) -> dict[str, Any]:
    """Echo the raw assistant content blocks back as the assistant turn."""
    return {"role": "assistant", "content": getattr(response, "content", [])}


def _anthropic_tool_results_turn(
    executed: list[tuple[str, str, dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    """All tool results in ONE user message (tool_use_id pairing contract)."""
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": json.dumps(output, ensure_ascii=False, default=str),
            }
            for tool_id, _name, _args, output in executed
        ],
    }


def _openai_assistant_turn(response: Any) -> dict[str, Any]:
    """Re-serialise the OpenAI assistant message (content + tool_calls)."""
    msg = response.choices[0].message
    turn: dict[str, Any] = {
        "role": "assistant",
        "content": getattr(msg, "content", None),
    }
    tool_calls = getattr(msg, "tool_calls", None) or []
    if tool_calls:
        turn["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                    if isinstance(tc.function.arguments, str)
                    else json.dumps(tc.function.arguments, ensure_ascii=False),
                },
            }
            for tc in tool_calls
        ]
    return turn


def _openai_tool_results_turns(
    executed: list[tuple[str, str, dict[str, Any], dict[str, Any]]],
) -> list[dict[str, Any]]:
    """One ``role="tool"`` message per executed call."""
    return [
        {
            "role": "tool",
            "tool_call_id": tool_id,
            "content": json.dumps(output, ensure_ascii=False, default=str),
        }
        for tool_id, _name, _args, output in executed
    ]


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

#: Hard ceiling on loop iterations regardless of caller configuration.
_MAX_ITERATIONS_CEILING: int = 8


def run_tool_loop(
    question: str,
    *,
    system_prompt: str,
    tool_specs: list[ToolSpec],
    execute_tool: Callable[[str, dict[str, Any]], dict[str, Any]],
    provider: str = PROVIDER_ANTHROPIC,
    model: str,
    history: list[dict[str, Any]] | None = None,
    max_iterations: int = 4,
    max_tokens: int = 1024,
    timeout_s: float = 30.0,
    max_retries: int = 1,
    client: Any = None,
    api_key: str | None = None,
    dynamic_context: str = "",
    truncatable_fields: frozenset[str] = frozenset(),
    truncate_max_items: int = 10,
    no_answer_fallback: str = "No answer was produced.",
    _request_fn: Any = None,
) -> ToolLoopResult:
    """Run a bounded multi-turn tool-use cycle and return a grounded result.

    Parameters
    ----------
    question:
        User question in natural language.
    system_prompt:
        STATIC system prompt text (cached via cache_control on Anthropic).
    tool_specs:
        Domain tool registry.  Unknown tool names chosen by the LLM are
        answered with a structured error result (the loop continues, letting
        the model correct itself within the iteration budget).
    execute_tool:
        ``(tool_name, tool_args) -> dict`` deterministic executor.  Must not
        raise for expected error cases (return ``{"status": "error", ...}``);
        unexpected exceptions are caught and surfaced as error tool results.
    history:
        Optional prior conversation messages (provider-dialect format) that
        precede the current question.  The caller owns history persistence.
    dynamic_context:
        Per-request grounding context, appended as a NON-cached system block
        (Anthropic) or inline system suffix (OpenAI / Gemini).
    no_answer_fallback:
        ``final_text`` used when the loop ends without model text (domain
        packages localize this).

    Returns
    -------
    ToolLoopResult
        Always returns — never raises.  Check ``result.outcome``.
    """
    _max_iter = max(1, min(int(max_iterations), _MAX_ITERATIONS_CEILING))
    trace: list[ToolCallRecord] = []
    _in_tok = 0
    _out_tok = 0
    _cache_tok = 0

    known_tools: frozenset[str] = frozenset(s.name for s in tool_specs)
    tools = build_tools(provider, tool_specs)

    # System construction: Anthropic gets split cached blocks; OpenAI/Gemini
    # get a single concatenated system string (their caching is automatic /
    # not block-based).
    system_blocks: list[dict[str, Any]] | None = None
    if provider == PROVIDER_ANTHROPIC:
        system_blocks = build_cached_system_blocks(
            system_prompt, dynamic_suffix=dynamic_context,
        )
        tools = apply_tools_cache_control(tools)
        system_text = system_prompt + (("\n\n" + dynamic_context) if dynamic_context else "")
    else:
        system_text = system_prompt + (("\n\n" + dynamic_context) if dynamic_context else "")

    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": question})

    llm_used = False
    iterations = 0

    while iterations < _max_iter:
        iterations += 1
        call: OrchCallResult = call_orch_provider(
            provider,
            model=model,
            system=system_text,
            tools=tools,
            messages=messages,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            max_retries=max_retries,
            client=client,
            api_key=api_key,
            _request_fn=_request_fn,
            _system_blocks=system_blocks,
        )
        _in_tok += call.input_tokens or 0
        _out_tok += call.output_tokens or 0
        _cache_tok += call.cache_read_tokens or 0

        if call.error_code is not None:
            outcome = LOOP_NO_CLIENT if call.attempts == 0 else LOOP_LLM_ERROR
            _LOG.warning(
                "llm_tool_loop provider failure [%s] %s (iteration %d)",
                call.error_code, call.error_msg, iterations,
            )
            return ToolLoopResult(
                question=question,
                final_text=no_answer_fallback,
                outcome=outcome,
                llm_used=llm_used,
                model=model if llm_used else "none",
                iterations=iterations,
                tool_trace=trace,
                error=f"[{call.error_code}] {call.error_msg}",
                input_tokens=_in_tok,
                output_tokens=_out_tok,
                cache_read_tokens=_cache_tok,
            )

        llm_used = True
        response = call.response
        tool_calls = parse_all_tool_calls(response, provider)

        # --- Final answer: no tool calls in this turn -----------------------
        if not tool_calls:
            text = extract_text_from_response(response, provider)
            if text:
                return ToolLoopResult(
                    question=question,
                    final_text=text,
                    outcome=LOOP_OK,
                    llm_used=True,
                    model=model,
                    iterations=iterations,
                    tool_trace=trace,
                    input_tokens=_in_tok,
                    output_tokens=_out_tok,
                    cache_read_tokens=_cache_tok,
                )
            return ToolLoopResult(
                question=question,
                final_text=no_answer_fallback,
                outcome=LOOP_NO_ANSWER,
                llm_used=True,
                model=model,
                iterations=iterations,
                tool_trace=trace,
                error="model stopped without text or tool calls",
                input_tokens=_in_tok,
                output_tokens=_out_tok,
                cache_read_tokens=_cache_tok,
            )

        # --- Execute ALL tool calls from this turn ---------------------------
        executed: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
        for tool_id, tool_name, tool_args in tool_calls:
            if not tool_name or tool_name not in known_tools:
                output: dict[str, Any] = {
                    "status": "error",
                    "error": f"unknown tool: {tool_name!r}",
                    "known_tools": sorted(known_tools),
                }
                trace.append(ToolCallRecord(
                    tool_name=tool_name or "<missing>",
                    tool_args=tool_args,
                    tool_output=output,
                    error="unknown_tool",
                ))
            else:
                try:
                    raw = execute_tool(tool_name, tool_args)
                    if not isinstance(raw, dict):
                        raw = {"status": "ok", "result": raw}
                    output = truncate_list_fields(
                        raw, truncatable_fields, truncate_max_items,
                    ) if truncatable_fields else raw
                    trace.append(ToolCallRecord(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        tool_output=output,
                    ))
                except Exception as exc:  # noqa: BLE001
                    output = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
                    trace.append(ToolCallRecord(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        tool_output=output,
                        error=str(exc),
                    ))
            executed.append((tool_id or f"call_{len(executed)}", tool_name or "", tool_args, output))

        # --- Feed results back (provider dialect) ----------------------------
        if provider == PROVIDER_OPENAI:
            messages.append(_openai_assistant_turn(response))
            messages.extend(_openai_tool_results_turns(executed))
        elif provider == PROVIDER_GEMINI:
            # call_orch_provider forwards only messages[0]["content"] to
            # Gemini, so multi-turn tool use is emulated: fold the tool
            # results into a single follow-up prompt for a final text turn.
            results_text = "\n".join(
                f"[tool {name}({json.dumps(args, ensure_ascii=False, default=str)})] -> "
                f"{json.dumps(output, ensure_ascii=False, default=str)}"
                for _tid, name, args, output in executed
            )
            messages = [{
                "role": "user",
                "content": (
                    f"{question}\n\nTOOL RESULTS (ground your answer ONLY in these):\n"
                    f"{results_text}\n\nAnswer the question now without calling more tools."
                ),
            }]
        else:  # Anthropic (default)
            messages.append(_anthropic_assistant_turn(response))
            messages.append(_anthropic_tool_results_turn(executed))

    # --- Iteration budget exhausted ------------------------------------------
    return ToolLoopResult(
        question=question,
        final_text=no_answer_fallback,
        outcome=LOOP_MAX_ITERATIONS,
        llm_used=llm_used,
        model=model if llm_used else "none",
        iterations=iterations,
        tool_trace=trace,
        error=f"max iterations ({_max_iter}) reached without a final answer",
        input_tokens=_in_tok,
        output_tokens=_out_tok,
        cache_read_tokens=_cache_tok,
    )

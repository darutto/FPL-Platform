"""
worldcup_assistant.ask
=======================
Orchestrator-primary ask entrypoint for the World Cup domain.

Thin domain wrapper around ``llm_orchestrator_core.run_tool_loop``: injects
the WC system prompt, the WC tool registry, and the startup grounding
context.  The LLM reasons and selects tools; ``execute_wc_tool`` grounds
every fact deterministically and localizes it to Spanish.

Configuration (env)
-------------------
WC_PROVIDER        anthropic | openai | gemini   (default: anthropic)
WC_ORCH_MODEL      provider model id             (default: claude-opus-4-8)
WC_MAX_ITERATIONS  tool-loop bound               (default: 4)
WC_MAX_TOKENS      generation cap per call       (default: 1024)
WC_TIMEOUT_S       per-attempt provider timeout  (default: 30)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from llm_orchestrator_core import (
    LOOP_OK,
    PROVIDER_ANTHROPIC,
    ToolLoopResult,
    run_tool_loop,
)

from .context_builder import WC_SYSTEM_PROMPT
from .tools import WC_TOOL_SPECS, WC_TRUNCATABLE_FIELDS, execute_wc_tool

#: Default model: per the plan, the orchestrator-primary WC path defaults to
#: claude-opus-4-8 (multi-turn info questions need stronger tool selection
#: than the FPL single-shot Haiku path).
DEFAULT_WC_MODEL: str = "claude-opus-4-8"

#: Spanish fallback shown when no grounded answer could be produced.
_NO_ANSWER_ES: str = (
    "Lo siento, no pude obtener una respuesta con datos del Mundial en este "
    "momento. Inténtalo de nuevo en unos segundos."
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, ""))
    except (ValueError, TypeError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, ""))
    except (ValueError, TypeError):
        return default


@dataclass(frozen=True)
class WCAskResult:
    """Domain-shaped result consumed by ``wc_server`` to build AskResponse."""

    question:    str
    final_text:  str
    outcome:     str
    llm_used:    bool
    model:       str
    iterations:  int
    tool_trace:  list[dict[str, Any]] = field(default_factory=list)
    error:       str | None = None
    total_tokens: int = 0


def ask_wc(
    question: str,
    *,
    dynamic_context: str = "",
    history: list[dict[str, Any]] | None = None,
    client: Any = None,
    api_key: str | None = None,
    _request_fn: Any = None,
) -> WCAskResult:
    """Answer one World Cup question through the grounded tool loop.

    Always returns — never raises.  ``dynamic_context`` is the startup
    tournament snapshot (non-cached system block); ``history`` is the
    ``wc:``-namespaced session transcript owned by the server layer.
    """
    provider = os.environ.get("WC_PROVIDER", PROVIDER_ANTHROPIC).lower().strip()
    model = os.environ.get("WC_ORCH_MODEL", DEFAULT_WC_MODEL)

    result: ToolLoopResult = run_tool_loop(
        question,
        system_prompt=WC_SYSTEM_PROMPT,
        tool_specs=WC_TOOL_SPECS,
        execute_tool=execute_wc_tool,
        provider=provider,
        model=model,
        history=history,
        max_iterations=_env_int("WC_MAX_ITERATIONS", 4),
        max_tokens=_env_int("WC_MAX_TOKENS", 1024),
        timeout_s=_env_float("WC_TIMEOUT_S", 30.0),
        client=client,
        api_key=api_key,
        dynamic_context=dynamic_context,
        truncatable_fields=WC_TRUNCATABLE_FIELDS,
        no_answer_fallback=_NO_ANSWER_ES,
        _request_fn=_request_fn,
    )

    return WCAskResult(
        question=question,
        final_text=result.final_text,
        outcome=result.outcome,
        llm_used=result.llm_used,
        model=result.model,
        iterations=result.iterations,
        tool_trace=[
            {
                "tool": rec.tool_name,
                "args": rec.tool_args,
                "output_status": rec.tool_output.get("status"),
                "error": rec.error,
            }
            for rec in result.tool_trace
        ],
        error=result.error,
        total_tokens=result.total_tokens,
    )


def is_ok(result: WCAskResult) -> bool:
    return result.outcome == LOOP_OK

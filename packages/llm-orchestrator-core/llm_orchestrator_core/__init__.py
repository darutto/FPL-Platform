"""
llm_orchestrator_core
======================
Domain-neutral LLM orchestration primitives shared by grounded assistants.

Extracted (Iteration 1, World Cup domain) from the generic parts of
``fpl_grounded_assistant.provider_client`` / ``orchestrator.py``:

* ``provider_client``  — unified provider call contract (Anthropic / OpenAI /
  Gemini) with bounded retries, error normalisation, and token usage
  extraction.  No domain types, no domain env vars, no domain logging tags.
* ``tool_schema``      — ``ToolSpec`` dataclass + per-provider wire-format
  serialisation (``to_anthropic`` / ``to_openai`` / ``to_gemini``) and
  ``build_tools()``.
* ``tool_loop``        — generic bounded tool-use loop: the LLM selects tools,
  a caller-supplied executor runs them deterministically, results are fed
  back until the model produces a final text answer.

Contamination rule: this package MUST NOT import from any ``fpl_*`` or
``worldcup_*`` package.  Domain packages depend on it, never the reverse.
"""

from .provider_client import (  # noqa: F401
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    PROVIDER_GEMINI,
    PERR_RATE_LIMIT,
    PERR_AUTH,
    PERR_TIMEOUT,
    PERR_NETWORK,
    PERR_PROVIDER,
    OrchCallResult,
    ProviderCallResult,
    call_provider_request,
    call_orch_provider,
    check_provider_health,
)
from .tool_schema import ToolSpec, build_tools  # noqa: F401
from .tool_loop import (  # noqa: F401
    LOOP_OK,
    LOOP_NO_CLIENT,
    LOOP_LLM_ERROR,
    LOOP_NO_ANSWER,
    LOOP_MAX_ITERATIONS,
    ToolCallRecord,
    ToolLoopResult,
    run_tool_loop,
    build_cached_system_blocks,
    apply_tools_cache_control,
)

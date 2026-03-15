"""
fpl_grounded_assistant
=======================
Minimal end-to-end grounded-assistant harness for the fpl-platform.

Phase 1h public surface::

    from fpl_grounded_assistant import ask, route, render, RouteResult

Phase 2k public surface (model-facing dispatcher)::

    from fpl_grounded_assistant import dispatch, DispatchResult
    from fpl_grounded_assistant import (
        INTENT_CAPTAIN_SCORE, INTENT_RANK_CANDIDATES, INTENT_CURRENT_GAMEWEEK,
        INTENT_PLAYER_SUMMARY, INTENT_PLAYER_RESOLVE, INTENT_UNSUPPORTED,
        SUPPORTED_INTENTS,
    )

Phase 2m public surface (minimal LLM adapter)::

    from fpl_grounded_assistant import adapt, AdapterResponse

Quick usage::

    result = ask("Who is Salah?", bootstrap)
    # {
    #   "selected_tool": "resolve_player",
    #   "tool_input":    {"query": "salah"},
    #   "raw_output":    {"status": "ok", "player_id": 2, ...},
    #   "answer_text":   "Salah (Mohamed Salah) plays for Liverpool ...",
    # }

    result = dispatch("Should I captain Haaland?", bootstrap)
    # DispatchResult(intent="captain_score", selected_tool="get_captain_score", ...)

No LLM integration, no HTTP server, no live API calls in this slice.
Requires fpl_tool_runner (Phase 1g) and all its transitive dependencies.
"""

from .dispatcher import (
    # Phase 2k: intent constants
    INTENT_CAPTAIN_SCORE,
    INTENT_RANK_CANDIDATES,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_SUMMARY,
    INTENT_PLAYER_RESOLVE,
    INTENT_UNSUPPORTED,
    SUPPORTED_INTENTS,
    # Phase 2k: tool→intent mapping (exported for test access)
    _TOOL_TO_INTENT,
    # Phase 2k: types and entrypoint
    DispatchResult,
    dispatch,
    # Phase 2l: outcome constants
    OUTCOME_OK,
    OUTCOME_UNSUPPORTED_INTENT,
    OUTCOME_NOT_FOUND,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS,
    OUTCOME_ERROR,
    # Phase 2l: intent manifest
    INTENT_MANIFEST,
)
from .adapter import (
    # Phase 2m: model-facing adapter
    adapt,
    AdapterResponse,
)
from .conversation_fixtures import (
    # Phase 2n: contract fixtures
    ConversationFixture,
    FIXTURE_DEFINITIONS,
    STANDARD_BOOTSTRAP,
    AMBIGUOUS_BOOTSTRAP,
    run_all,
)
from .llm_layer import (
    # Phase 3a: LLM integration layer
    LLMResponse,
    SYSTEM_PROMPT,
    DEFAULT_MODEL,
    _OUTCOME_INSTRUCTION,
    build_user_prompt,
    ask_llm,
    _get_anthropic_client,
    _ANTHROPIC_AVAILABLE,
)
from .final_response import (
    # Phase 3c: unified final-response policy
    FinalResponse,
    FinalResponseDebug,
    FINAL_TEXT_POLICY,
    respond,
)
from .final_response_fixtures import (
    # Phase 3d: final response contract fixtures
    FinalResponseFixture,
    FINAL_RESPONSE_FIXTURE_DEFINITIONS,
    run_all as run_all_final_response,
)
from .llm_review import (
    # Phase 3b: LLM behavior hardening
    ReviewResult,
    VIOLATION_OVERCONFIDENT_NON_OK,
    VIOLATION_INVENTED_NUMBERS,
    VIOLATION_AMBIGUOUS_FALSE_RESOLUTION,
    VIOLATION_EMPTY_LLM_TEXT,
    _OVERCONFIDENT_PHRASES,
    _AMBIGUOUS_RESOLUTION_PHRASES,
    _NON_OK_OUTCOMES,
    _check_overconfidence,
    _check_numeric_invention,
    _check_ambiguous_false_resolution,
    _check_empty_llm_text,
    review_llm_response,
    ask_llm_safe,
)
from .explainer import (
    # Phase 2j: threshold constants
    FORM_HIGH,
    FORM_LOW,
    FDR_EASY,
    FDR_HARD,
    XGI_HIGH,
    XGI_LOW,
    RISK_ROTATION,
    RISK_HIGH,
    # Phase 2j: display maps
    _ROLE_REASON,
    _COMPACT_EXCLUDED,
    # Phase 2j: public functions
    explain_captain,
    explain_captain_compact,
)
from .harness import ask
from .renderer import (
    render,
    # Phase 2i: tier + set-piece display helpers (exported for test access)
    _TIER_LABEL,
    _TIER_SHORT,
    _SET_PIECE_LABEL,
    _SET_PIECE_SHORT,
    _tier_display,
    _tier_short,
    _set_piece_clause,
    _set_piece_suffix,
)
from .router import RouteResult, route
from .conversation_state import (
    # Phase 4e: minimal multi-turn conversation state
    ConversationState,
    ConversationSession,
    resolve_pronouns,
    _PRONOUNS,
)
from .reference_resolver import (
    # Phase 4f: LLM-assisted reference resolution
    ReferenceResolution,
    resolve_reference,
    resolve_reference_llm,
    build_resolver_prompt,
    RESOLVER_SYSTEM_PROMPT,
    _CONFIDENCE_THRESHOLD,
    _INTENT_TO_CANONICAL,
    _parse_resolver_response,
    _build_canonical_question,
)

__all__ = [
    # Phase 2n: contract fixtures
    "ConversationFixture",
    "FIXTURE_DEFINITIONS",
    "STANDARD_BOOTSTRAP",
    "AMBIGUOUS_BOOTSTRAP",
    "run_all",
    # Phase 3d: final response contract fixtures
    "FinalResponseFixture",
    "FINAL_RESPONSE_FIXTURE_DEFINITIONS",
    "run_all_final_response",
    # Phase 3c: final-response policy
    "FinalResponse",
    "FinalResponseDebug",
    "FINAL_TEXT_POLICY",
    "respond",
    # Phase 3a: LLM layer
    "LLMResponse",
    "SYSTEM_PROMPT",
    "DEFAULT_MODEL",
    "_OUTCOME_INSTRUCTION",
    "build_user_prompt",
    "ask_llm",
    "_get_anthropic_client",
    "_ANTHROPIC_AVAILABLE",
    # Phase 3b: LLM review
    "ReviewResult",
    "VIOLATION_OVERCONFIDENT_NON_OK",
    "VIOLATION_INVENTED_NUMBERS",
    "VIOLATION_AMBIGUOUS_FALSE_RESOLUTION",
    "VIOLATION_EMPTY_LLM_TEXT",
    "_OVERCONFIDENT_PHRASES",
    "_AMBIGUOUS_RESOLUTION_PHRASES",
    "_NON_OK_OUTCOMES",
    "_check_overconfidence",
    "_check_numeric_invention",
    "_check_ambiguous_false_resolution",
    "_check_empty_llm_text",
    "review_llm_response",
    "ask_llm_safe",
    # Phase 2m: adapter
    "adapt",
    "AdapterResponse",
    # Phase 2k: dispatcher
    "dispatch",
    "DispatchResult",
    "INTENT_CAPTAIN_SCORE",
    "INTENT_RANK_CANDIDATES",
    "INTENT_CURRENT_GAMEWEEK",
    "INTENT_PLAYER_SUMMARY",
    "INTENT_PLAYER_RESOLVE",
    "INTENT_UNSUPPORTED",
    "SUPPORTED_INTENTS",
    "_TOOL_TO_INTENT",
    # Phase 2l: outcomes + manifest
    "OUTCOME_OK",
    "OUTCOME_UNSUPPORTED_INTENT",
    "OUTCOME_NOT_FOUND",
    "OUTCOME_AMBIGUOUS",
    "OUTCOME_MISSING_ARGUMENTS",
    "OUTCOME_ERROR",
    "INTENT_MANIFEST",
    # Phase 4e: multi-turn state
    "ConversationState",
    "ConversationSession",
    "resolve_pronouns",
    "_PRONOUNS",
    # Phase 4f: LLM-assisted reference resolution
    "ReferenceResolution",
    "resolve_reference",
    "resolve_reference_llm",
    "build_resolver_prompt",
    "RESOLVER_SYSTEM_PROMPT",
    "_CONFIDENCE_THRESHOLD",
    "_INTENT_TO_CANONICAL",
    "_parse_resolver_response",
    "_build_canonical_question",
    # core harness
    "ask",
    "route",
    "render",
    "RouteResult",
    # Phase 2i helpers
    "_TIER_LABEL",
    "_TIER_SHORT",
    "_SET_PIECE_LABEL",
    "_SET_PIECE_SHORT",
    "_tier_display",
    "_tier_short",
    "_set_piece_clause",
    "_set_piece_suffix",
    # Phase 2j: thresholds + explainer
    "FORM_HIGH",
    "FORM_LOW",
    "FDR_EASY",
    "FDR_HARD",
    "XGI_HIGH",
    "XGI_LOW",
    "RISK_ROTATION",
    "RISK_HIGH",
    "_ROLE_REASON",
    "_COMPACT_EXCLUDED",
    "explain_captain",
    "explain_captain_compact",
]

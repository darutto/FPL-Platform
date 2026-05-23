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
    INTENT_COMPARE_PLAYERS,         # Phase 5a
    INTENT_TRANSFER_ADVICE,         # Phase 6a
    INTENT_CHIP_ADVICE,             # Phase 6b
    INTENT_MULTI_INTENT,            # Phase 6c
    INTENT_PLAYER_FIXTURE_RUN,      # Phase 7h
    INTENT_DIFFERENTIAL_PICKS,      # Phase 7g
    INTENT_PLAYER_FORM,             # Phase 2.6d
    INTENT_INJURY_LIST,             # Phase 2.6d
    INTENT_PRICE_CHANGES,           # Phase 2.6d
    INTENT_TEAM_FIXTURE_CALENDAR,   # Phase 2.6e
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
    OUTCOME_NEEDS_CLARIFICATION,  # Phase 2.7e
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
    DIFFERENTIAL_BOOTSTRAP,   # Phase 7j: low-ownership ok-path bootstrap
    DGW_BOOTSTRAP,            # Phase 8c: double-gameweek (6 teams × 2 GW28 fixtures)
    BGW_BOOTSTRAP,            # Phase 8c: blank-gameweek (2 teams with no GW28 fixture)
    PLAYER_FORM_BOOTSTRAP,    # Phase 2.6d: player form test injection
    PRICE_CHANGES_BOOTSTRAP,  # Phase 2.6d: price changes test fixture
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
    ResolverDebug,   # Phase 4g: resolver debug bundle
    FINAL_TEXT_POLICY,
    respond,
    # Phase 5g: structured comparison metadata
    ComparisonMeta,
    # Phase 5i: per-player comparison context
    ComparisonPlayerContext,
    # Phase 7a: structured transfer metadata
    TransferMeta,
    # Phase 7b: structured chip advice metadata
    ChipAdviceMeta,
    # Phase 7h: structured fixture run metadata
    FixtureEntry,
    FixtureRunMeta,
    # Phase 7g: structured differential picks metadata
    DifferentialEntry,
    DifferentialPicksMeta,
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
from .harness import ask, ask_v2  # ask_v2: Phase M1 (MCP_architecture)
from . import intent_aliases as intent_aliases  # noqa: F401 (Phase M1)
from . import input_normalizer as input_normalizer  # noqa: F401 (Phase M1)
from . import resource_registry as resource_registry  # noqa: F401 (Phase M1)
from . import decision_router as decision_router  # noqa: F401 (Phase M1)
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
from .comparison import (   # Phase 5a/5d/5h
    compare_players,
    # Phase 5d: comparative explainability
    _explain_comparison,
    _margin_label,
    _FORM_ADV_THRESHOLD,
    _FDR_ADV_THRESHOLD,
    _XGI_ADV_THRESHOLD,
    _RISK_ADV_THRESHOLD,
    _MARGIN_NARROW,
    _MARGIN_CLEAR,
    # Phase 5h: role-aware set-piece phrasing
    _set_piece_advantage_phrase,
)
from .transfer_advisor import (   # Phase 6a
    get_transfer_advice,
    _TRANSFER_THRESHOLD_STRONG,
)
from .player_fixture_run import (  # Phase 7h
    get_player_fixture_run,
    DEFAULT_HORIZON as FIXTURE_RUN_DEFAULT_HORIZON,
)
from .differential_picks import (  # Phase 7g
    get_differential_picks,
    OWNERSHIP_THRESHOLD as DIFFERENTIAL_OWNERSHIP_THRESHOLD,
    TOP_N as DIFFERENTIAL_TOP_N,
)
from .chip_advisor import (       # Phase 6b
    get_chip_advice,
    CHIP_TRIPLE_CAPTAIN,
    CHIP_WILDCARD,
    CHIP_BENCH_BOOST,
    CHIP_FREE_HIT,
    SUPPORTED_CHIPS,
    _TC_FAVORABLE_THRESHOLD,
    _TC_MARGINAL_THRESHOLD,
    _WC_EARLY_CUTOFF,
    _WC_LATE_CUTOFF,
    _BB_FAVORABLE_FDR,
    _BB_MARGINAL_FDR,
)
from .player_form import get_player_form              # Phase 2.6d — triggers TOOL_REGISTRY self-registration
from .injury_list import get_injury_list              # Phase 2.6d
from .price_changes import get_price_changes          # Phase 2.6d
from .position_fixture_run import get_position_fixture_run  # Phase 2.6e.4 — triggers TOOL_REGISTRY self-registration
from .transfer_suggestion import get_transfer_suggestion    # Phase 2.6h — triggers TOOL_REGISTRY self-registration
from .find_players import find_players                      # P2.1 — triggers TOOL_REGISTRY self-registration
from .get_player_snapshot import get_player_snapshot        # P2.2 — triggers TOOL_REGISTRY self-registration
from .get_player_history import get_player_history          # P2.3 — triggers TOOL_REGISTRY self-registration
from .get_fixtures_for_gw import get_fixtures_for_gw        # P2.4 — triggers TOOL_REGISTRY self-registration
from .get_gameweek_context import get_gameweek_context      # P2.5 — triggers TOOL_REGISTRY self-registration
from .get_team_snapshot import get_team_snapshot            # P2.6 — triggers TOOL_REGISTRY self-registration
from .web_fetch import web_fetch                            # P2.7 — triggers TOOL_REGISTRY self-registration
from .team_fixture_calendar import (                  # Phase 2.6e
    get_team_fixture_calendar,
    DEFAULT_HORIZON as TEAM_CALENDAR_DEFAULT_HORIZON,
    DEFAULT_TOP_N   as TEAM_CALENDAR_DEFAULT_TOP_N,
)
from .router import (
    RouteResult,
    route,
    # Phase 7h: fixture run routing constants
    _FIXTURE_RUN_PREFIXES,
    _FIXTURE_RUN_SUFFIXES,
    _FIXTURE_RUN_GAME_WORDS,
    # Phase 7g: differential picks routing constants
    _DIFFERENTIAL_KEYWORDS,
)
from .multi_intent import detect_multi_intent  # Phase 6c
from .conversation_state import (
    # Phase 4e: minimal multi-turn conversation state
    ConversationState,
    ConversationSession,
    resolve_pronouns,
    _PRONOUNS,
    # Phase 5c: comparison follow-up support
    resolve_comparison_followup,
    _COMP_FOLLOWUP_PREFIXES,
    _COMP_INSTEAD_SUFFIXES,
    # Phase 7f: transfer follow-up support
    resolve_transfer_followup,
    _TRANSFER_FOLLOWUP_PREFIXES,
    _TRANSFER_INSTEAD_SUFFIXES,
    # Phase 8d-i: fixture run follow-up support
    resolve_fixture_run_followup,
    _FIXTURE_FOLLOWUP_PREFIXES,
    _FIXTURE_INSTEAD_SUFFIXES,
    _FIXTURE_INTERROGATIVE_STARTERS,
    _FIXTURE_REMAINDER_NON_PLAYER_STARTERS,
    _FIXTURE_REMAINDER_CONTENT_BLOCKLIST,
    # Phase 8d-ii: differential follow-up support
    resolve_differential_followup,
    _DIFF_FOLLOWUP_PREFIXES,
    _DIFF_INSTEAD_SUFFIXES,
    _DIFF_INTERROGATIVE_STARTERS,
    _DIFF_REMAINDER_NON_PLAYER_STARTERS,
    _DIFF_REMAINDER_CONTENT_BLOCKLIST,
    # Phase 2.7c: player form follow-up support
    resolve_player_form_followup,
    _FORM_EXACT_PHRASES,
    _FORM_FRAGMENT_PHRASES,
    _FORM_N_GAMES_RE,
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
    # Phase 5f: LLM-assisted comparison follow-up resolution
    resolve_comparison_followup_llm,
    build_comp_resolver_prompt,
    COMP_RESOLVER_SYSTEM_PROMPT,
    _parse_comp_resolver_response,
    _COMP_RESOLVER_MAX_TOKENS,
)
from .telemetry import (                    # Phase 2.7g: in-process telemetry
    record_response as record_response,
    get_snapshot as get_snapshot,
    reset as reset_telemetry,
)

__all__ = [
    # Phase 2n: contract fixtures
    "ConversationFixture",
    "FIXTURE_DEFINITIONS",
    "STANDARD_BOOTSTRAP",
    "AMBIGUOUS_BOOTSTRAP",
    "DIFFERENTIAL_BOOTSTRAP",   # Phase 7j
    "DGW_BOOTSTRAP",            # Phase 8c
    "BGW_BOOTSTRAP",            # Phase 8c
    "run_all",
    # Phase 3d: final response contract fixtures
    "FinalResponseFixture",
    "FINAL_RESPONSE_FIXTURE_DEFINITIONS",
    "run_all_final_response",
    # Phase 3c: final-response policy
    "FinalResponse",
    "FinalResponseDebug",
    "ResolverDebug",
    "FINAL_TEXT_POLICY",
    "respond",
    "ComparisonMeta",           # Phase 5g
    "ComparisonPlayerContext",  # Phase 5i
    "TransferMeta",             # Phase 7a
    "ChipAdviceMeta",           # Phase 7b
    "FixtureEntry",             # Phase 7h
    "FixtureRunMeta",           # Phase 7h
    "DifferentialEntry",        # Phase 7g
    "DifferentialPicksMeta",    # Phase 7g
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
    "INTENT_COMPARE_PLAYERS",
    "INTENT_TRANSFER_ADVICE",      # Phase 6a
    "INTENT_CHIP_ADVICE",          # Phase 6b
    "INTENT_MULTI_INTENT",         # Phase 6c
    "INTENT_PLAYER_FIXTURE_RUN",   # Phase 7h
    "INTENT_DIFFERENTIAL_PICKS",   # Phase 7g
    "INTENT_UNSUPPORTED",
    "SUPPORTED_INTENTS",
    "_TOOL_TO_INTENT",
    # Phase 5a/5d/5h: comparison
    "compare_players",
    "_explain_comparison",
    "_margin_label",
    "_FORM_ADV_THRESHOLD",
    "_FDR_ADV_THRESHOLD",
    "_XGI_ADV_THRESHOLD",
    "_RISK_ADV_THRESHOLD",
    "_MARGIN_NARROW",
    "_MARGIN_CLEAR",
    "_set_piece_advantage_phrase",  # Phase 5h
    # Phase 6a: transfer advice
    "get_transfer_advice",
    "_TRANSFER_THRESHOLD_STRONG",
    # Phase 7h: fixture run
    "get_player_fixture_run",
    "FIXTURE_RUN_DEFAULT_HORIZON",
    "_FIXTURE_RUN_PREFIXES",
    "_FIXTURE_RUN_SUFFIXES",
    "_FIXTURE_RUN_GAME_WORDS",
    # Phase 7g: differential picks
    "get_differential_picks",
    "_DIFFERENTIAL_KEYWORDS",
    "DIFFERENTIAL_OWNERSHIP_THRESHOLD",
    "DIFFERENTIAL_TOP_N",
    # Phase 6b: chip advice
    "get_chip_advice",
    "CHIP_TRIPLE_CAPTAIN",
    "CHIP_WILDCARD",
    "CHIP_BENCH_BOOST",
    "CHIP_FREE_HIT",
    "SUPPORTED_CHIPS",
    "_TC_FAVORABLE_THRESHOLD",
    "_TC_MARGINAL_THRESHOLD",
    "_WC_EARLY_CUTOFF",
    "_WC_LATE_CUTOFF",
    "_BB_FAVORABLE_FDR",
    "_BB_MARGINAL_FDR",
    # Phase 2l: outcomes + manifest
    "OUTCOME_OK",
    "OUTCOME_UNSUPPORTED_INTENT",
    "OUTCOME_NOT_FOUND",
    "OUTCOME_AMBIGUOUS",
    "OUTCOME_MISSING_ARGUMENTS",
    "OUTCOME_ERROR",
    "OUTCOME_NEEDS_CLARIFICATION",  # Phase 2.7e
    "INTENT_MANIFEST",
    # Phase 4e: multi-turn state
    "ConversationState",
    "ConversationSession",
    "resolve_pronouns",
    "_PRONOUNS",
    # Phase 5c: comparison follow-up
    "resolve_comparison_followup",
    "_COMP_FOLLOWUP_PREFIXES",
    "_COMP_INSTEAD_SUFFIXES",
    # Phase 7f: transfer follow-up
    "resolve_transfer_followup",
    "_TRANSFER_FOLLOWUP_PREFIXES",
    "_TRANSFER_INSTEAD_SUFFIXES",
    # Phase 8d-i: fixture run follow-up
    "resolve_fixture_run_followup",
    "_FIXTURE_FOLLOWUP_PREFIXES",
    "_FIXTURE_INSTEAD_SUFFIXES",
    "_FIXTURE_INTERROGATIVE_STARTERS",
    "_FIXTURE_REMAINDER_NON_PLAYER_STARTERS",
    "_FIXTURE_REMAINDER_CONTENT_BLOCKLIST",
    # Phase 8d-ii: differential follow-up
    "resolve_differential_followup",
    "_DIFF_FOLLOWUP_PREFIXES",
    "_DIFF_INSTEAD_SUFFIXES",
    "_DIFF_INTERROGATIVE_STARTERS",
    "_DIFF_REMAINDER_NON_PLAYER_STARTERS",
    "_DIFF_REMAINDER_CONTENT_BLOCKLIST",
    # Phase 2.7c: player form follow-up
    "resolve_player_form_followup",
    "_FORM_EXACT_PHRASES",
    "_FORM_FRAGMENT_PHRASES",
    "_FORM_N_GAMES_RE",
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
    # Phase 5f: LLM-assisted comparison follow-up resolution
    "resolve_comparison_followup_llm",
    "build_comp_resolver_prompt",
    "COMP_RESOLVER_SYSTEM_PROMPT",
    "_parse_comp_resolver_response",
    "_COMP_RESOLVER_MAX_TOKENS",
    # Phase 6c: multi-intent detection
    "detect_multi_intent",
    # Phase 2.7g: in-process telemetry
    "record_response",
    "get_snapshot",
    "reset_telemetry",
    # P2.1: atomic find_players tool
    "find_players",
    # P2.2: atomic get_player_snapshot tool
    "get_player_snapshot",
    # P2.3: atomic get_player_history tool
    "get_player_history",
    # P2.4: atomic get_fixtures_for_gw tool
    "get_fixtures_for_gw",
    # P2.5: atomic get_gameweek_context tool
    "get_gameweek_context",
    # P2.6: atomic get_team_snapshot tool
    "get_team_snapshot",
    # P2.7: atomic web_fetch tool (allowlisted football/FPL URLs)
    "web_fetch",
    # core harness
    "ask",
    "ask_v2",
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

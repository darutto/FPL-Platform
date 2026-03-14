"""
fpl_tool_contract
==================
LLM-friendly tool wrappers for the fpl-platform query layer.

Phase 1f public surface:

    from fpl_tool_contract import (
        tool_resolve_player,
        tool_get_player_summary,
        tool_get_current_gameweek,
    )

Phase 2a additions:

    from fpl_tool_contract import tool_get_captain_score

Phase 2b additions:

    from fpl_tool_contract import tool_rank_captain_candidates

Every function accepts a *bootstrap* dict and returns a plain dict
with a mandatory ``"status"`` key:

    "ok"         — resolution succeeded; answer fields are present
    "ambiguous"  — multiple players share the query; ask for clarification
    "not_found"  — no match; acknowledge to the user
    "error"      — runner-level failure (unknown tool, missing required arg,
                   or invalid candidate_inputs)

No LLM integration, no live API calls, no consumer app wiring in this slice.
This package forms the tool-contract boundary for a future chat interface.

Requires (all Tier A, parity-validated):
    fpl_api_client          (Phase 1c)
    fpl_player_registry     (Phase 1d)
    fpl_query_tools         (Phase 1e)
    fpl_data_core           (Phase 1a/1b — via fpl_query_tools)
    fpl_captain_engine      (Phase 2b — canonical captain score formula)
"""

from .tools import (
    tool_get_captain_score,
    tool_get_current_gameweek,
    tool_get_player_summary,
    tool_rank_captain_candidates,
    tool_resolve_player,
)

__all__ = [
    "tool_resolve_player",
    "tool_get_player_summary",
    "tool_get_current_gameweek",
    "tool_get_captain_score",
    "tool_rank_captain_candidates",
]



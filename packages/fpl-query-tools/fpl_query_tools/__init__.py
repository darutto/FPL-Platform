"""
fpl_query_tools
================
Read-only query helpers composing the fpl-platform owned packages.

Phase 1e public surface:

    from fpl_query_tools import (
        resolve_player_query,
        get_player_summary,
        get_current_gameweek_from_bootstrap,
    )

All functions take explicit in-memory inputs — no live network calls,
no file I/O, no LLM integration.

This package forms the first tool layer for a future grounded chat interface.

Requires (all Tier A, parity-validated):
    fpl_player_registry   (Phase 1d)
    fpl_data_core         (Phase 1a/1b)
    fpl_api_client        (Phase 1c)
"""

from .queries import (
    get_current_gameweek_from_bootstrap,
    get_player_summary,
    resolve_player_query,
)

__all__ = [
    "resolve_player_query",
    "get_player_summary",
    "get_current_gameweek_from_bootstrap",
]



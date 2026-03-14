"""
fpl_tool_runner
================
In-process tool registry and dispatch engine for the fpl-platform.

Phase 1g public surface::

    from fpl_tool_runner import (
        ToolSpec,
        ToolRegistry,
        TOOL_REGISTRY,
        TOOL_SPECS,
        run_tool,
    )

Quick usage::

    result = run_tool("resolve_player", {"query": "Haaland"}, bootstrap)
    # → {"status": "ok", "player_id": 1, "web_name": "Haaland", ...}

    result = run_tool("get_current_gameweek", {}, bootstrap)
    # → {"status": "ok", "gameweek": 28}

No LLM integration, no HTTP server, no consumer app wiring in this slice.
Requires fpl_tool_contract (Phase 1f) and all its transitive dependencies.
"""

from .runner import TOOL_REGISTRY, ToolRegistry, run_tool
from .specs import GET_CURRENT_GAMEWEEK_SPEC, GET_PLAYER_SUMMARY_SPEC, RESOLVE_PLAYER_SPEC, TOOL_SPECS, ToolSpec

__all__ = [
    "ToolSpec",
    "ToolRegistry",
    "TOOL_REGISTRY",
    "TOOL_SPECS",
    "run_tool",
    # Individual specs (convenience re-exports)
    "RESOLVE_PLAYER_SPEC",
    "GET_PLAYER_SUMMARY_SPEC",
    "GET_CURRENT_GAMEWEEK_SPEC",
]



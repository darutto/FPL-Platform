"""
fpl_tool_runner.runner
=======================
In-process tool registry and dispatch engine.

Wraps fpl_tool_contract functions behind a uniform ``run(name, args, bootstrap)``
interface.  All execution is local — no HTTP server, no LLM integration yet.

The ``TOOL_REGISTRY`` module constant is the default registry, pre-populated
with the three Phase 1g tools.  Use ``run_tool(name, args, bootstrap)`` for
the most convenient call site.

Error handling
--------------
Tool-runner errors (unknown tool, missing required input) are returned as
structured dicts rather than raised exceptions, so callers can treat them
identically to data-level outcomes::

    {"status": "error", "code": "unknown_tool",    "message": "..."}
    {"status": "error", "code": "missing_argument", "message": "..."}

This keeps the status vocabulary complete and allows a future LLM dispatcher
to relay the error back to the model without crashing.
"""

from __future__ import annotations

from typing import Any, Callable

from fpl_tool_contract import (
    tool_get_current_gameweek,
    tool_get_player_summary,
    tool_resolve_player,
    tool_get_captain_score,
    tool_rank_captain_candidates,
)

from .specs import (
    GET_CURRENT_GAMEWEEK_SPEC,
    GET_PLAYER_SUMMARY_SPEC,
    RESOLVE_PLAYER_SPEC,
    GET_CAPTAIN_SCORE_SPEC,
    RANK_CAPTAIN_CANDIDATES_SPEC,
    ToolSpec,
)


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """In-process registry of callable tool specs.

    Usage::

        result = TOOL_REGISTRY.run("resolve_player", {"query": "Haaland"}, bootstrap)

    Attributes
    ----------
    tools:
        Ordered list of registered :class:`~fpl_tool_runner.specs.ToolSpec`
        objects.  Preserve insertion order for deterministic ``to_openai_tools()``
        and ``to_anthropic_tools()`` output.
    """

    def __init__(self) -> None:
        self._specs:    dict[str, ToolSpec] = {}
        self._handlers: dict[str, Callable[..., dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        spec:    ToolSpec,
        handler: Callable[..., dict[str, Any]],
    ) -> None:
        """Register a tool spec and its handler function.

        The handler signature must be one of:
          - ``handler(args, bootstrap)``  — for tools with parameters
          - ``handler(bootstrap)``        — for tools with no parameters
        The registry dispatches based on the spec's ``required`` list.
        """
        self._specs[spec.name]    = spec
        self._handlers[spec.name] = handler

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_tools(self) -> list[str]:
        """Return names of all registered tools in registration order."""
        return list(self._specs.keys())

    def get_spec(self, name: str) -> ToolSpec | None:
        """Return the ToolSpec for *name*, or ``None`` if not found."""
        return self._specs.get(name)

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Return a list of OpenAI function-calling tool dicts.

        Drop directly into ``openai.chat.completions.create(tools=...)``.
        """
        return [spec.to_openai() for spec in self._specs.values()]

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        """Return a list of Anthropic tool_use dicts.

        Drop directly into ``anthropic.Anthropic().messages.create(tools=...)``.
        """
        return [spec.to_anthropic() for spec in self._specs.values()]

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def run(
        self,
        name:      str,
        args:      dict[str, Any],
        bootstrap: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate *args* against the tool's schema, then dispatch.

        Parameters
        ----------
        name:
            Tool name (must match a registered spec).
        args:
            Input arguments dict.  For ``get_current_gameweek`` pass ``{}``.
        bootstrap:
            Full FPL bootstrap dict from ``fpl_api_client.get_bootstrap()``.

        Returns
        -------
        dict
            Structured output from the underlying tool, or an error dict
            with ``status="error"`` and an explanatory ``message``.
        """
        spec = self._specs.get(name)
        if spec is None:
            known = ", ".join(f"'{n}'" for n in self._specs)
            return {
                "status":  "error",
                "code":    "unknown_tool",
                "message": (
                    f"Unknown tool '{name}'. "
                    f"Available tools: {known}."
                ),
            }

        # Validate required arguments
        required: list[str] = spec.parameters.get("required", [])
        for req in required:
            if req not in args:
                return {
                    "status":  "error",
                    "code":    "missing_argument",
                    "message": (
                        f"Tool '{name}' requires argument '{req}' "
                        f"but it was not provided."
                    ),
                }

        handler = self._handlers[name]
        if required:
            # Tools with parameters: pass args dict + bootstrap
            return handler(args, bootstrap)
        else:
            # Tools with no parameters (get_current_gameweek): pass only bootstrap
            return handler(bootstrap)


# ---------------------------------------------------------------------------
# Default registry (pre-populated)
# ---------------------------------------------------------------------------

def _resolve_player_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    query = args["query"]
    # Accept numeric strings as ints for id-based lookup
    try:
        query = int(query)
    except (ValueError, TypeError):
        pass
    return tool_resolve_player(query, bootstrap)


def _get_player_summary_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    query = args["query"]
    try:
        query = int(query)
    except (ValueError, TypeError):
        pass
    return tool_get_player_summary(query, bootstrap)


def _get_current_gameweek_handler(
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    return tool_get_current_gameweek(bootstrap)


def _get_captain_score_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    query = args.get("query")
    # Pass explicit scoring inputs if provided; None causes tool to auto-derive
    # scoring inputs from the player's bootstrap element (Phase 5m).
    explicit = {k: v for k, v in args.items() if k != "query"} or None
    return tool_get_captain_score(query, bootstrap, explicit)


def _rank_captain_candidates_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    return tool_rank_captain_candidates(args.get("candidates", []), bootstrap)


TOOL_REGISTRY = ToolRegistry()
TOOL_REGISTRY.register(RESOLVE_PLAYER_SPEC,            _resolve_player_handler)
TOOL_REGISTRY.register(GET_PLAYER_SUMMARY_SPEC,        _get_player_summary_handler)
TOOL_REGISTRY.register(GET_CURRENT_GAMEWEEK_SPEC,      _get_current_gameweek_handler)
TOOL_REGISTRY.register(GET_CAPTAIN_SCORE_SPEC,         _get_captain_score_handler)
TOOL_REGISTRY.register(RANK_CAPTAIN_CANDIDATES_SPEC,   _rank_captain_candidates_handler)


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def run_tool(
    name:      str,
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch a tool call against the default :data:`TOOL_REGISTRY`.

    Equivalent to ``TOOL_REGISTRY.run(name, args, bootstrap)``.

    Example::

        result = run_tool("resolve_player", {"query": "Haaland"}, bootstrap)
        # → {"status": "ok", "player_id": 1, "web_name": "Haaland", ...}

        result = run_tool("get_current_gameweek", {}, bootstrap)
        # → {"status": "ok", "gameweek": 28}
    """
    return TOOL_REGISTRY.run(name, args, bootstrap)
"""
fpl_grounded_assistant.tool_schema_registry
============================================
Phase Orch-2a: Deterministic tool schema registry for grounded tools.

Provides a read-only registry of JSON-schema-like function specs for all
ten grounded tools exposed by the dispatcher.  Schemas are static, additive,
and test-validated.  No runtime wiring or orchestration logic lives here.

This module is a **pure data layer** — no imports from the live FPL stack are
needed and the module produces no side-effects on import.

Intended consumers
------------------
* Phase Orch-3: orchestrator tool-use loop (calls get_tool_schema to build
  tool lists for the LLM API)
* Phase Orch-4: endpoint wiring (serialises schemas for introspection routes)
* Test suites: structural validation without requiring bootstrap data

Registry API
------------
``TOOL_NAMES``                       : frozenset[str]  — all registered names
``list_tool_schemas()``              → list[str]       — sorted name list
``get_tool_schema(name)``            → ToolSchema | None
``validate_tool_schema_shape(s)``    → bool            — structural check

Registered tools (all 10 grounded intents)
-------------------------------------------
+----------------------------+----------------------------------+
| Tool name                  | Intent label                     |
+============================+==================================+
| get_current_gameweek       | current_gameweek                 |
| get_player_summary         | player_summary                   |
| resolve_player             | player_resolve                   |
| get_captain_score          | captain_score                    |
| rank_captain_candidates    | rank_candidates                  |
| compare_players            | compare_players                  |
| get_transfer_advice        | transfer_advice                  |
| get_chip_advice            | chip_advice                      |
| get_player_fixture_run     | player_fixture_run               |
| get_differential_picks     | differential_picks               |
+----------------------------+----------------------------------+

Schema format
-------------
Each ``ToolSchema`` follows the JSON Schema draft-07 ``parameters`` format
used by both the OpenAI function-calling API and the Anthropic tool_use API.
``to_openai()`` and ``to_anthropic()`` serialise to the respective wire shapes.

Design invariants
-----------------
* Schemas are backend-authoritative: required arg lists match exactly what
  the router extracts and what run_tool/tool_contract expects.
* No optional args are listed as required.
* Bootstrap data is never listed as a parameter — it is always an implicit
  runtime argument injected by the orchestration layer.
* ``additionalProperties: false`` is set for all top-level parameter objects
  to catch argument name typos early.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# ToolSchema dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolSchema:
    """Immutable specification for one callable grounded tool.

    Attributes
    ----------
    name:
        Stable snake_case identifier.  Matches the tool name used by
        ``route()``, ``run_tool()``, and the dispatcher's ``_TOOL_TO_INTENT``
        map.  Must be unique within the registry.
    description:
        Concise description for human and LLM consumers.
    parameters:
        JSON Schema (draft-07) ``object`` describing tool inputs.
        Compatible with OpenAI ``function.parameters`` and Anthropic
        ``input_schema``.
    """

    name:        str
    description: str
    parameters:  dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        """Return an OpenAI function-calling tool dict."""
        return {
            "type": "function",
            "function": {
                "name":        self.name,
                "description": self.description,
                "parameters":  self.parameters,
            },
        }

    def to_anthropic(self) -> dict[str, Any]:
        """Return an Anthropic tool_use tool dict."""
        return {
            "name":         self.name,
            "description":  self.description,
            "input_schema": self.parameters,
        }

    def to_gemini(self) -> dict[str, Any]:
        """Return a Gemini function-declaration dict.

        Intended for use inside a ``{"function_declarations": [...]}`` wrapper
        when building the full Gemini tools list::

            tools = [{"function_declarations": [s.to_gemini() for s in _ALL_SCHEMAS]}]
        """
        return {
            "name":        self.name,
            "description": self.description,
            "parameters":  self.parameters,
        }


# ---------------------------------------------------------------------------
# Shared property fragments (avoid repetition across schemas)
# ---------------------------------------------------------------------------

_PLAYER_QUERY_PROP: dict[str, Any] = {
    "type":        ["string", "integer"],
    "description": (
        "Player identifier: FPL element id (int), web_name, "
        "first or second name, or a known alias (e.g. 'KDB', 'Mo', 'el Vikingo')."
    ),
}

_SCORE_INPUT_PROPS: dict[str, Any] = {
    "form": {
        "type":        "number",
        "description": "Recent form override (0-10). Auto-derived from bootstrap when omitted.",
    },
    "fixture_difficulty": {
        "type":        "integer",
        "description": (
            "Opponent strength override (1-5). Auto-derived from the injected "
            "fixture_difficulty_map when omitted."
        ),
    },
    "xgi_per_90": {
        "type":        "number",
        "description": "Expected goal involvement per 90 mins override. Auto-derived when omitted.",
    },
    "minutes_risk": {
        "type":        "number",
        "description": "Rotation/injury risk override (0-100). Auto-derived when omitted.",
    },
}


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

#: No required args — bootstrap is implicit runtime context.
GET_CURRENT_GAMEWEEK_SCHEMA = ToolSchema(
    name="get_current_gameweek",
    description=(
        "Return the current (or next upcoming) FPL gameweek number. "
        "Returns status='ok' with the gameweek integer, "
        "or status='not_found' if the season has not started or has ended."
    ),
    parameters={
        "type":                 "object",
        "properties":           {},
        "required":             [],
        "additionalProperties": False,
    },
)

GET_PLAYER_SUMMARY_SCHEMA = ToolSchema(
    name="get_player_summary",
    description=(
        "Return a full summary for a specific FPL player: "
        "position, cost (£m), ownership, and availability status. "
        "Use when the user asks about a player's price, stats, or availability."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": _PLAYER_QUERY_PROP,
        },
        "required":             ["query"],
        "additionalProperties": False,
    },
)

RESOLVE_PLAYER_SCHEMA = ToolSchema(
    name="resolve_player",
    description=(
        "Resolve a player query to a canonical FPL identity record. "
        "Returns status='ok' with identity fields (name, team, position), "
        "status='ambiguous' when multiple players match (ask for clarification), "
        "or status='not_found' when no player matches."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": _PLAYER_QUERY_PROP,
        },
        "required":             ["query"],
        "additionalProperties": False,
    },
)

GET_CAPTAIN_SCORE_SCHEMA = ToolSchema(
    name="get_captain_score",
    description=(
        "Score a single player as a captain candidate. "
        "Returns captain tier, confidence, and explanatory signals. "
        "All scoring inputs (form, fixture_difficulty, xgi_per_90, minutes_risk) "
        "are auto-derived from the bootstrap; supply them only to override."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type":        ["string", "integer"],
                "description": "Player name, ID, or alias to score.",
            },
            **_SCORE_INPUT_PROPS,
        },
        "required":             ["query"],
        "additionalProperties": False,
    },
)

RANK_CAPTAIN_CANDIDATES_SCHEMA = ToolSchema(
    name="rank_captain_candidates",
    description=(
        "Rank a list of captain candidates by captain score in descending order. "
        "All scoring inputs are auto-derived from the bootstrap unless overridden "
        "per candidate. When no candidates list is supplied the dispatcher "
        "auto-selects the top-10 available players by form."
    ),
    parameters={
        "type": "object",
        "properties": {
            "candidates": {
                "type":  "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type":        ["string", "integer"],
                            "description": "Player name, ID, or alias.",
                        },
                        **_SCORE_INPUT_PROPS,
                    },
                    "required": ["query"],
                },
                "description": "Candidates to rank.",
            },
        },
        "required":             ["candidates"],
        "additionalProperties": False,
    },
)

COMPARE_PLAYERS_SCHEMA = ToolSchema(
    name="compare_players",
    description=(
        "Compare two players by position-aware captain score and return a "
        "grounded recommendation. Use when the user asks 'X vs Y' or "
        "'should I captain X or Y'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query_a": {
                "type":        ["string", "integer"],
                "description": "First player name, ID, or alias.",
            },
            "query_b": {
                "type":        ["string", "integer"],
                "description": "Second player name, ID, or alias.",
            },
        },
        "required":             ["query_a", "query_b"],
        "additionalProperties": False,
    },
)

GET_TRANSFER_ADVICE_SCHEMA = ToolSchema(
    name="get_transfer_advice",
    description=(
        "Recommend whether to sell one player and buy another. "
        "Computes a captain-score differential and returns a deterministic "
        "verdict. Use when the user says 'should I sell X for Y'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query_out": {
                "type":        ["string", "integer"],
                "description": "Player to sell (name, ID, or alias).",
            },
            "query_in": {
                "type":        ["string", "integer"],
                "description": "Player to buy (name, ID, or alias).",
            },
        },
        "required":             ["query_out", "query_in"],
        "additionalProperties": False,
    },
)

GET_CHIP_ADVICE_SCHEMA = ToolSchema(
    name="get_chip_advice",
    description=(
        "Return deterministic advice on whether to use an FPL chip this gameweek. "
        "Evaluates gameweek type (normal / double / blank), fixture difficulty, "
        "and captain score signals."
    ),
    parameters={
        "type": "object",
        "properties": {
            "chip": {
                "type":        "string",
                "enum":        ["triple_captain", "wildcard", "bench_boost", "free_hit"],
                "description": "The chip to evaluate.",
            },
        },
        "required":             ["chip"],
        "additionalProperties": False,
    },
)

GET_PLAYER_FIXTURE_RUN_SCHEMA = ToolSchema(
    name="get_player_fixture_run",
    description=(
        "Return the upcoming fixture run for a player (default 5 fixtures). "
        "Includes opponent, home/away flag, and fixture difficulty rating for "
        "each upcoming gameweek."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type":        ["string", "integer"],
                "description": "Player name, ID, or alias.",
            },
        },
        "required":             ["query"],
        "additionalProperties": False,
    },
)

#: No required args — bootstrap is implicit runtime context.
GET_DIFFERENTIAL_PICKS_SCHEMA = ToolSchema(
    name="get_differential_picks",
    description=(
        "Return top differential FPL picks: players owned by fewer than 15% of "
        "managers, ranked by position-aware score. Use when the user asks about "
        "low-ownership options or differentials."
    ),
    parameters={
        "type":                 "object",
        "properties":           {},
        "required":             [],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# Registry construction
# ---------------------------------------------------------------------------

_ALL_SCHEMAS: tuple[ToolSchema, ...] = (
    GET_CURRENT_GAMEWEEK_SCHEMA,
    GET_PLAYER_SUMMARY_SCHEMA,
    RESOLVE_PLAYER_SCHEMA,
    GET_CAPTAIN_SCORE_SCHEMA,
    RANK_CAPTAIN_CANDIDATES_SCHEMA,
    COMPARE_PLAYERS_SCHEMA,
    GET_TRANSFER_ADVICE_SCHEMA,
    GET_CHIP_ADVICE_SCHEMA,
    GET_PLAYER_FIXTURE_RUN_SCHEMA,
    GET_DIFFERENTIAL_PICKS_SCHEMA,
)

#: Immutable dict mapping tool name → ToolSchema.
_REGISTRY: dict[str, ToolSchema] = {s.name: s for s in _ALL_SCHEMAS}

#: Frozenset of all registered tool names.  Stable across imports.
TOOL_NAMES: frozenset[str] = frozenset(_REGISTRY)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_tool_schemas() -> list[str]:
    """Return a sorted list of all registered tool names.

    The list is alphabetically sorted and stable across Python versions.

    Returns
    -------
    list[str]
        Sorted tool name strings.

    Examples
    --------
    >>> "get_captain_score" in list_tool_schemas()
    True
    >>> list_tool_schemas() == sorted(list_tool_schemas())
    True
    """
    return sorted(_REGISTRY.keys())


def get_tool_schema(name: str) -> ToolSchema | None:
    """Return the ``ToolSchema`` for *name*, or ``None`` if not registered.

    Parameters
    ----------
    name:
        Tool name (snake_case).

    Returns
    -------
    ToolSchema | None

    Examples
    --------
    >>> schema = get_tool_schema("get_captain_score")
    >>> schema.name
    'get_captain_score'
    >>> get_tool_schema("nonexistent") is None
    True
    """
    return _REGISTRY.get(name)


def validate_tool_schema_shape(schema: Any) -> bool:
    """Return ``True`` iff *schema* satisfies all structural requirements.

    Checks performed
    ----------------
    1. Is a ``ToolSchema`` instance.
    2. ``name`` is a non-empty string with no spaces or hyphens
       (enforces snake_case convention).
    3. ``description`` is a non-empty string.
    4. ``parameters`` is a dict with:
       * ``"type" == "object"``
       * ``"properties"`` is a dict (may be empty for no-arg tools)
       * ``"required"`` is a list

    Parameters
    ----------
    schema:
        Any object to check.

    Returns
    -------
    bool
        ``True`` when all checks pass, ``False`` on any failure.
        Never raises.

    Examples
    --------
    >>> validate_tool_schema_shape(get_tool_schema("get_captain_score"))
    True
    >>> validate_tool_schema_shape({"name": "x"})
    False
    """
    try:
        if not isinstance(schema, ToolSchema):
            return False

        # name: non-empty, no spaces, no hyphens
        if not isinstance(schema.name, str) or not schema.name:
            return False
        if " " in schema.name or "-" in schema.name:
            return False

        # description: non-empty str
        if not isinstance(schema.description, str) or not schema.description.strip():
            return False

        # parameters: dict with type/properties/required
        params = schema.parameters
        if not isinstance(params, dict):
            return False
        if params.get("type") != "object":
            return False
        if not isinstance(params.get("properties"), dict):
            return False
        if not isinstance(params.get("required"), list):
            return False

        return True

    except Exception:  # noqa: BLE001
        return False

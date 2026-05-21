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

Registered tools (all 17 grounded intents)
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
| get_player_form            | player_form                      |  (Phase 2.6d)
| get_injury_list            | injury_list                      |  (Phase 2.6d)
| get_price_changes          | price_changes                    |  (Phase 2.6d)
| get_team_fixture_calendar  | team_fixture_calendar            |  (Phase 2.6e)
| get_team_schedule          | team_schedule                    |  (Phase 2.6e.3)
| get_position_fixture_run   | position_fixture_run             |  (Phase 2.6e.4)
| get_transfer_suggestion    | transfer_suggestion              |  (Phase 2.6h)
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
        "Current/next FPL GW number. Returns: {status:'ok', gameweek:int} | {status:'not_found'}."
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
        "Full summary for one FPL player: position, cost(£m), ownership, availability. "
        "Use for price/stats/availability queries."
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
        "Resolve query → canonical FPL identity (name/team/position). "
        "Returns: {status:'ok',...} | {status:'ambiguous',...} | {status:'not_found'}."
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
        "Score one player as captain candidate. Returns: tier, confidence, signals. "
        "Inputs (form/fdr/xgi_per_90/minutes_risk) auto-derived; override optional."
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
        "Rank captain candidates by score (desc). Inputs auto-derived; override per candidate. "
        "Omit candidates → auto top-10 by form."
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
        "Compare two players by position-aware captain score; returns grounded recommendation. "
        "Use for 'X vs Y' or 'captain X or Y' queries."
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
        "Sell/buy decision: captain-score diff → deterministic verdict. "
        "Use for 'should I sell X for Y' queries."
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
        "Chip usage advice (triple_captain/wildcard/bench_boost/free_hit). "
        "Evaluates GW type (normal/double/blank), FDR, captain signals."
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
        "Upcoming fixture run for a player (default 5 GWs). "
        "Returns: opponent, home/away, FDR per GW."
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
        "Top differential FPL picks: ownership <15%, ranked by position-aware score. "
        "Use for low-ownership/differential queries."
    ),
    parameters={
        "type":                 "object",
        "properties":           {},
        "required":             [],
        "additionalProperties": False,
    },
)

# ---------------------------------------------------------------------------
# Phase 2.6 grounded tools — registered in M3 preflight (B1 closure).
#
# Each schema describes the LLM-visible argument surface, mirroring how the
# dispatcher invokes the underlying handler.  Bootstrap remains an implicit
# runtime argument and is never listed as a parameter.
# ---------------------------------------------------------------------------

GET_PLAYER_FORM_SCHEMA = ToolSchema(
    name="get_player_form",
    description=(
        "Player GW history: minutes/goals/assists/bonus/points for last N GWs. "
        "Use for recent-form or last-games queries."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": _PLAYER_QUERY_PROP,
            "n_games": {
                "type":        "integer",
                "description": (
                    "Number of most-recent gameweeks to return (default 5, "
                    "clamped 1–38)."
                ),
                "minimum":     1,
                "maximum":     38,
            },
        },
        "required":             ["query"],
        "additionalProperties": False,
    },
)

#: No required args — bootstrap is implicit runtime context.
GET_INJURY_LIST_SCHEMA = ToolSchema(
    name="get_injury_list",
    description=(
        "Unavailable/doubtful FPL players (status!='a'): name, team, position, "
        "status, chance_of_playing, news. Use for injury/doubt/unavailable queries."
    ),
    parameters={
        "type":                 "object",
        "properties":           {},
        "required":             [],
        "additionalProperties": False,
    },
)

#: No required args — bootstrap is implicit runtime context.
GET_PRICE_CHANGES_SCHEMA = ToolSchema(
    name="get_price_changes",
    description=(
        "Players with recent price change (non-zero cost_change_event), grouped: risers/fallers. "
        "Use for price-change/riser/faller queries."
    ),
    parameters={
        "type":                 "object",
        "properties":           {},
        "required":             [],
        "additionalProperties": False,
    },
)

GET_TEAM_FIXTURE_CALENDAR_SCHEMA = ToolSchema(
    name="get_team_fixture_calendar",
    description=(
        "Rank ALL PL teams by upcoming FDR (easiest/hardest) over N GWs. "
        "NOT for single-team schedule (use get_team_schedule) or single-player."
    ),
    parameters={
        "type": "object",
        "properties": {
            "mode": {
                "type":        "string",
                "enum":        ["easiest", "hardest"],
                "description": (
                    "Sort direction. 'easiest' (default) ranks lowest average "
                    "FDR first; 'hardest' ranks highest first."
                ),
            },
            "horizon": {
                "type":        "integer",
                "description": (
                    "Number of upcoming gameweeks to include (default 5, "
                    "clamped 1–10)."
                ),
                "minimum":     1,
                "maximum":     10,
            },
            "top_n": {
                "type":        "integer",
                "description": (
                    "Maximum number of teams to return (default 5, clamped "
                    "1–20)."
                ),
                "minimum":     1,
                "maximum":     20,
            },
        },
        "required":             [],
        "additionalProperties": False,
    },
)

GET_TEAM_SCHEDULE_SCHEMA = ToolSchema(
    name="get_team_schedule",
    description=(
        "One club's upcoming fixtures with DGW/BGW labels over N GWs. "
        "Use for single-team schedule queries (e.g. 'Arsenal fixtures next 5')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "team_query": {
                "type":        "string",
                "description": (
                    "Team identifier: full name, short_name, or common alias "
                    "(e.g. 'Arsenal', 'ARS', 'Liverpool')."
                ),
            },
            "horizon": {
                "type":        "integer",
                "description": (
                    "Number of upcoming gameweeks to include (default 5, "
                    "clamped 1–10)."
                ),
                "minimum":     1,
                "maximum":     10,
            },
        },
        "required":             ["team_query"],
        "additionalProperties": False,
    },
)

GET_POSITION_FIXTURE_RUN_SCHEMA = ToolSchema(
    name="get_position_fixture_run",
    description=(
        "Rank teams by FDR for a specific position (GKP/DEF/MID/FWD). "
        "Use for 'best fixtures for defenders/midfielders/forwards' queries."
    ),
    parameters={
        "type": "object",
        "properties": {
            "position_query": {
                "type":        "string",
                "description": (
                    "Position name or alias: 'goalkeeper', 'defender', "
                    "'midfielder', 'forward' (or Spanish equivalents)."
                ),
            },
            "mode": {
                "type":        "string",
                "enum":        ["easiest", "hardest"],
                "description": "Sort direction (default 'easiest').",
            },
            "horizon": {
                "type":        "integer",
                "description": (
                    "Number of upcoming gameweeks to include (default 5, "
                    "clamped 1–10)."
                ),
                "minimum":     1,
                "maximum":     10,
            },
        },
        "required":             ["position_query"],
        "additionalProperties": False,
    },
)

GET_TRANSFER_SUGGESTION_SCHEMA = ToolSchema(
    name="get_transfer_suggestion",
    description=(
        "Ranked transfer targets filtered by position/club/price ceiling. "
        "Use for 'best X to buy' or 'cheap forwards under Y'. NOT for sell decisions or differentials."
    ),
    parameters={
        "type": "object",
        "properties": {
            "position_query": {
                "type":        "string",
                "description": (
                    "Optional position filter: 'goalkeeper', 'defender', "
                    "'midfielder', 'forward' (or Spanish equivalents). "
                    "Omit to consider all positions."
                ),
            },
            "team_query": {
                "type":        "string",
                "description": (
                    "Optional club filter: team name, short_name, or alias."
                ),
            },
            "max_price": {
                "type":        "number",
                "description": (
                    "Optional price ceiling in millions (e.g. 8.0 means "
                    "£8.0m or less)."
                ),
                "minimum":     0,
            },
            "horizon": {
                "type":        "integer",
                "description": (
                    "Number of upcoming gameweeks used for FDR scoring "
                    "(default 5, clamped 1–10)."
                ),
                "minimum":     1,
                "maximum":     10,
            },
            "top_n": {
                "type":        "integer",
                "description": (
                    "Maximum number of suggestions to return (default 5, "
                    "clamped 1–20)."
                ),
                "minimum":     1,
                "maximum":     20,
            },
        },
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
    # Phase 2.6 tools — registered in M3 preflight (blocker B1).
    GET_PLAYER_FORM_SCHEMA,
    GET_INJURY_LIST_SCHEMA,
    GET_PRICE_CHANGES_SCHEMA,
    GET_TEAM_FIXTURE_CALENDAR_SCHEMA,
    GET_TEAM_SCHEDULE_SCHEMA,
    GET_POSITION_FIXTURE_RUN_SCHEMA,
    GET_TRANSFER_SUGGESTION_SCHEMA,
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

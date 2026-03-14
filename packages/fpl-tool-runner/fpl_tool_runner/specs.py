"""
fpl_tool_runner.specs
======================
Machine-readable tool specifications for the fpl-platform tool surface.

Each ToolSpec contains:
  - name         Stable tool identifier (snake_case)
  - description  Human/LLM-readable description of what the tool does
  - parameters   JSON Schema for tool inputs  (OpenAI ``parameters`` format)
  - output_schema JSON Schema documenting the structured output shape

Schema format
-------------
``parameters`` follows JSON Schema draft-07, identical to the format expected
by the OpenAI function-calling API and the Anthropic tool_use API.

Dual-format export
------------------
``ToolSpec.to_openai()``     → dict ready for OpenAI   ``tools=[...]``
``ToolSpec.to_anthropic()``  → dict ready for Anthropic ``tools=[...]``

Status vocabulary (all outputs)
---------------------------------
``"ok"``         Tool resolved successfully; all answer fields present.
``"ambiguous"``  Multiple players match; caller must request clarification.
``"not_found"``  No match; caller should acknowledge.
``"error"``      Runner-level failure (unknown tool, missing required arg).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolSpec:
    """Immutable specification for one callable tool.

    Attributes
    ----------
    name:
        Stable snake_case identifier.  Must be unique within a registry.
    description:
        Concise description of the tool's purpose for human and LLM consumers.
    parameters:
        JSON Schema (draft-07) object describing tool inputs.
        Compatible with both OpenAI ``function.parameters`` and Anthropic
        ``input_schema`` format.
    output_schema:
        JSON Schema documenting the tool's output shape.  Used for testing
        and documentation; not enforced at runtime (the tool-contract layer
        guarantees correct shapes).
    """

    name:          str
    description:   str
    parameters:    dict[str, Any]
    output_schema: dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        """Return an OpenAI function-calling tool dict.

        Compatible with ``openai.chat.completions.create(tools=[...])``::

            client.chat.completions.create(
                model="gpt-4o",
                tools=[spec.to_openai() for spec in TOOL_SPECS],
                messages=[...],
            )
        """
        return {
            "type": "function",
            "function": {
                "name":        self.name,
                "description": self.description,
                "parameters":  self.parameters,
            },
        }

    def to_anthropic(self) -> dict[str, Any]:
        """Return an Anthropic tool_use tool dict.

        Compatible with ``anthropic.Anthropic().messages.create(tools=[...])``::

            client.messages.create(
                model="claude-opus-4-6",
                tools=[spec.to_anthropic() for spec in TOOL_SPECS],
                messages=[...],
            )
        """
        return {
            "name":         self.name,
            "description":  self.description,
            "input_schema": self.parameters,
        }


# ---------------------------------------------------------------------------
# Shared schema fragments
# ---------------------------------------------------------------------------

_QUERY_PROPERTY: dict[str, Any] = {
    "type":        ["string", "integer"],
    "description": (
        "Player identifier: FPL element id (int), web_name, "
        "first or second name, or a known alias (e.g. 'KDB', 'Mo', 'el Vikingo')."
    ),
}

_STATUS_ENUM    = ["ok", "ambiguous", "not_found", "error"]
_PLAYER_STATUSES = ["Available", "Doubtful", "Injured", "Suspended", "Unavailable"]
_POSITIONS       = ["GKP", "DEF", "MID", "FWD"]
_RESOLVED_VIA    = ["id", "web_name", "exact_name", "alias"]

_PLAYER_OK_PROPS: dict[str, Any] = {
    "status":       {"type": "string", "enum": ["ok"]},
    "player_id":    {"type": "integer",  "description": "FPL element id"},
    "web_name":     {"type": "string",   "description": "FPL display name"},
    "name":         {"type": "string",   "description": "First Last full name"},
    "team":         {"type": "string",   "description": "Full team name"},
    "team_short":   {"type": "string",   "description": "Three-letter abbreviation"},
    "position":     {"type": "string",   "enum": _POSITIONS},
    "status_label": {"type": "string",   "enum": _PLAYER_STATUSES},
    "resolved_via": {"type": "string",   "enum": _RESOLVED_VIA},
    "query":        {"type": "string",   "description": "The original query string"},
}

_NON_OK_PROPS: dict[str, Any] = {
    "status":  {"type": "string", "enum": ["ambiguous", "not_found", "error"]},
    "query":   {"type": "string"},
    "message": {"type": "string"},
}


# ---------------------------------------------------------------------------
# Tool: resolve_player
# ---------------------------------------------------------------------------

RESOLVE_PLAYER_SPEC = ToolSpec(
    name="resolve_player",
    description=(
        "Resolve a player query to a canonical FPL player identity record. "
        "Accepts a player id, web_name, first/second name, or known alias "
        "(e.g. 'KDB', 'Mo', 'el Vikingo'). "
        "Returns status='ok' with core identity fields, "
        "status='ambiguous' when multiple players share the query (ask for clarification), "
        "or status='not_found' when no player matches."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": _QUERY_PROPERTY,
        },
        "required": ["query"],
    },
    output_schema={
        "oneOf": [
            {
                "title": "ok",
                "type": "object",
                "required": ["status", "player_id", "web_name", "name",
                             "team", "team_short", "position",
                             "status_label", "resolved_via", "query"],
                "properties": _PLAYER_OK_PROPS,
                "additionalProperties": False,
            },
            {
                "title": "ambiguous_or_not_found_or_error",
                "type": "object",
                "required": ["status", "message"],
                "properties": _NON_OK_PROPS,
            },
        ]
    },
)


# ---------------------------------------------------------------------------
# Tool: get_player_summary
# ---------------------------------------------------------------------------

GET_PLAYER_SUMMARY_SPEC = ToolSpec(
    name="get_player_summary",
    description=(
        "Return a full player summary suitable for grounded answer generation. "
        "Includes all identity fields from resolve_player plus "
        "current cost (£m) and ownership percentage. "
        "Use this when the user asks about a specific player's details, "
        "availability, price, or ownership. "
        "Returns the same status vocabulary as resolve_player."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": _QUERY_PROPERTY,
        },
        "required": ["query"],
    },
    output_schema={
        "oneOf": [
            {
                "title": "ok",
                "type": "object",
                "required": ["status", "player_id", "web_name", "name",
                             "team", "team_short", "position", "cost_m",
                             "status_label", "selected_by_percent",
                             "resolved_via", "query"],
                "properties": {
                    **_PLAYER_OK_PROPS,
                    "cost_m": {
                        "type":        ["number", "null"],
                        "description": "Current cost in £m (e.g. 14.5)",
                    },
                    "selected_by_percent": {
                        "type":        ["string", "null"],
                        "description": "Ownership percentage string (e.g. '52.3')",
                    },
                },
                "additionalProperties": False,
            },
            {
                "title": "ambiguous_or_not_found_or_error",
                "type": "object",
                "required": ["status", "message"],
                "properties": _NON_OK_PROPS,
            },
        ]
    },
)


# ---------------------------------------------------------------------------
# Tool: get_current_gameweek
# ---------------------------------------------------------------------------

GET_CURRENT_GAMEWEEK_SPEC = ToolSpec(
    name="get_current_gameweek",
    description=(
        "Return the current (or next upcoming) FPL gameweek number. "
        "Returns status='ok' with the gameweek integer, "
        "or status='not_found' if the season has not started or has ended."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    output_schema={
        "oneOf": [
            {
                "title": "ok",
                "type": "object",
                "required": ["status", "gameweek"],
                "properties": {
                    "status":   {"type": "string", "enum": ["ok"]},
                    "gameweek": {"type": "integer", "description": "Gameweek number"},
                },
                "additionalProperties": False,
            },
            {
                "title": "not_found_or_error",
                "type": "object",
                "required": ["status", "message"],
                "properties": {
                    "status":  {"type": "string", "enum": ["not_found", "error"]},
                    "message": {"type": "string"},
                },
            },
        ]
    },
)


# ---------------------------------------------------------------------------
# Tool: get_captain_score
# ---------------------------------------------------------------------------

GET_CAPTAIN_SCORE_SPEC = ToolSpec(
    name="get_captain_score",
    description=(
        "Score a single player as a captain candidate, "
        "returning captain tier, confidence, and explanatory signals."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Player name or ID to score",
            },
            "form": {
                "type": "number",
                "description": "Recent form (0–10)",
            },
            "fixture_difficulty": {
                "type": "integer",
                "description": "Opponent strength (1–5)",
            },
            "xgi_per_90": {
                "type": "number",
                "description": "Expected goal involvement per 90 minutes",
            },
            "minutes_risk": {
                "type": "number",
                "description": "Rotation/injury risk (0–100)",
            },
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "tier": {"type": "string"},
            "captain_score": {"type": "number"},
        },
    },
)


# ---------------------------------------------------------------------------
# Tool: rank_captain_candidates
# ---------------------------------------------------------------------------

RANK_CAPTAIN_CANDIDATES_SPEC = ToolSpec(
    name="rank_captain_candidates",
    description=(
        "Rank a list of captain candidates by captain score, "
        "returning them in descending score order."
    ),
    parameters={
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Player name or ID"},
                        "form": {"type": "number"},
                        "fixture_difficulty": {"type": "integer"},
                        "xgi_per_90": {"type": "number"},
                        "minutes_risk": {"type": "number"},
                    },
                    "required": ["query"],
                },
                "description": "List of candidate dicts to rank",
            },
        },
        "required": ["candidates"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "ranked_candidates": {"type": "array"},
        },
    },
)


# ---------------------------------------------------------------------------
# Canonical list of all tool specs
# ---------------------------------------------------------------------------

TOOL_SPECS: list[ToolSpec] = [
    RESOLVE_PLAYER_SPEC,
    GET_PLAYER_SUMMARY_SPEC,
    GET_CURRENT_GAMEWEEK_SPEC,
    GET_CAPTAIN_SCORE_SPEC,
    RANK_CAPTAIN_CANDIDATES_SPEC,
]
"""
fpl_grounded_assistant.tool_schema_registry
============================================
Phase Orch-2a: Deterministic tool schema registry for grounded tools.

Provides a read-only registry of JSON-schema-like function specs for all
grounded tools exposed by the dispatcher.  Schemas are static, additive,
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

Registered tools (34 grounded tools, including compatibility and FI tools)
-------------------------------------------------------------------------
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
| get_fixture_outlook        | orchestrator-only: 2-axis outlook|  (Track D/FI2)
| find_players               | atomic: fuzzy name search        |  (P2.1)
| get_player_snapshot        | atomic: single-player snapshot   |  (P2.2)
| get_player_history         | atomic: per-GW history           |  (P2.3)
| get_fixtures_for_gw        | atomic: GW fixture list+FDR      |  (P2.4)
| get_gameweek_context       | atomic: temporal GW context      |  (P2.5)
| get_team_snapshot          | atomic: single-team overview     |  (P2.6)
| web_fetch                  | atomic: allowlisted URL fetch    |  (P2.7)
| rank_players_by_metric     | atomic: ranked player list       |  (P2.8)
| build_squad                | exact 15-man squad under budget  |  (S1)
| select_players_within_budget | best N of one position, completable | (S2)
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
        Compatible with OpenAI Responses ``parameters`` and Anthropic
        ``input_schema``.
    """

    name:        str
    description: str
    parameters:  dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        """Return an OpenAI Responses API function-calling tool dict."""
        return {
            "type":        "function",
            "name":        self.name,
            "description": self.description,
            "parameters":  self.parameters,
            # Existing schemas are not guaranteed to satisfy every strict-mode
            # constraint (notably required/additionalProperties), so opt out
            # explicitly while still using the current Responses wire shape.
            "strict":      False,
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

            offered = get_offered_tool_schemas(football_intelligence_enabled=False)
            tools = [{"function_declarations": [s.to_gemini() for s in offered]}]
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
        "candidates is required: pass the players to rank."
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
        "Evaluates GW type (normal/double/blank), FDR, captain signals. "
        "It does NOT build or price a squad: for 'is bench boost viable if I build "
        "a team from scratch' call build_squad for the squad and its totals, then "
        "this tool for the chip verdict."
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
        "Use for 'best X to buy' or 'cheap forwards under Y'. NOT for sell decisions or differentials. "
        "Returns INDEPENDENT suggestions: each one is ranked on its own, so the list "
        "does not check squad legality, the three-per-club cap, or whether the players "
        "on it can be bought TOGETHER within a budget. The price filter is a per-player "
        "ceiling, not a combined one. "
        "When the question asks for a specific NUMBER of players that must fit a budget "
        "together \u2014 'cuatro medios que me permita el presupuesto', 'dos delanteros' "
        "\u2014 use select_players_within_budget, which does that arithmetic and proves a "
        "legal squad is still completable. For a full 15-man squad use build_squad."
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
# Track D / FI2 — get_fixture_outlook (two-axis difficulty + run detection)
# ---------------------------------------------------------------------------

GET_FIXTURE_OUTLOOK_SCHEMA = ToolSchema(
    name="get_fixture_outlook",
    description=(
        "Two-axis fixture outlook over N GWs (default 10). axis='attack' = how "
        "easy it is to SCORE (use for attackers/captaincy); axis='defence' = how "
        "easy it is to keep a CLEAN SHEET (use for defenders/goalkeepers). "
        "Returns per-GW difficulty bands (1=easiest…5=hardest), detected good/bad "
        "RUNS (≥3 consecutive GWs), and a Spanish schedule-only verdict. "
        "Omit team_query for ALL teams ranked easiest-first (the grid). For a "
        "player, resolve their club first, then pass that club as team_query."
    ),
    parameters={
        "type": "object",
        "properties": {
            "axis": {
                "type":        "string",
                "enum":        ["attack", "defence"],
                "description": (
                    "Which difficulty axis to read. 'attack' for goal-scoring "
                    "(attackers/captaincy); 'defence' for clean sheets "
                    "(defenders/GKP)."
                ),
            },
            "team_query": {
                "type":        "string",
                "description": (
                    "Optional team name, short_name, or alias (e.g. 'Arsenal', "
                    "'ARS', 'Spurs'). Omit to get every team ranked easiest-first."
                ),
            },
            "horizon": {
                "type":        "integer",
                "description": "Upcoming GWs to analyse (default 10, clamped 1–15).",
                "minimum":     1,
                "maximum":     15,
            },
        },
        # axis is required so the runner dispatches handler(args, bootstrap) and
        # the model consciously picks the position-relevant axis.
        "required":             ["axis"],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# P2.1 atomic tool — find_players fuzzy name search
# ---------------------------------------------------------------------------

FIND_PLAYERS_SCHEMA = ToolSchema(
    name="find_players",
    description=(
        "Fuzzy player name search (accent+case insensitive). Returns candidates with "
        "full grounding payload: id, availability, form, cost, ownership, match_rank. "
        "not_found when no match."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name_query": {
                "type":        "string",
                "description": "Player name substring (case-insensitive, accent-insensitive)",
            },
            "limit": {
                "type":        "integer",
                "description": "Max results (1-10, default 5)",
                "minimum":     1,
                "maximum":     10,
            },
        },
        "required":             ["name_query"],
        "additionalProperties": False,
    },
)

# ---------------------------------------------------------------------------
# P2.2 atomic tool — get_player_snapshot single-player lookup
# ---------------------------------------------------------------------------

GET_PLAYER_SNAPSHOT_SCHEMA = ToolSchema(
    name="get_player_snapshot",
    description=(
        "Single player full grounding payload by name or numeric FPL element id. Returns status=ok+player "
        "(1 match), ambiguous+candidates (multi-match), or not_found. Use for "
        "every general named-player lookup, profile, or current-stat question."
    ),
    parameters={
        "type": "object",
        "properties": {
            "player_name": {
                "type":        ["string", "integer"],
                "description": "Player name (case/accent-insensitive) or numeric FPL element id",
            },
        },
        "required":             ["player_name"],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# P2.3 atomic tool — get_player_history per-GW temporal window
# ---------------------------------------------------------------------------

GET_PLAYER_HISTORY_SCHEMA = ToolSchema(
    name="get_player_history",
    description=(
        "Per-GW history for one player over last N gameweeks. Returns history list "
        "(minutes, points, goals, assists, xG, xA, BPS) + summary. "
        "status=ambiguous on multi-match; not_found / error otherwise."
    ),
    parameters={
        "type": "object",
        "properties": {
            "player_name": {
                "type":        "string",
                "description": "Player name (case-insensitive, accent-insensitive)",
            },
            "last_n_gws": {
                "type":        "integer",
                "description": "Number of recent gameweeks to return (1-38, default 5)",
                "minimum":     1,
                "maximum":     38,
            },
        },
        "required":             ["player_name"],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# P2.4 atomic tool — get_fixtures_for_gw GW fixture list with FDR
# ---------------------------------------------------------------------------

GET_FIXTURES_FOR_GW_SCHEMA = ToolSchema(
    name="get_fixtures_for_gw",
    description=(
        "All fixtures for a GW with FDR per team. Returns fixture list (kickoff, teams, FDR, "
        "scores) + summary (totals, easiest/hardest, DGW+BGW teams). "
        "status=invalid_argument on out-of-range gw_number."
    ),
    parameters={
        "type": "object",
        "properties": {
            "gw_number": {
                "type":        "integer",
                "description": "Gameweek number (1-38)",
                "minimum":     1,
                "maximum":     38,
            },
        },
        "required":             ["gw_number"],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# P2.5 atomic tool — get_gameweek_context temporal GW grounding
# ---------------------------------------------------------------------------

GET_GAMEWEEK_CONTEXT_SCHEMA = ToolSchema(
    name="get_gameweek_context",
    description=(
        "Current/next GW with deadlines + blank/double alerts for next 5 GWs. "
        "Returns current_gw, next_gw, season status, blank_gw_alerts, "
        "double_gw_alerts. No args. Use before reasoning about next GW."
    ),
    parameters={
        "type":                 "object",
        "properties":           {},
        "required":             [],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# P2.6 atomic tool — get_team_snapshot single-team overview
# ---------------------------------------------------------------------------

GET_TEAM_SNAPSHOT_SCHEMA = ToolSchema(
    name="get_team_snapshot",
    description=(
        "Single team snapshot: form, next N fixtures+FDR, top N players (full grounding payload), "
        "summary (avg FDR, easy/hard run, top scorer). "
        "status=ambiguous on multi-match (e.g. 'manchester')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "team_name": {
                "type":        "string",
                "description": (
                    "Team name, short code, or substring (case+accent insensitive). "
                    "E.g. 'wolves', 'WOL', 'Wolverhampton', 'aston villa', 'AVL'."
                ),
            },
            "top_n_players": {
                "type":        "integer",
                "description": "Max top players to return (1-10, default 5)",
                "minimum":     1,
                "maximum":     10,
            },
            "fixture_horizon": {
                "type":        "integer",
                "description": "Number of upcoming fixtures to include (1-10, default 5)",
                "minimum":     1,
                "maximum":     10,
            },
        },
        "required":             ["team_name"],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# i39 atomic tool — get_my_squad (the connected user's own squad)
# ---------------------------------------------------------------------------

GET_MY_SQUAD_SCHEMA = ToolSchema(
    name="get_my_squad",
    description=(
        "The connected user's own 15-man FPL squad for a gameweek: starting XI + bench "
        "(pick order), captain/vice-captain, price, injury/availability status, form, "
        "and any active chip. "
        "CALL IT WHENEVER THE QUESTION PRESUPPOSES THE USER ALREADY HAS A SQUAD, with "
        "or without a possessive. Possessives ('mi equipo', 'mi plantilla', 'mis "
        "suplentes', 'evalúa mi equipo') are the obvious case, not the only one: the "
        "condition is that answering correctly requires knowing what they already own. "
        "That includes references to the rest of a squad they already have ('ya tengo "
        "el resto del equipo armado'), to the budget they have left ('el presupuesto "
        "que me queda'), to transfers they have already made or are making ('después de "
        "estas ventas'), and to filling specific slots in an existing squad ('necesito "
        "4 medios', 'dos delanteros y un defensa'). Fetch the squad first, then answer. "
        "DO NOT CALL IT when nothing in the question implies an existing squad -- "
        "a general market question ('¿qué defensas baratos hay?'), a comparison between "
        "players ('compara Haaland y Salah'), or the state of the gameweek ('¿cuál es "
        "la jornada actual?') are answered without it, and pulling someone's squad into "
        "them only adds irrelevant context. Never for a hypothetical or another "
        "manager's team. "
        "status='no_team_connected' when no team is linked (ask the user to connect one, "
        "never ask them to paste their 15 players by hand)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "gw": {
                "type":        "integer",
                "description": (
                    "Gameweek to fetch picks for (1-38). Defaults to the current gameweek. "
                    "A future GW has no published picks yet and is clamped down to the "
                    "current GW automatically (response gw_clamped=true, requested_gw echoes "
                    "what was asked for) — the current squad is still the right basis for "
                    "planning a future chip or transfer."
                ),
                "minimum":     1,
                "maximum":     38,
            },
        },
        "required":             [],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# P2.7 atomic tool — web_fetch (allowlisted football/FPL URL fetch)
# ---------------------------------------------------------------------------

WEB_FETCH_SCHEMA = ToolSchema(
    name="web_fetch",
    description=(
        "Fetch news from allowlisted football/FPL domains (BBC sport, Athletic, PL, FPL, "
        "FBref, Transfermarkt). status=refused for off-topic URLs or SSRF. No cache."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type":        "string",
                "description": (
                    "Full URL to fetch. Must be on an allowlisted football/FPL domain. "
                    "status=refused returned for any non-allowlisted domain or private IP."
                ),
            },
        },
        "required":             ["url"],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# P2.8 atomic tool — rank_players_by_metric ranked player list
# ---------------------------------------------------------------------------

RANK_PLAYERS_BY_METRIC_SCHEMA = ToolSchema(
    name="rank_players_by_metric",
    description=(
        "Top N players by any supported bootstrap metric: performance and per-90 rates; "
        "price; current-GW transfer momentum; set-piece order; cards; xGC; ICT components; "
        "and saves. Filter by position, minutes, and price bounds. "
        "Ranks the CURRENT snapshot only: it has NO knowledge of fixtures, opponents, "
        "schedule difficulty or future gameweeks, and no metric expresses them. "
        "For a question about upcoming gameweeks ('next 5', 'over the run', "
        "'best fixtures'), use get_transfer_suggestion, which takes a horizon. "
        "Use this for top/best/most-by-metric queries about present-state metrics, "
        "even when the metric may be unknown (the tool validates and returns valid_metrics). "
        "It also answers the LEAST/CHEAPEST/LOWEST variants -- pass order='asc' rather "
        "than reordering a descending list, which would only rank the wrong end. "
        "A ranked list is not a squad: it ignores budget, positional quotas and the "
        "three-per-club cap, so use build_squad when the answer has to be a legal squad, "
        "and select_players_within_budget when it has to be a specific number of players "
        "that fit a budget together."
    ),
    parameters={
        "type": "object",
        "properties": {
            "metric": {
                "type":        "string",
                "description": (
                    "Metric to rank by. Common aliases: xgi, xg, xa, ict, ppg, xgi/90, "
                    "price/precio, transfers_in/out, penalties/penales, corners, free kicks, "
                    "yellow/red cards, xgc, influence, creativity, threat, saves/paradas. "
                    "Pass unknown values through so the tool returns unknown_metric."
                ),
            },
            "top_n": {
                "type":        "integer",
                "description": "Max players to return (1-50, default 10)",
                "minimum":     1,
                "maximum":     50,
            },
            "position": {
                "type":        "string",
                "description": (
                    "Optional position filter: GKP/DEF/MID/FWD (case-insensitive). "
                    "Spanish: portero/defensa/centrocampista/delantero."
                ),
            },
            "min_minutes": {
                "type":        "integer",
                "description": (
                    "Exclude players with fewer minutes (default 0). "
                    "SET THIS WHENEVER order='asc' on any accumulating metric -- goals, "
                    "assists, cards, xGC, saves, clean sheets, points and every "
                    "per-90 rate. A player who has not played has 0 of all of them, and "
                    "0 sorts to the very top of an ascending list, so the answer fills "
                    "with players who never appeared. Use at least a full match's worth "
                    "of minutes: 60-90. min_minutes=1 filters NOTHING -- one minute "
                    "still leaves ~0 in every accumulating metric. The exception is "
                    "price (now_cost), where a 4.0m player with no minutes is a "
                    "legitimate bench-fodder answer, and the 'minutes' metric itself, "
                    "where players with none are exactly what a rotation or injury "
                    "question is asking for. If you "
                    "omit it under order='asc' the tool applies a 60-minute floor "
                    "itself and reports it in min_minutes_filter; pass your own value "
                    "when you want a different one."
                ),
                "minimum":     0,
            },
            "min_price": {
                "type":        "number",
                "description": "Inclusive minimum player price in GBP millions.",
                "minimum":     0,
            },
            "max_price": {
                "type":        "number",
                "description": "Inclusive maximum player price in GBP millions.",
                "minimum":     0,
            },
            "order": {
                "type":        "string",
                "enum":        ["desc", "asc"],
                "description": (
                    "Sort direction. Default 'desc' = highest value first. "
                    "Use 'asc' for LOWEST-first questions -- 'menos', 'más barato', "
                    "'más baratos', 'menor', 'peor', 'diferencial', 'cheapest', "
                    "'fewest', 'lowest'. Without it a 'cheapest defenders' question "
                    "gets the MOST expensive ones. With 'asc' on anything except "
                    "price, ALSO set min_minutes to at least 60 (a full match), or "
                    "every value ties at 0 and the list is players who never played."
                ),
            },
        },
        "required":             ["metric"],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# S1 — build_squad: exact constrained squad construction
#
# The LLM cannot do constrained squad arithmetic. Measured, not assumed: across
# the agentic-loop experiment models produced squads costing 117.5 and 133.5
# against a 100.0 budget while stating the total as 100.0m, with every
# individual price grounded correctly. This tool owns the arithmetic so no
# prompt has to ask a model to be careful with it.
#
# The description states fixture blindness BEFORE the capability, following
# 7a05a96: a description that over-promises coverage sends models to the wrong
# tool, and that failure is silent.
# ---------------------------------------------------------------------------

BUILD_SQUAD_SCHEMA = ToolSchema(
    name="build_squad",
    description=(
        "Builds a complete, legal 15-man FPL squad under a budget and does all the "
        "arithmetic itself. Enforces exactly 2 GKP / 5 DEF / 5 MID / 3 FWD, at most 3 "
        "players per club, and the budget ceiling; returns the squad, every price, "
        "totals that reconcile, and a starting XI. When no legal squad fits it says so "
        "explicitly and reports the cheapest legal squad's cost rather than returning a "
        "near-miss. "
        "USE IT for 'build me a squad', 'armar un equipo desde cero', wildcard drafts, "
        "bench-boost feasibility, and any question whose answer must add up to a budget. "
        "IT ALWAYS RETURNS 15: for a question about FEWER players that must still fit a "
        "budget \u2014 'four midfielders my budget allows', 'dos delanteros' \u2014 use "
        "select_players_within_budget, which picks a slice and proves the rest of the "
        "squad is still completable. "
        "NEVER total the prices or check the three-per-club limit yourself: quote this "
        "tool's totals verbatim. "
        "WHAT IT DOES NOT CONSIDER: fixtures, opponents, schedule difficulty or any "
        "future gameweek. It ranks on the season-to-date bootstrap only (objective "
        "'total_points' by default, or 'points_per_game'; 'form' is not offered because "
        "it reads 0.0 for every player pre-season). No view on captaincy, price changes "
        "or rotation risk, and it excludes only players not flagged available. It "
        "maximises the total across all 15 and does not discount bench slots -- exactly "
        "right for a bench-boost question, slightly bench-heavy otherwise. Pair it with "
        "get_fixture_outlook or get_transfer_suggestion when the question is about the "
        "upcoming run."
    ),
    parameters={
        "type": "object",
        "properties": {
            "budget": {
                "type":        "number",
                "description": (
                    "TOTAL budget in millions (default 100.0). Pass the whole budget even "
                    "when players are locked -- their cost is deducted automatically. For "
                    "'Haaland is a lock, so I start at -15.5' pass budget=100.0 and "
                    "locked_players=['Haaland'], NOT budget=84.5."
                ),
                "minimum":     0,
            },
            "locked_players": {
                "type":        "array",
                "description": (
                    "Players the squad must contain, by name, alias or element id. Their "
                    "price is charged against the budget."
                ),
                "items":       {"type": ["string", "integer"]},
            },
            "formation": {
                "type":        "string",
                "description": (
                    "Starting-XI shape as DEF-MID-FWD, e.g. '4-5-1' or '3-4-3' (the "
                    "goalkeeper is implicit). Picks the XI out of the 15; it does NOT "
                    "change the 15-man squad split. Omit for the best legal shape."
                ),
            },
            "position_counts": {
                "type":        "object",
                "description": (
                    "Override the 15-man SQUAD split, e.g. {'DEF': 4, 'MID': 6}. Rarely "
                    "needed, and NOT how to express a formation: a real FPL squad is "
                    "always 2/5/5/3, so any override returns a squad that cannot be "
                    "entered in the game, flagged in warnings."
                ),
                "properties": {
                    "GKP": {"type": "integer", "minimum": 0},
                    "DEF": {"type": "integer", "minimum": 0},
                    "MID": {"type": "integer", "minimum": 0},
                    "FWD": {"type": "integer", "minimum": 0},
                },
                "additionalProperties": False,
            },
            "objective": {
                "type":        "string",
                "enum":        ["points_per_game", "total_points"],
                "description": (
                    "What to maximise. 'total_points' (default) is season points and "
                    "rewards players who actually played; 'points_per_game' is "
                    "per-appearance and will favour small-sample backups unless "
                    "min_minutes is raised."
                ),
            },
            "min_minutes": {
                "type":        "integer",
                "description": (
                    "Exclude players below this minutes total (default 1, i.e. anyone who "
                    "has played). Raise it to suppress small-sample picks."
                ),
                "minimum":     0,
            },
        },
        "required":             [],
        "additionalProperties": False,
    },
)

# ---------------------------------------------------------------------------
# S2 — select_players_within_budget: partial selection that stays completable
# ---------------------------------------------------------------------------

SELECT_PLAYERS_SCHEMA = ToolSchema(
    name="select_players_within_budget",
    description=(
        "Picks the best N players of ONE position that a legal 15-man squad can still "
        "absorb, and does all the arithmetic itself. It charges the locked players and "
        "the picks against the same budget, applies the three-per-club cap, and PROVES "
        "a legal filling of the remaining slots exists before returning anything, so a "
        "selection that would strand the budget is never offered. Returns the picks, "
        "each price, the selection's total cost, the budget left, and the witness squad "
        "that proves the picks fit. "
        "USE IT for partial-squad questions that carry money: '4 midfielders my budget "
        "allows', 'dos delanteros, estoy indeciso entre baratos y caros', 'which 3 "
        "defenders can I afford if Haaland is a lock', 'the best keeper for what's left "
        "after these transfers'. "
        "BOUNDARY WITH build_squad, which is the only other tool that does squad "
        "arithmetic: build_squad returns the WHOLE 15, this returns a SLICE of one. Ask "
        "build_squad for a full team or a wildcard draft; ask this for any smaller "
        "number of players. Asking here for all 15 is the wrong tool, and so is asking "
        "build_squad for four midfielders. "
        "NEVER total the prices, subtract a locked player's cost, or check the "
        "three-per-club limit yourself: quote this tool's totals verbatim. "
        "WHAT IT DOES NOT CONSIDER: fixtures, opponents, schedule difficulty or any "
        "future gameweek. It ranks on the season-to-date bootstrap only (objective "
        "'total_points' by default, or 'points_per_game'; 'form' is not offered because "
        "it reads 0.0 for every player pre-season). No view on captaincy, price changes "
        "or rotation risk, and it excludes only players not flagged available. It picks "
        "ONE position per call, so a two-position question takes two calls. Pair it with "
        "get_fixture_outlook or get_transfer_suggestion when the question is also about "
        "the upcoming run — those rank on fixtures but cannot keep a squad legal. "
        "The witness squad it returns is the CHEAPEST legal completion, included only as "
        "proof the picks are affordable; it is not a recommended bench. "
        "When no selection of that size fits, it returns an explicit infeasible answer "
        "naming what would be affordable instead, never a near-miss dressed up as valid."
    ),
    parameters={
        "type": "object",
        "properties": {
            "position": {
                "type":        "string",
                "description": (
                    "The one position to pick from: 'goalkeeper', 'defender', "
                    "'midfielder', 'forward', their FPL codes (GKP/DEF/MID/FWD), or the "
                    "Spanish equivalents ('portero', 'defensa', 'medio', 'delantero')."
                ),
            },
            "count": {
                "type":        "integer",
                "description": (
                    "How many players to pick, e.g. 4 for 'cuatro medios'. Must leave "
                    "room inside the position's squad quota (2 GKP / 5 DEF / 5 MID / "
                    "3 FWD) once the locked players are counted."
                ),
                "minimum":     1,
            },
            "budget": {
                "type":        "number",
                "description": (
                    "TOTAL budget in millions (default 100.0). Pass the whole budget "
                    "even when players are locked — their cost is deducted "
                    "automatically. For 'Haaland is a lock, so I start at -15.5' pass "
                    "budget=100.0 and locked_players=['Haaland'], NOT budget=84.5."
                ),
                "minimum":     0,
            },
            "locked_players": {
                "type":        "array",
                "description": (
                    "Players already in the squad, by name, alias or element id. Their "
                    "price is charged against the budget and their clubs count towards "
                    "the three-per-club cap."
                ),
                "items":       {"type": ["string", "integer"]},
            },
            "max_price": {
                "type":        "number",
                "description": (
                    "Optional ceiling in millions on EACH picked player, e.g. 6.0 for "
                    "'medios baratos'. Bounds the picks only — the remaining squad "
                    "slots are unaffected."
                ),
                "minimum":     0,
            },
            "min_price": {
                "type":        "number",
                "description": (
                    "Optional floor in millions on EACH picked player, e.g. 9.0 for "
                    "'delanteros premium'. Bounds the picks only."
                ),
                "minimum":     0,
            },
            "objective": {
                "type":        "string",
                "enum":        ["points_per_game", "total_points"],
                "description": (
                    "What to maximise across the picks. 'total_points' (default) is "
                    "season points and rewards players who actually played; "
                    "'points_per_game' is per-appearance and will favour small-sample "
                    "backups unless min_minutes is raised."
                ),
            },
            "min_minutes": {
                "type":        "integer",
                "description": (
                    "Exclude players below this minutes total (default 1, i.e. anyone "
                    "who has played). Raise it to suppress small-sample picks."
                ),
                "minimum":     0,
            },
        },
        "required":             ["position", "count"],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# Web search — last-resort, premium-gated tool (kept OUT of _ALL_SCHEMAS)
# ---------------------------------------------------------------------------
# This schema is appended to the per-request tool list ONLY when web search is
# both toggled on by the user AND their tier is eligible (see
# orchestrator._build_tools(web_search_enabled=...) and fpl_server.py's
# WEB_SEARCH_TIERS gate). Keeping it separate from _ALL_SCHEMAS guarantees the
# base deterministic registry is unchanged and the model cannot reach for web
# search unless it was explicitly enabled for that turn.

SEARCH_WEB_SCHEMA = ToolSchema(
    name="search_web",
    description=(
        "LAST RESORT. Live web search for FPL/football information that NO other "
        "tool can provide: breaking news, injuries/doubts, suspensions, "
        "press-conference quotes, transfer/lineup rumours, or opinion/prediction "
        "questions. NEVER use it for player stats, prices, fixtures, or form — "
        "those have dedicated tools and are always more reliable. "
        "QUERY CONSTRUCTION: `query` must be concise, keyword-heavy, and "
        "stripped of conversational filler (e.g. 'Salah lesion estado Liverpool', "
        "not the user's raw sentence)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type":        "string",
                "description": (
                    "Concise, keyword-heavy search query (no conversational "
                    "filler). Player/team/topic keywords only."
                ),
            },
        },
        "required":             ["query"],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# T-zonal atomic tools — tactical zonal-weakness intelligence (owned
# Understat store). Orchestrator-callable only: deliberately NOT in
# _TOOL_TO_INTENT / SUPPORTED_INTENTS / the classifier (narrated as text).
# ---------------------------------------------------------------------------

GET_ZONAL_WEAKNESS_SCHEMA = ToolSchema(
    name="get_zonal_weakness",
    description=(
        "Use ONLY when the user asks purely which zones a team concedes in "
        "(por dónde/en qué zonas concede), with NO mention of players or "
        "exploiting. If they mention who can exploit/attack it, use "
        "get_zonal_opportunity instead. Shows where the attacking opportunity "
        "is per pitch zone — xGA/game vs league baseline (delta_vs_avg is the "
        "signal; penalties excluded, reported separately), owned Understat "
        "data. Zones ONLY, no player names. Opportunity read only — never "
        "buy/sell advice."
    ),
    parameters={
        "type": "object",
        "properties": {
            "team": {
                "type":        "string",
                "description": "Team name / short_name / alias (e.g. 'Crystal Palace', 'CRY').",
            },
        },
        "required":             ["team"],
        "additionalProperties": False,
    },
)

GET_ZONAL_OPPORTUNITY_SCHEMA = ToolSchema(
    name="get_zonal_opportunity",
    description=(
        "Use whenever the user asks WHO / WHICH PLAYERS can exploit, attack "
        "or take advantage of an opponent's weak zones (quién puede "
        "explotarlo/atacarlo, qué jugadores lo aprovechan) — EVEN IF the "
        "question also asks which zones they concede. This is the PRIMARY "
        "tool for any 'zones + players' question about an opponent: it shows "
        "where to attack (weak zones vs league baseline) WITH the matched "
        "players to exploit each zone, from owned Understat data. Opportunity "
        "signal only — never buy/sell advice."
    ),
    parameters={
        "type": "object",
        "properties": {
            "opponent": {
                "type":        "string",
                "description": "Opposing team name / short_name / alias whose defence to probe.",
            },
        },
        "required":             ["opponent"],
        "additionalProperties": False,
    },
)


GET_PLAYER_ZONAL_OUTLOOK_SCHEMA = ToolSchema(
    name="get_player_zonal_outlook",
    description=(
        "Use when the SUBJECT is a specific NAMED PLAYER and the question is "
        "whether their upcoming fixtures suit them zonally — do the next "
        "opponents' weak zones match where the player generates xG (¿le "
        "vienen bien los próximos rivales a X?, ¿contra quién juega X y le "
        "favorece el cruce?). Per-GW favorable/neutral matchup read over the "
        "next 1-5 fixtures (default 3), from owned Understat shot data + the "
        "fixture calendar. Opportunity signal only — never buy/sell advice."
    ),
    parameters={
        "type": "object",
        "properties": {
            "player": {
                "type":        "string",
                "description": "Player name as known (e.g. 'Saka', 'Bukayo Saka').",
            },
            "horizon": {
                "type":        "integer",
                "description": "Upcoming GWs to analyse (1-5, default 3).",
            },
        },
        "required":             ["player"],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# FI-7b1 intelligence tool shells
# ---------------------------------------------------------------------------

GET_EXPECTED_MINUTES_SCHEMA = ToolSchema(
    name="get_expected_minutes",
    description=(
        "Return governed expected-minutes intelligence for one player. "
        "FI-7b1 exposes a non-operational shell only."
    ),
    parameters={
        "type": "object",
        "properties": {"player": _PLAYER_QUERY_PROP},
        "required": ["player"],
        "additionalProperties": False,
    },
)

GET_TACTICAL_ROLE_SCHEMA = ToolSchema(
    name="get_tactical_role",
    description=(
        "Return governed tactical-role intelligence for one player. "
        "FI-7b1 exposes a non-operational shell only."
    ),
    parameters={
        "type": "object",
        "properties": {"player": _PLAYER_QUERY_PROP},
        "required": ["player"],
        "additionalProperties": False,
    },
)

GET_FIXTURE_CONTEXT_SCHEMA = ToolSchema(
    name="get_fixture_context",
    description=(
        "Return governed fixture context for a team and fixture. "
        "FI-7b1 exposes a non-operational shell only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "team": {
                "type": ["string", "integer"],
                "description": "Team name, short name, or canonical identifier.",
            },
            "fixture": {
                "type": ["string", "integer"],
                "description": "Fixture reference supplied by the caller.",
            },
        },
        "required": ["team", "fixture"],
        "additionalProperties": False,
    },
)

GET_PLAYER_INTELLIGENCE_SCHEMA = ToolSchema(
    name="get_player_intelligence",
    description=(
        "Return the governed M1, M2, and M3 intelligence bundle for one "
        "player. FI-7b1 exposes a non-operational shell only."
    ),
    parameters={
        "type": "object",
        "properties": {"player": _PLAYER_QUERY_PROP},
        "required": ["player"],
        "additionalProperties": False,
    },
)

FI7B_TOOL_SCHEMAS: tuple[ToolSchema, ...] = (
    GET_EXPECTED_MINUTES_SCHEMA,
    GET_TACTICAL_ROLE_SCHEMA,
    GET_FIXTURE_CONTEXT_SCHEMA,
    GET_PLAYER_INTELLIGENCE_SCHEMA,
)


# ---------------------------------------------------------------------------
# Registry construction
# ---------------------------------------------------------------------------

_BASE_REGISTERED_SCHEMAS: tuple[ToolSchema, ...] = (
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
    # Track D / FI2 — two-axis fixture outlook + run detection
    GET_FIXTURE_OUTLOOK_SCHEMA,
    # P2.1 atomic tool
    FIND_PLAYERS_SCHEMA,
    # P2.2 atomic tool
    GET_PLAYER_SNAPSHOT_SCHEMA,
    # P2.3 atomic tool
    GET_PLAYER_HISTORY_SCHEMA,
    # P2.4 atomic tool
    GET_FIXTURES_FOR_GW_SCHEMA,
    # P2.5 atomic tool
    GET_GAMEWEEK_CONTEXT_SCHEMA,
    # P2.6 atomic tool
    GET_TEAM_SNAPSHOT_SCHEMA,
    # i39 atomic tool — connected user's own squad
    GET_MY_SQUAD_SCHEMA,
    # P2.7 atomic tool
    WEB_FETCH_SCHEMA,
    # P2.8 atomic tool
    RANK_PLAYERS_BY_METRIC_SCHEMA,
    # S1 — exact constrained squad construction
    BUILD_SQUAD_SCHEMA,
    SELECT_PLAYERS_SCHEMA,
    # T-zonal atomic tools (orchestrator-only; no intent, no card)
    GET_ZONAL_WEAKNESS_SCHEMA,
    GET_ZONAL_OPPORTUNITY_SCHEMA,
    GET_PLAYER_ZONAL_OUTLOOK_SCHEMA,
)

# Compatibility adapters remain registered and directly callable, but are no
# longer choices the LLM can make for new chat turns. General named-player
# lookup is represented by get_player_snapshot alone.
DEPRECATED_LLM_TOOL_NAMES: frozenset[str] = frozenset({
    "find_players",
    "resolve_player",
    "get_player_summary",
})

_BASE_OFFERED_SCHEMAS: tuple[ToolSchema, ...] = tuple(
    schema
    for schema in _BASE_REGISTERED_SCHEMAS
    if schema.name not in DEPRECATED_LLM_TOOL_NAMES
)

_ALL_SCHEMAS: tuple[ToolSchema, ...] = (
    *_BASE_REGISTERED_SCHEMAS,
    *FI7B_TOOL_SCHEMAS,
)

#: Immutable dict mapping tool name → ToolSchema.
_REGISTRY: dict[str, ToolSchema] = {s.name: s for s in _ALL_SCHEMAS}

#: Frozenset of all registered tool names.  Stable across imports.
TOOL_NAMES: frozenset[str] = frozenset(_REGISTRY)

#: Names of the four FI-7b tools controlled by the master offered-set flag.
FI7B_TOOL_NAMES: frozenset[str] = frozenset(s.name for s in FI7B_TOOL_SCHEMAS)

#: search_web is intentionally excluded from _ALL_SCHEMAS / TOOL_NAMES (it is
#: premium-gated and opt-in per request — see SEARCH_WEB_SCHEMA docstring
#: above). This separate registry/name-set is consulted ONLY when the caller
#: explicitly enables web search for the turn (orchestrator.py).
_REGISTRY_WITH_SEARCH: dict[str, ToolSchema] = {**_REGISTRY, SEARCH_WEB_SCHEMA.name: SEARCH_WEB_SCHEMA}
TOOL_NAMES_WITH_SEARCH: frozenset[str] = frozenset(_REGISTRY_WITH_SEARCH)


def get_offered_tool_schemas(
    football_intelligence_enabled: bool,
) -> tuple[ToolSchema, ...]:
    """Return the immutable LLM-offered schema set for one flag state."""
    if football_intelligence_enabled:
        return (*_BASE_OFFERED_SCHEMAS, *FI7B_TOOL_SCHEMAS)
    return _BASE_OFFERED_SCHEMAS


def get_offered_tool_names(
    football_intelligence_enabled: bool,
    *,
    web_search_enabled: bool = False,
) -> frozenset[str]:
    """Return names reachable through LLM tool dispatch for one request."""
    names = frozenset(
        schema.name
        for schema in get_offered_tool_schemas(football_intelligence_enabled)
    )
    if web_search_enabled:
        return names | {SEARCH_WEB_SCHEMA.name}
    return names


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
    return _REGISTRY_WITH_SEARCH.get(name)


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

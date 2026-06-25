"""
worldcup_assistant.tools
=========================
World Cup tool registry: JSON-schema provider specs + deterministic executor.

Pattern audited from ``fpl_grounded_assistant.tool_schema_registry`` /
``orchestrator.py`` (Task 1): the schema registry is the only source of tool
definitions; tool execution is always deterministic (an API call, never the
LLM); the LLM selects tools and phrases the answer but cannot alter grounded
data.

Every executor result passes through ``locale_es.localize_payload`` so
country names, statuses, stages, and positions are Spanish BEFORE the LLM or
any structured response field sees them.

Tool results use the ``{"status": "ok" | "error", ...}`` envelope so the
tool loop and (later) cards can branch without parsing prose.
"""
from __future__ import annotations

from typing import Any, Callable

from llm_orchestrator_core import ToolSpec
from worldcup_api_client import (
    WorldCupAPIError,
    get_bracket,
    get_fantasy_top_players,
    get_fixtures,
    get_head_to_head,
    get_lineup,
    get_live_scores,
    get_match_stats,
    get_player_info,
    get_player_wc2022_summary,
    get_squad,
    get_standings,
    get_top_assists,
    get_top_scorers,
    get_wc2022_results,
)

from .locale_es import localize_payload
from .web_search import search_web

# ---------------------------------------------------------------------------
# Provider tool specs (JSON Schema draft-07 parameter objects)
# ---------------------------------------------------------------------------

_TEAM_PROP: dict[str, Any] = {
    "type": "string",
    "description": (
        "Team name in ENGLISH as used by the data API (e.g. 'Ivory Coast', "
        "'United States', 'Spain'). Translate Spanish user input to the "
        "English FIFA name before calling."
    ),
}

_MATCH_ID_PROP: dict[str, Any] = {
    "type": ["string", "integer"],
    "description": "Match identifier from a fixtures or live-scores result.",
}

WC_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="get_live_scores",
        description=(
            "All World Cup 2026 matches currently in play, with live scores "
            "and match minute. Use for any '¿cómo va…?' / current-score question."
        ),
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        name="get_fixtures",
        description=(
            "Tournament fixture schedule and results. Optionally filter by "
            "team, date (YYYY-MM-DD), or stage. Use for 'cuándo juega…', "
            "today's matches, and past results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "team": _TEAM_PROP,
                "date": {
                    "type": "string",
                    "description": "Filter by date, format YYYY-MM-DD.",
                },
                "stage": {
                    "type": "string",
                    "description": (
                        "Filter by stage enum: group_stage, round_of_32, "
                        "round_of_16, quarter_final, semi_final, third_place, final."
                    ),
                },
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_squad",
        description=(
            "Full tournament squad (players, positions, clubs) for one "
            "national team. Use for roster / 'plantilla' / player-info questions."
        ),
        parameters={
            "type": "object",
            "properties": {"team": _TEAM_PROP},
            "required": ["team"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_lineup",
        description=(
            "Confirmed starting lineup and bench for one match. Lineups "
            "appear roughly an hour before kickoff."
        ),
        parameters={
            "type": "object",
            "properties": {"match_id": _MATCH_ID_PROP},
            "required": ["match_id"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_standings",
        description=(
            "Group-stage standings. Optionally one group letter (A–L). Use "
            "for 'clasificación' / '¿cómo va el grupo…?' questions."
        ),
        parameters={
            "type": "object",
            "properties": {
                "group": {
                    "type": "string",
                    "description": "Single group letter A–L. Omit for all groups.",
                },
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_bracket",
        description=(
            "Knockout-stage bracket (Dieciseisavos/Round of 32 → Final). Each "
            "match gives both sides as either a confirmed team or a pending "
            "slot described in Spanish (e.g. '2.º del Grupo A', 'Ganador del "
            "partido 74', 'Mejor 3.º (Grupos A/B/C/D/F)'). Use for "
            "'¿cómo queda(n) los cruces/octavos/llave/bracket?', 'a quién "
            "enfrenta el ganador del Grupo X', and any knockout-pairing "
            "question. Confirmed pairings appear as groups finish; before that "
            "the slot descriptions explain who will play whom. Optionally "
            "filter by stage."
        ),
        parameters={
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "description": (
                        "Filter to one knockout round: round_of_32, "
                        "round_of_16, quarter_final, semi_final, third_place, "
                        "final. Omit for the full bracket."
                    ),
                },
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_top_scorers",
        description=(
            "Tournament top GOALSCORERS ranking (goals + assists from match "
            "results). Use for 'goleadores' / who has scored the most goals. "
            "Do NOT use this for fantasy-points questions — use "
            "get_fantasy_top_players instead."
        ),
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        name="get_top_assists",
        description=(
            "Tournament top ASSIST providers ranking (assists + goals from "
            "match results). Use for 'asistencias' / 'asistidores' / who has "
            "set up the most goals. Sibling of get_top_scorers, sorted by "
            "assists first."
        ),
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        name="get_fantasy_top_players",
        description=(
            "FIFA Fantasy points leaderboard: players ranked by total FANTASY "
            "POINTS earned this tournament (a scoring system based on goals, "
            "assists, clean sheets, minutes played, bonus, etc — NOT the same "
            "as goals scored). Use for '¿qué jugador ha hecho más puntos?', "
            "'mejores delanteros de fantasy', 'jugador más en forma', "
            "'jugadores más valiosos'. Optionally filter by position and/or team."
        ),
        parameters={
            "type": "object",
            "properties": {
                "position": {
                    "type": "string",
                    "description": (
                        "Filter by position: GK, DEF, MID, or FWD "
                        "(Spanish names like 'delantero' also accepted). "
                        "Omit for all positions."
                    ),
                },
                "team": _TEAM_PROP,
                "limit": {
                    "type": "integer",
                    "description": "Max number of players to return (default 10, max 50).",
                },
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_player_info",
        description=(
            "Single-player profile: team, position, price, FIFA Fantasy stats "
            "(total/avg points, form) and tournament goals/assists. Use for "
            "'/jugador' and player-info questions. For comparisons ('Mbappé vs "
            "Haaland', '/comparar'), call this once per player (one call each)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Player name as written by the user (any spelling/accents).",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_player_wc2022_stats",
        description=(
            "WC2022 (Qatar) tournament stats for a player who also played in "
            "that World Cup: appearances, minutes, goals, assists, yellow/red "
            "cards, GK saves, key passes, average match rating. This is a "
            "fast local lookup (no live API call). Call this alongside "
            "get_player_info for '/jugador' and '/comparar' to add historical "
            "depth — most players won't have WC2022 data (only ~590 of the "
            "2026 squads also played in 2022), which is expected, not an error."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Player name as written by the user (any spelling/accents).",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_wc2022_results",
        description=(
            "Match results from the WC2022 (Qatar) tournament: final scores "
            "(incl. penalty shootouts), venue, date, stage. This is a fast "
            "local lookup (no live API call). Use for questions about the "
            "previous World Cup ('Mundial pasado/2022'), e.g. 'cómo le fue a "
            "Argentina en 2022', 'quién ganó el mundial pasado', 'resultados "
            "de octavos de final 2022'. Optionally filter by team and/or "
            "stage; omit both for all 64 matches."
        ),
        parameters={
            "type": "object",
            "properties": {
                "team": {
                    "type": "string",
                    "description": (
                        "Team name in ENGLISH as used by the data API (e.g. "
                        "'Argentina', 'Netherlands'). Omit for all teams."
                    ),
                },
                "stage": {
                    "type": "string",
                    "description": (
                        "Filter by stage enum: group_stage, round_of_16, "
                        "quarter_final, semi_final, third_place, final. "
                        "Omit for all stages."
                    ),
                },
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_head_to_head",
        description=(
            "Historical head-to-head record between two national teams. Use "
            "for comparison and 'historial' questions."
        ),
        parameters={
            "type": "object",
            "properties": {"team_a": _TEAM_PROP, "team_b": _TEAM_PROP},
            "required": ["team_a", "team_b"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_match_stats",
        description=(
            "In-play or full-time statistics for one match (possession, "
            "shots, cards, corners…)."
        ),
        parameters={
            "type": "object",
            "properties": {"match_id": _MATCH_ID_PROP},
            "required": ["match_id"],
            "additionalProperties": False,
        },
    ),
]

# ---------------------------------------------------------------------------
# Web search — last-resort, premium-gated tool (kept OUT of the base registry)
# ---------------------------------------------------------------------------
# This spec is appended to the per-request tool list ONLY when web search is
# both toggled on by the user AND their tier is eligible (see ask_wc /
# wc_server). Keeping it separate from WC_TOOL_SPECS guarantees the base
# deterministic registry is unchanged and the model cannot reach for web
# search unless it was explicitly enabled for that turn.

WEB_SEARCH_TOOL_SPEC: ToolSpec = ToolSpec(
    name="web_search",
    description=(
        "LAST RESORT. Live web search for World Cup information that NO other "
        "tool can provide: breaking news, injuries/dudas, suspensions, "
        "press-conference quotes, transfer/lineup rumours, or opinion/"
        "prediction questions. NEVER use it for scores, fixtures, standings, "
        "squads, goalscorers, assists, fantasy points or any stat — those have "
        "dedicated tools and are always more reliable. "
        "QUERY CONSTRUCTION: the `query` must be concise, keyword-heavy, and "
        "stripped of conversational filler. Never pass the user's raw "
        "conversational sentence directly. Example — user 'oye, ¿sabes si "
        "Mbappé está lesionado para el partido de mañana?' → "
        "query: 'Mbappé lesión estado Francia'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Concise, keyword-heavy search query (no conversational "
                    "filler). Player/team/topic keywords only."
                ),
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)

#: Full tool set (base + web search). Used for name validation / introspection;
#: the actual per-request list is built by ``build_wc_tool_specs``.
ALL_WC_TOOL_SPECS: list[ToolSpec] = [*WC_TOOL_SPECS, WEB_SEARCH_TOOL_SPEC]

WC_TOOL_NAMES: frozenset[str] = frozenset(s.name for s in ALL_WC_TOOL_SPECS)


def build_wc_tool_specs(*, web_search_enabled: bool = False) -> list[ToolSpec]:
    """Per-request tool list.

    Returns the base deterministic registry, plus ``web_search`` only when it
    was explicitly enabled for this turn (toggle on AND tier eligible). When
    disabled the tool is simply absent, so the model cannot call it — zero risk
    of silent paid-search spend.
    """
    if web_search_enabled:
        return ALL_WC_TOOL_SPECS
    return WC_TOOL_SPECS

#: List-valued tool-output fields subject to token-budget truncation
#: (mirrors the FPL orchestrator's _TRUNCATABLE_FIELDS lever).
#: "players" is deliberately excluded: get_squad's full roster (~50-55
#: entries pre-cut) backs the squad card and should render in full, and
#: get_fantasy_top_players already self-limits via its own `limit` arg
#: (default 10, max 50).
WC_TRUNCATABLE_FIELDS: frozenset[str] = frozenset({
    "matches", "fixtures", "scorers", "assisters", "events", "results",
})


# ---------------------------------------------------------------------------
# Deterministic executor
# ---------------------------------------------------------------------------

_CLIENT_DISPATCH: dict[str, Callable[..., Any]] = {
    "get_live_scores":  lambda args: get_live_scores(),
    "get_fixtures":     lambda args: get_fixtures(
        team=args.get("team"), date=args.get("date"), stage=args.get("stage"),
    ),
    "get_squad":        lambda args: get_squad(args["team"]),
    "get_lineup":       lambda args: get_lineup(args["match_id"]),
    "get_standings":    lambda args: get_standings(group=args.get("group")),
    "get_bracket":      lambda args: get_bracket(stage=args.get("stage")),
    "get_top_scorers":  lambda args: get_top_scorers(),
    "get_top_assists":  lambda args: get_top_assists(),
    "get_fantasy_top_players": lambda args: get_fantasy_top_players(
        position=args.get("position"), team=args.get("team"), limit=args.get("limit"),
    ),
    "get_head_to_head": lambda args: get_head_to_head(args["team_a"], args["team_b"]),
    "get_player_info":  lambda args: get_player_info(args["name"]),
    "get_player_wc2022_stats": lambda args: get_player_wc2022_summary(args["name"]),
    "get_wc2022_results": lambda args: get_wc2022_results(team=args.get("team"), stage=args.get("stage")),
    "get_match_stats":  lambda args: get_match_stats(args["match_id"]),
    "web_search":       lambda args: search_web(args["query"]),
}

_REQUIRED_ARGS: dict[str, tuple[str, ...]] = {
    "get_squad":        ("team",),
    "get_lineup":       ("match_id",),
    "get_head_to_head": ("team_a", "team_b"),
    "get_player_info":  ("name",),
    "get_player_wc2022_stats": ("name",),
    "get_match_stats":  ("match_id",),
    "web_search":       ("query",),
}


def execute_wc_tool(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    """Execute one WC tool deterministically and return a localized envelope.

    Always returns a dict — expected failures (unknown tool, missing args,
    API error) come back as ``{"status": "error", ...}`` so the tool loop
    can feed them to the LLM instead of crashing the turn.
    """
    if tool_name not in _CLIENT_DISPATCH:
        return {"status": "error", "error": f"unknown tool: {tool_name!r}"}

    missing = [a for a in _REQUIRED_ARGS.get(tool_name, ()) if not tool_args.get(a)]
    if missing:
        return {
            "status": "error",
            "error": f"missing required argument(s): {', '.join(missing)}",
        }

    try:
        data = _CLIENT_DISPATCH[tool_name](tool_args)
    except WorldCupAPIError as exc:
        return {"status": "error", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    localized = localize_payload(data)
    if isinstance(localized, dict):
        return {"status": "ok", **localized}
    return {"status": "ok", "result": localized}

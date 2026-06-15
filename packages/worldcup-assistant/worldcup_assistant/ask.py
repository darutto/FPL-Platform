"""
worldcup_assistant.ask
=======================
Orchestrator-primary ask entrypoint for the World Cup domain.

Thin domain wrapper around ``llm_orchestrator_core.run_tool_loop``: injects
the WC system prompt, the WC tool registry, and the startup grounding
context.  The LLM reasons and selects tools; ``execute_wc_tool`` grounds
every fact deterministically and localizes it to Spanish.

Configuration (env)
-------------------
WC_PROVIDER        anthropic | openai | gemini   (default: anthropic)
WC_ORCH_MODEL      provider model id             (default: claude-opus-4-8)
WC_MAX_ITERATIONS  tool-loop bound               (default: 4)
WC_MAX_TOKENS      generation cap per call       (default: 1024)
WC_TIMEOUT_S       per-attempt provider timeout  (default: 30)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from llm_orchestrator_core import (
    LOOP_OK,
    PROVIDER_GEMINI,
    ToolLoopResult,
    run_tool_loop,
)

from .context_builder import WC_SYSTEM_PROMPT
from .tools import WC_TRUNCATABLE_FIELDS, build_wc_tool_specs, execute_wc_tool

#: Maps a tool name to the tool-output key holding its card-ready payload.
#: The last successful call of each tool in the trace wins (most recent
#: data for that card type). A ``None`` key means "the whole tool_output
#: (minus 'status')" rather than one sub-key. Values are already
#: locale_es-localized by ``execute_wc_tool`` before they land in
#: ``tool_output``.
_STRUCTURED_TOOL_FIELDS: dict[str, tuple[str, str | None]] = {
    "get_standings": ("standings", "groups"),
    "get_top_scorers": ("top_scorers", "scorers"),
    "get_top_assists": ("top_assists", "assisters"),
    "get_fantasy_top_players": ("fantasy_top_players", "players"),
    "get_fixtures": ("fixtures", "matches"),
    "get_live_scores": ("fixtures", "matches"),
    "get_squad": ("squad", None),
    "get_head_to_head": ("head_to_head", None),
    "get_wc2022_results": ("wc2022_results", "matches"),
    # Whole tool output (minus status) → WCAskResult.web_search. Carries
    # {results, timestamp}; `summary` (the Spanish synthesis) and `topic` are
    # injected post-loop from the orchestrator's final_text / query below —
    # Tavily never produces them.
    "web_search": ("web_search", None),
}

#: Tool name for the last-resort web search. Its grounded status is deliberately
#: NOT counted toward the "Datos verificados" badge (see ``grounded`` below) and
#: its payload gets the model synthesis injected as ``summary``.
_WEB_SEARCH_TOOL: str = "web_search"

#: Tool whose successful calls are collected (deduped by player name, in
#: trace order) into ``WCAskResult.players_info`` — one entry for '/jugador',
#: two for '/comparar' (one get_player_info call per player).
_PLAYER_INFO_TOOL: str = "get_player_info"

#: Tool whose successful calls are collected (deduped by player name, in
#: trace order) into ``WCAskResult.wc2022_stats`` — supplementary WC2022
#: tournament aggregates (cards, minutes, saves, key passes, rating) for
#: players who also featured in the 2022 World Cup. Only players with
#: ``status: "ok"`` (i.e. found in the cached WC2022 dataset) appear here.
_PLAYER_WC2022_TOOL: str = "get_player_wc2022_stats"

#: Hybrid model architecture: the WC orchestrator/router is the gatekeeper for
#: tool selection, negative-constraint adherence, and (when web search is
#: enabled) search-query construction. It is standardized on a high-tier Pro
#: model — a smaller model over-calls web_search and passes raw conversational
#: sentences as queries. Provider token in our stack is "gemini" (NOT "google";
#: provider_client matches on PROVIDER_GEMINI == "gemini" and falls back to
#: anthropic for anything unrecognized). Both are overridable via env.
DEFAULT_WC_PROVIDER: str = PROVIDER_GEMINI
DEFAULT_WC_MODEL: str = "gemini-2.5-pro"

#: Spanish fallback shown when no grounded answer could be produced.
_NO_ANSWER_ES: str = (
    "Lo siento, no pude obtener una respuesta con datos del Mundial en este "
    "momento. Inténtalo de nuevo en unos segundos."
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, ""))
    except (ValueError, TypeError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, ""))
    except (ValueError, TypeError):
        return default


@dataclass(frozen=True)
class WCAskResult:
    """Domain-shaped result consumed by ``wc_server`` to build AskResponse."""

    question:    str
    final_text:  str
    outcome:     str
    llm_used:    bool
    model:       str
    iterations:  int
    tool_trace:  list[dict[str, Any]] = field(default_factory=list)
    error:       str | None = None
    total_tokens: int = 0
    standings:   dict[str, Any] | None = None
    top_scorers: list[dict[str, Any]] | None = None
    top_assists: list[dict[str, Any]] | None = None
    fantasy_top_players: list[dict[str, Any]] | None = None
    fixtures:    list[dict[str, Any]] | None = None
    squad:       dict[str, Any] | None = None
    head_to_head: dict[str, Any] | None = None
    players_info: list[dict[str, Any]] | None = None
    wc2022_stats: list[dict[str, Any]] | None = None
    wc2022_results: list[dict[str, Any]] | None = None
    web_search:  dict[str, Any] | None = None
    grounded:    bool = False


def ask_wc(
    question: str,
    *,
    dynamic_context: str = "",
    history: list[dict[str, Any]] | None = None,
    web_search_enabled: bool = False,
    client: Any = None,
    api_key: str | None = None,
    _request_fn: Any = None,
) -> WCAskResult:
    """Answer one World Cup question through the grounded tool loop.

    Always returns — never raises.  ``dynamic_context`` is the startup
    tournament snapshot (non-cached system block); ``history`` is the
    ``wc:``-namespaced session transcript owned by the server layer.

    ``web_search_enabled`` adds the last-resort, premium-gated ``web_search``
    tool to this turn's tool list. The server layer sets it only when the user
    toggled web search on AND their tier is eligible — so when False the tool is
    absent and the model cannot incur paid-search spend.
    """
    provider = os.environ.get("WC_PROVIDER", DEFAULT_WC_PROVIDER).lower().strip()
    model = os.environ.get("WC_ORCH_MODEL", DEFAULT_WC_MODEL)

    result: ToolLoopResult = run_tool_loop(
        question,
        system_prompt=WC_SYSTEM_PROMPT,
        tool_specs=build_wc_tool_specs(web_search_enabled=web_search_enabled),
        execute_tool=execute_wc_tool,
        provider=provider,
        model=model,
        history=history,
        max_iterations=_env_int("WC_MAX_ITERATIONS", 4),
        max_tokens=_env_int("WC_MAX_TOKENS", 1024),
        timeout_s=_env_float("WC_TIMEOUT_S", 30.0),
        client=client,
        api_key=api_key,
        dynamic_context=dynamic_context,
        truncatable_fields=WC_TRUNCATABLE_FIELDS,
        no_answer_fallback=_NO_ANSWER_ES,
        _request_fn=_request_fn,
    )

    structured: dict[str, Any] = {}
    players_info: list[dict[str, Any]] = []
    seen_players: set[str] = set()
    wc2022_stats: list[dict[str, Any]] = []
    seen_wc2022_players: set[str] = set()
    web_search_query: str | None = None
    # True iff at least one *deterministic* tool call this turn returned grounded
    # data — i.e. the answer is backed by a real tournament API/dataset result,
    # not just LLM prose. web_search is deliberately EXCLUDED: its results are
    # unverified external synthesis and must surface as "Búsqueda web + IA", never
    # "Datos verificados" (see MessageList.tsx OriginBadges).
    grounded = any(
        not rec.error
        and rec.tool_output.get("status") == "ok"
        and rec.tool_name != _WEB_SEARCH_TOOL
        for rec in result.tool_trace
    )
    for rec in result.tool_trace:
        if rec.error or rec.tool_output.get("status") != "ok":
            continue
        if rec.tool_name == _PLAYER_INFO_TOOL:
            payload = {k: v for k, v in rec.tool_output.items() if k != "status"}
            player_name = payload.get("player")
            if player_name and player_name not in seen_players:
                seen_players.add(player_name)
                players_info.append(payload)
            continue
        if rec.tool_name == _PLAYER_WC2022_TOOL:
            payload = {k: v for k, v in rec.tool_output.items() if k != "status"}
            player_name = payload.get("name")
            if player_name and player_name not in seen_wc2022_players:
                seen_wc2022_players.add(player_name)
                wc2022_stats.append(payload)
            continue
        field_map = _STRUCTURED_TOOL_FIELDS.get(rec.tool_name)
        if field_map is None:
            continue
        field_name, payload_key = field_map
        if payload_key is None:
            structured[field_name] = {k: v for k, v in rec.tool_output.items() if k != "status"}
        else:
            structured[field_name] = rec.tool_output.get(payload_key)
        if rec.tool_name == _WEB_SEARCH_TOOL:
            # Topic = the model's optimized query (keyword phrase) for the card
            # header. Captured here so the most recent web_search call wins.
            web_search_query = rec.tool_args.get("query")

    # web_search post-processing: the card's prose is the orchestrator's Spanish
    # synthesis (final_text), NOT Tavily's raw (often English) `answer`. Inject
    # `summary` + `topic`, and drop `answer` so the unverified English quick-take
    # never reaches the UI.
    web_search_payload = structured.get("web_search")
    if isinstance(web_search_payload, dict):
        web_search_payload.pop("answer", None)
        web_search_payload["summary"] = result.final_text
        if web_search_query:
            web_search_payload["topic"] = web_search_query

    return WCAskResult(
        question=question,
        final_text=result.final_text,
        outcome=result.outcome,
        llm_used=result.llm_used,
        model=result.model,
        iterations=result.iterations,
        tool_trace=[
            {
                "tool": rec.tool_name,
                "args": rec.tool_args,
                "output_status": rec.tool_output.get("status"),
                "error": rec.error,
            }
            for rec in result.tool_trace
        ],
        error=result.error,
        total_tokens=result.total_tokens,
        standings=structured.get("standings"),
        top_scorers=structured.get("top_scorers"),
        top_assists=structured.get("top_assists"),
        fantasy_top_players=structured.get("fantasy_top_players"),
        fixtures=structured.get("fixtures"),
        squad=structured.get("squad"),
        head_to_head=structured.get("head_to_head"),
        players_info=players_info or None,
        wc2022_stats=wc2022_stats or None,
        wc2022_results=structured.get("wc2022_results"),
        web_search=structured.get("web_search"),
        grounded=grounded,
    )


def is_ok(result: WCAskResult) -> bool:
    return result.outcome == LOOP_OK

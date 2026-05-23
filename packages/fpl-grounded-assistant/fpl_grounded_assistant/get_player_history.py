"""
fpl_grounded_assistant.get_player_history
==========================================
P2.3: Atomic get_player_history tool — per-GW performance history for a single player.

Where ``get_player_snapshot`` returns the player's *current* grounding payload,
``get_player_history`` returns the temporal window: how the player has performed
across the last N completed gameweeks.

This answers the "que jugador ha hecho más puntos en las últimas 6 jornadas" class
of queries that require more than a snapshot.

Resolution algorithm
--------------------
Identical to get_player_snapshot (and get_player_snapshot re-uses find_players):

1. Normalize the query (NFKD + lowercase + accent strip).
2. Rank 0 — exact match: Exactly 1 → ok.  More than 1 → ambiguous.
3. Rank 1 — prefix match: Exactly 1 → ok.  More than 1 → ambiguous.
4. Rank 2 — substring match: Any matches → ambiguous.
5. No matches → not_found.

Single source of truth: matching helpers imported from find_players.

History fetch
-------------
Uses ``_fetch_element_summary`` from ``player_form`` — that module already owns
the circuit-guard + bootstrap-injection pattern.  Re-exporting it keeps a single
HTTP fetch path for element-summary throughout the package.

Test-injection: embed ``_element_summaries`` in the bootstrap dict exactly as
player_form does::

    bootstrap["_element_summaries"] = {
        str(player_id): {"history": [...]}
    }

Caching
-------
Per-player history is stable within a day but can change after a GW deadline.
An in-memory LRU cache (capacity: ``_CACHE_MAX_SIZE`` players, TTL: 1 hour)
avoids redundant element-summary calls inside a single process.  The cache is
bypassed when the bootstrap-injection path is active.

Registration
------------
Registers ``get_player_history`` in ``TOOL_REGISTRY`` as a side-effect of import.
``__init__.py`` imports this module so ``run_tool("get_player_history", ...)`` works.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

# Re-use name-resolution helpers — single source of truth.
from fpl_grounded_assistant.find_players import (
    _normalize,
    _build_match_dict,
    _safe_int,
    _safe_float,
)

# Re-use the element-summary fetch helper (circuit guard, bootstrap injection).
from fpl_grounded_assistant.player_form import _fetch_element_summary


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_AMBIGUOUS_CANDIDATES: int = 5
_MAX_LAST_N_GWS: int = 38
_DEFAULT_LAST_N_GWS: int = 5

#: Max number of players whose history we cache in-process.
_CACHE_MAX_SIZE: int = 50

#: Cache TTL in seconds (1 hour).
_CACHE_TTL_S: float = 3600.0

# ---------------------------------------------------------------------------
# In-memory LRU cache (player_id → (timestamp, element_summary_dict))
# ---------------------------------------------------------------------------

_history_cache: OrderedDict[int, tuple[float, dict[str, Any]]] = OrderedDict()


def _cache_get(player_id: int) -> dict[str, Any] | None:
    """Return cached element summary for player_id, or None if absent/stale."""
    entry = _history_cache.get(player_id)
    if entry is None:
        return None
    ts, data = entry
    if time.monotonic() - ts > _CACHE_TTL_S:
        _history_cache.pop(player_id, None)
        return None
    # Move to end (most-recently-used).
    _history_cache.move_to_end(player_id)
    return data


def _cache_set(player_id: int, data: dict[str, Any]) -> None:
    """Store element summary in the LRU cache, evicting oldest if at capacity."""
    if player_id in _history_cache:
        _history_cache.move_to_end(player_id)
    _history_cache[player_id] = (time.monotonic(), data)
    while len(_history_cache) > _CACHE_MAX_SIZE:
        _history_cache.popitem(last=False)


def _cache_clear() -> None:
    """Clear the entire history cache (test helper)."""
    _history_cache.clear()


# ---------------------------------------------------------------------------
# Resolution helpers (same algorithm as get_player_snapshot)
# ---------------------------------------------------------------------------

def _resolve_player(
    player_name: str,
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Resolve player_name to one of: ok, ambiguous, not_found.

    Returns a dict with keys appropriate for each status, mirroring
    get_player_snapshot's contract for status/player/ambiguous/not_found.

    On "ok", the returned dict has:
        status="ok", player_id, web_name, team_short, position
    On "ambiguous":
        status="ambiguous", query, candidates, message
    On "not_found":
        status="not_found", query, message
    """
    normalized_query = _normalize(player_name.strip())

    elements: list[dict[str, Any]] = bootstrap.get("elements", []) or []
    teams: list[dict[str, Any]] = bootstrap.get("teams", []) or []
    element_types: list[dict[str, Any]] = bootstrap.get("element_types", []) or []

    rank_bucket: dict[int, int] = {}

    for el in elements:
        el_id = el.get("id")
        if el_id is None:
            continue

        first   = _normalize(el.get("first_name", "") or "")
        second  = _normalize(el.get("second_name", "") or "")
        web     = _normalize(el.get("web_name", "") or "")
        composite = f"{first} {second} {web}"

        if normalized_query in (first, second, web):
            rank_bucket[el_id] = 0
            continue
        if (
            first.startswith(normalized_query)
            or second.startswith(normalized_query)
            or web.startswith(normalized_query)
        ):
            rank_bucket[el_id] = 1
            continue
        if normalized_query in composite:
            rank_bucket[el_id] = 2

    def _at_rank(target_rank: int) -> list[dict[str, Any]]:
        bucket = [
            el for el in elements
            if rank_bucket.get(el.get("id")) == target_rank
        ]
        bucket.sort(key=lambda el: -_safe_int(el.get("total_points"), 0))
        return bucket

    exact_matches  = _at_rank(0)
    prefix_matches = _at_rank(1)
    substr_matches = _at_rank(2)

    def _ok_from_element(el: dict[str, Any]) -> dict[str, Any]:
        payload = _build_match_dict(el, teams, element_types, match_rank=0)
        return {
            "status":     "ok",
            "player_id":  payload["id"],
            "web_name":   payload["web_name"],
            "team_short": payload["team_short"],
            "position":   payload["position"],
        }

    def _ambiguous_from(els: list[dict[str, Any]], rank: int) -> dict[str, Any]:
        candidates = [
            _build_match_dict(el, teams, element_types, match_rank=rank)
            for el in els[:_MAX_AMBIGUOUS_CANDIDATES]
        ]
        return {
            "status":     "ambiguous",
            "query":      normalized_query,
            "candidates": candidates,
            "message":    f"Multiple players match '{normalized_query}'. Please specify.",
        }

    if len(exact_matches) == 1:
        return _ok_from_element(exact_matches[0])
    if len(exact_matches) > 1:
        return _ambiguous_from(exact_matches, 0)

    if len(prefix_matches) == 1:
        return _ok_from_element(prefix_matches[0])
    if len(prefix_matches) > 1:
        return _ambiguous_from(prefix_matches, 1)

    if len(substr_matches) > 0:
        return _ambiguous_from(substr_matches, 2)

    return {
        "status":  "not_found",
        "query":   normalized_query,
        "message": f"No player matching '{normalized_query}'.",
    }


# ---------------------------------------------------------------------------
# History field extraction
# ---------------------------------------------------------------------------

def _extract_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Extract the full history entry dict from a raw FPL history record."""
    return {
        "round":                        _safe_int(entry.get("round"), 0),
        "opponent_team_short":          str(entry.get("opponent_team_short") or entry.get("opponent_team") or ""),
        "was_home":                     bool(entry.get("was_home", False)),
        "minutes":                      _safe_int(entry.get("minutes"), 0),
        "total_points":                 _safe_int(entry.get("total_points"), 0),
        "goals_scored":                 _safe_int(entry.get("goals_scored"), 0),
        "assists":                      _safe_int(entry.get("assists"), 0),
        "clean_sheets":                 _safe_int(entry.get("clean_sheets"), 0),
        "yellow_cards":                 _safe_int(entry.get("yellow_cards"), 0),
        "red_cards":                    _safe_int(entry.get("red_cards"), 0),
        "saves":                        _safe_int(entry.get("saves"), 0),
        "bonus":                        _safe_int(entry.get("bonus"), 0),
        "bps":                          _safe_int(entry.get("bps"), 0),
        "expected_goals":               _safe_float(entry.get("expected_goals"), 0.0),
        "expected_assists":             _safe_float(entry.get("expected_assists"), 0.0),
        "expected_goal_involvements":   _safe_float(entry.get("expected_goal_involvements"), 0.0),
        "expected_goals_conceded":      _safe_float(entry.get("expected_goals_conceded"), 0.0),
        "value":                        _safe_int(entry.get("value"), 0),
        "transfers_in":                 _safe_int(entry.get("transfers_in"), 0),
        "transfers_out":                _safe_int(entry.get("transfers_out"), 0),
        "selected":                     _safe_int(entry.get("selected"), 0),
        "kickoff_time":                 entry.get("kickoff_time"),
    }


# The 22 required fields for each history entry
HISTORY_ENTRY_REQUIRED_FIELDS: tuple[str, ...] = (
    "round",
    "opponent_team_short",
    "was_home",
    "minutes",
    "total_points",
    "goals_scored",
    "assists",
    "clean_sheets",
    "yellow_cards",
    "red_cards",
    "saves",
    "bonus",
    "bps",
    "expected_goals",
    "expected_assists",
    "expected_goal_involvements",
    "expected_goals_conceded",
    "value",
    "transfers_in",
    "transfers_out",
    "selected",
    "kickoff_time",
)


def _build_summary(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary aggregations across the returned history window."""
    gws_played     = sum(1 for h in history if h["minutes"] > 0)
    total_points   = sum(h["total_points"] for h in history)
    total_minutes  = sum(h["minutes"] for h in history)
    total_goals    = sum(h["goals_scored"] for h in history)
    total_assists  = sum(h["assists"] for h in history)
    total_xgi      = sum(h["expected_goal_involvements"] for h in history)
    avg_form: float = total_points / gws_played if gws_played > 0 else 0.0

    return {
        "gws_played":    gws_played,
        "total_points":  total_points,
        "total_minutes": total_minutes,
        "total_goals":   total_goals,
        "total_assists": total_assists,
        "avg_form":      round(avg_form, 2),
        "total_xgi":     round(total_xgi, 2),
    }


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def get_player_history(
    player_name: str,
    last_n_gws: int = _DEFAULT_LAST_N_GWS,
    bootstrap: "dict[str, Any] | None" = None,
) -> dict[str, Any]:
    """Per-gameweek performance history for a single player.

    Resolves player_name using the same exact/prefix/substring algorithm as
    get_player_snapshot (ambiguity is first-class). Once resolved, fetches
    the player's element-summary from the FPL API and returns the last N
    gameweeks of stats.

    Args:
        player_name: case-insensitive, accent-insensitive.
        last_n_gws: how many recent gameweeks to return (1-38, default 5,
                    capped at 38).
        bootstrap: live FPL bootstrap; fetched if None.

    Returns one of:
        # Single unambiguous match:
        {
            "status": "ok",
            "player": {
                "id": <int>,
                "web_name": <str>,
                "team_short": <str>,
                "position": <str>
            },
            "last_n_gws": <int>,                # actual N returned (<= requested)
            "history": [
                {
                    "round": <int>,             # gameweek number
                    "opponent_team_short": <str>,
                    "was_home": <bool>,
                    "minutes": <int>,
                    "total_points": <int>,
                    "goals_scored": <int>,
                    "assists": <int>,
                    "clean_sheets": <int>,
                    "yellow_cards": <int>,
                    "red_cards": <int>,
                    "saves": <int>,
                    "bonus": <int>,
                    "bps": <int>,
                    "expected_goals": <float>,
                    "expected_assists": <float>,
                    "expected_goal_involvements": <float>,
                    "expected_goals_conceded": <float>,
                    "value": <int>,             # price in tenths of pound at that GW
                    "transfers_in": <int>,
                    "transfers_out": <int>,
                    "selected": <int>,
                    "kickoff_time": <str | None>,  # ISO timestamp if available
                },
                ...  # ordered most-recent-first
            ],
            "summary": {
                "gws_played": <int>,
                "total_points": <int>,
                "total_minutes": <int>,
                "total_goals": <int>,
                "total_assists": <int>,
                "avg_form": <float>,         # points / gws_played
                "total_xgi": <float>,
            }
        }
        # OR ambiguous:
        {
            "status": "ambiguous",
            "query": <normalized name>,
            "candidates": [<up to 5 candidate dicts, full grounding payload>],
            "message": "Multiple players match '<query>'. Please specify."
        }
        # OR not found:
        {
            "status": "not_found",
            "query": <normalized name>,
            "message": "No player matching '<query>'."
        }
        # OR error fetching history:
        {
            "status": "error",
            "code": "fetch_failed",
            "message": "Could not fetch history for player '<web_name>': <reason>"
        }
    """
    # ------------------------------------------------------------------
    # 0. Validate inputs
    # ------------------------------------------------------------------
    if not isinstance(player_name, str) or not player_name.strip():
        return {
            "status":  "error",
            "code":    "invalid_argument",
            "message": "player_name must be a non-empty string.",
        }

    # Silent cap on last_n_gws
    try:
        last_n_gws = max(1, min(int(last_n_gws), _MAX_LAST_N_GWS))
    except (ValueError, TypeError):
        last_n_gws = _DEFAULT_LAST_N_GWS

    # ------------------------------------------------------------------
    # 1. Guard: bootstrap required
    # ------------------------------------------------------------------
    if bootstrap is None:
        normalized_query = _normalize(player_name.strip())
        return {
            "status":  "not_found",
            "query":   normalized_query,
            "message": f"No player matching '{normalized_query}'.",
        }

    # ------------------------------------------------------------------
    # 2. Resolve player name (same algorithm as get_player_snapshot)
    # ------------------------------------------------------------------
    resolution = _resolve_player(player_name, bootstrap)

    if resolution["status"] != "ok":
        # Pass through ambiguous / not_found unchanged
        return resolution

    player_id  = resolution["player_id"]
    web_name   = resolution["web_name"]
    team_short = resolution["team_short"]
    position   = resolution["position"]

    # ------------------------------------------------------------------
    # 3. Fetch element summary (with LRU cache; bypass on injection path)
    # ------------------------------------------------------------------
    # Check bootstrap injection first (test path — bypass cache).
    injected = bootstrap.get("_element_summaries", {})
    if str(player_id) in injected:
        elem_summary = injected[str(player_id)]
    else:
        # Try in-memory cache.
        elem_summary = _cache_get(player_id)
        if elem_summary is None:
            elem_summary = _fetch_element_summary(player_id, bootstrap)
            if elem_summary is not None:
                _cache_set(player_id, elem_summary)

    if elem_summary is None:
        return {
            "status":  "error",
            "code":    "fetch_failed",
            "message": (
                f"Could not fetch history for player '{web_name}': "
                "element-summary API unavailable or timed out."
            ),
        }

    # ------------------------------------------------------------------
    # 4. Extract and slice history
    # ------------------------------------------------------------------
    raw_history: list[dict[str, Any]] = elem_summary.get("history", []) or []

    # Take the last last_n_gws entries (most recent), then reverse to most-recent-first.
    tail = raw_history[-last_n_gws:] if raw_history else []
    tail = list(reversed(tail))

    history = [_extract_history_entry(entry) for entry in tail]

    # ------------------------------------------------------------------
    # 5. Build response
    # ------------------------------------------------------------------
    return {
        "status": "ok",
        "player": {
            "id":         player_id,
            "web_name":   web_name,
            "team_short": team_short,
            "position":   position,
        },
        "last_n_gws": len(history),
        "history":    history,
        "summary":    _build_summary(history),
    }


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

GET_PLAYER_HISTORY_SPEC = ToolSpec(
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
    output_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["ok", "ambiguous", "not_found", "error"],
            },
            "player": {
                "type":        "object",
                "description": "Player identity (id, web_name, team_short, position) — only when status=ok",
            },
            "last_n_gws": {
                "type":        "integer",
                "description": "Actual number of GW entries returned (only when status=ok)",
            },
            "history": {
                "type":        "array",
                "description": "Per-GW history entries, most-recent first (only when status=ok)",
            },
            "summary": {
                "type":        "object",
                "description": "Aggregated stats over the returned window (only when status=ok)",
            },
            "query": {
                "type":        "string",
                "description": "Normalized query (present on ambiguous/not_found)",
            },
            "candidates": {
                "type":        "array",
                "description": "Up to 5 candidate grounding payloads (only when status=ambiguous)",
            },
            "message": {
                "type":        "string",
                "description": "Human-readable explanation (ambiguous/not_found/error)",
            },
        },
    },
)


def _get_player_history_handler(
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``get_player_history()``."""
    try:
        return get_player_history(
            player_name=args["player_name"],
            last_n_gws=args.get("last_n_gws", _DEFAULT_LAST_N_GWS),
            bootstrap=bootstrap,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status":  "error",
            "code":    "tool_exception",
            "message": f"get_player_history raised an unexpected error: {exc}",
        }


# Register with the shared tool registry so run_tool("get_player_history", ...) works.
TOOL_REGISTRY.register(GET_PLAYER_HISTORY_SPEC, _get_player_history_handler)

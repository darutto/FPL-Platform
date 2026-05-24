"""
fpl_grounded_assistant.get_player_snapshot
===========================================
P2.2: Atomic get_player_snapshot tool — single-player full grounding payload.

Where ``find_players`` returns a candidate LIST, ``get_player_snapshot``
returns ONE player's full grounding payload, OR an ``ambiguous`` status with
up to 5 candidates when the name resolves to more than one player.

This is the MPC_learning pattern: ambiguity is a first-class status, not
silently resolved.

Resolution algorithm
--------------------
1. Normalize the query (NFKD + lowercase + accent strip) — same helper as
   ``find_players``.
2. Rank 0 — exact match (query == web_name, first_name, OR second_name):
   - Exactly 1 → status="ok" with single player.
   - More than 1 → status="ambiguous" with all exact matches (e.g. two
     "Diallo" players in the squad).
3. Rank 1 — prefix match (any name field starts with the query):
   - Exactly 1 → status="ok" (auto-resolve single prefix).
   - More than 1 → status="ambiguous" with up to 5 prefix matches.
4. Rank 2 — substring match (query anywhere in composite name):
   - Any matches → status="ambiguous" (too loose to auto-resolve).
5. No matches at any rank → status="not_found".

Grounding payload
-----------------
Single-answer ("ok") response omits ``match_rank`` (it is meaningless for a
single result).  Ambiguous candidates INCLUDE ``match_rank`` so the LLM can
tiebreak or explain the options to the user.

Reuse
-----
All matching logic and the 21-field grounding-payload builder are imported
directly from ``find_players`` — SINGLE SOURCE of truth.  The helpers exposed
from ``find_players`` are:
    _normalize          — Unicode normalization
    _build_match_dict   — 21-field grounding payload builder
    _safe_int           — safe integer coercion (used for total_points sort)

Registration
------------
This module registers ``get_player_snapshot`` in ``TOOL_REGISTRY`` as a
side-effect of import.  The package's ``__init__.py`` imports this module so
``run_tool("get_player_snapshot", ...)`` works automatically after any
full-package import.
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

# Re-use helpers from find_players — single source of truth.
from fpl_grounded_assistant.find_players import (
    _normalize,
    _build_match_dict,
    _safe_int,
)

_MAX_AMBIGUOUS_CANDIDATES: int = 5


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def get_player_snapshot(
    player_name: str,
    bootstrap: "dict[str, Any] | None" = None,
) -> dict[str, Any]:
    """Single player full grounding payload by name.

    Resolution: exact match (case + accent insensitive) wins immediately.
    If multiple exact matches OR multiple prefix matches without a tiebreaker,
    return status='ambiguous' with up to 5 candidates (LLM decides what to do).

    Args:
        player_name: player name (case-insensitive, unicode-normalized).
        bootstrap: live FPL bootstrap; if None, returns not_found.

    Returns one of:
        # Single unambiguous match:
        {
            "status": "ok",
            "player": {
                # 20-field grounding payload (21 minus match_rank)
                # id, web_name, team_short, position, minutes_played_season,
                # status, news, news_added, chance_of_playing_this_round,
                # form, total_points, points_per_game, expected_goals,
                # expected_assists, expected_goal_involvements, ict_index,
                # now_cost, selected_by_percent, transfers_in_event,
                # transfers_out_event
            }
        }
        # OR ambiguous resolution:
        {
            "status": "ambiguous",
            "query": <normalized name>,
            "candidates": [<up to 5 grounding-payload dicts with match_rank>],
            "message": "Multiple players match '<query>'. Please specify."
        }
        # OR not found:
        {
            "status": "not_found",
            "query": <normalized name>,
            "message": "No player matching '<query>'."
        }
    """
    # ------------------------------------------------------------------
    # 0. Validate and normalize inputs
    # ------------------------------------------------------------------
    if not isinstance(player_name, str) or not player_name.strip():
        return {
            "status":  "error",
            "code":    "invalid_argument",
            "message": "player_name must be a non-empty string.",
        }

    normalized_query = _normalize(player_name.strip())

    # ------------------------------------------------------------------
    # 1. Guard: bootstrap required
    # ------------------------------------------------------------------
    if bootstrap is None:
        return {
            "status":  "not_found",
            "query":   normalized_query,
            "message": f"No player matching '{normalized_query}'.",
        }

    elements: list[dict[str, Any]] = bootstrap.get("elements", []) or []
    teams: list[dict[str, Any]] = bootstrap.get("teams", []) or []
    element_types: list[dict[str, Any]] = bootstrap.get("element_types", []) or []

    # ------------------------------------------------------------------
    # 2. Classify each element into rank buckets (same algorithm as find_players)
    # ------------------------------------------------------------------
    rank_bucket: dict[int, int] = {}

    for el in elements:
        el_id = el.get("id")
        if el_id is None:
            continue

        first   = _normalize(el.get("first_name", "") or "")
        second  = _normalize(el.get("second_name", "") or "")
        web     = _normalize(el.get("web_name", "") or "")
        composite = f"{first} {second} {web}"

        # Rank 0: exact match on any canonical name field
        if normalized_query in (first, second, web):
            rank_bucket[el_id] = 0
            continue

        # Rank 1: prefix match on any name field
        if (
            first.startswith(normalized_query)
            or second.startswith(normalized_query)
            or web.startswith(normalized_query)
        ):
            rank_bucket[el_id] = 1
            continue

        # Rank 2: substring match anywhere in composite
        if normalized_query in composite:
            rank_bucket[el_id] = 2

    # ------------------------------------------------------------------
    # 3. Separate by rank
    # ------------------------------------------------------------------
    def _elements_at_rank(target_rank: int) -> list[dict[str, Any]]:
        """Return elements at a specific rank, sorted by total_points desc."""
        bucket = [
            el for el in elements
            if rank_bucket.get(el.get("id")) == target_rank
        ]
        bucket.sort(key=lambda el: -_safe_int(el.get("total_points"), 0))
        return bucket

    exact_matches   = _elements_at_rank(0)
    prefix_matches  = _elements_at_rank(1)
    substr_matches  = _elements_at_rank(2)

    # ------------------------------------------------------------------
    # 4. Resolution rules
    # ------------------------------------------------------------------

    # Rule 2: exact match(es)
    if len(exact_matches) == 1:
        player_dict = _build_match_dict(
            exact_matches[0], teams, element_types, match_rank=0
        )
        # Single answer: drop match_rank (meaningless for a unique result)
        player_dict.pop("match_rank", None)
        return {
            "status": "ok",
            "player": player_dict,
        }

    if len(exact_matches) > 1:
        candidates = [
            _build_match_dict(el, teams, element_types, match_rank=0)
            for el in exact_matches[:_MAX_AMBIGUOUS_CANDIDATES]
        ]
        return {
            "status":     "ambiguous",
            "query":      normalized_query,
            "candidates": candidates,
            "message":    f"Multiple players match '{normalized_query}'. Please specify.",
        }

    # Rule 3: prefix match(es)
    if len(prefix_matches) == 1:
        player_dict = _build_match_dict(
            prefix_matches[0], teams, element_types, match_rank=1
        )
        player_dict.pop("match_rank", None)
        return {
            "status": "ok",
            "player": player_dict,
        }

    if len(prefix_matches) > 1:
        candidates = [
            _build_match_dict(el, teams, element_types, match_rank=1)
            for el in prefix_matches[:_MAX_AMBIGUOUS_CANDIDATES]
        ]
        return {
            "status":     "ambiguous",
            "query":      normalized_query,
            "candidates": candidates,
            "message":    f"Multiple players match '{normalized_query}'. Please specify.",
        }

    # Rule 4: substring match(es) — always ambiguous (too loose to auto-resolve)
    if len(substr_matches) > 0:
        candidates = [
            _build_match_dict(el, teams, element_types, match_rank=2)
            for el in substr_matches[:_MAX_AMBIGUOUS_CANDIDATES]
        ]
        return {
            "status":     "ambiguous",
            "query":      normalized_query,
            "candidates": candidates,
            "message":    f"Multiple players match '{normalized_query}'. Please specify.",
        }

    # Rule 5: nothing found
    return {
        "status":  "not_found",
        "query":   normalized_query,
        "message": f"No player matching '{normalized_query}'.",
    }


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

GET_PLAYER_SNAPSHOT_SPEC = ToolSpec(
    name="get_player_snapshot",
    description=(
        "Single player full grounding payload by name. Returns status=ok+player "
        "(1 match), ambiguous+candidates (multi-match), or not_found. "
        "For candidate lists use find_players instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "player_name": {
                "type":        "string",
                "description": "Player name (case-insensitive, accent-insensitive)",
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
                "description": "Full 20-field grounding payload (only when status=ok)",
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
                "description": "Human-readable explanation (ambiguous/not_found)",
            },
        },
    },
)


def _get_player_snapshot_handler(
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``get_player_snapshot()``."""
    try:
        return get_player_snapshot(
            player_name=args["player_name"],
            bootstrap=bootstrap,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status":  "error",
            "code":    "tool_exception",
            "message": f"get_player_snapshot raised an unexpected error: {exc}",
        }


# Register with the shared tool registry so run_tool("get_player_snapshot", ...) works.
TOOL_REGISTRY.register(GET_PLAYER_SNAPSHOT_SPEC, _get_player_snapshot_handler)

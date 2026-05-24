"""
fpl_grounded_assistant.find_players
=====================================
P2.1: Atomic find_players tool — fuzzy player name search.

Provides the foundational atomic tool for the P2 expansion.  Downstream P2
tools (get_player_snapshot, get_player_history) depend on this module for
name resolution.

Matching algorithm
------------------
Three-rank matching, by priority:

    Rank 0 — exact match on normalized web_name or first/second_name.
    Rank 1 — prefix match: the normalized query is a prefix of the normalized
              player name (web_name, first_name, or second_name).
    Rank 2 — substring match: the normalized query appears anywhere in the
              normalized concatenation of first+second+web_name.

Within each rank, ties are broken by total_points descending (higher points
first).  Players passing any rank are included in the result; no player
appears more than once (lowest rank wins if the name matches multiple criteria).

Unicode normalization
---------------------
Both the query and stored player names are normalized via NFKD + accent
stripping so that "Núñez" matches "Nunez", "Hernández" matches "Hernandez", etc.

Grounding payload
-----------------
Every match dict includes the full P2 binding grounding payload:
- Identity:       id, web_name, team_short, position
- Availability:   minutes_played_season, status, news, news_added,
                  chance_of_playing_this_round
- Form:           form, total_points, points_per_game, expected_goals,
                  expected_assists, expected_goal_involvements, ict_index
- Selection meta: now_cost, selected_by_percent, transfers_in_event,
                  transfers_out_event
- Match meta:     match_rank

Missing bootstrap fields use safe defaults (None / "" / 0) — the key is
always present in the output dict.

Registration
------------
This module registers ``find_players`` in ``TOOL_REGISTRY`` as a side-effect
of import.  The grounded assistant package's ``__init__.py`` imports all tool
submodules, so ``run_tool("find_players", ...)`` works automatically after
any full-package import.
"""
from __future__ import annotations

import unicodedata
from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_POSITION_MAP: dict[int, str] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

_STATUS_MAP: dict[str, str] = {
    "a": "Available",
    "d": "Doubtful",
    "i": "Injured",
    "s": "Suspended",
    "n": "Not in squad",
    "u": "Unavailable",
}

_MAX_LIMIT: int = 10


# ---------------------------------------------------------------------------
# Unicode normalization helper
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Normalize a string: NFKD decompose, strip combining diacritics, lowercase.

    Examples
    --------
    >>> _normalize("Núñez")
    'nunez'
    >>> _normalize("Hernández")
    'hernandez'
    >>> _normalize("De Bruyne")
    'de bruyne'
    """
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.lower()


# ---------------------------------------------------------------------------
# Grounding payload extraction
# ---------------------------------------------------------------------------

def _team_short(element: dict[str, Any], teams: list[dict[str, Any]]) -> str:
    """Return the short team name for an element, or '' if not found."""
    team_id = element.get("team")
    for team in teams:
        if team.get("id") == team_id:
            return team.get("short_name", "") or ""
    return ""


def _position_label(element: dict[str, Any], element_types: list[dict[str, Any]]) -> str:
    """Return position label (GKP/DEF/MID/FWD) for an element.

    Falls back to _POSITION_MAP integer lookup, then '' on failure.
    """
    et_id = element.get("element_type")
    # Try element_types table first
    for et in element_types:
        if et.get("id") == et_id:
            return et.get("singular_name_short", "") or ""
    # Fallback: hardcoded map
    return _POSITION_MAP.get(et_id, "") if et_id is not None else ""


def _map_status(code: str | None) -> str:
    """Map FPL status code to human-readable string."""
    if code is None:
        return "Unknown"
    return _STATUS_MAP.get(code, "Unknown")


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Parse a value that may be a string or numeric; return default on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Parse a value that may be a string or numeric; return default on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _build_match_dict(
    element: dict[str, Any],
    teams: list[dict[str, Any]],
    element_types: list[dict[str, Any]],
    match_rank: int,
) -> dict[str, Any]:
    """Build the full grounding payload dict for a matched element.

    Every field in the binding grounding contract is present.  Missing
    bootstrap fields use safe defaults (None / "" / 0).
    """
    return {
        # Identity
        "id":         element.get("id", 0),
        "web_name":   element.get("web_name", ""),
        "team_short": _team_short(element, teams),
        "position":   _position_label(element, element_types),
        # Availability
        "minutes_played_season":          _safe_int(element.get("minutes"), 0),
        "status":                         _map_status(element.get("status")),
        "news":                           element.get("news") or "",
        "news_added":                     element.get("news_added"),  # None if absent
        "chance_of_playing_this_round":   element.get("chance_of_playing_this_round"),  # int | None
        # Form & performance
        "form":                      _safe_float(element.get("form"), 0.0),
        "total_points":              _safe_int(element.get("total_points"), 0),
        "points_per_game":           _safe_float(element.get("points_per_game"), 0.0),
        "expected_goals":            _safe_float(element.get("expected_goals"), 0.0),
        "expected_assists":          _safe_float(element.get("expected_assists"), 0.0),
        "expected_goal_involvements": _safe_float(element.get("expected_goal_involvements"), 0.0),
        "ict_index":                 _safe_float(element.get("ict_index"), 0.0),
        # Selection meta
        "now_cost":             _safe_int(element.get("now_cost"), 0),
        "selected_by_percent":  _safe_float(element.get("selected_by_percent"), 0.0),
        "transfers_in_event":   _safe_int(element.get("transfers_in_event"), 0),
        "transfers_out_event":  _safe_int(element.get("transfers_out_event"), 0),
        # Match confidence
        "match_rank": match_rank,
    }


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def find_players(
    name_query: str,
    limit: int = 5,
    bootstrap: "dict[str, Any] | None" = None,
) -> dict[str, Any]:
    """Fuzzy player name search returning candidates with full grounding payload.

    Matching: exact match (rank 0) > prefix match (rank 1) > substring match
    (rank 2). Within rank, order by total_points desc as tiebreaker.

    Args:
        name_query: substring of player name to match (case-insensitive,
            unicode-normalized — Spanish accents do not matter).
        limit: max results to return. Capped at 10 (silent cap if higher).
        bootstrap: live FPL bootstrap data. If None, returns not_found with
            an error note (bootstrap is always injected by the dispatcher in
            normal operation).

    Returns:
        {
            "status": "ok" | "not_found",
            "query": <normalized name_query>,
            "match_count": <int>,
            "matches": [...],
        }

        On tool-level error:
        {
            "status": "error",
            "code": <str>,
            "message": <str>,
        }
    """
    # ------------------------------------------------------------------
    # 0. Validate and normalize inputs
    # ------------------------------------------------------------------
    if not isinstance(name_query, str) or not name_query.strip():
        return {
            "status":  "error",
            "code":    "invalid_argument",
            "message": "name_query must be a non-empty string.",
        }

    # Silent cap on limit
    limit = max(1, min(int(limit) if isinstance(limit, (int, float)) else 5, _MAX_LIMIT))

    normalized_query = _normalize(name_query.strip())

    # ------------------------------------------------------------------
    # 1. Guard: bootstrap required
    # ------------------------------------------------------------------
    if bootstrap is None:
        return {
            "status":      "not_found",
            "query":       normalized_query,
            "match_count": 0,
            "matches":     [],
        }

    elements: list[dict[str, Any]] = bootstrap.get("elements", []) or []
    teams: list[dict[str, Any]] = bootstrap.get("teams", []) or []
    element_types: list[dict[str, Any]] = bootstrap.get("element_types", []) or []

    # ------------------------------------------------------------------
    # 2. Classify each element into a rank bucket
    # ------------------------------------------------------------------
    # rank_bucket: element_id → rank (0/1/2)
    rank_bucket: dict[int, int] = {}

    for el in elements:
        el_id = el.get("id")
        if el_id is None:
            continue

        first   = _normalize(el.get("first_name", "") or "")
        second  = _normalize(el.get("second_name", "") or "")
        web     = _normalize(el.get("web_name", "") or "")
        # Composite string for substring matching
        composite = f"{first} {second} {web}"

        # Rank 0: exact match on any canonical name field
        if normalized_query in (first, second, web):
            rank_bucket[el_id] = 0
            continue

        # Rank 1: prefix match on any name field or composite
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
    # 3. Sort: rank asc, then total_points desc as tiebreaker
    # ------------------------------------------------------------------
    matched_elements: list[dict[str, Any]] = [
        el for el in elements if el.get("id") in rank_bucket
    ]

    matched_elements.sort(
        key=lambda el: (
            rank_bucket[el.get("id")],
            -_safe_int(el.get("total_points"), 0),
        )
    )

    # ------------------------------------------------------------------
    # 4. Apply limit and build grounding payloads
    # ------------------------------------------------------------------
    top: list[dict[str, Any]] = matched_elements[:limit]

    if not top:
        return {
            "status":      "not_found",
            "query":       normalized_query,
            "match_count": 0,
            "matches":     [],
        }

    matches: list[dict[str, Any]] = [
        _build_match_dict(
            el, teams, element_types, rank_bucket[el.get("id")]
        )
        for el in top
    ]

    return {
        "status":      "ok",
        "query":       normalized_query,
        "match_count": len(matches),
        "matches":     matches,
    }


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

FIND_PLAYERS_SPEC = ToolSpec(
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
    output_schema={
        "type": "object",
        "properties": {
            "status":      {"type": "string", "enum": ["ok", "not_found", "error"]},
            "query":       {"type": "string"},
            "match_count": {"type": "integer"},
            "matches":     {"type": "array"},
        },
    },
)


def _find_players_handler(
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``find_players()``."""
    try:
        return find_players(
            name_query=args["name_query"],
            limit=args.get("limit", 5),
            bootstrap=bootstrap,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status":  "error",
            "code":    "tool_exception",
            "message": f"find_players raised an unexpected error: {exc}",
        }


# Register with the shared tool registry so run_tool("find_players", ...) works.
TOOL_REGISTRY.register(FIND_PLAYERS_SPEC, _find_players_handler)

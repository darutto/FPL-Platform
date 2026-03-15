"""
fpl_grounded_assistant.router
==============================
Deterministic question-to-tool router.

Maps user-style natural-language questions to a ``(tool_name, tool_args)``
pair that can be passed directly to ``fpl_tool_runner.run_tool()``.

No LLM is involved — routing is pure rule-based pattern matching so the
full harness is deterministic and testable without any model calls.

Phase 2a changes
----------------
* ``_extract_player_query`` now preserves **original query casing** so that
  alias-sensitive lookups like "KDB" reach the registry with their original
  capitalisation intact.  (The registry's alias index is already
  case-insensitive, but this makes the ``query`` field in tool outputs reflect
  what the user typed, and future-proofs against any case-sensitive path.)
* Added realistic intent phrasings to ``_SUMMARY_PREFIXES`` and
  ``_RESOLVE_PREFIXES``.
* Added ``get_captain_score`` intent (``_CAPTAIN_SCORE_PREFIXES``) — checked
  before summary/resolve to prevent false matches on the word "captain".

Phase 2b changes
----------------
* Added ``rank_captain_candidates`` intent (``_RANK_PREFIXES`` /
  ``_RANKING_KEYWORDS``) — checked before captain-score to prevent false
  matches on "captain rankings" being consumed by captain-score routing.
  The tool takes no arguments from the router; ``candidates_list`` is
  injected by the harness / adapter layer.

Supported intents
-----------------
``get_current_gameweek``
    Triggered by gameweek-related keywords.
    No player extraction needed.

``rank_captain_candidates``   ← Phase 2b
    Triggered by ranking/listing keywords ("top captains", "rank captains",
    "captain rankings", etc.).
    No player extraction — tool receives a candidates list from the caller.

``compare_players``   ← Phase 5a
    Triggered by comparison keywords ("compare X and Y", "X vs Y",
    "who is better X or Y").  Both player queries extracted.

``get_captain_score``   ← Phase 2a
    Triggered by captain-scoring keywords ("should I captain", "captain score
    for", etc.).  Player name extracted from the question.
    ``candidate_inputs`` (form/fixture/xgi/minutes) are merged in by the
    harness, not the router.

``get_player_summary``
    Triggered by "summary", "tell me about", "details", "stats", etc.
    Player name extracted from the question.

``resolve_player``
    Triggered by "who is", "find", "look up", "lookup", "search", etc.
    Player name extracted from the question.

Returns ``None`` for unrecognised questions.

Known gaps (still deferred to LLM integration)
-----------------------------------------------
- No fuzzy/partial keyword matching (e.g. "gw?" alone won't trigger gameweek)
- No multi-turn context — every question is stateless
- No pronoun resolution ("What about him?")
- No combined intents ("Who is Salah and what gameweek is it?")
- Extraction strips leading intent phrases but doesn't handle trailing clauses
  (e.g. "Is Saka fit to play?" is not routed — the question doesn't start with
  a known prefix, so route() returns None and the harness returns unrecognised)
- Captain score routing requires candidate_inputs supplied externally; router
  only extracts the player query
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouteResult:
    """The output of a successful routing decision."""
    tool_name: str
    tool_args: dict[str, Any]


# ---------------------------------------------------------------------------
# Intent prefix tables
# ---------------------------------------------------------------------------
# Ordered longest-first so greedy prefix stripping removes the most specific
# phrase before falling back to shorter ones.

_COMPARE_PREFIXES: tuple[str, ...] = (
    "who would you captain between",
    "who should i captain between",
    "which player is better",
    "which is better",
    "who is better",
    "who's better",
    "compare",
)

_COMPARE_CONNECTORS: tuple[str, ...] = (
    " vs ",
    " versus ",
    " or ",
    " and ",
)

_RANK_PREFIXES: tuple[str, ...] = (
    "give me captain rankings",
    "show me captain rankings",
    "get captain rankings",
    "captain rankings for",
    "rank my captains",
    "rank captains",
    "rank the captains",
    "rank captain candidates",
    "top captains this week",
    "top captains for",
    "top captains",
    "best captains this week",
    "best captains",
    "captain rankings",
)

_RANKING_KEYWORDS: tuple[str, ...] = (
    "rank my captains",
    "rank captains",
    "top captains",
    "captain rankings",
    "best captains",
)

_CAPTAIN_SCORE_PREFIXES: tuple[str, ...] = (
    "what is the captain score for",
    "what's the captain score for",
    "get captain score for",
    "get the captain score for",
    "captain score for",
    "captaincy score for",
    "captaincy for",
    "should i captain",
    "should i pick",
    "captain pick",
)

_SUMMARY_PREFIXES: tuple[str, ...] = (
    "give me a summary for",
    "give me a summary of",
    "give me the summary for",
    "show me a summary for",
    "show me the summary for",
    "get me a summary of",
    "get me a summary for",
    "what are the stats for",
    "what are the stats on",
    "show me stats for",
    "show me the stats for",
    "get me stats for",
    "get stats for",
    "get a summary for",
    "get summary for",
    "summary for",
    "summary of",
    "tell me about",
    "details for",
    "details on",
    "stats for",
    "stats on",
)

_RESOLVE_PREFIXES: tuple[str, ...] = (
    "who is",
    "who's",
    "can you find",
    "find player",
    "find",
    "look up",
    "lookup",
    "search for",
    "search",
    "tell me who",
    "show me",
    "get info on",
    "get info for",
    "info on",
    "info for",
    "resolve",
)

_GAMEWEEK_KEYWORDS: tuple[str, ...] = (
    "current gameweek",
    "current gw",
    "what gameweek",
    "which gameweek",
    "what gw",
    "which gw",
    "gameweek is it",
    "gameweek are we",
    "gameweek number",
    "gameweek?",
    "gameweek",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase and strip edge whitespace / punctuation."""
    return text.strip().lower().rstrip("?!.")


def _extract_player_query(
    original: str,
    q_norm: str,
    prefixes: tuple[str, ...],
) -> str:
    """Strip the first matching intent prefix and return the remainder with
    **original casing** preserved.

    Uses *q_norm* (lowercase) for prefix matching to keep intent detection
    case-insensitive, then slices from *original* at the same character
    position so the returned query preserves the capitalisation the user typed.

    Parameters
    ----------
    original:
        The question with original casing, edge punctuation stripped
        (e.g. ``"Who is KDB"``).
    q_norm:
        The lowercase, stripped version of the same string
        (e.g. ``"who is kdb"``).
    prefixes:
        Tuple of lowercase intent prefix strings to try, longest first.

    Returns
    -------
    str
        The player query in original casing, stripped of leading/trailing
        whitespace and punctuation.

    Examples
    --------
    >>> _extract_player_query("Who is KDB", "who is kdb", ("who is",))
    'KDB'
    >>> _extract_player_query("Tell me about De Bruyne",
    ...                       "tell me about de bruyne", ("tell me about",))
    'De Bruyne'
    """
    # Greedy prefix scan — start of string first (most common case)
    for prefix in prefixes:
        if q_norm.startswith(prefix):
            remainder = original[len(prefix):].strip().strip("?!.,")
            return remainder

    # Fallback — prefix anywhere in the string
    for prefix in prefixes:
        idx = q_norm.find(prefix)
        if idx != -1:
            remainder = original[idx + len(prefix):].strip().strip("?!.,")
            return remainder

    # Last resort: return original stripped as-is
    return original.strip().strip("?!.,")


# ---------------------------------------------------------------------------
# Comparison helper
# ---------------------------------------------------------------------------

def _try_route_comparison(q_orig: str, q_norm: str) -> RouteResult | None:
    """Detect a two-player comparison question and extract both player queries.

    Handles:
    * Prefixed forms — "compare X and Y", "who is better X or Y", etc.
    * Bare connector forms — "X vs Y", "X versus Y"

    Returns a ``RouteResult`` with ``tool_name="compare_players"`` and
    ``tool_args={"query_a": ..., "query_b": ...}`` when detected, else ``None``.
    """
    # 1. Prefixed forms
    for prefix in _COMPARE_PREFIXES:
        if q_norm.startswith(prefix):
            remainder_norm = q_norm[len(prefix):].strip().lstrip(",: ")
            remainder_orig = q_orig[len(prefix):].strip().lstrip(",: ")
            for conn in _COMPARE_CONNECTORS:
                idx = remainder_norm.find(conn)
                if idx != -1:
                    part_a = remainder_orig[:idx].strip().rstrip(",")
                    part_b = remainder_orig[idx + len(conn):].strip()
                    if part_a and part_b:
                        return RouteResult(
                            tool_name="compare_players",
                            tool_args={"query_a": part_a, "query_b": part_b},
                        )

    # 2. Bare "X vs Y" / "X versus Y" (no explicit prefix required)
    for conn in (" vs ", " versus "):
        idx = q_norm.find(conn)
        if idx != -1:
            part_a = q_orig[:idx].strip()
            part_b = q_orig[idx + len(conn):].strip()
            if part_a and part_b:
                return RouteResult(
                    tool_name="compare_players",
                    tool_args={"query_a": part_a, "query_b": part_b},
                )

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def route(question: str) -> RouteResult | None:
    """
    Route *question* to a ``(tool_name, tool_args)`` pair.

    Returns ``None`` if the question cannot be mapped to any known tool.

    Parameters
    ----------
    question:
        Raw user question in any capitalisation.

    Returns
    -------
    RouteResult | None

    Notes
    -----
    Player queries are extracted in **original casing** so that aliases like
    ``"KDB"`` reach the tool runner unchanged.  (The registry's alias index is
    case-insensitive, but preserving casing makes ``query`` fields in tool
    outputs reflect what the user typed.)
    """
    q_norm = _normalise(question)
    q_orig = question.strip().rstrip("?!.")   # original casing, edge punctuation removed

    # ── Gameweek intent ──────────────────────────────────────────────────
    if any(kw in q_norm for kw in _GAMEWEEK_KEYWORDS):
        return RouteResult(tool_name="get_current_gameweek", tool_args={})

    # ── Rank candidates intent (checked before captain-score) ─────────────
    if any(q_norm.startswith(p) or p in q_norm for p in _RANK_PREFIXES) or \
       any(kw in q_norm for kw in _RANKING_KEYWORDS):
        return RouteResult(
            tool_name="rank_captain_candidates",
            tool_args={},
        )

    # ── Compare players intent (checked before captain-score) ─────────────
    _compare_result = _try_route_comparison(q_orig, q_norm)
    if _compare_result is not None:
        return _compare_result

    # ── Captain score intent (checked before summary/resolve) ─────────────
    if any(q_norm.startswith(p) or p in q_norm for p in _CAPTAIN_SCORE_PREFIXES):
        player_query = _extract_player_query(q_orig, q_norm, _CAPTAIN_SCORE_PREFIXES)
        if player_query:
            return RouteResult(
                tool_name="get_captain_score",
                tool_args={"query": player_query},
            )

    # ── Summary intent ───────────────────────────────────────────────────
    if any(q_norm.startswith(p) or p in q_norm for p in _SUMMARY_PREFIXES):
        player_query = _extract_player_query(q_orig, q_norm, _SUMMARY_PREFIXES)
        if player_query:
            return RouteResult(
                tool_name="get_player_summary",
                tool_args={"query": player_query},
            )

    # ── Resolve/identity intent ──────────────────────────────────────────
    if any(q_norm.startswith(p) or p in q_norm for p in _RESOLVE_PREFIXES):
        player_query = _extract_player_query(q_orig, q_norm, _RESOLVE_PREFIXES)
        if player_query:
            return RouteResult(
                tool_name="resolve_player",
                tool_args={"query": player_query},
            )

    return None
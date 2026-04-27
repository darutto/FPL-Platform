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

``get_transfer_advice``   ← Phase 6a
    Triggered by transfer keywords ("should I sell X for Y",
    "transfer out X for Y", "swap X for Y", "replace X with Y").
    Both player queries extracted (query_out and query_in).

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

``get_differential_picks``   ← Phase 7g
    Triggered by differential/low-ownership keywords.
    No player extraction needed.

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

# ---------------------------------------------------------------------------
# Chip advice keyword tables  (Phase 6b)
# ---------------------------------------------------------------------------

# Chip keyword → canonical chip name.  Ordered longest-match-first where
# ambiguous (e.g. "free hit" before a hypothetical shorter alias).
_CHIP_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("triple captain",  "triple_captain"),
    ("triple-captain",  "triple_captain"),
    ("bench boost",     "bench_boost"),
    ("bench-boost",     "bench_boost"),
    ("benchboost",      "bench_boost"),
    ("free hit",        "free_hit"),
    ("free-hit",        "free_hit"),
    ("freehit",         "free_hit"),
    ("wildcard",        "wildcard"),
    ("wild card",       "wildcard"),
)

# Advisory phrases that signal a chip advice question (not just chip mention).
_CHIP_ADVISORY_PHRASES: tuple[str, ...] = (
    "should i",
    "is this a good",
    "is now a good",
    "is it a good",
    "good time to",
    "good week to",
    "good week for",
    "good gameweek",
    "this week",
    "this gameweek",
    "worth using",
    "worth playing",
    "time to use",
    "time to play",
    "when should",
    "when to use",
    "when to play",
    "activate",
)


_TRANSFER_PREFIXES: tuple[str, ...] = (
    "should i sell",
    "should i transfer out",
    "should i transfer",
    "sell",
    "transfer out",
    "swap",
    "replace",
)

_TRANSFER_CONNECTORS: tuple[str, ...] = (
    " and bring in ",   # longest first to avoid partial match
    " for ",
    " with ",
)

_COMPARE_PREFIXES: tuple[str, ...] = (
    "who would you captain between",
    "who should i captain between",
    "which player is better",
    "which is better",
    "who is better",
    "who's better",
    "comparame",   # Spanish "compare me"
    "compara",     # Spanish "compare"
    "compare",
)

_COMPARE_CONNECTORS: tuple[str, ...] = (
    " vs ",
    " versus ",
    " or ",
    " and ",
    " y ",      # Spanish "and"
    " e ",      # Spanish "and" before i/hi (e.g. "Ibrahim e Iglesias")
    " contra ", # Spanish "versus"
    " con ",    # Spanish "with" (used after "comparame/compara")
)

# Connectors safe to use for bare (prefix-free) scan.  Restricted to
# connectors that unambiguously separate two player names without additional
# context — e.g. " or " is excluded because "Palmer or Salah for the armband"
# would capture trailing text as part of the second player name.
_BARE_COMPARE_CONNECTORS: tuple[str, ...] = (
    " vs ",
    " versus ",
    " y ",      # Spanish "and"
    " e ",      # Spanish "and" before i/hi
    " contra ", # Spanish "versus"
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

# ---------------------------------------------------------------------------
# Fixture run keyword tables  (Phase 7h)
# ---------------------------------------------------------------------------

# Prefix forms: "upcoming fixtures for X", "fixtures for X", "fixture run for X"
_FIXTURE_RUN_PREFIXES: tuple[str, ...] = (
    "show me the upcoming fixtures for",
    "show me upcoming fixtures for",
    "show me fixtures for",
    "get the upcoming fixtures for",
    "get upcoming fixtures for",
    "get fixtures for",
    "upcoming fixtures for",
    "fixture schedule for",
    "fixture run for",
    "fixtures for",
)

# Suffix forms: "X fixtures", "X fixture run", "X's fixtures", etc.
# IMPORTANT: possessive forms ("'s X") must come before their plain counterparts
# (" X") so "Haaland's fixtures" matches "'s fixtures" first (giving player
# "Haaland") rather than " fixtures" first (which would give player "Haaland's").
_FIXTURE_RUN_SUFFIXES: tuple[str, ...] = (
    "'s fixture run",
    " fixture run",
    "'s fixture schedule",
    " fixture schedule",
    "'s fixtures",
    " fixtures",
)

# Terminal words that signal an "X next [N] games/fixtures" pattern
_FIXTURE_RUN_GAME_WORDS: frozenset[str] = frozenset(
    {"game", "games", "fixture", "fixtures"}
)


# ---------------------------------------------------------------------------
# Differential picks keyword tables  (Phase 7g)
# ---------------------------------------------------------------------------

# Keywords that unambiguously signal a differential-picks query.
# Ordered longest-first so the most specific phrase is checked first.
_DIFFERENTIAL_KEYWORDS: tuple[str, ...] = (
    "differential picks",
    "good differentials",
    "best differentials",
    "top differentials",
    "show me differentials",
    "show differentials",
    "differentials this week",
    "differentials for this week",
    "differentials for gw",
    "low ownership picks",
    "low-ownership picks",
    "low ownership players",
    "low-ownership players",
    "low owned picks",
    "low owned players",
    "low owned options",
    "low ownership options",
    "differential options",
    "differential candidates",
    "differentials",
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
# Transfer helper  (Phase 6a)
# ---------------------------------------------------------------------------

def _try_route_chip(q_norm: str) -> RouteResult | None:
    """Detect a chip advice question and return a RouteResult, or None.

    Requires BOTH a recognised chip keyword AND at least one advisory phrase
    to avoid false-matching questions that merely mention a chip.

    Examples matched:
    * "should I wildcard this week"
    * "should I use bench boost now"
    * "is this a good week for triple captain"
    * "free hit this week"
    * "should I activate triple captain"

    Returns a ``RouteResult`` with ``tool_name="get_chip_advice"`` and
    ``tool_args={"chip": <chip_name>}`` when detected, else ``None``.
    """
    chip: str | None = None
    for keyword, canonical in _CHIP_KEYWORDS:
        if keyword in q_norm:
            chip = canonical
            break
    if chip is None:
        return None

    if not any(phrase in q_norm for phrase in _CHIP_ADVISORY_PHRASES):
        return None

    return RouteResult(
        tool_name="get_chip_advice",
        tool_args={"chip": chip},
    )


def _try_route_transfer(q_orig: str, q_norm: str) -> "RouteResult | None":
    """Detect a transfer question and extract player_out and player_in queries.

    Handles prefix forms such as:
    * "should I sell Saka for Palmer"
    * "should I transfer out Bruno for Foden"
    * "sell Haaland for Salah"
    * "swap Saka for Palmer"
    * "replace Saka with Palmer"

    Returns a ``RouteResult`` with ``tool_name="get_transfer_advice"`` and
    ``tool_args={"query_out": ..., "query_in": ...}`` when detected, else ``None``.
    """
    for prefix in _TRANSFER_PREFIXES:
        if q_norm.startswith(prefix):
            remainder_norm = q_norm[len(prefix):].strip()
            remainder_orig = q_orig[len(prefix):].strip().rstrip("?!.")
            for conn in _TRANSFER_CONNECTORS:
                idx = remainder_norm.find(conn)
                if idx != -1:
                    out_part = remainder_orig[:idx].strip()
                    in_part  = remainder_orig[idx + len(conn):].strip().rstrip("?!.")
                    if out_part and in_part:
                        return RouteResult(
                            tool_name="get_transfer_advice",
                            tool_args={"query_out": out_part, "query_in": in_part},
                        )
    return None


# ---------------------------------------------------------------------------
# Fixture run helper  (Phase 7h)
# ---------------------------------------------------------------------------

def _try_route_fixture_run(q_orig: str, q_norm: str) -> "RouteResult | None":
    """Detect a fixture-run question and extract the player query.

    Handles three forms:
    * Prefix: "upcoming fixtures for X", "fixtures for X", "fixture run for X"
    * Suffix: "X fixtures", "X's fixtures", "X fixture run"
    * Next-N: "X next [N] games", "X next [N] fixtures"

    Returns a ``RouteResult`` with ``tool_name="get_player_fixture_run"`` and
    ``tool_args={"query": <player>}`` when detected, else ``None``.
    """
    # 1. Prefix forms: checked longest-first (guaranteed by tuple ordering)
    for prefix in _FIXTURE_RUN_PREFIXES:
        if q_norm.startswith(prefix):
            player = q_orig[len(prefix):].strip().rstrip("?!.,")
            if player:
                return RouteResult(
                    tool_name="get_player_fixture_run",
                    tool_args={"query": player},
                )

    # 2. Suffix forms: "X fixtures", "X fixture run", etc.
    for suffix in _FIXTURE_RUN_SUFFIXES:
        if q_norm.endswith(suffix):
            player_end = len(q_orig) - len(suffix)
            player = q_orig[:player_end].strip()
            if player:
                return RouteResult(
                    tool_name="get_player_fixture_run",
                    tool_args={"query": player},
                )

    # 3. "X next [N] games/fixtures" — player precedes " next "
    tokens = q_norm.split()
    if tokens and tokens[-1] in _FIXTURE_RUN_GAME_WORDS and " next " in q_norm:
        idx = q_norm.find(" next ")
        player = q_orig[:idx].strip()
        if player:
            return RouteResult(
                tool_name="get_player_fixture_run",
                tool_args={"query": player},
            )

    return None


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

    # 2. Bare connector forms — no explicit prefix required.
    # Only connectors in _BARE_COMPARE_CONNECTORS are used here; ambiguous
    # connectors like " or " are excluded to avoid capturing trailing context
    # (e.g. "Palmer or Salah for the armband" → part_b = "Salah for the armband").
    #
    # Guard: require part_a to be at most 3 words so that intent-prefixed
    # questions like "quien capito entre Semenyo y Cherki" (4 words before
    # the connector) fall through to the LLM classifier rather than being
    # routed with incorrect player extraction.
    _BARE_CONN_MAX_WORDS = 3
    for conn in _BARE_COMPARE_CONNECTORS:
        idx = q_norm.find(conn)
        if idx != -1:
            part_a = q_orig[:idx].strip()
            part_b = q_orig[idx + len(conn):].strip().rstrip("?!.")
            if part_a and part_b and len(part_a.split()) <= _BARE_CONN_MAX_WORDS:
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

    # ── Chip advice intent (Phase 6b; checked first — "gameweek" appears in
    #    chip questions like "free hit this gameweek" so must precede gameweek)
    _chip_result = _try_route_chip(q_norm)
    if _chip_result is not None:
        return _chip_result

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

    # ── Transfer advice intent (Phase 6a; after comparison, before captain) ─
    _transfer_result = _try_route_transfer(q_orig, q_norm)
    if _transfer_result is not None:
        return _transfer_result

    # ── Fixture run intent (Phase 7h; after transfer, before captain) ──────
    _fixture_result = _try_route_fixture_run(q_orig, q_norm)
    if _fixture_result is not None:
        return _fixture_result

    # ── Differential picks intent (Phase 7g; after fixture run) ─────────────
    if any(kw in q_norm for kw in _DIFFERENTIAL_KEYWORDS):
        return RouteResult(
            tool_name="get_differential_picks",
            tool_args={},
        )

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
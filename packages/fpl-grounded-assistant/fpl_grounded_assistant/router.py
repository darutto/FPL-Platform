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

# M4: import Spanish alias tables from intent_aliases (single source of truth)
from .intent_aliases import (
    TRANSFER_SPANISH_PREFIXES,
    TRANSFER_SPANISH_CONNECTORS,
    FIXTURE_RUN_SPANISH_PREFIXES,
    FIXTURE_RUN_SPANISH_SUFFIXES,
    DIFFERENTIAL_SPANISH_KEYWORDS,
    GAMEWEEK_SPANISH_KEYWORDS,
    CALENDARIO_DE_PREFIX,
)


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
    ("triple capitan",  "triple_captain"),   # Spanish no-accent (Phase 2.7a Story 1.4)
    ("triple capitán",  "triple_captain"),   # Spanish with accent (Phase 2.7a Story 1.4)
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
    # English advisory phrases
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
    # Spanish advisory phrases  (Phase 2.6c)
    # Story 1b.1 — wildcard timing phrasing
    "debería usar",         # "should I use" (with accent)
    "deberia usar",         # "should I use" (no accent)
    "antes o después",      # "before or after" (with accent)
    "antes o despues",      # "before or after" (no accent)
    "cuándo usar",          # "when to use" (with accent)
    "cuando usar",          # "when to use" (no accent)
    # Story 1b.2 — bench boost conditional phrasing
    "tiene sentido",        # "makes sense"
    "vale la pena",         # "worth it"
    "activar",              # Spanish "to activate" (≈ English "activate")
    "conviene usar",        # "is it worth using"
    "conviene activar",     # "is it worth activating"
    # Story 1b.3 — spent-chip sequencing phrasing
    "ya usé",               # "I already used" (with accent)
    "ya use",               # "I already used" (no accent)
    "ya gasté",             # "I already spent" (with accent)
    "ya gaste",             # "I already spent" (no accent)
    "ya lo usé",            # "I already used it" (with accent)
    "ya lo use",            # "I already used it" (no accent)
    # Story 1.4 — Spanish timing / usage phrasing  (Phase 2.7a)
    "es buen momento",      # "is it a good time" (to use)
    "usar mi",              # "use my [chip]"
    "es buena idea",        # "is it a good idea"
    "buen momento para",    # "good time to"
)


# ---------------------------------------------------------------------------
# Spanish name-prefix noise  (Phase 2.6b — Story 1.1)
# ---------------------------------------------------------------------------

# Leading Spanish tokens that prefix player names in natural questions.
# Strip these from extracted player tokens before passing to the registry.
# Ordered longest-first so "tengo a " is stripped before "a ".
_SPANISH_NAME_PREFIXES: tuple[str, ...] = (
    "tengo a ",    # "I have [player]" — 8 chars
    "al ",         # "a el" contraction — 3 chars
    "a ",          # accusative direct-object marker — 2 chars
)


def _strip_spanish_name_prefix(token: str) -> str:
    """Strip leading Spanish preposition noise from an extracted player token.

    ``"a Salah"`` → ``"Salah"``, ``"al Saka"`` → ``"Saka"``,
    ``"tengo a Rashford"`` → ``"Rashford"``.

    Comparison is case-insensitive; casing of the remainder is preserved.
    """
    token_lower = token.lower()
    for prefix in _SPANISH_NAME_PREFIXES:
        if token_lower.startswith(prefix):
            return token[len(prefix):]
    return token


_TRANSFER_PREFIXES: tuple[str, ...] = (
    "should i sell",
    "should i transfer out",
    "should i transfer",
    "sell",
    "transfer out",
    "swap",
    "replace",
    # Spanish transfer prefixes (M4 — imported from intent_aliases)
    *TRANSFER_SPANISH_PREFIXES,
)

_TRANSFER_CONNECTORS: tuple[str, ...] = (
    " and bring in ",   # longest first to avoid partial match
    # Spanish connectors (M4 — imported from intent_aliases; longest first)
    *TRANSFER_SPANISH_CONNECTORS,
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
    # Spanish generic captaincy ranking phrases  (Phase 2.6b)
    "quién debería capitanear esta semana",
    "quien deberia capitanear esta semana",
    "quién debería capitar esta semana",
    "quien deberia capitar esta semana",
    "quién debería capitanear",
    "quien deberia capitanear",
    "a quién capitaneo esta semana",
    "a quien capitaneo esta semana",
    "dame el ranking de capitanes",
    "ranking de capitanes",
    "capitán para esta semana",
    "capitan para esta semana",
)

_RANKING_KEYWORDS: tuple[str, ...] = (
    "rank my captains",
    "rank captains",
    "top captains",
    "captain rankings",
    "best captains",
    "ranking de capitanes",    # Spanish  (Phase 2.6b)
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
    # Spanish single-player captain score phrases  (Phase 2.6b)
    # (generic "who should I captain" phrases → _RANK_PREFIXES instead)
    "debería capitanear a",
    "deberia capitanear a",
    "debería capitar a",
    "deberia capitar a",
    "debería capitanear",
    "deberia capitanear",
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
    # Spanish player summary phrases  (Phase 2.6b)
    "cuántos puntos lleva",     # "how many points has [player] scored"
    "cuantos puntos lleva",     # without accent
    "dame un resumen de",       # "give me a summary of"
    "dame el resumen de",       # "give me the summary of"
    "dame las stats de",        # "give me the stats of"
    "información sobre",        # "information about"
    "informacion sobre",        # without accent
    "cómo le va",               # "how is [player] doing"
    "como le va",               # without accent
    "resumen de",               # "summary of"
    "precio de",                # "price of"
    "stats de",                 # "stats of"
    # Spanish injury-check phrases routed to player_summary  (Phase 2.6d Story 2.3)
    "está lesionado",           # "is [player] injured"
    "esta lesionado",
    "está disponible",          # "is [player] available"
    "esta disponible",
    "tiene lesión",             # "has an injury"
    "tiene lesion",
    "puede jugar",              # "can [player] play"
    "está en duda",             # "is [player] doubtful"
    "esta en duda",
    "está descartado",          # "is [player] ruled out"
    "esta descartado",
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
# Player form keyword tables  (Phase 2.6d Story 2.1)
# ---------------------------------------------------------------------------

import re as _re  # noqa: E402 — placed here for locality
import unicodedata as _unicodedata  # noqa: E402 — placed here for locality

# Regex to extract a small positive integer as n_games from the question.
# Matches digits 1-38 followed by a games/GW unit word.
_N_GAMES_RE = _re.compile(
    r'\b([1-9][0-9]?)\s*'
    r'(?:jornadas?|partidos?|juegos?|gw|gameweeks?|games?|semanas?)\b',
    _re.IGNORECASE,
)

_PLAYER_FORM_DEFAULT_N: int = 5


def _deaccent(text: str) -> str:
    """Strip combining diacritical marks (accents) from *text*.

    Called only within the player-form routing path so that accent variants
    (e.g. "últimos" vs "ultimos", "estadísticas" vs "estadisticas") are
    matched uniformly without globalising normalisation elsewhere.

    Examples
    --------
    >>> _deaccent("dame las estadísticas de los últimos")
    'dame las estadisticas de los ultimos'
    """
    return "".join(
        c for c in _unicodedata.normalize("NFD", text)
        if _unicodedata.category(c) != "Mn"
    )


# Regex matching a count+unit noise fragment that may leak into a player name
# slot when the player precedes a count phrase.
# E.g. ", en 5 partidos" or " en los ultimos 5 partidos" trailing after name.
# Used in _try_route_player_form Pattern 2 (Story 2.3 guard).
_COUNT_UNIT_NOISE_RE = _re.compile(
    r'\s*,?\s*\ben\s+(?:los?\s+)?(?:últimos?|ultimos?|últimas?|ultimas?)\s+'
    r'[1-9][0-9]?\s*(?:jornadas?|partidos?|juegos?|gw|gameweeks?|games?|semanas?)?'
    r'.*$',
    _re.IGNORECASE,
)

# Prefix forms where the player name comes AFTER the prefix.
# E.g. "historial de puntos de Cherki"
_PLAYER_FORM_PREFIXES: tuple[str, ...] = (
    "dame el historial de puntos de",
    "historial de puntos de",
    "dame el historial de",
    "historial de",
)

# Prefix forms where the player name comes between the prefix and a
# "en los últimos / en las últimas" middle keyword.
# E.g. "cómo ha estado Salah en los últimos 3 partidos"
# E.g. "dame los stats de Cherki en los ultimos 5"    (Story 2.1)
# E.g. "dame las stats de Cherki, en 5 partidos"      (Story 2.1 — comma sep)
#
# Stored WITHOUT accents; _try_route_player_form deaccents both the query and
# these entries before matching so all accent variants are handled uniformly
# (Story 2.2 — accent-insensitive matching).
_PLAYER_FORM_PLAYER_FIRST_PREFIXES: tuple[str, ...] = (
    "como ha estado",            # "cómo ha estado" (deaccented)
    "cuantos puntos ha sacado",  # "cuántos puntos ha sacado" (deaccented)
    "que tal ha estado",         # "qué tal ha estado" (deaccented)
    "dame las stats de",         # Story 2.1: player-first compact phrasing
    "dame los stats de",         # Story 2.1: "los" variant
)

# Split keywords: player appears before these, N+context appears after.
# Stored WITHOUT accents; the routing path deaccents the query before matching
# (Story 2.2).
_PLAYER_FORM_MIDDLE_KWS: tuple[str, ...] = (
    " en los ultimos ",
    " en las ultimas ",
)

# Prefix forms where N comes right after the prefix and player follows "de".
# E.g. "dame las stats de los últimos 5 partidos de Cherki"
# Stored WITHOUT accents so that _deaccent()-based matching handles any
# mixed-accent variant the user may type (Story 2.2).
_PLAYER_FORM_N_FIRST_PREFIXES: tuple[str, ...] = (
    "dame las stats de los ultimos",
    "dame las estadisticas de los ultimos",
)


def _extract_n_games(q_norm: str) -> int:
    """Extract the first valid N from a form-query question string."""
    m = _N_GAMES_RE.search(q_norm)
    if m:
        return min(int(m.group(1)), 38)
    return _PLAYER_FORM_DEFAULT_N


# ---------------------------------------------------------------------------
# Injury list keyword tables  (Phase 2.6d Story 2.3)
# ---------------------------------------------------------------------------

_INJURY_LIST_KEYWORDS: tuple[str, ...] = (
    "hay dudas para esta jornada",
    "hay dudas para",
    "jugadores en duda",
    "jugadores lesionados",
    "jugadores con dudas",
    "lesionados esta semana",
    "lista de bajas",
    "lista de dudas",
    "quién está en duda",
    "quien esta en duda",
    "hay algún jugador lesionado",
    "hay algun jugador lesionado",
    "quiénes están lesionados",
    "quienes estan lesionados",
    "bajas para esta semana",
    "injury list",
    "doubts this gw",
    "doubtful players",
)


# ---------------------------------------------------------------------------
# Price changes keyword tables  (Phase 2.6d Story 2.4)
# ---------------------------------------------------------------------------

_PRICE_CHANGES_KEYWORDS: tuple[str, ...] = (
    "quién está subiendo de precio",
    "quien esta subiendo de precio",
    "quién sube de precio",
    "quien sube de precio",
    "quién ha subido de precio",
    "quien ha subido de precio",
    "subiendo de precio esta semana",
    "quién está bajando de precio",
    "quien esta bajando de precio",
    "quién baja de precio",
    "quien baja de precio",
    "quién ha bajado de precio",
    "quien ha bajado de precio",
    "bajando de precio",
    "jugadores que suben de precio",
    "jugadores que bajan de precio",
    # Story 1.3 — generic "changed price this week" phrasing  (Phase 2.7a)
    "han cambiado de precio",    # "have changed price"
    "cambiado de precio",        # "changed price"
    "cambios de precio esta semana",   # "price changes this week"
    "changed price this week",
    "changed their price",
    # Existing English / Spanish
    "price risers",
    "price fallers",
    "price changes",
    "cambios de precio",
    "subidas de precio",
    "bajadas de precio",
)


# ---------------------------------------------------------------------------
# Team fixture calendar keyword tables  (Phase 2.6e)
# ---------------------------------------------------------------------------

# Keywords that signal an EASIEST team calendar query (no named player).
# Checked before player_fixture_run so bare "best fixtures" patterns don't
# need a player name to route here.  Player-specific queries ("fixtures for
# Haaland") are caught earlier by _try_route_fixture_run() in route().
_TEAM_CALENDAR_EASIEST_KEYWORDS: tuple[str, ...] = (
    # Spanish
    "mejor calendario las proximas",
    "mejor calendario las próximas",
    "mejor calendario proximas",
    "mejor calendario próximas",
    "mejor calendario",
    "mejores calendarios",
    "mejores fixtures",
    "equipos con mejor calendario",
    "equipos con los mejores",
    "que equipos tienen el mejor",
    "que equipos tienen los mejores",
    # English
    "teams easiest fixtures",
    "teams with easiest fixtures",
    "teams with best fixtures",
    "best upcoming fixtures",
    "easiest upcoming fixtures",
    "easiest fixture run",
    "best fixture run",
    "best fixtures next",
    "easiest fixtures next",
    "easiest schedule",
    "best schedule",
    "teams with easy fixtures",
    "teams easy fixtures",
    "best run of fixtures",
    "easiest run of fixtures",
    "fixture difficulty ranking",
    "which teams have best fixtures",
    "which teams have easiest",
)

# Keywords that signal a HARDEST team calendar query.
_TEAM_CALENDAR_HARDEST_KEYWORDS: tuple[str, ...] = (
    # Spanish
    "peor calendario las proximas",
    "peor calendario las próximas",
    "peor calendario proximas",
    "peor calendario",
    "peores calendarios",
    "peores fixtures",
    "equipos con peor calendario",
    "equipos con los peores",
    "que equipos tienen el peor",
    "que equipos tienen los peores",
    # English
    "teams hardest fixtures",
    "teams with hardest fixtures",
    "teams with worst fixtures",
    "worst upcoming fixtures",
    "hardest upcoming fixtures",
    "hardest fixture run",
    "worst fixture run",
    "worst fixtures next",
    "hardest fixtures next",
    "hardest schedule",
    "worst schedule",
    "teams with hard fixtures",
    "worst run of fixtures",
    "hardest run of fixtures",
    "which teams have worst fixtures",
    "which teams have hardest",
)


# ---------------------------------------------------------------------------
# Position-filtered fixture calendar tables  (Phase 2.6e.4)
# ---------------------------------------------------------------------------

# Maps lowercase position words to canonical query strings for the handler.
_POSITION_WORDS: dict[str, str] = {
    "goalkeeper":      "goalkeeper",  "goalkeepers":     "goalkeeper",
    "gkp":             "goalkeeper",
    "defender":        "defender",    "defenders":       "defender",
    "def":             "defender",
    "midfielder":      "midfielder",  "midfielders":     "midfielder",
    "mid":             "midfielder",
    "forward":         "forward",     "forwards":        "forward",
    "striker":         "forward",     "strikers":        "forward",
    "fwd":             "forward",
    # Spanish
    "portero":         "portero",     "porteros":        "portero",
    "defensa":         "defensa",     "defensas":        "defensa",
    "defensor":        "defensa",     "defensores":      "defensa",
    "centrocampista":  "centrocampista", "centrocampistas": "centrocampista",
    "mediocampista":   "centrocampista", "mediocampistas":  "centrocampista",
    "medio":           "centrocampista", "medios":          "centrocampista",
    "delantero":       "delantero",   "delanteros":      "delantero",
    "atacante":        "delantero",   "atacantes":       "delantero",
    "punta":           "delantero",   "puntas":          "delantero",
}

# Prefix patterns: "best teams for {position}", "mejores equipos para {position}"
# Each entry is (lowercase_prefix, mode).  Sorted longest-first.
_POSITION_CALENDAR_PREFIXES: tuple[tuple[str, str], ...] = tuple(sorted(
    [
        ("which teams have easiest fixtures for",  "easiest"),
        ("which teams have best fixtures for",     "easiest"),
        ("teams with best fixtures for",           "easiest"),
        ("which teams have hardest fixtures for",  "hardest"),
        ("which teams have worst fixtures for",    "hardest"),
        ("teams with worst fixtures for",          "hardest"),
        ("equipos con mejor calendario para",      "easiest"),
        ("equipos con peor calendario para",       "hardest"),
        ("easiest fixtures for",                   "easiest"),
        ("hardest fixtures for",                   "hardest"),
        ("best fixture run for",                   "easiest"),
        ("worst fixture run for",                  "hardest"),
        ("best fixtures for",                      "easiest"),
        ("worst fixtures for",                     "hardest"),
        ("mejor calendario para",                  "easiest"),
        ("peor calendario para",                   "hardest"),
        ("mejores equipos para",                   "easiest"),
        ("peores equipos para",                    "hardest"),
        ("mejores fixtures para",                  "easiest"),
        ("peores fixtures para",                   "hardest"),
        ("best teams for",                         "easiest"),
        ("worst teams for",                        "hardest"),
    ],
    key=lambda x: -len(x[0]),
))

# Inline markers: "{position} with best/worst fixtures"
_POSITION_INLINE_EASIEST: frozenset[str] = frozenset({
    " with best fixtures",
    " with easiest fixtures",
    " with best upcoming fixtures",
    " with best fixture run",
    " con mejor calendario",
    " con mejores fixtures",
    " con los mejores fixtures",
})
_POSITION_INLINE_HARDEST: frozenset[str] = frozenset({
    " with worst fixtures",
    " with hardest fixtures",
    " with worst upcoming fixtures",
    " with worst fixture run",
    " con peor calendario",
    " con peores fixtures",
    " con los peores fixtures",
})


# ---------------------------------------------------------------------------
# Single-team schedule keyword tables  (Phase 2.6e.3)
# ---------------------------------------------------------------------------

# Spanish prefix forms: "calendario del {team} ..."
_TEAM_SCHEDULE_SPANISH_PREFIXES: tuple[str, ...] = (
    "proximos partidos del ",
    "proximas jornadas del ",
    "calendario del ",
    "partidos del ",
    "fixtures del ",
)

# Known PL team name tokens (lowercase) for disambiguating
# "{team} fixtures [next N]" from "{player} fixtures [next N]".
# The value is the team_query string passed to the handler.
# Sorted longest-first to prevent "man" matching before "man city".
_TEAM_SCHEDULE_KNOWN_NAMES: tuple[tuple[str, str], ...] = tuple(sorted(
    [
        ("manchester city",    "Manchester City"),
        ("manchester utd",     "Manchester Utd"),
        ("manchester united",  "Manchester United"),
        ("crystal palace",     "Crystal Palace"),
        ("aston villa",        "Aston Villa"),
        ("west ham",           "West Ham"),
        ("nottingham forest",  "Nottingham Forest"),
        ("nottm forest",       "Nottm Forest"),
        ("man city",           "Man City"),
        ("man united",         "Man United"),
        ("man utd",            "Man Utd"),
        ("arsenal",            "Arsenal"),
        ("bournemouth",        "Bournemouth"),
        ("brentford",          "Brentford"),
        ("brighton",           "Brighton"),
        ("chelsea",            "Chelsea"),
        ("everton",            "Everton"),
        ("fulham",             "Fulham"),
        ("ipswich",            "Ipswich"),
        ("leicester",          "Leicester"),
        ("liverpool",          "Liverpool"),
        ("newcastle",          "Newcastle"),
        ("southampton",        "Southampton"),
        ("tottenham",          "Tottenham"),
        ("spurs",              "Spurs"),
        ("wolves",             "Wolves"),
        ("wolverhampton",      "Wolverhampton"),
        ("forest",             "Forest"),
        ("palace",             "Crystal Palace"),
        ("villa",              "Aston Villa"),
    ],
    key=lambda x: -len(x[0]),   # longest alias checked first
))

# Flat dict: lowercase single-token alias → team_query string.
# Used by _extract_team_token for O(1) lookup of individual tokens.
# Excludes multi-word aliases (those are handled via substring scan).
_TEAM_NAME_LOOKUP: dict[str, str] = {
    alias: tq
    for alias, tq in _TEAM_SCHEDULE_KNOWN_NAMES
    if " " not in alias
}


def _extract_team_token(q_norm: str) -> str | None:
    """Return the first known team name found in a normalised query string.

    Checks multi-word aliases first (sorted longest-first so "manchester city"
    beats "manchester"), then individual tokens.  Returns the ``team_query``
    string (e.g. ``"Arsenal"``) or ``None`` when no known team is found.

    Used by ``_try_route_transfer_suggestion`` to extract a club filter from
    phrases like "best Arsenal midfielders to buy" or "delanteros del Liverpool".
    """
    # Multi-word check (already sorted longest-first in _TEAM_SCHEDULE_KNOWN_NAMES)
    for alias_norm, team_query in _TEAM_SCHEDULE_KNOWN_NAMES:
        if " " in alias_norm:
            padded = " " + q_norm + " "
            if (" " + alias_norm + " ") in padded:
                return team_query
    # Single-token check
    for tok in q_norm.split():
        clean = tok.rstrip(".,")
        if clean in _TEAM_NAME_LOOKUP:
            return _TEAM_NAME_LOOKUP[clean]
    return None


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
    # Spanish fixture-run prefixes (M4 — imported from intent_aliases).
    # NOTE: "calendario de " is NOT listed here — it is handled separately
    # in _try_route_fixture_run() via the CALENDARIO_DE_PREFIX disambiguation
    # guard (team token check first, then falls here if no team found).
    *FIXTURE_RUN_SPANISH_PREFIXES,
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
    # Spanish suffix forms (M4 — imported from intent_aliases)
    *FIXTURE_RUN_SPANISH_SUFFIXES,
)

# Terminal words that signal an "X next [N] games/fixtures" pattern
_FIXTURE_RUN_GAME_WORDS: frozenset[str] = frozenset(
    {"game", "games", "fixture", "fixtures"}
)


# ---------------------------------------------------------------------------
# Transfer suggestion keyword tables  (Phase 2.6h)
# ---------------------------------------------------------------------------

# Price extraction regex: "under 8.0", "below 8", "less than 7.5",
# "7.5m", "7.5 million", "bajo 7.5", "menos de 8", "precio menor a 8",
# "de no mas de 8", "no más de 7.5"  (Phase 2.7a Story 1.1/1.2)
import re as _re_price
_PRICE_RE = _re_price.compile(
    r'(?:under|below|less than|bajo|menos de|precio menor a|de no m[aá]s de|no m[aá]s de)\s+(\d+\.?\d*)'
    r'|(\d+\.?\d*)\s*(?:m\b|million\b|millones?\b)',
    _re_price.IGNORECASE,
)


def _extract_price_ceiling(q_norm: str) -> float | None:
    """Extract a price ceiling in millions from a normalised query string."""
    m = _PRICE_RE.search(q_norm)
    if not m:
        return None
    val_str = m.group(1) or m.group(2)
    try:
        return float(val_str)
    except (TypeError, ValueError):
        return None


# Flat dict for O(1) single-token team-name lookup (derived from _TEAM_SCHEDULE_KNOWN_NAMES
# which is defined below — populated lazily after that tuple is constructed).
# We define it after _TEAM_SCHEDULE_KNOWN_NAMES; see _TEAM_NAME_LOOKUP assignment below.

# Buy-intent suffix markers — appear AFTER the position word in the query.
# "to buy", "to sign", "para fichar", etc. are unambiguous purchase signals.
_BUY_SUFFIXES: tuple[str, ...] = (
    " to buy",
    " to sign",
    " to transfer in",
    " to bring in",
    " worth buying",
    " worth signing",
    " para fichar",
    " para comprar",
    " a fichar",
    " a comprar",
    # Spanish "cheap" qualifier — signals buy intent after a position word
    # e.g. "delanteros baratos del liverpool"  (Phase 2.7a Story 1.2)
    " baratos",
    " baratas",
)

# Prefix forms where position is optional (general buy intent).
_TRANSFER_SUGGESTION_PREFIXES: tuple[str, ...] = (
    "who should i buy",
    "who do you recommend buying",
    "best players to buy",
    "cheap players to buy",
    "who to buy",
    "who to sign",
    "players to buy",
    "players to sign",
    "a quien fichar",
    "a quién fichar",
    "quien fichar",
    "quién fichar",
    "quien comprar",
    "quién comprar",
    # Spanish "players from {team}" general-list intent  (Phase 2.7a Story 1.1)
    # "jugadores del arsenal por menos de 8" — team + price without buy suffix
    "jugadores del ",
    "jugadores de ",
)

# Prefix forms where position PRECEDES the keyword: "best {pos} to buy ..."
# Keys are checked as startswith after stripping "best"/"top"/"cheap" lead-in.
_TRANSFER_SUGGESTION_LEAD_WORDS: frozenset[str] = frozenset({
    "best", "top", "cheap", "affordable", "mejores", "baratos",
})

# Spanish imperative verbs that signal a player-list request when followed by
# a position word and a team or price constraint.  Used by Form 3b in
# ``_try_route_transfer_suggestion``.  (Phase 2.7a Story 1.2)
_SPANISH_IMPERATIVE_LEADS: frozenset[str] = frozenset({"dame", "necesito", "muéstrame", "muestrame"})


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
    # Spanish synonyms (M4 — imported from intent_aliases; longest first)
    *DIFFERENTIAL_SPANISH_KEYWORDS,
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
    # Spanish synonyms (M4 — imported from intent_aliases)
    *GAMEWEEK_SPANISH_KEYWORDS,
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
            return _strip_spanish_name_prefix(remainder)

    # Fallback — prefix anywhere in the string
    for prefix in prefixes:
        idx = q_norm.find(prefix)
        if idx != -1:
            remainder = original[idx + len(prefix):].strip().strip("?!.,")
            return _strip_spanish_name_prefix(remainder)

    # Last resort: return original stripped as-is
    return _strip_spanish_name_prefix(original.strip().strip("?!.,"))


# ---------------------------------------------------------------------------
# Player form helper  (Phase 2.6d Story 2.1 / Phase 2.7b Stories 2.1-2.3)
# ---------------------------------------------------------------------------

def _try_route_player_form(q_orig: str, q_norm: str) -> "RouteResult | None":
    """Detect a player-form / history question and return a RouteResult.

    Handles three surface patterns:

    1. ``"historial de puntos de X"`` — player follows prefix
    2. ``"{prefix} X en los ultimos N"`` — player between a recognised prefix
       and a middle split keyword.
       Phase 2.7b Story 2.1: also covers "dame los stats de X en los ultimos N"
       and "dame las stats de X, en N partidos" (player-first compact phrasing).
       Phase 2.7b Story 2.2: prefix + middle-keyword tables are stored without
       accents; matching is performed against _deaccent(q_norm) so any
       mixed-accent variant is handled uniformly.
       Phase 2.7b Story 2.3: trailing count/unit noise stripped from extracted
       player name via _COUNT_UNIT_NOISE_RE.
    3. ``"dame las stats de los ultimos N partidos de X"`` — N follows prefix,
       player follows "partidos|jornadas de".
       Phase 2.7b Story 2.2: prefix matching uses _deaccent() so mixed-accent
       queries like "dame las estadisticas de los ultimos" also fire.

    Returns ``RouteResult(tool_name="get_player_form",
    tool_args={"query": player, "n_games": N})`` or ``None``.
    """
    n = _extract_n_games(q_norm)

    # Accent-normalised query — used for all player-form matching (Story 2.2).
    q_deacc = _deaccent(q_norm)

    # Pattern 1: "historial de X" — player at end
    for prefix in _PLAYER_FORM_PREFIXES:
        if q_norm.startswith(prefix):
            raw = q_orig[len(prefix):].strip().rstrip("?!.,")
            # Strip trailing "en los ultimos..." noise if present.
            # Use _deaccent on both sides so accent variants are caught.
            raw_deacc = _deaccent(raw.lower())
            for kw in _PLAYER_FORM_MIDDLE_KWS:
                idx = raw_deacc.find(kw.strip())
                if idx != -1:
                    raw = raw[:idx].strip()
                    break
            player = _strip_spanish_name_prefix(raw)
            if player:
                return RouteResult(
                    tool_name="get_player_form",
                    tool_args={"query": player, "n_games": n},
                )

    # Pattern 2: "{prefix} X en los ultimos N"  (Story 2.1 + 2.2 + 2.3)
    # Prefixes and middle keywords stored without accents; compare q_deacc.
    for prefix in _PLAYER_FORM_PLAYER_FIRST_PREFIXES:
        if q_deacc.startswith(prefix):
            rem_deacc = q_deacc[len(prefix):].strip()
            rem_orig  = q_orig[len(prefix):].strip()
            # Sub-case A: middle keyword found — player is before the keyword.
            for kw in _PLAYER_FORM_MIDDLE_KWS:
                idx = rem_deacc.find(kw)
                if idx != -1:
                    raw_player = rem_orig[:idx].strip().rstrip(",?")
                    # Story 2.3: strip count/unit noise that leaked into name.
                    raw_player = _COUNT_UNIT_NOISE_RE.sub(
                        "", raw_player
                    ).strip().rstrip(",?")
                    player = _strip_spanish_name_prefix(raw_player)
                    if player:
                        return RouteResult(
                            tool_name="get_player_form",
                            tool_args={"query": player, "n_games": n},
                        )
            # Sub-case B: no "en los ultimos" keyword — Story 2.1 compact form
            # "dame los stats de X, en N partidos".  Locate the N+unit match
            # in rem_deacc; everything before its start (stripped of trailing
            # comma/space/"en") is the player name.
            #
            # Guard: skip if rem_deacc starts with "los ultimos" or "las ultimas"
            # — that is a Pattern 3 N-first form (handled below) and would
            # produce a garbage player name like "ultimos".
            _is_n_first = (
                rem_deacc.startswith("los ultimos ")
                or rem_deacc.startswith("las ultimas ")
            )
            m_count = _N_GAMES_RE.search(rem_deacc)
            if m_count and not _is_n_first:
                # Walk back from the digit to strip any "en" + comma separator.
                cut = m_count.start()
                raw_player = rem_orig[:cut].strip().rstrip(",").rstrip()
                # Strip a trailing bare "en" connector that precedes the count.
                raw_player = _re.sub(r'\s+en\s*$', '', raw_player,
                                     flags=_re.IGNORECASE).strip().rstrip(",?")
                # Sanity: must be non-empty and not a bare digit.
                if raw_player and not _re.fullmatch(r'\d+', raw_player.strip()):
                    player = _strip_spanish_name_prefix(raw_player)
                    if player:
                        return RouteResult(
                            tool_name="get_player_form",
                            tool_args={"query": player, "n_games": n},
                        )

    # Pattern 3: "dame las stats de los ultimos N partidos de X"  (Story 2.2)
    # _PLAYER_FORM_N_FIRST_PREFIXES stored without accents; compare q_deacc.
    for prefix in _PLAYER_FORM_N_FIRST_PREFIXES:
        if q_deacc.startswith(prefix):
            rem_deacc = q_deacc[len(prefix):].strip()
            rem_orig  = q_orig[len(prefix):].strip()
            # Find "de X" after the number + unit phrase.
            for de_kw in (" partidos de ", " jornadas de ", " games de ",
                          " partidos ", " jornadas "):
                idx = rem_deacc.find(de_kw)
                if idx != -1:
                    after = rem_orig[idx + len(de_kw):].strip().rstrip("?!.,")
                    # Story 2.3: strip any residual count/unit fragments.
                    after = _COUNT_UNIT_NOISE_RE.sub(
                        "", after
                    ).strip().rstrip("?!.,")
                    player = _strip_spanish_name_prefix(after)
                    if player:
                        return RouteResult(
                            tool_name="get_player_form",
                            tool_args={"query": player, "n_games": n},
                        )
            # Fallback: if only a prefix+number is found with no "de", skip
    return None


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
                    out_part = _strip_spanish_name_prefix(remainder_orig[:idx].strip())
                    in_part  = _strip_spanish_name_prefix(
                        remainder_orig[idx + len(conn):].strip().rstrip("?!.")
                    )
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

    # 1b. "calendario de {player}" (M4 §7.3 disambiguation).
    #     _try_route_team_schedule already claimed "calendario de {known_team}".
    #     If we reach here with this prefix, the remainder is a player name.
    if q_norm.startswith(CALENDARIO_DE_PREFIX):
        remainder_orig = q_orig[len(CALENDARIO_DE_PREFIX):].strip().rstrip("?!.,")
        player = _strip_spanish_name_prefix(remainder_orig)
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

def _try_route_team_calendar(q_norm: str) -> RouteResult | None:
    """Detect a team fixture calendar ranking question.

    Checks for hardest patterns first (more specific), then easiest.
    Extracts an optional horizon (N gameweeks) from the question.
    Returns ``RouteResult(tool_name="get_team_fixture_calendar",
    tool_args={"mode": ..., "horizon": N})`` or ``None``.
    """
    n = _extract_n_games(q_norm)   # reuses existing GW-count extractor

    for kw in _TEAM_CALENDAR_HARDEST_KEYWORDS:
        if kw in q_norm:
            return RouteResult(
                tool_name="get_team_fixture_calendar",
                tool_args={"mode": "hardest", "horizon": n},
            )

    for kw in _TEAM_CALENDAR_EASIEST_KEYWORDS:
        if kw in q_norm:
            return RouteResult(
                tool_name="get_team_fixture_calendar",
                tool_args={"mode": "easiest", "horizon": n},
            )

    return None


def _try_route_transfer_suggestion(q_orig: str, q_norm: str) -> "RouteResult | None":
    """Detect a transfer target suggestion query.

    Handles three forms:
    1. General buy prefix: "who should I buy", "a quién fichar"
    2. "{pos} to buy [under X]": position word at start + buy-intent suffix
    3. "best/cheap [{team}] {pos} to buy [under X]": lead word, optional team,
       position, buy suffix — team may precede OR follow the position word

    Phase 2.6i: all three forms also extract an optional team name token via
    ``_extract_team_token()`` and pass it as ``team_query`` in ``tool_args``.

    Routing collision notes:
    * ``_TRANSFER_PREFIXES`` (transfer_advice) fires first on "sell X for Y" —
      no overlap because we require a buy-suffix or explicit buy prefix.
    * ``_DIFFERENTIAL_KEYWORDS`` uses entirely different phrases.
    * ``_POSITION_CALENDAR_PREFIXES`` catches "best teams for {pos}" —
      we only match "{pos} to buy" or "best {pos} to buy", not "best teams for".
    * Team schedule catches "{team} schedule" — we require a position + buy suffix.
    """
    n         = _extract_n_games(q_norm)
    max_price = _extract_price_ceiling(q_norm)

    # 1. General buy prefix (position and team both optional)
    for prefix in _TRANSFER_SUGGESTION_PREFIXES:
        if q_norm.startswith(prefix):
            remainder = q_norm[len(prefix):].strip()
            pos_token = remainder.split()[0].rstrip(".,") if remainder.split() else ""
            pos_query = _POSITION_WORDS.get(pos_token, None)
            return RouteResult(
                tool_name="get_transfer_suggestion",
                tool_args={
                    "position_query": pos_query,
                    "team_query":     _extract_team_token(q_norm),
                    "max_price":      max_price,
                    "horizon":        n,
                },
            )

    tokens = q_norm.split()

    # 2. "{pos} to buy [under X]" — position word at start, buy suffix in rest
    if tokens and tokens[0] in _POSITION_WORDS:
        rest = q_norm[len(tokens[0]):]
        for suffix in _BUY_SUFFIXES:
            if rest.startswith(suffix) or suffix in rest:
                return RouteResult(
                    tool_name="get_transfer_suggestion",
                    tool_args={
                        "position_query": _POSITION_WORDS[tokens[0]],
                        "team_query":     _extract_team_token(q_norm),
                        "max_price":      max_price,
                        "horizon":        n,
                    },
                )

    # 3. "best/cheap [{team}] {pos} to buy [under X]"
    #    Lead word + optional team token(s) + position word + buy suffix.
    #    Scanning all rem_tokens (not just [0]) lets team names precede position.
    if tokens and tokens[0] in _TRANSFER_SUGGESTION_LEAD_WORDS:
        remainder = q_norm[len(tokens[0]):].strip()
        rem_tokens = remainder.split()
        for i, tok in enumerate(rem_tokens):
            clean = tok.rstrip(".,")
            if clean in _POSITION_WORDS:
                # Found the position word; check for buy suffix in the tail
                pos_idx = remainder.find(clean)
                rest    = remainder[pos_idx + len(clean):]
                for suffix in _BUY_SUFFIXES:
                    if rest.startswith(suffix) or suffix in rest:
                        return RouteResult(
                            tool_name="get_transfer_suggestion",
                            tool_args={
                                "position_query": _POSITION_WORDS[clean],
                                "team_query":     _extract_team_token(q_norm),
                                "max_price":      max_price,
                                "horizon":        n,
                            },
                        )
                break   # position found but no buy suffix — not a buy query

    # 3b. Spanish imperative "{dame} {pos} de/del {team} [baratos] [price]"
    #     Handles queries where a position word follows a Spanish imperative and
    #     there is team or price context — e.g.:
    #     "dame mediocampistas de chelsea baratos, de no mas de 8 millones"
    #     Guards: must have BOTH a position word at token[1] AND (team OR price).
    #     This prevents false matches on player-form queries like
    #     "dame el historial de ..." where "el" is not a position word.
    #     Checked before Form 4 so position is extracted rather than defaulting to ALL.
    #     (Phase 2.7a Story 1.2)
    if tokens and tokens[0] in _SPANISH_IMPERATIVE_LEADS:
        remainder_imp = q_norm[len(tokens[0]):].strip()
        imp_tokens = remainder_imp.split()
        if imp_tokens:
            first_imp = imp_tokens[0].rstrip(".,")
            if first_imp in _POSITION_WORDS:
                imp_team = _extract_team_token(q_norm)
                if imp_team or max_price is not None:
                    return RouteResult(
                        tool_name="get_transfer_suggestion",
                        tool_args={
                            "position_query": _POSITION_WORDS[first_imp],
                            "team_query":     imp_team,
                            "max_price":      max_price,
                            "horizon":        n,
                        },
                    )

    # 4. No-position club-filtered buy query (Phase 2.6j).
    #    Fires when a known team token is present and buy intent can be inferred:
    #      A) explicit buy suffix (e.g. "to buy", "para fichar"), or
    #      B) explicit buy prefix (e.g. "who should I buy"), or
    #      C) lead word + price ceiling ("best Arsenal players under 8").
    #    Forms 1-3 have already exhausted all position-bearing paths, so reaching
    #    here means no position word was found — position defaults to ALL.
    #
    #    Collision-safe:
    #    * Team schedule fires before this and claims "{team} schedule" phrases.
    #    * "best teams for {pos}" → position_fixture_run (fired even earlier).
    #    * No buy suffix/prefix in fixture phrases → condition never met for them.
    #    * Differential keywords ("differentials") do not contain team tokens.
    team_token = _extract_team_token(q_norm)
    if team_token:
        has_buy_suffix = any(suffix in q_norm for suffix in _BUY_SUFFIXES)
        has_buy_prefix = any(q_norm.startswith(pfx) for pfx in _TRANSFER_SUGGESTION_PREFIXES)
        has_lead_price = (
            bool(tokens)
            and tokens[0] in _TRANSFER_SUGGESTION_LEAD_WORDS
            and max_price is not None
        )
        if has_buy_suffix or has_buy_prefix or has_lead_price:
            return RouteResult(
                tool_name="get_transfer_suggestion",
                tool_args={
                    "position_query": None,
                    "team_query":     team_token,
                    "max_price":      max_price,
                    "horizon":        n,
                },
            )

    return None


def _try_route_position_fixture_run(q_orig: str, q_norm: str) -> "RouteResult | None":
    """Detect a position-filtered fixture calendar query.

    Handles two forms:
    1. Prefix: "best teams for defenders [next N]"
    2. Inline: "defenders with best fixtures [next N]"

    Returns ``RouteResult(tool_name="get_position_fixture_run", ...)`` or ``None``.
    Must be called BEFORE ``_try_route_team_schedule`` and ``_try_route_fixture_run``.
    """
    n = _extract_n_games(q_norm)

    # 1. Prefix patterns (longest-first due to tuple sort order)
    for prefix_norm, mode in _POSITION_CALENDAR_PREFIXES:
        if q_norm.startswith(prefix_norm + " ") or q_norm == prefix_norm:
            remainder = q_norm[len(prefix_norm):].strip()
            if not remainder:
                continue
            pos_token = remainder.split()[0].rstrip(".,")
            if pos_token in _POSITION_WORDS:
                return RouteResult(
                    tool_name="get_position_fixture_run",
                    tool_args={
                        "position_query": _POSITION_WORDS[pos_token],
                        "mode":           mode,
                        "horizon":        n,
                    },
                )

    # 2. Inline: "{position} with best/worst fixtures [next N]"
    tokens = q_norm.split()
    if tokens:
        first = tokens[0]
        if first in _POSITION_WORDS:
            rest = q_norm[len(first):]
            for marker in _POSITION_INLINE_EASIEST:
                if rest.startswith(marker) or marker in rest:
                    return RouteResult(
                        tool_name="get_position_fixture_run",
                        tool_args={
                            "position_query": _POSITION_WORDS[first],
                            "mode":           "easiest",
                            "horizon":        n,
                        },
                    )
            for marker in _POSITION_INLINE_HARDEST:
                if rest.startswith(marker) or marker in rest:
                    return RouteResult(
                        tool_name="get_position_fixture_run",
                        tool_args={
                            "position_query": _POSITION_WORDS[first],
                            "mode":           "hardest",
                            "horizon":        n,
                        },
                    )

    return None


def _try_route_team_schedule(q_orig: str, q_norm: str) -> "RouteResult | None":
    """Detect a single-team fixture schedule question.

    Handles three forms:
    1. Spanish prefix: "calendario del {team} [proximas N jornadas]"
    2. Schedule suffix/phrase: "{team} schedule [next N]"
    3. Known-team fixtures: "{known_team} fixtures [next N]"
       (alias dict guards against routing player-name fixture queries here)

    Returns ``RouteResult(tool_name="get_team_schedule",
    tool_args={"team_query": ..., "horizon": N})`` or ``None``.

    Must be called AFTER ``_try_route_team_calendar()`` so all-team ranking
    queries (which also contain team-related words) are not intercepted.
    Must be called BEFORE ``_try_route_fixture_run()`` so known team names
    like "Arsenal fixtures" are not misrouted to the player fixture tool.
    """
    n = _extract_n_games(q_norm)

    # 1. Spanish prefix "calendario del {team} ..."
    for prefix in _TEAM_SCHEDULE_SPANISH_PREFIXES:
        if q_norm.startswith(prefix):
            remainder = q_orig[len(prefix):].strip()
            # Trim at common Spanish continuation words
            for stop in ("próximas", "proximas", "jornadas", "semanas",
                         "siguiente", "las ", "los "):
                idx = remainder.lower().find(stop)
                if idx > 0:
                    remainder = remainder[:idx].strip().rstrip(",")
                    break
            if remainder:
                return RouteResult(
                    tool_name="get_team_schedule",
                    tool_args={"team_query": remainder, "horizon": n},
                )

    # 1b. "calendario de {team}" (M4 §7.3 disambiguation).
    #     "calendario de " (without "del") is ambiguous: may be a team or a player.
    #     Strategy:
    #       a) If remainder contains " del " (e.g. "los proximos 5 del City"),
    #          extract what follows "del " and treat as the team query — this
    #          mirrors how _TEAM_SCHEDULE_SPANISH_PREFIXES handles "calendario del ".
    #       b) Otherwise search the full remainder for a known team token.
    #          If found → team_schedule.  If not → fall through to fixture_run.
    #     Examples:
    #       "calendario de Arsenal"               → team_schedule (Arsenal is a team)
    #       "calendario de los proximos 5 del City" → team_schedule (del → City)
    #       "calendario de Haaland"               → player_fixture_run (no team)
    if q_norm.startswith(CALENDARIO_DE_PREFIX):
        remainder_norm = q_norm[len(CALENDARIO_DE_PREFIX):].strip()
        remainder_orig = q_orig[len(CALENDARIO_DE_PREFIX):].strip()
        # Path a: "... del {team}" — peel off the "del " segment and extract team.
        _del_marker = " del "
        del_idx = remainder_norm.find(_del_marker)
        if del_idx != -1:
            after_del_norm = remainder_norm[del_idx + len(_del_marker):].strip()
            after_del_orig = remainder_orig[del_idx + len(_del_marker):].strip()
            # Trim at common continuation words.
            for stop in ("próximas", "proximas", "próximos", "proximos",
                         "jornadas", "semanas", "partidos", "siguientes"):
                idx2 = after_del_norm.find(stop)
                if idx2 > 0:
                    after_del_orig = after_del_orig[:idx2].strip().rstrip(",")
                    break
            if after_del_orig:
                return RouteResult(
                    tool_name="get_team_schedule",
                    tool_args={"team_query": after_del_orig, "horizon": n},
                )
        # Path b: search the full remainder for a known registered team token.
        team_tok = _extract_team_token(remainder_norm)
        if team_tok:
            return RouteResult(
                tool_name="get_team_schedule",
                tool_args={"team_query": team_tok, "horizon": n},
            )
        # No known team → fall through; _try_route_fixture_run will handle
        # "calendario de {player}" using CALENDARIO_DE_PREFIX as a prefix.

    # 2. "schedule" keyword — unambiguous team intent marker.
    #    Match "{team} schedule [next N]" or "{team} upcoming schedule".
    #    Use endswith or " schedule next " to avoid matching
    #    "fixture schedule for X" (which starts with "fixture schedule").
    if q_norm.endswith(" schedule") or " schedule next " in q_norm:
        # Extract team as everything before " schedule"
        idx = q_norm.find(" schedule")
        team_part = q_orig[:idx].strip().rstrip(",") if idx > 0 else ""
        if team_part:
            return RouteResult(
                tool_name="get_team_schedule",
                tool_args={"team_query": team_part, "horizon": n},
            )

    # 3. "{known_team} fixtures [next N]" or "{known_team} upcoming [fixtures]"
    for alias_norm, team_query in _TEAM_SCHEDULE_KNOWN_NAMES:
        if (
            q_norm.startswith(alias_norm + " fixture")
            or q_norm.startswith(alias_norm + " upcoming")
            or q_norm == alias_norm
        ):
            return RouteResult(
                tool_name="get_team_schedule",
                tool_args={"team_query": team_query, "horizon": n},
            )

    return None


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
                    part_a = _strip_spanish_name_prefix(
                        remainder_orig[:idx].strip().rstrip(",")
                    )
                    part_b = _strip_spanish_name_prefix(
                        remainder_orig[idx + len(conn):].strip()
                    )
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
    # Note: "tengo a Saka" counts as 3 words — passes guard, then preposition
    # stripping normalises it to "Saka" before registry lookup.
    _BARE_CONN_MAX_WORDS = 3
    for conn in _BARE_COMPARE_CONNECTORS:
        idx = q_norm.find(conn)
        if idx != -1:
            part_a = _strip_spanish_name_prefix(q_orig[:idx].strip())
            part_b = _strip_spanish_name_prefix(q_orig[idx + len(conn):].strip().rstrip("?!."))
            if part_a and part_b and len(q_orig[:idx].strip().split()) <= _BARE_CONN_MAX_WORDS:
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

    # ── Position-filtered calendar intent (Phase 2.6e.4; BEFORE team-calendar so
    #    "{position} with best fixtures next N" is not swallowed by the team-calendar
    #    substring match "best fixtures next" which lives inside these queries)
    _pos_result = _try_route_position_fixture_run(q_orig, q_norm)
    if _pos_result is not None:
        return _pos_result

    # ── Team fixture calendar intent (Phase 2.6e; before gameweek + fixture-run)
    #    Must precede gameweek because phrases like "best fixtures next 5 gameweeks"
    #    contain the substring "gameweek".  Must precede fixture-run because
    #    questions ending in " fixtures" (e.g. "teams with worst upcoming fixtures")
    #    are caught by the fixture-run suffix matcher before reaching team calendar.
    _calendar_result = _try_route_team_calendar(q_norm)
    if _calendar_result is not None:
        return _calendar_result

    # ── Single-team schedule intent (Phase 2.6e.3; after team-calendar ranking,
    #    before fixture-run — known team names are caught here, not misrouted)
    _schedule_result = _try_route_team_schedule(q_orig, q_norm)
    if _schedule_result is not None:
        return _schedule_result

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

    # ── Transfer suggestion intent (Phase 2.6h; after transfer_advice, before
    #    fixture_run — "to buy" suffix guards against player-fixture collisions)
    _sugg_result = _try_route_transfer_suggestion(q_orig, q_norm)
    if _sugg_result is not None:
        return _sugg_result

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

    # ── Price changes intent (Phase 2.6d; before player summary) ────────────
    if any(kw in q_norm for kw in _PRICE_CHANGES_KEYWORDS):
        return RouteResult(tool_name="get_price_changes", tool_args={})

    # ── Injury list intent (Phase 2.6d; before player summary) ──────────────
    if any(kw in q_norm for kw in _INJURY_LIST_KEYWORDS):
        return RouteResult(tool_name="get_injury_list", tool_args={})

    # ── Player form intent (Phase 2.6d; before player summary) ──────────────
    _form_result = _try_route_player_form(q_orig, q_norm)
    if _form_result is not None:
        return _form_result

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
"""
fpl_grounded_assistant.intent_aliases
======================================
Phase M1 (MCP_architecture): Centralized Spanish<->English alias tables
for the six M1 @resources.

This module is the single source of truth for `@resource` name aliasing.
The decision_router consults this map to canonicalize user input like
`@lesionados` -> `injuries` (canonical resource key).

Design rules
------------
* Spanish-first per project memory: Spanish aliases come first, English
  aliases follow. Both are accepted.
* Aliases are case-folded and NFC-normalized before lookup.
* Aliases are RESOURCE names only — no entity-style shortcuts
  (`@palmer`, `@chelsea` are explicitly out of scope).
* Aliases for the seven slash-prompts (M2) are NOT included here —
  prompt aliases will live in `prompt_registry.py` in M2.

Public surface
--------------
* `RESOURCE_CANONICAL` — frozenset of the six canonical resource keys.
* `RESOURCE_ALIASES` — dict mapping every alias (lowercased, NFC) to its
  canonical key.
* `resolve_resource(name)` — return canonical key or None.
* `list_resources()` — return the six canonical keys in registration order.
"""
from __future__ import annotations

import unicodedata
from typing import Iterable

# ---------------------------------------------------------------------------
# Canonical resource keys (the six M1 resources)
# ---------------------------------------------------------------------------

INJURIES     = "injuries"
TOP_FORM     = "top_form"
TOP_XG       = "top_xg"
TOP_POINTS   = "top_points"
TOP_MINUTES  = "top_minutes"
POPULAR      = "popular"

RESOURCE_CANONICAL: frozenset[str] = frozenset({
    INJURIES, TOP_FORM, TOP_XG, TOP_POINTS, TOP_MINUTES, POPULAR,
})

# Registration order — used for `list_resources()` and `GET /resources`.
_RESOURCE_ORDER: tuple[str, ...] = (
    INJURIES, TOP_FORM, TOP_XG, TOP_POINTS, TOP_MINUTES, POPULAR,
)


# ---------------------------------------------------------------------------
# Alias tables (Spanish-first)
# ---------------------------------------------------------------------------

# Each canonical key maps to a tuple of accepted aliases. The canonical
# English key itself is also a valid alias (added programmatically below).
_RAW_ALIASES: dict[str, tuple[str, ...]] = {
    INJURIES: (
        # Spanish
        "lesionados", "lesiones", "bajas", "dudas",
        # English
        "injuries", "injured", "injury",
    ),
    TOP_FORM: (
        # Spanish
        "forma", "mejor_forma", "top_forma", "en_forma",
        # English
        "top_form", "form", "best_form",
    ),
    TOP_XG: (
        # Spanish
        "xg", "top_xg_es", "expectativa", "esperados",
        # English
        "top_xg", "xgi", "expected_goals", "expected_goal_involvements",
    ),
    TOP_POINTS: (
        # Spanish
        "puntos", "mejores_puntos", "top_puntos", "puntuacion",
        # English
        "top_points", "points", "best_points",
    ),
    TOP_MINUTES: (
        # Spanish
        "minutos", "mas_minutos", "top_minutos",
        # English
        "top_minutes", "minutes", "most_minutes",
    ),
    POPULAR: (
        # Spanish
        "populares", "mas_seleccionados", "mas_elegidos",
        # English
        "popular", "most_owned", "ownership", "top_owned",
    ),
}


def _nfc_fold(s: str) -> str:
    """Return *s* NFC-normalized, casefolded, with surrounding whitespace stripped."""
    return unicodedata.normalize("NFC", s).strip().casefold()


# Build forward map: alias (folded) -> canonical key.
RESOURCE_ALIASES: dict[str, str] = {}
for _canon, _aliases in _RAW_ALIASES.items():
    RESOURCE_ALIASES[_nfc_fold(_canon)] = _canon
    for _a in _aliases:
        RESOURCE_ALIASES[_nfc_fold(_a)] = _canon


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_resource(name: str) -> str | None:
    """Return the canonical resource key for *name*, or None if not registered.

    The input is NFC-normalized and casefolded before lookup. Leading `@`
    is stripped if present.
    """
    if not isinstance(name, str):
        return None
    cleaned = name.strip()
    if cleaned.startswith("@"):
        cleaned = cleaned[1:]
    folded = _nfc_fold(cleaned)
    if not folded:
        return None
    return RESOURCE_ALIASES.get(folded)


def list_resources() -> tuple[str, ...]:
    """Return the six canonical resource keys in stable registration order."""
    return _RESOURCE_ORDER


def all_aliases_for(canonical: str) -> Iterable[str]:
    """Return all accepted aliases (folded) for *canonical*."""
    return tuple(a for a, c in RESOURCE_ALIASES.items() if c == canonical)


# ---------------------------------------------------------------------------
# Router-intent aliases (M4 — Spanish Hardening)
# ---------------------------------------------------------------------------
# These are keyword/synonym tables that belong to the "alias" category:
# they are synonyms/paraphrases of a fixed concept used for keyword matching.
# They are imported by router.py so router.py can eliminate its local copies.
#
# Tables that are GRAMMATICAL SCAFFOLDING (prefix/suffix/connector patterns
# for sentence parsing) stay in router.py — see audit table in M4 report.
#
# Section 1: Transfer-advice Spanish extensions (M0 §7.1)
# --------------------------------------------------------

TRANSFER_SPANISH_PREFIXES: tuple[str, ...] = (
    # Spanish imperative / verb forms for selling / swapping out a player.
    # Added M4.  Router extends _TRANSFER_PREFIXES with these.
    "vendo",          # "I sell" — compact Spanish verb
    "saco a",         # "I take out [player]"
    "doy de baja a",  # "I unregister / remove [player]"
    "doy de baja",    # without accusative "a" stripped separately
    "cambio",         # "I swap/exchange"
    "véndele",        # "sell him [player]" — regional imperative (Spain/LatAm)
    "vendele",        # no accent variant
)

TRANSFER_SPANISH_CONNECTORS: tuple[str, ...] = (
    # Spanish connectors separating player_out from player_in.
    # Added M4.  Router extends _TRANSFER_CONNECTORS with these.
    # Ordered longest-first (per existing convention).
    " por el ",  # "for the" — e.g. "vendo Salah por el Palmer"
    " por ",     # "for" — e.g. "vendo Salah por Palmer"
)

# Section 2: Player-fixture-run Spanish extensions (M0 §7.2)
# -----------------------------------------------------------

FIXTURE_RUN_SPANISH_PREFIXES: tuple[str, ...] = (
    # Spanish prefix forms for player fixture-run queries.
    # Added M4.  Router extends _FIXTURE_RUN_PREFIXES with these.
    # NOTE: "calendario de " is deliberately excluded here because it is
    # ambiguous: "calendario de Arsenal" → team_schedule, "calendario de
    # Haaland" → player_fixture_run.  The disambiguation is handled in
    # _try_route_team_schedule / _try_route_fixture_run via _extract_team_token.
    # See Section 3 below and _try_route_fixture_run_spanish() in router.py.
    "próximos partidos de",    # "upcoming matches of"
    "proximos partidos de",    # no accent
    "siguientes partidos de",  # "following matches of"
    "próximas jornadas de",    # "upcoming gameweeks of"
    "proximas jornadas de",    # no accent
    "partidos de",             # "matches of" — shorter form
)

FIXTURE_RUN_SPANISH_SUFFIXES: tuple[str, ...] = (
    # Spanish suffix forms for player fixture-run queries.
    # Added M4.  Router extends _FIXTURE_RUN_SUFFIXES with these.
    # INTENTIONALLY EMPTY: " partidos" is too ambiguous as a suffix —
    # "en los últimos 3 partidos" ends with " partidos" but signals player_form.
    # " fixtures" is already in the English table.
    # Spanish player fixture-run coverage is handled via prefix forms only.
)

# Section 3: "calendario de X" disambiguation trigger prefix (M0 §7.3)
# ----------------------------------------------------------------------
# The prefix "calendario de " (without "del") is ambiguous:
#   "calendario de Arsenal" → team_schedule  (team name token found)
#   "calendario de Haaland" → player_fixture_run  (no team name token)
# This constant is used by _try_route_team_schedule (which runs before
# _try_route_fixture_run) and by _try_route_fixture_run as a prefix check,
# guarded by _extract_team_token.

CALENDARIO_DE_PREFIX: str = "calendario de "

# Section 4: Differential-picks Spanish synonyms (M0 §7.6)
# ----------------------------------------------------------

DIFFERENTIAL_SPANISH_KEYWORDS: tuple[str, ...] = (
    # Spanish synonyms for differential picks.  Added M4.
    # Router extends _DIFFERENTIAL_KEYWORDS with these.
    "diferenciales esta semana",  # longest first per convention
    "diferenciales para",
    "diferenciales",
)

# Section 5: Current-gameweek Spanish synonyms (M0 §7.5)
# -------------------------------------------------------

GAMEWEEK_SPANISH_KEYWORDS: tuple[str, ...] = (
    # Spanish phrasings for current gameweek queries.  Added M4.
    # Router extends _GAMEWEEK_KEYWORDS with these.
    "qué jornada es",    # "what gameweek is it"
    "que jornada es",    # no accent
    "en qué jornada estamos",  # "what gameweek are we on"
    "en que jornada estamos",  # no accent
    "en qué gw estamos",       # "what gw are we on"
    "en que gw estamos",       # no accent
    "qué jornada estamos",     # short form
    "que jornada estamos",     # no accent
    "jornada actual",          # "current gameweek"
    "jornada en curso",        # "gameweek in progress"
)


# ---------------------------------------------------------------------------
# Prompt name aliases (M2)
# ---------------------------------------------------------------------------
# Centralized prompt-name aliases. Authoritative table lives in
# prompt_registry.py (alongside the PromptSpec definitions); we re-export
# resolve_prompt() and list_prompts() here so external callers (UI, server,
# verifier scripts) have a single ``intent_aliases`` import for both
# resources and prompts. Argument-name aliases stay per-ArgSpec in
# prompt_registry.py — they are tied to the schema, not the prompt name.

def resolve_prompt(name: str) -> str | None:
    """Return the canonical prompt name for *name*, or None.

    Thin re-export of ``prompt_registry.resolve_prompt`` so callers can
    treat ``intent_aliases`` as the single alias entry point.
    """
    # Local import avoids a circular at module load (prompt_registry imports
    # from dispatcher, which imports harness, which imports nothing here).
    from .prompt_registry import resolve_prompt as _rp
    return _rp(name)


def list_prompt_names() -> tuple[str, ...]:
    from .prompt_registry import list_prompts as _lp
    return _lp()

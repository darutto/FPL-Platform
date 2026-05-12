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

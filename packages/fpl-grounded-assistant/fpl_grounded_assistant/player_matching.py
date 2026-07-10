"""
fpl_grounded_assistant.player_matching
======================================
Shared, accent-robust player name matcher: external (Understat-style) player
names → FPL bootstrap elements.

Extracted from the zonal card's exploiter enrichment
(``zonal_weakness_tool._enrich_exploiters``), where the join was an ad-hoc
exact ``first_name second_name`` / ``web_name`` lookup — it missed accented
names (``Estêvão``, ``João Pedro``, ``Jiménez``) whenever the two sources
disagreed on diacritics or casing. Any tool that needs to bridge an outside
data source's player names onto the bootstrap should use
``resolve_fpl_player`` rather than growing another private join.

Matching contract:
- Accent- and case-insensitive (NFKD decompose, strip combining marks,
  casefold, collapse whitespace) — same normalization family as
  ``find_players._normalize``.
- Tiered: full ``first_name second_name`` → ``web_name`` → ``second_name``.
- Never guesses: a query that normalizes to something matching MULTIPLE
  elements within a tier (e.g. a bare surname "Silva") returns ``None``.
- No fuzzy matching — an unmatched name is the caller's cue to degrade
  gracefully, not to gamble on the wrong player.
"""
from __future__ import annotations

import unicodedata
from typing import Any

__all__ = ["resolve_fpl_player"]


def _norm(text: str) -> str:
    """NFKD-decompose, drop combining diacritics, casefold, collapse spaces."""
    nfkd = unicodedata.normalize("NFKD", str(text or ""))
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


#: Sentinel marking a normalized key claimed by more than one element.
_AMBIGUOUS: Any = object()


def _index(
    elements: list[dict[str, Any]], key: "callable"
) -> dict[str, Any]:
    """Normalized-key → element index; colliding keys become ``_AMBIGUOUS``."""
    idx: dict[str, Any] = {}
    for el in elements:
        k = _norm(key(el))
        if not k:
            continue
        if k in idx:
            idx[k] = _AMBIGUOUS
        else:
            idx[k] = el
    return idx


def resolve_fpl_player(
    understat_name: str, bootstrap: dict[str, Any]
) -> "dict[str, Any] | None":
    """Resolve an external player name to its FPL bootstrap element.

    Tries, accent/case-normalized: full ``first_name second_name``, then
    ``web_name``, then ``second_name``. Within a tier, a name shared by
    several elements (multiple "Silva") is ambiguous → ``None``, never a
    guess. Returns the element dict (→ ``element_type`` for position,
    ``team`` for club) or ``None``.
    """
    q = _norm(understat_name)
    if not q:
        return None
    elements = (bootstrap or {}).get("elements") or []
    tiers = (
        lambda el: f"{el.get('first_name', '')} {el.get('second_name', '')}",
        lambda el: el.get("web_name", ""),
        lambda el: el.get("second_name", ""),
    )
    for key in tiers:
        hit = _index(elements, key).get(q)
        if hit is _AMBIGUOUS:
            return None
        if hit is not None:
            return hit
    return None

"""The free transfers a user states in their own words.

The public FPL API does not expose how many free transfers a manager has, so
``plan_to_sign`` takes the number from the caller. The model is supposed to pass
it when the user says it, and sometimes does not («tengo 3 cambios disponibles»
once produced a route priced as if there were one free transfer). This module
reads the number off the turn's text deterministically, so the answer never
depends on the model remembering.

A closed list of patterns, on the text folded by ``normalize_player_name``
(lower case, no accents, punctuation as a space). Every pattern needs the number
to sit next to a word that says these are FREE / available / left transfers, so
"3 cambios de posición", a price or "3 jugadores" never match. A text that states
two different numbers is ambiguous and gives nothing. Range 0-5 (FPL's cap).
"""
from __future__ import annotations

import re
from typing import Any

from fpl_player_registry import normalize_player_name

MAX_FREE_TRANSFERS = 5

_WORDS = {
    "zero": 0, "cero": 0, "no": 0, "ningun": 0, "ninguno": 0,
    "one": 1, "un": 1, "uno": 1, "una": 1,
    "two": 2, "dos": 2,
    "three": 3, "tres": 3,
    "four": 4, "cuatro": 4,
    "five": 5, "cinco": 5,
}
_N = r"(\d{1,2}|" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")"
_ES_NOUN_ANY = r"(?:cambios?|transferencias?|traspasos?|fichajes?)"
_ES_FREE = r"(?:gratis|gratuitos?|gratuitas?|libres?|disponibles?|sin coste|sin costo)"

#: Each pattern captures the number as group 1.
_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        # Spanish: «3 cambios gratis», «tengo 3 cambios disponibles», «3 transferencias libres»
        r"\b" + _N + r" " + _ES_NOUN_ANY + r" " + _ES_FREE + r"\b",
        # «me quedan 2 cambios», «me queda 1 cambio»
        r"\bme quedan? " + _N + r" " + _ES_NOUN_ANY + r"\b",
        # English: «2 free transfers», «3 free transfers available»
        r"\b" + _N + r" free (?:transfers?|moves|changes)\b",
        # «2 FTs», «1 FT»
        r"\b" + _N + r" fts?\b",
        # «3 transfers available», «2 transfers left»
        r"\b" + _N + r" (?:transfers?|moves) (?:available|left|remaining)\b",
    )
)


def _to_int(token: str) -> int | None:
    value = int(token) if token.isdigit() else _WORDS.get(token)
    if value is None or not 0 <= value <= MAX_FREE_TRANSFERS:
        return None
    return value


def extract_free_transfers(text: Any) -> int | None:
    """The free-transfer count *text* states, or ``None`` (absent, out of range, ambiguous)."""
    folded = normalize_player_name(text)
    if not folded or len(folded) > 600:
        return None
    found: set[int | None] = set()
    for pattern in _PATTERNS:
        for match in pattern.finditer(folded):
            found.add(_to_int(match.group(1)))
    if len(found) != 1:
        return None
    return next(iter(found))

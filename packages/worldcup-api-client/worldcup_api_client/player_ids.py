"""
worldcup_api_client.player_ids
================================
Free-text player name -> ``players.json`` entry resolution.

Sibling of ``team_ids.resolve_squad_id``: the FIFA Fantasy ``players.json``
feed is the source of truth (``id``, ``firstName``, ``lastName``,
``knownName``) — there is no static name table to maintain here.

Matching is accent-insensitive (``unicodedata`` strips diacritics) so
"Mbappe" matches "Mbappé". Tries, in order: (1) exact match on ``knownName``,
"first last", or ``lastName``; (2) a shared whitespace-token of length >= 3
(e.g. "Mbappe" vs "Kylian Mbappe"); (3) the query as a substring of one of
those forms, for queries of length >= 4 (e.g. "Mbap" -> "Mbappe"). The
first candidate (feed order) wins ties; raises ``UnknownPlayerError`` when
nothing matches.
"""
from __future__ import annotations

import unicodedata


class UnknownPlayerError(Exception):
    """Raised by ``resolve_player`` for a name not found in ``players.json``."""


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return value.strip().lower()


def _candidate_names(player: dict) -> list[str]:
    known = player.get("knownName") or ""
    first = player.get("firstName") or ""
    last = player.get("lastName") or ""
    full = f"{first} {last}".strip()
    names = [n for n in (known, full, last) if n]
    return [_normalize(n) for n in names]


def resolve_player(name: str, players: list[dict]) -> dict:
    """Resolve a free-text player name to its ``players.json`` entry.

    Raises ``UnknownPlayerError`` for names with no exact or substring match.
    """
    key = _normalize(name)
    if not key:
        raise UnknownPlayerError(f"unknown player: {name!r}")

    # Pass 1: exact match on knownName / "first last" / lastName.
    for player in players:
        if key in _candidate_names(player):
            return player

    # Pass 2: shared whitespace-token of length >= 3 (e.g. "Mbappe" vs
    # "Kylian Mbappe").
    key_tokens = {t for t in key.split() if len(t) >= 3}
    if key_tokens:
        for player in players:
            for candidate in _candidate_names(player):
                if key_tokens & set(candidate.split()):
                    return player

    # Pass 3: the query is a substring of a candidate name (e.g. "Mbap" ->
    # "Mbappe"). Only the query-in-candidate direction is checked, and only
    # for queries of meaningful length, so short surnames can't false-match
    # against arbitrary long input.
    if len(key) >= 4:
        for player in players:
            for candidate in _candidate_names(player):
                if key in candidate:
                    return player

    raise UnknownPlayerError(f"unknown player: {name!r}")

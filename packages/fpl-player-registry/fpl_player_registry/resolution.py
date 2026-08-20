"""Canonical, collision-safe FPL player-name resolution.

The registry's historical lookup helpers intentionally have narrow and partly
different semantics.  This module provides the one ranked resolution contract
used by chat-facing tools: IDs, aliases, canonical names, prefixes, and (when
explicitly enabled by the caller) substrings.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

from .nicknames import KNOWN_NICKNAMES
from .registry import PlayerRecord, build_registry


_SPECIAL_CHAR_MAP: dict[int, str] = str.maketrans({
    ord("ø"): "o",
    ord("Ø"): "o",
    ord("æ"): "ae",
    ord("Æ"): "ae",
    ord("ß"): "ss",
})
_DASHES = frozenset("-‐‑‒–—―−")
_APOSTROPHES = frozenset("'’‘ʼ`")
_VIA_PRIORITY = {
    "id": 0,
    "web_name": 1,
    "exact_name": 2,
    "alias": 3,
    "compound_name": 4,
    "prefix": 5,
    "substring": 6,
}

#: Rank tiers, strongest first.  ``best_matches`` only ever returns one tier,
#: so a weaker tier can never make a stronger one ambiguous.
RANK_EXACT: int = 0
RANK_COMPOUND: int = 1
RANK_PREFIX: int = 2
RANK_SUBSTRING: int = 3

#: Highest rank a single-player caller may auto-resolve without asking the
#: user.  Substring matches stay wizard candidates even when unique.
RANK_AUTO_RESOLVE_MAX: int = RANK_PREFIX


def normalize_player_name(value: Any) -> str:
    """Return the canonical comparison form for a player-name value.

    Accents and casing are folded, dash variants become spaces, apostrophes
    are removed (``N'Golo`` equals ``Ngolo``), punctuation becomes a boundary,
    and repeated whitespace is collapsed.
    """
    text = str(value or "").translate(_SPECIAL_CHAR_MAP)
    decomposed = unicodedata.normalize("NFKD", text)
    out: list[str] = []
    for char in decomposed:
        if unicodedata.combining(char):
            continue
        if char in _APOSTROPHES:
            continue
        if char in _DASHES:
            out.append(" ")
            continue
        category = unicodedata.category(char)
        if category.startswith(("L", "N")):
            out.append(char.casefold())
        else:
            out.append(" ")
    return " ".join("".join(out).split())


@dataclass(frozen=True)
class PlayerMatch:
    """One ranked canonical player match."""

    record: PlayerRecord
    rank: int
    matched_via: str
    total_points: int = 0


@dataclass(frozen=True)
class PlayerResolution:
    """Ranked resolution result.  ``best_matches`` drives single-player tools."""

    query: str
    matches: tuple[PlayerMatch, ...]

    @property
    def best_matches(self) -> tuple[PlayerMatch, ...]:
        if not self.matches:
            return ()
        best_rank = self.matches[0].rank
        return tuple(match for match in self.matches if match.rank == best_rank)

    @property
    def status(self) -> str:
        count = len(self.best_matches)
        if count == 0:
            return "not_found"
        return "ok" if count == 1 else "ambiguous"

    @property
    def player(self) -> PlayerMatch | None:
        best = self.best_matches
        return best[0] if len(best) == 1 else None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _team_id_by_short(teams: Iterable[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for team in teams:
        team_id = team.get("id")
        short = normalize_player_name(team.get("short_name"))
        if short and team_id is not None:
            result[short] = _safe_int(team_id)
    return result


def compound_name_forms(first: str, second: str) -> set[str]:
    """Everyday name forms for a player whose FPL surname is compound.

    FPL stores the legal name (``Bruno`` + ``Borges Fernandes``) but people
    type the everyday one (``Bruno Fernandes``).  The everyday form keeps the
    given name and drops *leading* components of the surname, so generate
    exactly those suffixes rather than arbitrary word pairs::

        Bruno   + Borges Fernandes           -> bruno fernandes
        Gabriel + dos Santos Magalhaes       -> gabriel santos magalhaes
                                                gabriel magalhaes
        Matheus + Santos Carneiro da Cunha   -> matheus carneiro da cunha
                                                matheus da cunha
                                                matheus cunha

    Working on suffixes keeps multi-word surname particles intact: ``Virgil``
    + ``van Dijk`` yields ``virgil dijk`` but never the nonsense ``virgil van``.

    A multi-word given name also contributes its first word alone, so
    ``Jan Paul`` + ``van Hecke`` reaches ``jan van hecke`` and ``jan hecke``.

    Both arguments must already be normalized by :func:`normalize_player_name`.
    Returns an empty set for simple surnames — ``"first second"`` is a
    canonical field there and needs no derived form.
    """
    surname_words = second.split()
    if not first or len(surname_words) < 2:
        return set()

    forms: set[str] = set()
    for start in range(1, len(surname_words)):
        forms.add(f"{first} {' '.join(surname_words[start:])}")

    given_words = first.split()
    if len(given_words) > 1:
        given = given_words[0]
        for start in range(len(surname_words)):
            forms.add(f"{given} {' '.join(surname_words[start:])}")

    return forms


def _alias_targets(
    players: list[dict[str, Any]],
    aliases: dict[str, list[str]],
) -> dict[str, set[int]]:
    """Build alias -> player IDs without ever overwriting a collision."""
    by_web: dict[str, set[int]] = {}
    by_first: dict[str, set[int]] = {}
    by_second: dict[str, set[int]] = {}
    for player in players:
        player_id = player.get("id")
        if player_id is None:
            continue
        pid = _safe_int(player_id)
        by_web.setdefault(normalize_player_name(player.get("web_name")), set()).add(pid)
        by_first.setdefault(normalize_player_name(player.get("first_name")), set()).add(pid)
        by_second.setdefault(normalize_player_name(player.get("second_name")), set()).add(pid)

    index: dict[str, set[int]] = {}
    for configured_name, configured_aliases in aliases.items():
        key = normalize_player_name(configured_name)
        targets = set(by_web.get(key, set()))
        if not targets:
            targets.update(by_second.get(key, set()))
            targets.update(by_first.get(key, set()))
        if not targets:
            continue
        for alias in configured_aliases:
            alias_key = normalize_player_name(alias)
            if not alias_key:
                continue
            index.setdefault(alias_key, set()).update(targets)
            stripped = alias_key.removeprefix("el ").strip()
            if stripped and stripped != alias_key:
                index.setdefault(stripped, set()).update(targets)
    return index


def resolve_player_candidates(
    query: str | int,
    players: list[dict[str, Any]],
    teams: list[dict[str, Any]],
    *,
    allow_prefix: bool = True,
    allow_substring: bool = False,
    team_hint: str | None = None,
    aliases: dict[str, list[str]] | None = None,
) -> PlayerResolution:
    """Resolve *query* to ranked candidates with collision-safe ambiguity.

    All matches are returned in rank order so discovery callers can retain
    their list behavior.  Single-player callers must consume ``best_matches``.
    """
    normalized_query = normalize_player_name(query)
    if not normalized_query:
        return PlayerResolution(query=normalized_query, matches=())

    registry = build_registry(players, teams)
    raw_by_id = {
        _safe_int(player.get("id")): player
        for player in players
        if player.get("id") is not None
    }

    # IDs are season-local but authoritative and can never be ambiguous.
    try:
        numeric_id = int(str(query).strip())
    except (TypeError, ValueError):
        numeric_id = None
    if numeric_id is not None:
        record = registry.lookup_by_id(numeric_id)
        if record is None:
            return PlayerResolution(query=normalized_query, matches=())
        raw = raw_by_id.get(record.id, {})
        return PlayerResolution(
            query=normalized_query,
            matches=(PlayerMatch(record, RANK_EXACT, "id", _safe_int(raw.get("total_points"))),),
        )

    team_id: int | None = None
    if team_hint:
        team_id = _team_id_by_short(teams).get(normalize_player_name(team_hint))

    alias_index = _alias_targets(players, aliases if aliases is not None else KNOWN_NICKNAMES)
    candidates: dict[int, tuple[int, str]] = {}

    def add(player_id: int, rank: int, via: str) -> None:
        raw = raw_by_id.get(player_id)
        if raw is None or (team_id is not None and _safe_int(raw.get("team") or raw.get("team_id")) != team_id):
            return
        previous = candidates.get(player_id)
        if (
            previous is None
            or rank < previous[0]
            or (
                rank == previous[0]
                and _VIA_PRIORITY[via] < _VIA_PRIORITY[previous[1]]
            )
        ):
            candidates[player_id] = (rank, via)

    for player_id in alias_index.get(normalized_query, set()):
        add(player_id, RANK_EXACT, "alias")

    for player in players:
        player_id_raw = player.get("id")
        if player_id_raw is None:
            continue
        player_id = _safe_int(player_id_raw)
        first = normalize_player_name(player.get("first_name"))
        second = normalize_player_name(player.get("second_name"))
        web = normalize_player_name(player.get("web_name"))
        full = " ".join(part for part in (first, second) if part)
        fields = tuple(field for field in (web, first, second, full) if field)

        if normalized_query == web:
            add(player_id, RANK_EXACT, "web_name")
        elif normalized_query in fields:
            add(player_id, RANK_EXACT, "exact_name")
        elif normalized_query in compound_name_forms(first, second):
            add(player_id, RANK_COMPOUND, "compound_name")
        elif allow_prefix and any(field.startswith(normalized_query) for field in fields):
            add(player_id, RANK_PREFIX, "prefix")
        elif allow_substring and any(normalized_query in field for field in fields):
            add(player_id, RANK_SUBSTRING, "substring")

    ranked: list[PlayerMatch] = []
    for player_id, (rank, via) in candidates.items():
        record = registry.lookup_by_id(player_id)
        if record is None:
            continue
        raw = raw_by_id.get(player_id, {})
        ranked.append(PlayerMatch(record, rank, via, _safe_int(raw.get("total_points"))))
    ranked.sort(key=lambda match: (match.rank, -match.total_points, match.record.id))
    return PlayerResolution(query=normalized_query, matches=tuple(ranked))


__all__ = [
    "PlayerMatch",
    "PlayerResolution",
    "RANK_AUTO_RESOLVE_MAX",
    "RANK_COMPOUND",
    "RANK_EXACT",
    "RANK_PREFIX",
    "RANK_SUBSTRING",
    "compound_name_forms",
    "normalize_player_name",
    "resolve_player_candidates",
]

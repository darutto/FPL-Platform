"""
worldcup_api_client.team_ids
=============================
English-team-name -> FIFA Fantasy ``squadId`` (1-48) resolution.

The FIFA Fantasy feed (``squads.json``) is the source of truth for squad ids
and names — there is no static table to maintain here. ``resolve_squad_id``
takes the live squads list (already fetched/cached by ``wc_client``) and
matches a caller-supplied English team name against it.

Matching is accent-insensitive (``unicodedata`` strips diacritics) so
"Curacao" matches "Curaçao" and "Cote d'Ivoire" matches "Côte d'Ivoire"
without needing every accented variant spelled out. ``_ALIASES`` covers names
that differ structurally (not just by accents) from the FIFA Fantasy squad
name, e.g. "Ivory Coast" -> "Côte d'Ivoire", "South Korea" -> "Korea
Republic", "Iran" -> "IR Iran".
"""
from __future__ import annotations

import unicodedata


class UnknownTeamError(Exception):
    """Raised by ``resolve_squad_id`` for a name not found in ``squads.json``."""


#: Alternate/English-common names -> normalized FIFA Fantasy squad name.
_ALIASES: dict[str, str] = {
    "ivory coast": "cote d'ivoire",
    "cote d'ivoire": "cote d'ivoire",
    "côte d'ivoire": "cote d'ivoire",
    "cape verde": "cabo verde",
    "iran": "ir iran",
    "south korea": "korea republic",
    "republic of korea": "korea republic",
    "turkey": "turkiye",
    "czech republic": "czechia",
    "dr congo": "congo dr",
    "democratic republic of the congo": "congo dr",
    "congo": "congo dr",
    "united states": "usa",
    "united states of america": "usa",
    "us": "usa",
    "bosnia": "bosnia and herzegovina",
    "bosnia & herzegovina": "bosnia and herzegovina",
    "saudi": "saudi arabia",
}


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return value.strip().lower()


def resolve_squad_id(team: str, squads: list[dict]) -> int:
    """Resolve an English team name to its FIFA Fantasy ``squadId`` (1-48).

    ``squads`` is the parsed ``squads.json`` list (each entry has ``id``,
    ``name``, ``group``, ``abbr``). Matching is accent- and case-insensitive,
    with ``_ALIASES`` covering structurally-different common names. Raises
    ``UnknownTeamError`` (caught by the tools layer and turned into a
    ``{"status": "error"}`` result) for unrecognised names.
    """
    key = _normalize(team)
    key = _ALIASES.get(key, key)
    abbr_key = team.strip().upper()
    for squad in squads:
        if _normalize(squad["name"]) == key:
            return squad["id"]
        if squad.get("abbr", "").upper() == abbr_key:
            return squad["id"]
    raise UnknownTeamError(f"unknown team: {team!r}")

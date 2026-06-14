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
Republic", "Iran" -> "IR Iran". ``_ES_ALIASES`` covers the same kind of
structural difference for Spanish team names (e.g. "Marruecos" -> "Morocco",
"Catar" -> "Qatar") so resolution works even if the LLM passes the user's
Spanish team name through unchanged.
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

#: Spanish team names -> normalized FIFA Fantasy squad name. The tool
#: contract asks the LLM to translate Spanish input to the English FIFA name
#: before calling (see ``_TEAM_PROP`` in worldcup_assistant.tools), but that
#: translation is unreliable for an LLM under load — and a wrong/untranslated
#: name raises ``UnknownTeamError``, silently dropping the matching card (see
#: the 2026-06-13 /historial bug: "Brasil"/"Marruecos"/"Catar"/"Suiza" all
#: failed resolution). Resolving Spanish names here directly removes that
#: dependency entirely. Only entries that differ from the English name by
#: more than accents are needed — plain accent differences (e.g. "México" /
#: "Canadá" / "Panamá") are already handled by ``_normalize``.
_ES_ALIASES: dict[str, str] = {
    "argelia": "algeria",
    "belgica": "belgium",
    "bosnia y herzegovina": "bosnia and herzegovina",
    "brasil": "brazil",
    "rd del congo": "congo dr",
    "republica democratica del congo": "congo dr",
    "costa de marfil": "cote d'ivoire",
    "croacia": "croatia",
    "curazao": "curacao",
    "chequia": "czechia",
    "republica checa": "czechia",
    "egipto": "egypt",
    "inglaterra": "england",
    "francia": "france",
    "alemania": "germany",
    "irak": "iraq",
    "japon": "japan",
    "jordania": "jordan",
    "corea del sur": "korea republic",
    "marruecos": "morocco",
    "paises bajos": "netherlands",
    "holanda": "netherlands",
    "nueva zelanda": "new zealand",
    "noruega": "norway",
    "catar": "qatar",
    "arabia saudita": "saudi arabia",
    "arabia saudi": "saudi arabia",
    "escocia": "scotland",
    "sudafrica": "south africa",
    "espana": "spain",
    "suecia": "sweden",
    "suiza": "switzerland",
    "tunez": "tunisia",
    "turquia": "turkiye",
    "estados unidos": "usa",
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
    key = _ALIASES.get(key, _ES_ALIASES.get(key, key))
    abbr_key = team.strip().upper()
    for squad in squads:
        if _normalize(squad["name"]) == key:
            return squad["id"]
        if squad.get("abbr", "").upper() == abbr_key:
            return squad["id"]
    raise UnknownTeamError(f"unknown team: {team!r}")

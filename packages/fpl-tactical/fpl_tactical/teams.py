"""
fpl_tactical.teams
==================
Team-name bridges for the StrikerAPI source.

The store (and every zonal lookup) names clubs the way Understat did
("Manchester City", "Tottenham", "Coventry"), so StrikerAPI's abbreviations
and FPL's short names are translated to those exact strings at ingest. An
unmapped code fails the run: a new club must be added here on purpose.
"""

from __future__ import annotations

#: StrikerAPI ``abbrev`` -> store team name. Note MNC / MAN (FPL: MCI / MUN).
API_CODE_TO_STORE: dict[str, str] = {
    "ARS": "Arsenal",
    "AVL": "Aston Villa",
    "BHA": "Brighton",
    "BOU": "Bournemouth",
    "BRE": "Brentford",
    "CHE": "Chelsea",
    "COV": "Coventry",
    "CRY": "Crystal Palace",
    "EVE": "Everton",
    "FUL": "Fulham",
    "HUL": "Hull",
    "IPS": "Ipswich",
    "LEE": "Leeds",
    "LIV": "Liverpool",
    "MAN": "Manchester United",
    "MNC": "Manchester City",
    "NEW": "Newcastle United",
    "NFO": "Nottingham Forest",
    "SUN": "Sunderland",
    "TOT": "Tottenham",
}

#: FPL bootstrap ``short_name`` -> store team name (same targets).
FPL_SHORT_TO_STORE: dict[str, str] = {
    **{k: v for k, v in API_CODE_TO_STORE.items() if k not in ("MAN", "MNC")},
    "MUN": "Manchester United",
    "MCI": "Manchester City",
}


def store_name_from_api(code: str) -> str:
    try:
        return API_CODE_TO_STORE[code]
    except KeyError:
        raise KeyError(f"StrikerAPI team code {code!r} is not mapped in fpl_tactical.teams") from None


def store_name_from_fpl(short: str) -> str:
    try:
        return FPL_SHORT_TO_STORE[short]
    except KeyError:
        raise KeyError(f"FPL team short name {short!r} is not mapped in fpl_tactical.teams") from None

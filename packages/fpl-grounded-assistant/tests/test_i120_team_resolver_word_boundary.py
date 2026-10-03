"""i120 — the team resolver's last tier no longer accepts any substring.

``_resolve_team_result``'s fourth tier was ``q in name``: "tal" (from
"¿qué tal pinta…?") resolved to Crystal Palace, "ham" to Fulham, "ton" to a
three-way ambiguity — the query never named any of them. The tier now needs
a word-anchored match of at least 3 characters (a whole word below 4, a word
prefix from 4 up).

Two halves, both pinned against the 20 clubs of the live 2026-27 bootstrap:

* what still resolves — every club by name, by short_name, by every alias
  that targets it, plus the partial forms the tier exists for;
* what stops resolving — the fragments the old tier silently accepted.

Pure function, no provider and no network on any path.
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.team_fixture_calendar import (
    _TEAM_RESOLVE_ALIASES,
    _resolve_team_result,
)

# The 20 clubs of the live FPL bootstrap, 2026-27 (fetched 2026-10-03, GW5).
_TEAMS_2026_27 = [
    (1, "ARS", "Arsenal"),
    (2, "AVL", "Aston Villa"),
    (3, "BOU", "Bournemouth"),
    (4, "BRE", "Brentford"),
    (5, "BHA", "Brighton"),
    (6, "CHE", "Chelsea"),
    (7, "COV", "Coventry City"),
    (8, "CRY", "Crystal Palace"),
    (9, "EVE", "Everton"),
    (10, "FUL", "Fulham"),
    (11, "HUL", "Hull City"),
    (12, "IPS", "Ipswich Town"),
    (13, "LEE", "Leeds"),
    (14, "LIV", "Liverpool"),
    (15, "MCI", "Man City"),
    (16, "MUN", "Man Utd"),
    (17, "NEW", "Newcastle"),
    (18, "NFO", "Nott'm Forest"),
    (19, "TOT", "Spurs"),
    (20, "SUN", "Sunderland"),
]

BOOTSTRAP = {
    "teams": [
        {"id": i, "short_name": short, "name": name}
        for i, short, name in _TEAMS_2026_27
    ]
}
_SHORTS = {short for _, short, _ in _TEAMS_2026_27}


def _outcome(query: str) -> str:
    res = _resolve_team_result(query, BOOTSTRAP)
    if res["status"] == "ok":
        return res["team_data"]["short_name"]
    if res["status"] == "ambiguous":
        return "ambiguous:" + ",".join(sorted(c["short_name"] for c in res["candidates"]))
    return res["status"]


# ---------------------------------------------------------------------------
# What still resolves
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("short,name", [(s, n) for _, s, n in _TEAMS_2026_27])
def test_every_club_resolves_by_name_and_short_name(short, name):
    for query in (name, name.lower(), name.upper(), short, short.lower()):
        assert _outcome(query) == short, query


_ALIASES_IN_SEASON = sorted(
    (alias, code.upper())
    for alias, code in _TEAM_RESOLVE_ALIASES.items()
    if code.upper() in _SHORTS
)


def test_alias_list_covers_the_season():
    # Guard the parametrisation below against silently shrinking.
    assert len(_ALIASES_IN_SEASON) >= 25


@pytest.mark.parametrize("alias,short", _ALIASES_IN_SEASON)
def test_every_in_season_alias_resolves(alias, short):
    assert _outcome(alias) == short


@pytest.mark.parametrize(
    "query,expected",
    [
        # whole words, any length >= 3
        ("man", "ambiguous:MCI,MUN"),
        ("city", "ambiguous:COV,HUL,MCI"),
        ("utd", "MUN"),
        ("town", "IPS"),
        ("hull", "HUL"),
        ("crystal", "CRY"),
        ("coventry", "COV"),
        # word prefixes from 4 characters
        ("liver", "LIV"),
        ("sunder", "SUN"),
        ("crystal pal", "CRY"),
        ("nott", "NFO"),            # apostrophe is a word boundary
        ("ipsw", "IPS"),
    ],
)
def test_word_anchored_partials_still_resolve(query, expected):
    assert _outcome(query) == expected


# ---------------------------------------------------------------------------
# What stops resolving
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "query,was",
    [
        # the card's three
        ("tal", "CRY"),                       # «¿qué tal…?» → Crystal Palace
        ("ham", "FUL"),                       # Fulham, while West Ham is not in the league
        ("ton", "ambiguous:AVL,BHA,EVE"),
        # mid-word fragments
        ("pool", "LIV"),
        ("castle", "NEW"),
        ("ford", "BRE"),
        ("land", "SUN"),
        ("mouth", "BOU"),
        ("est", "NFO"),
        ("sea", "CHE"),
        # word-start fragments shorter than 4 that are not a whole word
        ("pal", "CRY"),
        ("bri", "BHA"),
        ("not", "NFO"),
        ("spu", "TOT"),
        ("vil", "AVL"),
        # one and two characters
        ("sp", "TOT"),
        ("li", "LIV"),
        ("m", "ambiguous:BOU,FUL,MCI,MUN,NFO"),
    ],
)
def test_fragments_the_old_tier_accepted_now_fail(query, was):
    # ``was`` documents the old outcome (measured against origin/main on the
    # live bootstrap); the assertion is that it is gone.
    assert _outcome(query) == "not_found", f"{query!r} used to give {was}"

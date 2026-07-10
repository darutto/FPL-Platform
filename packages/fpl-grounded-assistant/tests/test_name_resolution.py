"""
Tests for the name-resolution fix (fix/name-resolution).

Part A — team resolver (``team_fixture_calendar._resolve_team``):
the old ``_TEAM_RESOLVE_ALIASES`` mapped nicknames to long names absent
from the real FPL bootstrap ("man city" → "manchester city"), dead-ending
the natural abbreviated names across every team tool. Aliases now target
short_name codes. The 20-team regression fixture below uses the REAL
2025-26 FPL display names + codes (pinned from the live bootstrap
2026-07-09), so a season rollover with a new team whose alias/code is
missing fails loudly here.

Part B — shared player matcher (``player_matching.resolve_fpl_player``):
accent/case-robust Understat-name → FPL-element join (full name →
web_name → second_name; ambiguous → None), now backing the zonal card's
exploiter enrichment.
"""
from __future__ import annotations

import os as _os
import sys as _sys

import pytest

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG = _os.path.dirname(_HERE)
_PKGS = _os.path.dirname(_PKG)
for _p in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

from fpl_grounded_assistant.player_matching import resolve_fpl_player  # noqa: E402
from fpl_grounded_assistant.team_fixture_calendar import (  # noqa: E402
    _TEAM_RESOLVE_ALIASES,
    _resolve_team,
)
from fpl_grounded_assistant.zonal_weakness_tool import (  # noqa: E402
    _SHORT_TO_UNDERSTAT,
)

# ---------------------------------------------------------------------------
# Part A fixture — the REAL current 20 PL teams as the FPL bootstrap names
# them (display name, not the formal club name), pinned from the live
# bootstrap-static feed on 2026-07-09.
# ---------------------------------------------------------------------------

#: (FPL display name, short_name code, a common nickname/abbreviation).
CURRENT_PL_TEAMS: tuple[tuple[str, str, str], ...] = (
    ("Arsenal",        "ARS", "Gunners"),
    ("Aston Villa",    "AVL", "Villa"),
    ("Burnley",        "BUR", "burnley"),
    ("Bournemouth",    "BOU", "Cherries"),
    ("Brentford",      "BRE", "brentford"),
    ("Brighton",       "BHA", "Brighton & Hove Albion"),
    ("Chelsea",        "CHE", "chelsea"),
    ("Crystal Palace", "CRY", "Palace"),
    ("Everton",        "EVE", "Toffees"),
    ("Fulham",         "FUL", "fulham"),
    ("Leeds",          "LEE", "Leeds United"),
    ("Liverpool",      "LIV", "liverpool"),
    ("Man City",       "MCI", "Manchester City"),
    ("Man Utd",        "MUN", "Manchester United"),
    ("Newcastle",      "NEW", "Newcastle United"),
    ("Nott'm Forest",  "NFO", "Forest"),
    ("Sunderland",     "SUN", "sunderland"),
    ("Spurs",          "TOT", "Tottenham"),
    ("West Ham",       "WHU", "Hammers"),
    ("Wolves",         "WOL", "Wolverhampton"),
)

REAL_BOOTSTRAP: dict = {
    "teams": [
        {"id": i + 1, "name": name, "short_name": code}
        for i, (name, code, _nick) in enumerate(CURRENT_PL_TEAMS)
    ],
}


# ---------------------------------------------------------------------------
# Part A — every current team resolves from all three input forms
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "form_idx, form_label", [(0, "display name"), (1, "code"), (2, "nickname")]
)
@pytest.mark.parametrize("name, code, nick", CURRENT_PL_TEAMS)
def test_all_teams_resolve_three_ways(name, code, nick, form_idx, form_label):
    query = (name, code, nick)[form_idx]
    team = _resolve_team(query, REAL_BOOTSTRAP)
    assert team is not None, (
        f"{form_label} {query!r} failed to resolve — season rollover missing "
        f"an alias/code, or the resolver regressed?"
    )
    assert team["short_name"] == code, (
        f"{form_label} {query!r} resolved to {team['short_name']}, expected {code}"
    )


def test_resolution_is_case_insensitive():
    assert _resolve_team("man utd", REAL_BOOTSTRAP)["short_name"] == "MUN"
    assert _resolve_team("SPURS", REAL_BOOTSTRAP)["short_name"] == "TOT"
    assert _resolve_team("mci", REAL_BOOTSTRAP)["short_name"] == "MCI"


def test_previously_dead_display_names_now_resolve():
    """The exact five FPL display names the old alias map dead-ended."""
    for query, code in [
        ("Man City", "MCI"), ("Man Utd", "MUN"), ("Spurs", "TOT"),
        ("Wolves", "WOL"), ("Nott'm Forest", "NFO"),
    ]:
        team = _resolve_team(query, REAL_BOOTSTRAP)
        assert team is not None and team["short_name"] == code, query


def test_ambiguous_substring_returns_none():
    # "man" is a substring of both "Man City" and "Man Utd" — must not
    # silently pick the first.
    assert _resolve_team("man", REAL_BOOTSTRAP) is None


def test_unambiguous_substring_still_resolves():
    assert _resolve_team("sunder", REAL_BOOTSTRAP)["short_name"] == "SUN"


def test_unknown_and_empty_queries_return_none():
    assert _resolve_team("Real Madrid", REAL_BOOTSTRAP) is None
    assert _resolve_team("", REAL_BOOTSTRAP) is None
    assert _resolve_team("   ", REAL_BOOTSTRAP) is None


def test_alias_for_absent_team_returns_none():
    # "saints" → SOU: kept for when Southampton return, but the code is not
    # in the current bootstrap — must be a clean None, not a substring guess.
    assert "saints" in _TEAM_RESOLVE_ALIASES
    assert _resolve_team("saints", REAL_BOOTSTRAP) is None


def test_alias_targets_are_short_codes():
    """Every alias targets a lowercase <=4-char code, never a long name —
    the exact defect class this fix removes."""
    for alias, target in _TEAM_RESOLVE_ALIASES.items():
        assert target == target.lower(), alias
        assert len(target) <= 4 and " " not in target, (
            f"alias {alias!r} targets {target!r} — must be a short_name code"
        )


def test_understat_bridge_covers_all_current_teams():
    """Companion guard: the code→store-name bridge must have an entry for
    every current team short_name so no team silently drops out of the
    tactical tools. Fails loudly on season rollover."""
    missing = [
        code for _name, code, _nick in CURRENT_PL_TEAMS
        if code not in _SHORT_TO_UNDERSTAT
    ]
    assert missing == [], f"_SHORT_TO_UNDERSTAT missing entries: {missing}"


# ---------------------------------------------------------------------------
# Part B — shared player matcher
# ---------------------------------------------------------------------------

PLAYER_BOOTSTRAP: dict = {
    "elements": [
        {"id": 1, "first_name": "Bukayo", "second_name": "Saka",
         "web_name": "Saka", "element_type": 3, "team": 1},
        {"id": 2, "first_name": "Estêvão", "second_name": "Willian",
         "web_name": "Estêvão", "element_type": 3, "team": 7},
        {"id": 3, "first_name": "João Pedro", "second_name": "Junqueira de Jesus",
         "web_name": "João Pedro", "element_type": 4, "team": 7},
        {"id": 4, "first_name": "Raúl", "second_name": "Jiménez",
         "web_name": "Jiménez", "element_type": 4, "team": 10},
        {"id": 5, "first_name": "Bernardo", "second_name": "Silva",
         "web_name": "B.Silva", "element_type": 3, "team": 13},
        {"id": 6, "first_name": "Fabio", "second_name": "Silva",
         "web_name": "Fab.Silva", "element_type": 4, "team": 20},
    ],
}


def test_matched_full_name():
    el = resolve_fpl_player("Bukayo Saka", PLAYER_BOOTSTRAP)
    assert el is not None and el["id"] == 1


def test_matched_web_name_fallback():
    el = resolve_fpl_player("Saka", PLAYER_BOOTSTRAP)
    assert el is not None and el["id"] == 1


def test_accented_names_match_without_accents():
    # Understat often strips or alters diacritics — both directions must work.
    assert resolve_fpl_player("Estevao", PLAYER_BOOTSTRAP)["id"] == 2
    assert resolve_fpl_player("ESTÊVÃO", PLAYER_BOOTSTRAP)["id"] == 2
    assert resolve_fpl_player("Joao Pedro", PLAYER_BOOTSTRAP)["id"] == 3
    assert resolve_fpl_player("Raul Jimenez", PLAYER_BOOTSTRAP)["id"] == 4
    assert resolve_fpl_player("jimenez", PLAYER_BOOTSTRAP)["id"] == 4


def test_ambiguous_surname_returns_none():
    # Two Silvas: a bare surname must never guess.
    assert resolve_fpl_player("Silva", PLAYER_BOOTSTRAP) is None


def test_ambiguous_surname_full_name_still_resolves():
    assert resolve_fpl_player("Bernardo Silva", PLAYER_BOOTSTRAP)["id"] == 5
    assert resolve_fpl_player("Fabio Silva", PLAYER_BOOTSTRAP)["id"] == 6


def test_unmatched_and_empty_return_none():
    assert resolve_fpl_player("Lionel Messi", PLAYER_BOOTSTRAP) is None
    assert resolve_fpl_player("", PLAYER_BOOTSTRAP) is None
    assert resolve_fpl_player("Saka", {}) is None
    assert resolve_fpl_player("Saka", None) is None

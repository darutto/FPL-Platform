"""
Tests for hyphen-insensitive and abbreviation/nickname player-name matching.

Two classes of user error the chat must tolerate for both name tools
(find_players and get_player_snapshot — the LLM picks either):

  * dropped hyphen: "calvert lewin" must resolve "Calvert-Lewin"
    (and "gibbs white" -> "Gibbs-White"), via _normalize (dash -> space).
  * community abbreviation / initialism: "DCL" -> Calvert-Lewin,
    "VVD" -> Van Dijk, "MGW"/"MGG" -> Gibbs-White, resolved through the
    shared KNOWN_NICKNAMES alias table (rank-0 match).
"""
from __future__ import annotations

import os as _os
import sys as _sys

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
    _os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import pytest

import fpl_grounded_assistant  # noqa: E402,F401
from fpl_grounded_assistant.find_players import (  # noqa: E402
    find_players,
    _normalize,
    _ALIAS_TO_WEBNAME,
)
from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot  # noqa: E402


@pytest.fixture
def bs() -> dict:
    """Synthetic bootstrap with the hyphenated / abbreviated players under test."""
    return {
        "teams": [
            {"id": 1, "name": "Leeds", "short_name": "LEE", "code": 2},
            {"id": 2, "name": "Liverpool", "short_name": "LIV", "code": 1},
            {"id": 3, "name": "Nottm Forest", "short_name": "NFO", "code": 17},
            {"id": 4, "name": "Man City", "short_name": "MCI", "code": 43},
        ],
        "element_types": [
            {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
        "elements": [
            {"id": 10, "first_name": "Dominic", "second_name": "Calvert-Lewin",
             "web_name": "Calvert-Lewin", "team": 1, "element_type": 4,
             "total_points": 100, "minutes": 900, "status": "a", "now_cost": 55, "selected_by_percent": "10.0"},
            {"id": 11, "first_name": "Virgil", "second_name": "van Dijk",
             "web_name": "Van Dijk", "team": 2, "element_type": 2,
             "total_points": 120, "minutes": 900, "status": "a", "now_cost": 65, "selected_by_percent": "10.0"},
            {"id": 12, "first_name": "Morgan", "second_name": "Gibbs-White",
             "web_name": "Gibbs-White", "team": 3, "element_type": 3,
             "total_points": 90, "minutes": 900, "status": "a", "now_cost": 62, "selected_by_percent": "10.0"},
            {"id": 13, "first_name": "Erling", "second_name": "Haaland",
             "web_name": "Haaland", "team": 4, "element_type": 4,
             "total_points": 200, "minutes": 900, "status": "a", "now_cost": 150, "selected_by_percent": "10.0"},
        ],
    }


# ---------------------------------------------------------------------------
# _normalize — hyphen handling
# ---------------------------------------------------------------------------

def test_normalize_treats_hyphen_as_space_and_collapses():
    assert _normalize("Calvert-Lewin") == "calvert lewin"
    assert _normalize("calvert lewin") == "calvert lewin"
    assert _normalize("Gibbs-White") == "gibbs white"
    # diacritics still stripped (regression on the pre-existing behavior)
    assert _normalize("Núñez") == "nunez"


# ---------------------------------------------------------------------------
# Alias index integrity
# ---------------------------------------------------------------------------

def test_alias_index_has_new_abbreviations():
    assert _ALIAS_TO_WEBNAME["dcl"] == "Calvert-Lewin"
    assert _ALIAS_TO_WEBNAME["vvd"] == "Van Dijk"
    assert _ALIAS_TO_WEBNAME["mgw"] == "Gibbs-White"
    assert _ALIAS_TO_WEBNAME["mgg"] == "Gibbs-White"
    # pre-existing initialisms still present
    assert _ALIAS_TO_WEBNAME["kdb"] == "De Bruyne"
    assert _ALIAS_TO_WEBNAME["taa"] == "Alexander-Arnold"


# ---------------------------------------------------------------------------
# find_players — hyphen + abbreviation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query,expected", [
    ("calvert lewin", "Calvert-Lewin"),   # dropped hyphen
    ("Calvert-Lewin", "Calvert-Lewin"),   # with hyphen (unchanged)
    ("gibbs white",   "Gibbs-White"),     # dropped hyphen
    ("DCL",           "Calvert-Lewin"),   # abbreviation
    ("dcl",           "Calvert-Lewin"),   # case-insensitive
    ("VVD",           "Van Dijk"),
    ("MGW",           "Gibbs-White"),
    ("MGG",           "Gibbs-White"),
    ("erling",        "Haaland"),         # existing first-name nickname now wired
])
def test_find_players_resolves_hyphen_and_abbreviations(bs, query, expected):
    r = find_players(query, bootstrap=bs)
    assert r["status"] == "ok"
    assert r["matches"][0]["web_name"] == expected


def test_find_players_unknown_abbreviation_still_not_found(bs):
    """An unmapped token that matches no name must not resolve to anything."""
    r = find_players("zzz", bootstrap=bs)
    assert r["status"] == "not_found"


# ---------------------------------------------------------------------------
# get_player_snapshot — same shared alias table + hyphen normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query,expected", [
    ("calvert lewin", "Calvert-Lewin"),
    ("DCL",           "Calvert-Lewin"),
    ("VVD",           "Van Dijk"),
    ("MGW",           "Gibbs-White"),
])
def test_get_player_snapshot_resolves_hyphen_and_abbreviations(bs, query, expected):
    r = get_player_snapshot(query, bootstrap=bs)
    assert r["status"] == "ok"
    assert r["player"]["web_name"] == expected

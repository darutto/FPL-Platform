"""Colloquial given names resolve against the full first+last name.

FPL's ``web_name`` carries the surname only ("Jackson"), so "Nico Jackson" used
to resolve to nothing even though "Nicolas Jackson" is the same person.  The
fixed set below is the contract: every (query, expected full name) pair must
resolve to exactly that player.  Players are synthetic squads built from the
public name shapes -- no store values.
"""
from __future__ import annotations

import pytest

from fpl_player_registry import (
    RANK_COMPOUND,
    given_name_variant_forms,
    resolve_player_candidates,
)

TEAMS = [{"id": 1, "name": "Alpha", "short_name": "ALP"}]


def _p(pid: int, first: str, second: str, web: str, *, points: int = 0) -> dict:
    return {
        "id": pid, "first_name": first, "second_name": second, "web_name": web,
        "team": 1, "element_type": 4, "status": "a", "total_points": points,
    }


PLAYERS = [
    _p(1, "Nicolas", "Jackson", "N.Jackson"),
    _p(2, "Alexander", "Isak", "Isak"),
    _p(3, "Matthew", "Santos Carneiro da Cash", "Cash"),
    _p(4, "Benjamin", "White", "White"),
    _p(5, "Thomas", "Partey", "Partey"),
    _p(6, "Daniel", "Welbeck", "Welbeck"),
    _p(7, "Nico", "González", "N.Gonzalez"),
    _p(8, "Mohamed", "Salah", "M.Salah"),
    _p(9, "Anthony", "Gordon", "Gordon"),
    _p(10, "Samuel", "Chukwueze", "Chukwueze"),
    _p(11, "Joshua", "Zirkzee", "Zirkzee"),
    _p(12, "Oliver", "Watkins", "Watkins"),
]

#: (what a user types, expected player id)
COLLOQUIAL_NAMES = [
    ("nico jackson", 1),
    ("Nick Jackson", 1),
    ("Nico Jackson", 1),
    ("alex isak", 2),
    ("Alexandre Isak", 2),
    ("Matt Cash", 3),
    ("matt carneiro da cash", 3),
    ("Ben White", 4),
    ("Tom Partey", 5),
    ("Dan Welbeck", 6),
    ("Nicolas Gonzalez", 7),      # listed under the short form, typed formally
    ("Mo Salah", 8),
    ("Tony Gordon", 9),
    ("Sam Chukwueze", 10),
    ("Josh Zirkzee", 11),
    ("Ollie Watkins", 12),
]


@pytest.mark.parametrize("query,expected_id", COLLOQUIAL_NAMES)
def test_colloquial_name_resolves_to_one_player(query, expected_id):
    result = resolve_player_candidates(query, PLAYERS, TEAMS)
    assert result.status == "ok", (query, result.best_matches)
    assert result.player.record.id == expected_id


def test_variant_rank_is_compound_and_names_the_route():
    match = resolve_player_candidates("nico jackson", PLAYERS, TEAMS).player
    assert match.rank == RANK_COMPOUND
    assert match.matched_via == "given_name_variant"


def test_two_players_behind_one_diminutive_stay_ambiguous():
    players = [_p(1, "Alexander", "Smith", "Smith"), _p(2, "Alexandre", "Smith", "A.Smith")]
    result = resolve_player_candidates("alex smith", players, TEAMS)
    assert result.status == "ambiguous"
    assert {m.record.id for m in result.best_matches} == {1, 2}


def test_exact_full_name_outranks_a_variant():
    # A real "Nico Jackson" must win over "Nicolas Jackson" for "nico jackson".
    players = [_p(1, "Nicolas", "Jackson", "N.Jackson"), _p(2, "Nico", "Jackson", "Jackson")]
    result = resolve_player_candidates("nico jackson", players, TEAMS)
    assert result.status == "ok"
    assert result.player.record.id == 2


def test_wrong_surname_or_ungrouped_given_name_does_not_resolve():
    assert resolve_player_candidates("nico jacksn", PLAYERS, TEAMS).status == "not_found"
    assert resolve_player_candidates("zed jackson", PLAYERS, TEAMS).status == "not_found"
    # "Nico" must not drag in a different surname's player.
    assert resolve_player_candidates("nico salah", PLAYERS, TEAMS).status == "not_found"


def test_given_name_variant_forms_shape():
    forms = given_name_variant_forms("nicolas", "jackson")
    assert "nico jackson" in forms and "nick jackson" in forms
    assert "nicolas jackson" not in forms  # the player's own form is the exact field
    assert given_name_variant_forms("zed", "jackson") == set()

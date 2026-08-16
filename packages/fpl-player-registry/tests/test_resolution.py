"""Canonical player-resolution contract and collision regressions."""
from __future__ import annotations

import pytest

from fpl_player_registry import normalize_player_name, resolve_player_candidates


TEAMS = [
    {"id": 1, "name": "Alpha", "short_name": "ALP"},
    {"id": 2, "name": "Beta", "short_name": "BET"},
]


def _player(
    player_id: int,
    first: str,
    second: str,
    web: str,
    *,
    team: int = 1,
    points: int = 0,
) -> dict:
    return {
        "id": player_id,
        "first_name": first,
        "second_name": second,
        "web_name": web,
        "team": team,
        "element_type": 3,
        "status": "a",
        "total_points": points,
    }


def test_normalization_is_symmetric_for_accents_dashes_and_apostrophes():
    assert normalize_player_name("João  Pedro") == "joao pedro"
    assert normalize_player_name("Calvert‑Lewin") == "calvert lewin"
    assert normalize_player_name("Calvert-Lewin") == "calvert lewin"
    assert normalize_player_name("N’Golo") == "ngolo"
    assert normalize_player_name("N'Golo") == "ngolo"


def test_rank_order_and_best_non_empty_rank():
    players = [
        _player(1, "Alex", "Exact", "Alex", points=10),
        _player(2, "Alexander", "Prefix", "Alexander", points=200),
        _player(3, "Malalex", "Substring", "Malalex", points=300),
    ]
    result = resolve_player_candidates(
        "Alex", players, TEAMS, allow_prefix=True, allow_substring=True
    )
    assert [(match.record.id, match.rank) for match in result.matches] == [
        (1, 0), (2, 1), (3, 2)
    ]
    assert [match.record.id for match in result.best_matches] == [1]
    assert result.status == "ok"


def test_numeric_id_is_authoritative():
    players = [_player(7, "Seven", "Player", "Seven")]
    result = resolve_player_candidates(7, players, TEAMS)
    assert result.status == "ok"
    assert result.player is not None
    assert result.player.record.id == 7
    assert result.player.matched_via == "id"


def test_full_name_exact_match_is_rank_zero():
    players = [_player(1, "João", "Pedro", "João Pedro")]
    result = resolve_player_candidates("joao pedro", players, TEAMS)
    assert result.status == "ok"
    assert result.player is not None
    assert result.player.rank == 0


def test_substring_matching_requires_explicit_opt_in():
    players = [_player(1, "Morgan", "Gibbs-White", "Gibbs-White")]
    assert resolve_player_candidates("white", players, TEAMS).status == "not_found"
    result = resolve_player_candidates(
        "white", players, TEAMS, allow_substring=True
    )
    assert result.status == "ok"
    assert result.player is not None
    assert result.player.matched_via == "substring"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("VVD", "Van Dijk"),
        ("DCL", "Calvert-Lewin"),
        ("MGW", "Gibbs-White"),
        ("MGG", "Gibbs-White"),
        ("CHO", "Hudson-Odoi"),
        ("ESR", "Smith Rowe"),
        ("JWP", "Ward-Prowse"),
        ("KDB", "De Bruyne"),
        ("TAA", "Alexander-Arnold"),
        ("Mo", "Salah"),
    ],
)
def test_every_supported_abbreviation_resolves_functionally(query: str, expected: str):
    web_names = [
        "Van Dijk", "Calvert-Lewin", "Gibbs-White", "Hudson-Odoi",
        "Smith Rowe", "Ward-Prowse", "De Bruyne", "Alexander-Arnold", "Salah",
    ]
    players = [
        _player(index, f"First{index}", web, web)
        for index, web in enumerate(web_names, start=1)
    ]
    result = resolve_player_candidates(query, players, TEAMS)
    assert result.status == "ok"
    assert result.player is not None
    assert result.player.record.web_name == expected
    assert result.player.matched_via == "alias"


def test_alias_collision_is_ambiguous_and_never_last_write_wins():
    players = [
        _player(1, "Alpha", "One", "One"),
        _player(2, "Beta", "Two", "Two"),
    ]
    aliases = {"One": ["shared"], "Two": ["shared"]}
    result = resolve_player_candidates("shared", players, TEAMS, aliases=aliases)
    assert result.status == "ambiguous"
    assert {match.record.id for match in result.best_matches} == {1, 2}


def test_duplicate_aliases_for_one_player_are_deduplicated():
    players = [_player(1, "Alpha", "One", "One")]
    aliases = {"One": ["same", "same", "SAME"]}
    result = resolve_player_candidates("same", players, TEAMS, aliases=aliases)
    assert result.status == "ok"
    assert [match.record.id for match in result.best_matches] == [1]


def test_missing_alias_target_does_not_resolve_another_player():
    players = [_player(1, "Alpha", "One", "One")]
    result = resolve_player_candidates(
        "ghost", players, TEAMS, aliases={"Missing": ["ghost"]}
    )
    assert result.status == "not_found"


def test_team_hint_filters_same_name_candidates():
    players = [
        _player(1, "João", "Pedro", "João Pedro", team=1),
        _player(2, "João", "Pedro", "João Pedro", team=2),
    ]
    ambiguous = resolve_player_candidates("Joao Pedro", players, TEAMS)
    assert ambiguous.status == "ambiguous"
    resolved = resolve_player_candidates(
        "Joao Pedro", players, TEAMS, team_hint="BET"
    )
    assert resolved.status == "ok"
    assert resolved.player is not None
    assert resolved.player.record.id == 2

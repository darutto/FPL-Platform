import pytest

from football_data_contract import (
    CANONICAL_ID_HASH_LENGTH,
    CANONICAL_ID_PREFIXES,
    CanonicalIdCollisionError,
    assert_no_canonical_id_collisions,
    canonical_competition_id,
    canonical_fixture_id,
    canonical_player_id,
    canonical_season_id,
    canonical_team_id,
    player_identity_fingerprint,
    validate_canonical_id,
    validate_team_registry_key,
)


def test_canonical_id_formats_are_exact_and_deterministic() -> None:
    player = canonical_player_id("José O'Neil", "2000-01-02")
    team = canonical_team_id("england|arsenal-fc|men|first-team")
    competition = canonical_competition_id("the-fa", "premier-league", "men")
    season = canonical_season_id(competition, "2026-2027")
    fixture = canonical_fixture_id(competition, season, team, canonical_team_id("england|chelsea-fc|men|first-team"), "round-01-match-01")
    values = {"player": player, "team": team, "competition": competition, "season": season, "fixture": fixture}
    for entity_type, value in values.items():
        assert value.startswith(CANONICAL_ID_PREFIXES[entity_type])
        assert len(value) == len(CANONICAL_ID_PREFIXES[entity_type]) + CANONICAL_ID_HASH_LENGTH
        validate_canonical_id(entity_type, value)
    assert player == canonical_player_id("Jose O Neil", "2000-01-02")


def test_player_fingerprint_changes_require_migration() -> None:
    assert canonical_player_id("John Smith", None) != canonical_player_id("John Smith", "1990-01-01")
    assert canonical_player_id("John Smith", "1990-01-01") != canonical_player_id("John A Smith", "1990-01-01")


def test_team_alias_and_fixture_reschedule_do_not_change_identity() -> None:
    registry_key = "england|arsenal-fc|men|first-team"
    assert canonical_team_id(registry_key) == canonical_team_id(registry_key)
    competition = canonical_competition_id("the-fa", "premier-league", "men")
    season = canonical_season_id(competition, "2026-2027")
    home = canonical_team_id(registry_key)
    away = canonical_team_id("england|chelsea-fc|men|first-team")
    original = canonical_fixture_id(competition, season, home, away, "round-01-match-01")
    rescheduled = canonical_fixture_id(competition, season, home, away, "round-01-match-01")
    assert original == rescheduled


def test_collision_guard_compares_independent_fingerprints() -> None:
    value = canonical_player_id("One Player", None)
    with pytest.raises(CanonicalIdCollisionError):
        assert_no_canonical_id_collisions(((value, player_identity_fingerprint("One Player", None)), (value, player_identity_fingerprint("Other Player", None))))


def test_wrong_prefix_or_length_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_canonical_id("team", canonical_player_id("Player", None))


@pytest.mark.parametrize("registry_key", [
    "Arsenal", "", "england|arsenal|men", "england|arsenal|men|first-team|extra",
    "England|arsenal|men|first-team", "england|arsenal men|men|first-team",
    "|arsenal|men|first-team", "england|arsenal|men|", "england|arsenal!|men|first-team",
])
def test_team_registry_key_grammar_rejects_invalid_values(registry_key: str) -> None:
    with pytest.raises(ValueError):
        canonical_team_id(registry_key)


def test_team_registry_key_has_exact_governed_segments() -> None:
    assert validate_team_registry_key("england|arsenal|men|first-team") == (
        "england", "arsenal", "men", "first-team",
    )
    assert canonical_team_id("england|arsenal|men|first-team") == canonical_team_id("england|arsenal|men|first-team")


@pytest.mark.parametrize(("generator", "arguments"), [
    (canonical_competition_id, ("the-fa|premier", "league", "men")),
    (canonical_competition_id, ("the-fa", "premier|league", "men")),
    (canonical_competition_id, ("the-fa", "league", "men|senior")),
    (canonical_competition_id, (" the-fa", "league", "men")),
    (canonical_player_id, ("Player|Shifted", None)),
    (canonical_player_id, (" Player", None)),
    (canonical_player_id, ("Player", "2000|01|01")),
])
def test_reserved_separator_and_invalid_component_boundaries_fail_before_hashing(generator, arguments) -> None:
    with pytest.raises(ValueError):
        generator(*arguments)


def test_separator_validation_prevents_split_component_collision() -> None:
    with pytest.raises(ValueError):
        canonical_competition_id("the-fa|premier", "league", "men")
    with pytest.raises(ValueError):
        canonical_competition_id("the-fa", "premier|league", "men")


@pytest.mark.parametrize(("generator", "arguments"), [
    (canonical_player_id, ("", None)),
    (canonical_player_id, ("Player", "")),
    (canonical_competition_id, ("", "premier-league", "men")),
    (canonical_competition_id, ("the-fa", "   ", "men")),
    (canonical_competition_id, ("the-fa", "premier-league", "men ")),
])
def test_empty_whitespace_and_edge_whitespace_components_fail(generator, arguments) -> None:
    with pytest.raises(ValueError):
        generator(*arguments)


def test_season_and_fixture_free_components_are_validated() -> None:
    competition = canonical_competition_id("the-fa", "premier-league", "men")
    team = canonical_team_id("england|arsenal|men|first-team")
    other = canonical_team_id("england|chelsea|men|first-team")
    with pytest.raises(ValueError):
        canonical_season_id(competition, "2026|2027")
    with pytest.raises(ValueError):
        canonical_season_id(competition, "")
    season = canonical_season_id(competition, "2026-2027")
    with pytest.raises(ValueError):
        canonical_fixture_id(competition, season, team, other, "round|01")
    with pytest.raises(ValueError):
        canonical_fixture_id(competition, season, team, other, "   ")

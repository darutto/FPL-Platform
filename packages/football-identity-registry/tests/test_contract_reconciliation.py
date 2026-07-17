from dataclasses import fields
from pathlib import Path

import pytest
from football_data_contract import (
    CANONICAL_ID_HASH_LENGTH,
    CANONICAL_ID_PREFIXES,
    ProviderIdentifier,
    canonical_competition_id,
    canonical_fixture_id,
    canonical_player_id as contract_player_id,
    canonical_season_id,
    canonical_team_id,
    validate_canonical_id,
)
from football_identity_registry.canonical_ids import canonical_player_id as identity_player_id
from football_identity_registry.models import SourcePlayer
from football_identity_registry.store import OTHER_COLUMNS, PLAYER_COLUMNS, PlayerIdentityRow


def test_identity_generator_is_the_canonical_generator() -> None:
    generated = identity_player_id("José O'Neil", "2000-01-02")
    assert generated == contract_player_id("José O'Neil", "2000-01-02")
    assert generated.startswith(CANONICAL_ID_PREFIXES["player"])
    assert len(generated) == len(CANONICAL_ID_PREFIXES["player"]) + CANONICAL_ID_HASH_LENGTH
    validate_canonical_id("player", generated)


def test_identity_package_does_not_redefine_id_dialect() -> None:
    source = (Path(__file__).parents[1] / "football_identity_registry" / "canonical_ids.py").read_text(encoding="utf-8")
    assert '"player_' not in source and "sha256" not in source


def test_provider_vocabulary_is_shared_and_closed() -> None:
    assert SourcePlayer("understat", "u1", "Player").provider is ProviderIdentifier.UNDERSTAT
    with pytest.raises(ValueError):
        SourcePlayer("understtat", "u1", "Player")


def test_persisted_player_schema_uses_governed_types() -> None:
    assert tuple(field.name for field in fields(PlayerIdentityRow)) == PLAYER_COLUMNS
    row = PlayerIdentityRow(
        contract_player_id("Player", None), "fpl", "1", "player", "Player",
        None, None, "2026-08-01", None, "full_name_unique", .9, False,
    )
    assert row.provider is ProviderIdentifier.FPL
    assert all(columns[1] == "provider" and columns[0] == f"canonical_{entity}_id" for entity, columns in OTHER_COLUMNS.items())


def test_literal_canonical_id_governance_anchors() -> None:
    """Independent literals pin prefixes, length, grammar, order, and hashing."""
    player = contract_player_id("José O'Neil", "2000-01-02")
    team = canonical_team_id("england|arsenal|men|first-team")
    competition = canonical_competition_id("the-fa", "premier-league", "men")
    season = canonical_season_id(competition, "2026-2027")
    away = canonical_team_id("england|chelsea|men|first-team")
    fixture = canonical_fixture_id(
        competition, season, team, away, "round-01-match-01"
    )
    assert player == "player_365f648bdd9b01f5504c074e"
    assert team == "team_95409c689633dd59ec8ee8f5"
    assert competition == "competition_1721113dddcb228b9371f88d"
    assert season == "season_d93fe50bb7dbe68dca513212"
    assert fixture == "fixture_9670657776dfa3ee4de0c365"

    # Calling the helpers in a different order cannot affect their outputs.
    assert canonical_team_id("england|arsenal|men|first-team") == team
    assert contract_player_id("Jose O Neil", "2000-01-02") == player


def test_checkpoint_does_not_add_fi4_implementation() -> None:
    packages = Path(__file__).resolve().parents[2]
    forbidden = (
        packages / "sportmonks-client" / "sportmonks_client" / "normalize",
        packages / "sportmonks-client" / "sportmonks_client" / "ingest.py",
        packages / "football-data-contract" / "football_data_contract" / "store.py",
    )
    assert not any(path.exists() for path in forbidden)

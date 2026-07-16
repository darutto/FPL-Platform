from dataclasses import FrozenInstanceError, fields

import pytest

from football_data_contract import (
    AvailabilityState,
    AvailabilityStatus,
    CanonicalCompetition,
    CanonicalFixture,
    CanonicalPlayer,
    CanonicalSeason,
    CanonicalTeam,
    CompetitionTier,
    FixtureStatus,
    Flank,
    Formation,
    FormationDepth,
    InjuryRecord,
    PlayerMatchAppearance,
    PlayerMatchRole,
    PlayerMatchStats,
    ProviderIdentifier,
    ProviderRef,
    Provenance,
    StartingRole,
    Substitution,
    SuspensionRecord,
    TeamMatchStats,
    canonical_competition_id,
    canonical_fixture_id,
    canonical_player_id,
    canonical_season_id,
    canonical_team_id,
)


PROVENANCE = Provenance(
    source_provider=ProviderIdentifier.FPL,
    ingested_at="2026-07-14T18:00:00Z",
    source_timestamp=None,
    ingestion_run_id="run-fi1-test",
)
PLAYER_ID = canonical_player_id("Alex Player", None)
TEAM_ID = canonical_team_id("england|example-fc|men|first-team")
OTHER_TEAM_ID = canonical_team_id("england|other-fc|men|first-team")
COMPETITION_ID = canonical_competition_id("the-fa", "example-league", "men")
SEASON_ID = canonical_season_id(COMPETITION_ID, "2026-2027")
FIXTURE_ID = canonical_fixture_id(COMPETITION_ID, SEASON_ID, TEAM_ID, OTHER_TEAM_ID, "round-01-match-01")


@pytest.mark.parametrize(
    "instance",
    [
        CanonicalPlayer(PLAYER_ID, "Alex Player", "Alex", None, None, ("MID",), PROVENANCE),
        CanonicalTeam(TEAM_ID, "Example FC", "EXA", PROVENANCE),
        CanonicalCompetition(COMPETITION_ID, "Example League", CompetitionTier.LEAGUE, "GB", PROVENANCE),
        CanonicalSeason(SEASON_ID, "2026-2027", COMPETITION_ID, PROVENANCE),
        CanonicalFixture(FIXTURE_ID, SEASON_ID, COMPETITION_ID, "2026-08-15T14:00:00Z", TEAM_ID, OTHER_TEAM_ID, FixtureStatus.SCHEDULED, 1, PROVENANCE),
        PlayerMatchAppearance(FIXTURE_ID, PLAYER_ID, TEAM_ID, True, 90, None, None, None, PROVENANCE),
        PlayerMatchRole(FIXTURE_ID, PLAYER_ID, "4-3-3", "8", "right_winger", Flank.RIGHT, FormationDepth.ADVANCED, StartingRole.STARTER, PROVENANCE),
        Formation(FIXTURE_ID, TEAM_ID, "4-3-3", "2026-08-15T13:00:00Z", PROVENANCE),
        AvailabilityStatus(PLAYER_ID, "2026-08-14T12:00:00Z", AvailabilityState.AVAILABLE, None, None, PROVENANCE),
        InjuryRecord(PLAYER_ID, "2026-08-01T12:00:00Z", "ankle injury", None, None, PROVENANCE),
        SuspensionRecord(PLAYER_ID, "2026-08-01T12:00:00Z", "disciplinary", None, None, 1, PROVENANCE),
        Substitution(FIXTURE_ID, TEAM_ID, PLAYER_ID, canonical_player_id("Other Player", None), 70, PROVENANCE),
        TeamMatchStats(FIXTURE_ID, TEAM_ID, 55.2, 14, 6, 1.7, PROVENANCE),
        PlayerMatchStats(FIXTURE_ID, PLAYER_ID, TEAM_ID, 90, 1, 1, 3, 0.7, 0.4, 2, 1, PROVENANCE),
        ProviderRef(ProviderIdentifier.UNDERSTAT, "provider-player-1", "2026-07-01"),
        PROVENANCE,
    ],
)
def test_representative_contract_instances_are_frozen(instance) -> None:
    first_field = fields(instance)[0].name
    with pytest.raises(FrozenInstanceError):
        setattr(instance, first_field, "changed")


def test_tactical_role_uses_deployment_language() -> None:
    names = {field.name for field in fields(PlayerMatchRole)}
    assert {"derived_flank", "formation_depth", "starting_role"} <= names
    prohibited_name = "average" + "_position"
    assert prohibited_name not in names


def test_provenance_requires_utc_timestamp() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        Provenance(ProviderIdentifier.FPL, "2026-07-14T18:00:00", None, "run")

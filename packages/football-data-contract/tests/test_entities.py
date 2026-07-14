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
)


PROVENANCE = Provenance(
    source_provider=ProviderIdentifier.FPL,
    ingested_at="2026-07-14T18:00:00Z",
    source_timestamp=None,
    ingestion_run_id="run-fi1-test",
)


@pytest.mark.parametrize(
    "instance",
    [
        CanonicalPlayer("cp_1", "Alex Player", "Alex", None, None, ("MID",), PROVENANCE),
        CanonicalTeam("ct_1", "Example FC", "EXA", PROVENANCE),
        CanonicalCompetition("cc_1", "Example League", CompetitionTier.LEAGUE, "GB", PROVENANCE),
        CanonicalSeason("cs_1", "2026-2027", "cc_1", PROVENANCE),
        CanonicalFixture("cf_1", "cs_1", "cc_1", "2026-08-15T14:00:00Z", "ct_1", "ct_2", FixtureStatus.SCHEDULED, 1, PROVENANCE),
        PlayerMatchAppearance("cf_1", "cp_1", "ct_1", True, 90, None, None, None, PROVENANCE),
        PlayerMatchRole("cf_1", "cp_1", "4-3-3", "8", "right_winger", Flank.RIGHT, FormationDepth.ADVANCED, StartingRole.STARTER, PROVENANCE),
        Formation("cf_1", "ct_1", "4-3-3", "2026-08-15T13:00:00Z", PROVENANCE),
        AvailabilityStatus("cp_1", "2026-08-14T12:00:00Z", AvailabilityState.AVAILABLE, None, None, PROVENANCE),
        InjuryRecord("cp_1", "2026-08-01T12:00:00Z", "ankle injury", None, None, PROVENANCE),
        SuspensionRecord("cp_1", "2026-08-01T12:00:00Z", "disciplinary", None, None, 1, PROVENANCE),
        Substitution("cf_1", "ct_1", "cp_1", "cp_2", 70, PROVENANCE),
        TeamMatchStats("cf_1", "ct_1", 55.2, 14, 6, 1.7, PROVENANCE),
        PlayerMatchStats("cf_1", "cp_1", "ct_1", 90, 1, 1, 3, 0.7, 0.4, 2, 1, PROVENANCE),
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

import pytest

from football_data_contract import (
    AvailabilityState,
    CompetitionTier,
    EvidenceDirection,
    FixtureStatus,
    Flank,
    FormationDepth,
    ProviderIdentifier,
    SignalBasis,
    StartingRole,
    SubjectType,
)


EXPECTED = {
    ProviderIdentifier: {"fpl", "understat", "sportmonks", "vaastav"},
    AvailabilityState: {"available", "doubtful", "injured", "suspended", "unregistered", "unknown"},
    CompetitionTier: {"league", "domestic_cup", "continental"},
    FixtureStatus: {"scheduled", "live", "completed", "postponed", "cancelled", "abandoned", "unknown"},
    Flank: {"left", "central", "right"},
    FormationDepth: {"deep", "mid", "advanced"},
    StartingRole: {"starter", "substitute"},
    SignalBasis: {"observed", "inferred_proxy"},
    EvidenceDirection: {"positive", "negative", "neutral"},
    SubjectType: {"player", "team", "fixture"},
}


@pytest.mark.parametrize(("enum_type", "expected"), EXPECTED.items())
def test_enum_is_closed(enum_type, expected) -> None:
    assert {member.value for member in enum_type} == expected
    with pytest.raises(ValueError):
        enum_type("not_in_contract")

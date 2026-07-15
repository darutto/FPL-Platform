"""Provider-neutral canonical football and structured evidence contracts."""

from .entities import (
    AvailabilityStatus,
    CanonicalCompetition,
    CanonicalFixture,
    CanonicalPlayer,
    CanonicalSeason,
    CanonicalTeam,
    Formation,
    InjuryRecord,
    PlayerMatchAppearance,
    PlayerMatchRole,
    PlayerMatchStats,
    Substitution,
    SuspensionRecord,
    TeamMatchStats,
)
from .enums import (
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
from .evidence import EVIDENCE_CODES, EvidenceItem
from .provenance import ProviderRef, Provenance

__all__ = [
    "AvailabilityState", "AvailabilityStatus", "CanonicalCompetition",
    "CanonicalFixture", "CanonicalPlayer", "CanonicalSeason", "CanonicalTeam",
    "CompetitionTier", "EVIDENCE_CODES", "EvidenceDirection", "EvidenceItem",
    "FixtureStatus", "Flank", "Formation", "FormationDepth", "InjuryRecord",
    "PlayerMatchAppearance", "PlayerMatchRole", "PlayerMatchStats",
    "ProviderIdentifier", "ProviderRef", "Provenance", "SignalBasis",
    "StartingRole", "SubjectType", "Substitution", "SuspensionRecord",
    "TeamMatchStats",
]

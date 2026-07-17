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
from .identifiers import (
    CANONICAL_ID_HASH_LENGTH,
    CANONICAL_ID_PREFIXES,
    FINGERPRINT_SEPARATOR,
    CanonicalIdCollisionError,
    assert_no_canonical_id_collisions,
    canonical_competition_id,
    canonical_fixture_id,
    canonical_player_id,
    canonical_season_id,
    canonical_team_id,
    normalize_identity_name,
    player_identity_fingerprint,
    validate_canonical_id,
    validate_team_registry_key,
)
from .provenance import ProviderRef, Provenance

__all__ = [
    "AvailabilityState", "AvailabilityStatus", "CanonicalCompetition",
    "CanonicalFixture", "CanonicalPlayer", "CanonicalSeason", "CanonicalTeam",
    "CANONICAL_ID_HASH_LENGTH", "CANONICAL_ID_PREFIXES", "FINGERPRINT_SEPARATOR", "CanonicalIdCollisionError",
    "CompetitionTier", "EVIDENCE_CODES", "EvidenceDirection", "EvidenceItem",
    "FixtureStatus", "Flank", "Formation", "FormationDepth", "InjuryRecord",
    "PlayerMatchAppearance", "PlayerMatchRole", "PlayerMatchStats",
    "ProviderIdentifier", "ProviderRef", "Provenance", "SignalBasis",
    "StartingRole", "SubjectType", "Substitution", "SuspensionRecord",
    "TeamMatchStats", "assert_no_canonical_id_collisions", "canonical_competition_id",
    "canonical_fixture_id", "canonical_player_id", "canonical_season_id",
    "canonical_team_id", "normalize_identity_name", "player_identity_fingerprint",
    "validate_canonical_id", "validate_team_registry_key",
]

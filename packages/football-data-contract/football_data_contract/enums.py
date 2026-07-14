"""Closed provider-neutral vocabularies for canonical football data."""
from enum import StrEnum


class ProviderIdentifier(StrEnum):
    FPL = "fpl"
    UNDERSTAT = "understat"
    SPORTMONKS = "sportmonks"
    VAASTAV = "vaastav"


class AvailabilityState(StrEnum):
    AVAILABLE = "available"
    DOUBTFUL = "doubtful"
    INJURED = "injured"
    SUSPENDED = "suspended"
    UNREGISTERED = "unregistered"
    UNKNOWN = "unknown"


class CompetitionTier(StrEnum):
    LEAGUE = "league"
    DOMESTIC_CUP = "domestic_cup"
    CONTINENTAL = "continental"


class FixtureStatus(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    COMPLETED = "completed"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"
    UNKNOWN = "unknown"


class Flank(StrEnum):
    LEFT = "left"
    CENTRAL = "central"
    RIGHT = "right"


class FormationDepth(StrEnum):
    DEEP = "deep"
    MID = "mid"
    ADVANCED = "advanced"


class StartingRole(StrEnum):
    STARTER = "starter"
    SUBSTITUTE = "substitute"


class SignalBasis(StrEnum):
    OBSERVED = "observed"
    INFERRED_PROXY = "inferred_proxy"


class EvidenceDirection(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class SubjectType(StrEnum):
    PLAYER = "player"
    TEAM = "team"
    FIXTURE = "fixture"

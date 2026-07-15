"""Stable structured evidence contract shared with the UI mirror."""
from dataclasses import dataclass
from datetime import datetime
from .enums import EvidenceDirection, SignalBasis, SubjectType


EVIDENCE_CODES = frozenset(
    {
        "MINUTES_CONFIDENCE_HIGH",
        "MINUTES_CONFIDENCE_LOW",
        "ROTATION_RISK",
        "CAMEO_RISK",
        "ROLE_STABLE",
        "ROLE_CHANGED",
        "OUT_OF_POSITION",
        "OPPONENT_FLANK_WEAKNESS",
        "OPPONENT_UNIT_DISRUPTION",
        "FIXTURE_CONGESTION",
        "REST_ADVANTAGE",
        "SET_PIECE_ROLE",
        "AVAILABILITY_DOUBT",
    }
)

EVIDENCE_FIELD_NAMES = (
    "code",
    "label",
    "subject_type",
    "subject_id",
    "fixture_id",
    "impact",
    "direction",
    "confidence",
    "basis",
    "summary",
    "source_features",
    "model_version",
    "calculated_at",
)
EVIDENCE_NULLABLE_FIELDS = (
    "fixture_id",
)


def _require_utc_iso(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("calculated_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("calculated_at must include a UTC offset")
    if parsed.utcoffset().total_seconds() != 0:
        raise ValueError("calculated_at must be UTC")


@dataclass(frozen=True)
class EvidenceItem:
    code: str
    label: str
    subject_type: SubjectType
    subject_id: str
    fixture_id: str | None
    impact: float
    direction: EvidenceDirection
    confidence: float
    basis: SignalBasis
    summary: str
    source_features: tuple[str, ...]
    model_version: str
    calculated_at: str

    def __post_init__(self) -> None:
        if self.code not in EVIDENCE_CODES:
            raise ValueError(f"unknown evidence code: {self.code}")
        if not isinstance(self.subject_type, SubjectType):
            raise ValueError("subject_type must be a closed SubjectType value")
        if not isinstance(self.basis, SignalBasis):
            raise ValueError("basis must be observed or inferred_proxy")
        if not -10.0 <= self.impact <= 10.0:
            raise ValueError("impact must be between -10.0 and 10.0")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        expected_direction = (
            EvidenceDirection.POSITIVE
            if self.impact > 0
            else EvidenceDirection.NEGATIVE
            if self.impact < 0
            else EvidenceDirection.NEUTRAL
        )
        if self.direction is not expected_direction:
            raise ValueError("direction must agree with the sign of impact")
        if not isinstance(self.source_features, tuple):
            raise TypeError("source_features must be an immutable tuple")
        _require_utc_iso(self.calculated_at)

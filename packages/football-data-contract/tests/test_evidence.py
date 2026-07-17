from dataclasses import FrozenInstanceError, asdict, fields

import pytest

from football_data_contract import (
    EVIDENCE_CODES,
    EvidenceDirection,
    EvidenceItem,
    SignalBasis,
    SubjectType,
)
from football_data_contract.evidence import EVIDENCE_FIELD_NAMES


def make_evidence(**overrides) -> EvidenceItem:
    values = {
        "code": "ROLE_STABLE",
        "label": "Stable role",
        "subject_type": SubjectType.PLAYER,
        "subject_id": "player_365f648bdd9b01f5504c074e",
        "fixture_id": None,
        "impact": 2.0,
        "direction": EvidenceDirection.POSITIVE,
        "confidence": 0.8,
        "basis": SignalBasis.OBSERVED,
        "summary": "The player started in the same role across recent fixtures.",
        "source_features": ("role_stability",),
        "model_version": "tactical-role-v1",
        "calculated_at": "2026-07-14T18:00:00Z",
    }
    values.update(overrides)
    return EvidenceItem(**values)


def test_shape_and_serialization_order_are_stable() -> None:
    item = make_evidence()
    assert tuple(field.name for field in fields(EvidenceItem)) == EVIDENCE_FIELD_NAMES
    assert tuple(asdict(item)) == EVIDENCE_FIELD_NAMES


def test_evidence_shape_contains_no_provider_or_recommendation_fields() -> None:
    assert not {"provider", "provider_id", "recommendation"}.intersection(EVIDENCE_FIELD_NAMES)


def test_evidence_item_is_frozen() -> None:
    item = make_evidence()
    with pytest.raises(FrozenInstanceError):
        item.impact = 1.0


@pytest.mark.parametrize("impact", [-10.01, 10.01])
def test_invalid_impact_is_rejected(impact) -> None:
    with pytest.raises(ValueError, match="impact"):
        make_evidence(impact=impact)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_invalid_confidence_is_rejected(confidence) -> None:
    with pytest.raises(ValueError, match="confidence"):
        make_evidence(confidence=confidence)


@pytest.mark.parametrize(
    ("impact", "direction"),
    [(1.0, EvidenceDirection.NEGATIVE), (-1.0, EvidenceDirection.POSITIVE), (0.0, EvidenceDirection.POSITIVE)],
)
def test_direction_must_match_impact(impact, direction) -> None:
    with pytest.raises(ValueError, match="direction"):
        make_evidence(impact=impact, direction=direction)


def test_source_features_requires_immutable_tuple() -> None:
    with pytest.raises(TypeError, match="immutable tuple"):
        make_evidence(source_features=["role_stability"])


def test_unknown_evidence_code_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown evidence code"):
        make_evidence(code="BUY_PLAYER_NOW")


def test_basis_is_restricted_to_closed_enum() -> None:
    with pytest.raises(ValueError, match="basis"):
        make_evidence(basis="observed")


def test_evidence_codes_are_exactly_the_approved_registry() -> None:
    assert EVIDENCE_CODES == {
        "MINUTES_CONFIDENCE_HIGH", "MINUTES_CONFIDENCE_LOW", "ROTATION_RISK",
        "CAMEO_RISK", "ROLE_STABLE", "ROLE_CHANGED", "OUT_OF_POSITION",
        "OPPONENT_FLANK_WEAKNESS", "OPPONENT_UNIT_DISRUPTION",
        "FIXTURE_CONGESTION", "REST_ADVANTAGE", "SET_PIECE_ROLE",
        "AVAILABILITY_DOUBT",
    }


def test_calculated_at_requires_utc_iso() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        make_evidence(calculated_at="2026-07-14T18:00:00")

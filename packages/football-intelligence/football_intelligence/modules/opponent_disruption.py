"""FI-6d M4: deterministic non-operational opponent disruption skeleton."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from football_intelligence.features.store_v2 import FeatureV2ValidationError

from .contracts import ModuleResult, ModuleStatus


MODEL_VERSION = "opponent-personnel-disruption-v1"


def _utc(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise FeatureV2ValidationError(
            "calculated_at must be an ISO-8601 UTC timestamp"
        ) from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset().total_seconds() != 0
    ):
        raise FeatureV2ValidationError(
            "calculated_at must be an ISO-8601 UTC timestamp"
        )


@dataclass(frozen=True)
class OpponentPersonnelDisruptionInput:
    fixture_id: str
    team_id: str
    calculated_at: str

    def __post_init__(self) -> None:
        _utc(self.calculated_at)


@dataclass(frozen=True)
class OpponentPersonnelDisruptionResult(ModuleResult):
    pass


def evaluate_opponent_personnel_disruption(
    item: OpponentPersonnelDisruptionInput,
) -> OpponentPersonnelDisruptionResult:
    """Return the stable non-operational M4 result."""
    return OpponentPersonnelDisruptionResult(
        status=ModuleStatus.NOT_IMPLEMENTED,
        model_version=MODEL_VERSION,
        feature_registry_version=None,
        feature_build_id=None,
        fixture_id=item.fixture_id,
        team_id=item.team_id,
        confidence=0.0,
        reason_codes=("not_implemented",),
        evidence=(),
    )

"""FI-6e M5: deterministic non-operational flank matchup skeleton."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from football_intelligence.features.store_v2 import FeatureV2ValidationError

from .contracts import ModuleResult, ModuleStatus


MODEL_VERSION = "flank-matchup-v1"


def _utc(value: str) -> None:
    if not isinstance(value, str) or not value.endswith(("Z", "+00:00")):
        raise FeatureV2ValidationError(
            "calculated_at must be an ISO-8601 UTC timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
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
class FlankMatchupInput:
    fixture_id: str
    team_id: str
    player_id: str
    calculated_at: str

    def __post_init__(self) -> None:
        _utc(self.calculated_at)


@dataclass(frozen=True)
class FlankMatchupResult(ModuleResult):
    player_id: str


def evaluate_flank_matchup(item: FlankMatchupInput) -> FlankMatchupResult:
    """Return the stable non-operational M5 result."""
    return FlankMatchupResult(
        status=ModuleStatus.NOT_IMPLEMENTED,
        model_version=MODEL_VERSION,
        feature_registry_version=None,
        feature_build_id=None,
        fixture_id=item.fixture_id,
        team_id=item.team_id,
        confidence=0.0,
        reason_codes=("not_implemented",),
        evidence=(),
        player_id=item.player_id,
    )

"""FI-6a M1: deterministic starting and minutes confidence evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path

import pandas as pd

from football_data_contract.enums import (
    AvailabilityState,
    EvidenceDirection,
    SignalBasis,
    SubjectType,
)
from football_data_contract.evidence import EvidenceItem
from football_intelligence.features.registry_v2 import FEATURE_REGISTRY_VERSION
from football_intelligence.features.store_v2 import (
    BUILD_FAMILY,
    FeatureV2ValidationError,
    validate_feature_build_v2,
)

from .contracts import ModuleResult, ModuleStatus, UnsupportedFeatureContractError


MODEL_VERSION = "expected-minutes-v1"
COEFFICIENT_VERSION = "expected-minutes-hand-tuned-v1"
AVAILABILITY_INPUT_VERSION = "availability-input-v1"

# Hand-tuned v1 heuristics. They are deliberately centralized, pinned in tests,
# and must be backtested before being treated as calibrated probabilities.
CONGESTION_DAMPING_PER_WEIGHTED_FIXTURE = 0.025
MIN_CONGESTION_MULTIPLIER = 0.75
DOUBTFUL_FALLBACK_MULTIPLIER = 0.50
UNKNOWN_AVAILABILITY_MULTIPLIER = 0.75
HIGH_MINUTES_THRESHOLD = 55.0
LOW_MINUTES_THRESHOLD = 45.0


def _utc(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("calculated_at must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("calculated_at must be an ISO-8601 UTC timestamp")


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


@dataclass(frozen=True)
class AvailabilityInput:
    """Explicit provider-neutral M1 input; this is not an FI-5 v1 feature."""

    state: AvailabilityState | None = None
    chance_of_playing: float | None = None
    version: str = AVAILABILITY_INPUT_VERSION

    def __post_init__(self) -> None:
        if self.state is not None and not isinstance(self.state, AvailabilityState):
            raise TypeError("availability state must use the closed AvailabilityState enum")
        if self.chance_of_playing is not None and not 0.0 <= self.chance_of_playing <= 1.0:
            raise ValueError("chance_of_playing must be a fraction between 0 and 1")
        if self.version != AVAILABILITY_INPUT_VERSION:
            raise ValueError("unsupported availability input version")
        if self.chance_of_playing is not None and self.state is not AvailabilityState.DOUBTFUL:
            raise ValueError("chance_of_playing is valid only for doubtful availability")


@dataclass(frozen=True)
class ExpectedMinutesInput:
    fixture_id: str
    team_id: str
    player_id: str
    calculated_at: str
    feature_registry_version: str | None
    feature_build_id: str | None
    weighted_start_share_last_6: float | None = None
    weighted_start_denominator_last_6: float = 0.0
    eligible_team_fixtures_last_6: int = 0
    cameo_appearances_last_6: int = 0
    mean_minutes_when_started_last_6: float | None = None
    mean_minutes_when_cameo_last_6: float | None = None
    weighted_trailing_congestion_21d: float | None = None
    weighted_leading_congestion_21d: float | None = None
    availability: AvailabilityInput = AvailabilityInput()

    def __post_init__(self) -> None:
        _utc(self.calculated_at)
        if (self.feature_registry_version is None) != (self.feature_build_id is None):
            raise ValueError("feature registry and build identifiers must be present together")
        numeric = (
            self.weighted_start_share_last_6,
            self.weighted_start_denominator_last_6,
            self.mean_minutes_when_started_last_6,
            self.mean_minutes_when_cameo_last_6,
            self.weighted_trailing_congestion_21d,
            self.weighted_leading_congestion_21d,
        )
        if any(value is not None and not math.isfinite(float(value)) for value in numeric):
            raise ValueError("expected-minutes inputs must be finite")
        if self.weighted_start_share_last_6 is not None and not 0.0 <= self.weighted_start_share_last_6 <= 1.0:
            raise ValueError("weighted start share must be between 0 and 1")
        if not 0.0 <= self.weighted_start_denominator_last_6 <= 21.0:
            raise ValueError("weighted start denominator must be between 0 and 21")
        if not 0 <= self.eligible_team_fixtures_last_6 <= 6:
            raise ValueError("eligible fixture count must be between 0 and 6")
        if not 0 <= self.cameo_appearances_last_6 <= self.eligible_team_fixtures_last_6:
            raise ValueError("cameo count must be within the eligible fixture count")
        if any(value is not None and not 0.0 <= value <= 120.0 for value in (
            self.mean_minutes_when_started_last_6, self.mean_minutes_when_cameo_last_6,
        )):
            raise ValueError("conditional minutes must be between 0 and 120")
        if self.cameo_appearances_last_6 > 0 and self.mean_minutes_when_cameo_last_6 is None:
            raise ValueError("positive cameo history requires conditional cameo minutes")
        if (self.weighted_trailing_congestion_21d is None) != (self.weighted_leading_congestion_21d is None):
            raise ValueError("trailing and leading congestion context must be present together")
        if any(value is not None and not 0.0 <= value <= 40.0 for value in (
            self.weighted_trailing_congestion_21d, self.weighted_leading_congestion_21d,
        )):
            raise ValueError("weighted congestion must be between 0 and 40")


@dataclass(frozen=True)
class ExpectedMinutesResult(ModuleResult):
    player_id: str
    coefficient_version: str
    availability_input_version: str
    start_probability: float | None
    expected_minutes: float | None
    cameo_probability: float | None
    rotation_risk: float | None
    minutes_risk_v2: float | None


def _missing_input(fixture_id, team_id, player_id, calculated_at) -> ExpectedMinutesInput:
    return ExpectedMinutesInput(
        fixture_id=fixture_id,
        team_id=team_id,
        player_id=player_id,
        calculated_at=calculated_at,
        feature_registry_version=None,
        feature_build_id=None,
    )


def load_expected_minutes_input(
    feature_build: Path | None,
    base,
    context_build: Path | None,
    *,
    fixture_id: str,
    team_id: str,
    player_id: str,
    calculated_at: str,
    availability: AvailabilityInput = AvailabilityInput(),
) -> ExpectedMinutesInput:
    """Validate a bound FI-5b v2 build and select the exact M1/M3 rows."""
    if feature_build is None or not Path(feature_build).is_dir():
        return _missing_input(fixture_id, team_id, player_id, calculated_at)
    build = Path(feature_build)
    manifest_path = build / "manifest.json"
    if not manifest_path.is_file():
        return _missing_input(fixture_id, team_id, player_id, calculated_at)
    try:
        candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeatureV2ValidationError("invalid v2 feature manifest") from exc
    if isinstance(candidate, dict) and candidate.get("schema_version") == 1:
        raise UnsupportedFeatureContractError("unsupported_feature_contract: FI-6 requires feature schema 2")
    if base is None or context_build is None:
        raise FeatureV2ValidationError("FI-6 requires validated v2 source bindings")

    manifest = validate_feature_build_v2(build, base, context_build)
    if manifest["build_family"] != BUILD_FAMILY or manifest["feature_registry_version"] != FEATURE_REGISTRY_VERSION:
        raise UnsupportedFeatureContractError("unsupported_feature_contract: FI-6 requires fi5-registry-v2")

    player = pd.read_parquet(build / manifest["output_files"]["player_fixture_module_inputs"])
    team = pd.read_parquet(build / manifest["output_files"]["team_fixture_context_v2"])
    player_rows = player[
        (player.fixture_id.astype(str) == fixture_id)
        & (player.team_id.astype(str) == team_id)
        & (player.player_id.astype(str) == player_id)
    ]
    if player_rows.empty:
        return _missing_input(fixture_id, team_id, player_id, calculated_at)
    team_rows = team[(team.fixture_id.astype(str) == fixture_id) & (team.team_id.astype(str) == team_id)]
    p = player_rows.iloc[0]
    t = team_rows.iloc[0] if not team_rows.empty else None
    value = lambda row, name: None if row is None or pd.isna(row[name]) else row[name]
    return ExpectedMinutesInput(
        fixture_id=fixture_id,
        team_id=team_id,
        player_id=player_id,
        calculated_at=calculated_at,
        feature_registry_version=str(p.feature_registry_version),
        feature_build_id=str(p.feature_build_id),
        weighted_start_share_last_6=value(p, "weighted_start_share_last_6"),
        weighted_start_denominator_last_6=float(p.weighted_start_denominator_last_6),
        eligible_team_fixtures_last_6=int(p.eligible_team_fixtures_last_6),
        cameo_appearances_last_6=int(p.cameo_appearances_last_6),
        mean_minutes_when_started_last_6=value(p, "mean_minutes_when_started_last_6"),
        mean_minutes_when_cameo_last_6=value(p, "mean_minutes_when_cameo_last_6"),
        weighted_trailing_congestion_21d=value(t, "weighted_trailing_congestion_21d"),
        weighted_leading_congestion_21d=value(t, "weighted_leading_congestion_21d"),
        availability=availability,
    )


def _availability_multiplier(value: AvailabilityInput) -> tuple[float, float, tuple[str, ...]]:
    if value.state is None:
        return 1.0, 0.0, ("availability_context_missing",)
    if value.state is AvailabilityState.AVAILABLE:
        return 1.0, 1.0, ()
    if value.state is AvailabilityState.DOUBTFUL:
        multiplier = value.chance_of_playing if value.chance_of_playing is not None else DOUBTFUL_FALLBACK_MULTIPLIER
        quality = 1.0 if value.chance_of_playing is not None else 0.5
        return multiplier, quality, ("availability_doubt",)
    if value.state is AvailabilityState.UNKNOWN:
        return UNKNOWN_AVAILABILITY_MULTIPLIER, 0.5, ("availability_unknown",)
    return 0.0, 1.0, ("availability_unavailable",)


def _evidence(item: ExpectedMinutesInput, code, label, impact, confidence, summary, sources):
    direction = EvidenceDirection.POSITIVE if impact > 0 else EvidenceDirection.NEGATIVE if impact < 0 else EvidenceDirection.NEUTRAL
    return EvidenceItem(
        code=code,
        label=label,
        subject_type=SubjectType.PLAYER,
        subject_id=item.player_id,
        fixture_id=item.fixture_id,
        impact=impact,
        direction=direction,
        confidence=confidence,
        basis=SignalBasis.OBSERVED,
        summary=summary,
        source_features=tuple(sources),
        model_version=MODEL_VERSION,
        calculated_at=item.calculated_at,
    )


def evaluate_expected_minutes(item: ExpectedMinutesInput) -> ExpectedMinutesResult:
    """Evaluate M1 without I/O, global state, a wall clock, or provider knowledge."""
    if item.feature_registry_version not in (None, FEATURE_REGISTRY_VERSION):
        raise UnsupportedFeatureContractError("unsupported_feature_contract: FI-6 requires fi5-registry-v2")
    if (
        item.feature_registry_version is None
        or item.feature_build_id is None
        or item.weighted_start_denominator_last_6 <= 0
        or item.weighted_start_share_last_6 is None
        or item.mean_minutes_when_started_last_6 is None
    ):
        return ExpectedMinutesResult(
            status=ModuleStatus.MISSING_CONTEXT,
            model_version=MODEL_VERSION,
            feature_registry_version=item.feature_registry_version,
            feature_build_id=item.feature_build_id,
            fixture_id=item.fixture_id,
            team_id=item.team_id,
            player_id=item.player_id,
            confidence=0.0,
            reason_codes=("insufficient_start_history",),
            evidence=(),
            coefficient_version=COEFFICIENT_VERSION,
            availability_input_version=item.availability.version,
            start_probability=None,
            expected_minutes=None,
            cameo_probability=None,
            rotation_risk=None,
            minutes_risk_v2=None,
        )

    availability_multiplier, availability_quality, availability_reasons = _availability_multiplier(item.availability)
    congestion_known = item.weighted_trailing_congestion_21d is not None and item.weighted_leading_congestion_21d is not None
    congestion = (
        item.weighted_trailing_congestion_21d + item.weighted_leading_congestion_21d
        if congestion_known
        else 0.0
    )
    congestion_multiplier = max(
        MIN_CONGESTION_MULTIPLIER,
        1.0 - CONGESTION_DAMPING_PER_WEIGHTED_FIXTURE * congestion,
    )
    start_probability = _clamp(item.weighted_start_share_last_6 * availability_multiplier * congestion_multiplier)
    eligible = max(1, item.eligible_team_fixtures_last_6)
    cameo_share = item.cameo_appearances_last_6 / eligible
    cameo_probability = min(
        1.0 - start_probability,
        _clamp(cameo_share * availability_multiplier * congestion_multiplier),
    )
    cameo_minutes = item.mean_minutes_when_cameo_last_6 or 0.0
    expected_minutes = start_probability * item.mean_minutes_when_started_last_6 + cameo_probability * cameo_minutes
    rotation_risk = _clamp(1.0 - item.weighted_start_share_last_6 * congestion_multiplier)
    minutes_risk_v2 = 100.0 * _clamp(1.0 - expected_minutes / 90.0)
    history_quality = min(1.0, item.eligible_team_fixtures_last_6 / 6.0)
    confidence = _clamp(0.60 * history_quality + 0.20 * availability_quality + 0.20 * float(congestion_known))
    reasons = list(availability_reasons)
    if not congestion_known:
        reasons.append("congestion_context_missing")
    if item.eligible_team_fixtures_last_6 < 6:
        reasons.append("partial_start_history")

    evidence = []
    if confidence >= 0.75 and expected_minutes >= HIGH_MINUTES_THRESHOLD:
        evidence.append(_evidence(item, "MINUTES_CONFIDENCE_HIGH", "High minutes confidence", 3.0, confidence,
            "Recent selection history provides strong minutes evidence.", ("weighted_start_share_last_6", "mean_minutes_when_started_last_6")))
    elif confidence < 0.50 or expected_minutes < LOW_MINUTES_THRESHOLD:
        evidence.append(_evidence(item, "MINUTES_CONFIDENCE_LOW", "Low minutes confidence", -3.0, confidence,
            "Available history provides limited minutes confidence.", ("weighted_start_share_last_6",)))
    if rotation_risk >= 0.35:
        rotation_sources = ["weighted_start_share_last_6"]
        if congestion_known:
            rotation_sources.extend(("weighted_trailing_congestion_21d", "weighted_leading_congestion_21d"))
        evidence.append(_evidence(item, "ROTATION_RISK", "Rotation risk", -min(10.0, rotation_risk * 10.0), confidence,
            "Recent starts indicate rotation exposure, with schedule density included when available.", rotation_sources))
    if cameo_probability >= 0.20:
        evidence.append(_evidence(item, "CAMEO_RISK", "Cameo risk", -min(10.0, cameo_probability * 10.0), confidence,
            "Recent substitute appearances support a meaningful cameo probability.", ("cameo_appearances_last_6", "mean_minutes_when_cameo_last_6")))
    if item.availability.state not in (None, AvailabilityState.AVAILABLE):
        evidence.append(_evidence(item, "AVAILABILITY_DOUBT", "Availability doubt", -10.0 * (1.0 - availability_multiplier), confidence,
            "The explicit availability context reduces expected participation.", ("availability_state",)))

    evidence.sort(key=lambda value: (-abs(value.impact) * value.confidence, value.code))
    return ExpectedMinutesResult(
        status=ModuleStatus.OK,
        model_version=MODEL_VERSION,
        feature_registry_version=item.feature_registry_version,
        feature_build_id=item.feature_build_id,
        fixture_id=item.fixture_id,
        team_id=item.team_id,
        player_id=item.player_id,
        confidence=confidence,
        reason_codes=tuple(reasons),
        evidence=tuple(evidence),
        coefficient_version=COEFFICIENT_VERSION,
        availability_input_version=item.availability.version,
        start_probability=start_probability,
        expected_minutes=expected_minutes,
        cameo_probability=cameo_probability,
        rotation_risk=rotation_risk,
        minutes_risk_v2=minutes_risk_v2,
    )

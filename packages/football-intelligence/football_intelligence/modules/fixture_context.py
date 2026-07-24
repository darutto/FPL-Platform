"""FI-6c M3: deterministic team-fixture scheduling context evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import json
import math
from numbers import Integral
from pathlib import Path

import pandas as pd

from football_data_contract.enums import (
    EvidenceDirection,
    SignalBasis,
    SubjectType,
)
from football_data_contract.evidence import EvidenceItem
from football_intelligence.features.registry_v2 import (
    COMPETITION_WEIGHT_VERSION,
    CUTOFF_POLICY_VERSION,
    ENGINE_VERSION,
    FEATURE_REGISTRY_VERSION,
    MANIFEST_SCHEMA_VERSION,
)
from football_intelligence.features.store_v2 import (
    BUILD_FAMILY,
    FeatureV2ValidationError,
    validate_feature_build_v2,
)
from football_intelligence.ingestion.context_v2 import BANDS, STAGES, TIERS

from .contracts import ModuleResult, ModuleStatus, UnsupportedFeatureContractError


MODEL_VERSION = "fixture-context-v1"
FIXTURE_PRIORITY_VERSION = "fixture-priority-v1"
CONGESTION_EVIDENCE_THRESHOLD = 7.0
FULL_SCHEDULE_SAMPLE = 6
SPARSE_SCHEDULE_MAX = 2
FRESH_24H = 24.0
FRESH_72H = 72.0
FRESH_168H = 168.0

REASON_ORDER = (
    "feature_build_unavailable",
    "feature_manifest_unavailable",
    "fixture_context_row_unavailable",
    "unknown_league_position_band",
    "unknown_competition_stage",
    "target_competition_tier_unavailable",
    "stale_feature_build",
    "sparse_trailing_schedule",
    "sparse_leading_schedule",
    "previous_rest_anchor_unavailable",
    "next_rest_anchor_unavailable",
    "fixture_congestion",
)
MISSING_REASONS = frozenset(REASON_ORDER[:6])
LEAGUE_BANDS = (*BANDS, "unknown")
COMPETITION_STAGES = tuple(sorted(STAGES))
COMPETITION_TIERS = frozenset(TIERS)


class FixturePriority(StrEnum):
    UNKNOWN = "unknown"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


_CUP_PRIORITY = {
    "qualification": FixturePriority.NORMAL,
    "group": FixturePriority.NORMAL,
    "league_phase": FixturePriority.NORMAL,
    "round_of_32": FixturePriority.NORMAL,
    "round_of_16": FixturePriority.HIGH,
    "quarter_final": FixturePriority.HIGH,
    "semi_final": FixturePriority.CRITICAL,
    "final": FixturePriority.CRITICAL,
    "replay": FixturePriority.HIGH,
}
PRIORITY_TABLE = {
    (band, stage): (
        FixturePriority.UNKNOWN
        if band == "unknown" or stage == "unknown"
        else (
            FixturePriority.CRITICAL
            if stage == "league" and band in {"top", "bottom"}
            else FixturePriority.NORMAL
            if stage == "league"
            else _CUP_PRIORITY[stage]
        )
    )
    for band in LEAGUE_BANDS
    for stage in COMPETITION_STAGES
}


def _utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise FeatureV2ValidationError(f"{label} must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise FeatureV2ValidationError(f"{label} must be an ISO-8601 UTC timestamp")
    return parsed


def _optional_utc(value: str | None, label: str) -> datetime | None:
    return None if value is None else _utc(value, label)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


@dataclass(frozen=True)
class FixtureContextInput:
    fixture_id: str
    team_id: str
    calculated_at: str
    feature_registry_version: str | None
    feature_build_id: str | None
    feature_built_at: str | None
    weighted_trailing_congestion_21d: float | None = None
    weighted_leading_congestion_21d: float | None = None
    trailing_fixtures_considered: int | None = None
    leading_fixtures_considered: int | None = None
    previous_rest_days: float | None = None
    next_rest_days: float | None = None
    target_competition_tier: str | None = None
    target_competition_stage: str | None = None
    league_position_band: str | None = None
    schedule_context_as_of_utc: str | None = None
    standing_context_as_of_utc: str | None = None
    competition_weight_version: str | None = None
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        _utc(self.calculated_at, "calculated_at")
        if self.missing_reason is not None and self.missing_reason not in MISSING_REASONS:
            raise ValueError("unknown fixture-context missing reason")


@dataclass(frozen=True)
class FixtureContextResult(ModuleResult):
    calculated_at: str
    fixture_priority: FixturePriority | None
    fixture_priority_version: str
    congestion_index: float | None
    weighted_trailing_congestion_21d: float | None
    weighted_leading_congestion_21d: float | None
    previous_rest_days: float | None
    next_rest_days: float | None
    target_competition_tier: str | None
    target_competition_stage: str | None
    league_position_band: str | None
    competition_weight_version: str | None
    schedule_context_as_of_utc: str | None
    standing_context_as_of_utc: str | None


def _missing_input(
    fixture_id: str,
    team_id: str,
    calculated_at: str,
    reason: str,
) -> FixtureContextInput:
    return FixtureContextInput(
        fixture_id=fixture_id,
        team_id=team_id,
        calculated_at=calculated_at,
        feature_registry_version=None,
        feature_build_id=None,
        feature_built_at=None,
        missing_reason=reason,
    )


def _unsupported(message: str) -> UnsupportedFeatureContractError:
    return UnsupportedFeatureContractError(f"unsupported_feature_contract: {message}")


def _dispatch_manifest(candidate: object) -> None:
    if not isinstance(candidate, dict):
        raise FeatureV2ValidationError("invalid v2 feature manifest")
    checks = (
        ("schema_version", MANIFEST_SCHEMA_VERSION, "unsupported feature manifest schema"),
        ("build_family", BUILD_FAMILY, "unsupported feature family"),
        ("feature_registry_version", FEATURE_REGISTRY_VERSION, "unsupported feature registry version"),
        ("feature_engine_version", ENGINE_VERSION, "unsupported feature engine version"),
        ("cutoff_policy_version", CUTOFF_POLICY_VERSION, "unsupported cutoff policy version"),
    )
    for name, supported, message in checks:
        value = candidate.get(name)
        if value is not None and value != supported:
            raise _unsupported(message)


def load_fixture_context_input(
    feature_build: Path | None,
    base,
    context_build: Path | None,
    *,
    fixture_id: str,
    team_id: str,
    calculated_at: str,
) -> FixtureContextInput:
    """Validate a bound FI-5b v2 build and select one exact M3 row."""
    if feature_build is None or not Path(feature_build).is_dir():
        return _missing_input(fixture_id, team_id, calculated_at, "feature_build_unavailable")
    build = Path(feature_build)
    manifest_path = build / "manifest.json"
    if not manifest_path.is_file():
        if (build / "_features_latest.json").exists() or (build / "_features_v2_latest.json").exists():
            raise _unsupported("unversioned feature root is not accepted")
        return _missing_input(fixture_id, team_id, calculated_at, "feature_manifest_unavailable")
    try:
        candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeatureV2ValidationError("invalid v2 feature manifest") from exc
    _dispatch_manifest(candidate)
    if base is None or context_build is None:
        raise FeatureV2ValidationError("FI-6 requires validated v2 source bindings")

    manifest = validate_feature_build_v2(build, base, context_build)
    frame = pd.read_parquet(build / manifest["output_files"]["team_fixture_context_v2"])
    selected = frame[
        (frame.fixture_id.astype(str) == fixture_id)
        & (frame.team_id.astype(str) == team_id)
    ]
    if selected.empty:
        return _missing_input(fixture_id, team_id, calculated_at, "fixture_context_row_unavailable")
    if len(selected) != 1:
        raise FeatureV2ValidationError("duplicate fixture-context target row")
    row = selected.iloc[0]

    def value(name):
        return None if pd.isna(row[name]) else row[name]

    item = FixtureContextInput(
        fixture_id=fixture_id,
        team_id=team_id,
        calculated_at=calculated_at,
        feature_registry_version=str(row.feature_registry_version),
        feature_build_id=str(row.feature_build_id),
        feature_built_at=str(manifest["built_at"]),
        weighted_trailing_congestion_21d=float(row.weighted_trailing_congestion_21d),
        weighted_leading_congestion_21d=float(row.weighted_leading_congestion_21d),
        trailing_fixtures_considered=int(row.trailing_fixtures_considered),
        leading_fixtures_considered=int(row.leading_fixtures_considered),
        previous_rest_days=value("previous_rest_days"),
        next_rest_days=value("next_rest_days"),
        target_competition_tier=value("target_competition_tier"),
        target_competition_stage=str(row.target_competition_stage),
        league_position_band=str(row.league_position_band),
        schedule_context_as_of_utc=value("schedule_context_as_of_utc"),
        standing_context_as_of_utc=value("standing_context_as_of_utc"),
        competition_weight_version=str(row.competition_weight_version),
    )
    _validate_input(item)
    return item


def _validate_input(item: FixtureContextInput) -> dict[str, float]:
    if item.missing_reason is not None:
        return {}
    if item.feature_registry_version != FEATURE_REGISTRY_VERSION:
        raise _unsupported("unsupported feature registry version")
    if item.competition_weight_version != COMPETITION_WEIGHT_VERSION:
        raise _unsupported("unsupported competition weight version")
    if item.feature_build_id is None or item.feature_built_at is None:
        raise FeatureV2ValidationError("incomplete feature-build provenance")

    age_hours = (
        _utc(item.calculated_at, "calculated_at") - _utc(item.feature_built_at, "built_at")
    ).total_seconds() / 3600.0
    if age_hours < 0:
        raise FeatureV2ValidationError("built_at must not be later than calculated_at")

    counts = (item.trailing_fixtures_considered, item.leading_fixtures_considered)
    if any(not isinstance(value, Integral) or isinstance(value, bool) or value < 0 for value in counts):
        raise FeatureV2ValidationError("fixture-context counts must be nonnegative integers")
    weights = (
        item.weighted_trailing_congestion_21d,
        item.weighted_leading_congestion_21d,
    )
    if any(value is None or not math.isfinite(float(value)) or value < 0 for value in weights):
        raise FeatureV2ValidationError("weighted congestion must be finite and nonnegative")
    for count, weighted in zip(counts, weights):
        if not count <= weighted <= 1.25 * count:
            raise FeatureV2ValidationError("weighted congestion contradicts fixture count")

    for value in (item.previous_rest_days, item.next_rest_days):
        if value is not None and (
            not math.isfinite(float(value)) or not 0.0 < float(value) <= 365.0
        ):
            raise FeatureV2ValidationError("rest days must be within (0, 365]")
    if item.target_competition_tier is not None and item.target_competition_tier not in COMPETITION_TIERS:
        raise FeatureV2ValidationError("unknown target competition tier")
    if item.target_competition_stage not in STAGES:
        raise FeatureV2ValidationError("unknown competition stage vocabulary")
    if item.league_position_band not in LEAGUE_BANDS:
        raise FeatureV2ValidationError("unknown league-position-band vocabulary")

    _optional_utc(item.schedule_context_as_of_utc, "schedule_context_as_of_utc")
    _optional_utc(item.standing_context_as_of_utc, "standing_context_as_of_utc")
    if (item.leading_fixtures_considered > 0) != (item.schedule_context_as_of_utc is not None):
        raise FeatureV2ValidationError("leading schedule count contradicts audit timestamp")
    if (item.league_position_band != "unknown") != (item.standing_context_as_of_utc is not None):
        raise FeatureV2ValidationError("league-position band contradicts standings timestamp")
    return {"age_hours": age_hours}


def _freshness(age_hours: float) -> float:
    if age_hours <= FRESH_24H:
        return 1.0
    if age_hours <= FRESH_72H:
        return 0.8
    if age_hours <= FRESH_168H:
        return 0.5
    return 0.25


def _missing_result(item: FixtureContextInput, reason: str) -> FixtureContextResult:
    return FixtureContextResult(
        status=ModuleStatus.MISSING_CONTEXT,
        model_version=MODEL_VERSION,
        feature_registry_version=item.feature_registry_version,
        feature_build_id=item.feature_build_id,
        fixture_id=item.fixture_id,
        team_id=item.team_id,
        confidence=0.0,
        reason_codes=(reason,),
        evidence=(),
        calculated_at=item.calculated_at,
        fixture_priority=None,
        fixture_priority_version=FIXTURE_PRIORITY_VERSION,
        congestion_index=None,
        weighted_trailing_congestion_21d=None,
        weighted_leading_congestion_21d=None,
        previous_rest_days=None,
        next_rest_days=None,
        target_competition_tier=None,
        target_competition_stage=None,
        league_position_band=None,
        competition_weight_version=None,
        schedule_context_as_of_utc=None,
        standing_context_as_of_utc=None,
    )


def _evidence(item: FixtureContextInput, confidence: float) -> EvidenceItem:
    return EvidenceItem(
        code="FIXTURE_CONGESTION",
        label="Dense surrounding schedule",
        subject_type=SubjectType.TEAM,
        subject_id=item.team_id,
        fixture_id=item.fixture_id,
        impact=0.0,
        direction=EvidenceDirection.NEUTRAL,
        confidence=confidence,
        basis=SignalBasis.OBSERVED,
        summary="The team has a dense governed schedule surrounding the target fixture.",
        source_features=(
            "weighted_trailing_congestion_21d",
            "weighted_leading_congestion_21d",
        ),
        model_version=MODEL_VERSION,
        calculated_at=item.calculated_at,
    )


def evaluate_fixture_context(item: FixtureContextInput) -> FixtureContextResult:
    """Evaluate M3 without I/O, module dependencies, a wall clock, or providers."""
    validated = _validate_input(item)
    if item.missing_reason is not None:
        return _missing_result(item, item.missing_reason)
    if item.league_position_band == "unknown":
        return _missing_result(item, "unknown_league_position_band")
    if item.target_competition_stage == "unknown":
        return _missing_result(item, "unknown_competition_stage")
    if item.target_competition_tier is None:
        return _missing_result(item, "target_competition_tier_unavailable")

    priority = PRIORITY_TABLE[(item.league_position_band, item.target_competition_stage)]
    if priority is FixturePriority.UNKNOWN:
        raise FeatureV2ValidationError("complete priority context produced unknown priority")
    congestion = (
        item.weighted_trailing_congestion_21d
        + item.weighted_leading_congestion_21d
    )
    sample_count = item.trailing_fixtures_considered + item.leading_fixtures_considered
    confidence = round(_clamp(
        0.50 * _freshness(validated["age_hours"])
        + 0.30 * min(sample_count / FULL_SCHEDULE_SAMPLE, 1.0)
        + 0.10 * float(item.previous_rest_days is not None)
        + 0.10 * float(item.next_rest_days is not None)
    ), 4)

    conditions = {
        "stale_feature_build": validated["age_hours"] > FRESH_72H,
        "sparse_trailing_schedule": item.trailing_fixtures_considered <= SPARSE_SCHEDULE_MAX,
        "sparse_leading_schedule": item.leading_fixtures_considered <= SPARSE_SCHEDULE_MAX,
        "previous_rest_anchor_unavailable": item.previous_rest_days is None,
        "next_rest_anchor_unavailable": item.next_rest_days is None,
        "fixture_congestion": congestion >= CONGESTION_EVIDENCE_THRESHOLD,
    }
    reasons = tuple(reason for reason in REASON_ORDER if conditions.get(reason, False))
    evidence = (
        (_evidence(item, confidence),)
        if congestion >= CONGESTION_EVIDENCE_THRESHOLD
        else ()
    )
    return FixtureContextResult(
        status=ModuleStatus.OK,
        model_version=MODEL_VERSION,
        feature_registry_version=item.feature_registry_version,
        feature_build_id=item.feature_build_id,
        fixture_id=item.fixture_id,
        team_id=item.team_id,
        confidence=confidence,
        reason_codes=reasons,
        evidence=evidence,
        calculated_at=item.calculated_at,
        fixture_priority=priority,
        fixture_priority_version=FIXTURE_PRIORITY_VERSION,
        congestion_index=congestion,
        weighted_trailing_congestion_21d=item.weighted_trailing_congestion_21d,
        weighted_leading_congestion_21d=item.weighted_leading_congestion_21d,
        previous_rest_days=item.previous_rest_days,
        next_rest_days=item.next_rest_days,
        target_competition_tier=item.target_competition_tier,
        target_competition_stage=item.target_competition_stage,
        league_position_band=item.league_position_band,
        competition_weight_version=item.competition_weight_version,
        schedule_context_as_of_utc=item.schedule_context_as_of_utc,
        standing_context_as_of_utc=item.standing_context_as_of_utc,
    )

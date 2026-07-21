"""FI-6b M2: deterministic tactical-role and role-stability evaluation."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import json
import math
from numbers import Integral
from pathlib import Path

import pandas as pd

from football_data_contract.enums import (
    EvidenceDirection,
    Flank,
    FormationDepth,
    SignalBasis,
    SubjectType,
)
from football_data_contract.evidence import EvidenceItem
from football_intelligence.features.registry_v2 import (
    FEATURE_REGISTRY_VERSION,
    ROLE_MAPPING_VERSION,
)
from football_intelligence.features.store_v2 import (
    BUILD_FAMILY,
    FeatureV2ValidationError,
    validate_feature_build_v2,
)

from .contracts import ModuleResult, ModuleStatus, UnsupportedFeatureContractError


MODEL_VERSION = "tactical-role-v1"
NOMINAL_POSITION_INPUT_VERSION = "fpl-nominal-position-v1"
OUT_OF_POSITION_MAPPING_VERSION = "nominal-role-distance-v1"

ROLE_VOCABULARY = frozenset({
    "goalkeeper", "center_back", "full_back", "wing_back",
    "central_midfield", "wide_midfield", "winger", "forward",
})
STORE_FLANK_VOCABULARY = frozenset({"left", "right", "center"})
STORE_DEPTH_VOCABULARY = frozenset({"goalkeeper", "defense", "midfield", "attack"})
WINDOW_SEGMENTS = ("last_10", "last_3", "prior_7")
NOMINAL_POSITIONS = frozenset({"GK", "DEF", "MID", "FWD"})
NOMINAL_ROLE_CLASSES = {
    "GK": frozenset({"goalkeeper"}),
    "DEF": frozenset({"center_back", "full_back", "wing_back"}),
    "MID": frozenset({"central_midfield", "wide_midfield", "winger"}),
    "FWD": frozenset({"forward"}),
}
OUTFIELD_AXIS = {"DEF": 1, "MID": 2, "FWD": 3}
MAX_ROLE_DISTANCE = 2

MIN_MAPPED_STARTS = 3
FULL_SAMPLE_STARTS = 10
SPARSE_HISTORY_MAX = 5
STABLE_MIN_STARTS = 5
STABLE_THRESHOLD = 0.75
ROLE_CHANGE_MIN_STARTS = 2
OOP_EVIDENCE_THRESHOLD = 2 / MAX_ROLE_DISTANCE
FLOAT_TOLERANCE = 1e-9

SAMPLE_WEIGHT = 0.40
COVERAGE_WEIGHT = 0.25
FRESHNESS_WEIGHT = 0.15
BASIS_WEIGHT = 0.10
NOMINAL_WEIGHT = 0.10
OBSERVED_BASIS_QUALITY = 1.0
PROXY_BASIS_QUALITY = 0.6
FRESH_24H = 24.0
FRESH_72H = 72.0
FRESH_168H = 168.0
STALE_REASON_AFTER_HOURS = FRESH_72H

FLANK_MAP = {"left": Flank.LEFT, "right": Flank.RIGHT, "center": Flank.CENTRAL}
DEPTH_MAP = {
    "goalkeeper": FormationDepth.DEEP,
    "defense": FormationDepth.DEEP,
    "midfield": FormationDepth.MID,
    "attack": FormationDepth.ADVANCED,
}
ROLE_NOMINAL_CLASS = {
    role: nominal for nominal, roles in NOMINAL_ROLE_CLASSES.items() for role in roles
}


def _utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise FeatureV2ValidationError(f"{field} must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise FeatureV2ValidationError(f"{field} must be an ISO-8601 UTC timestamp")
    return parsed


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _lexical_mode(counts: Counter) -> str | None:
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


@dataclass(frozen=True)
class RoleShare:
    role: str
    share: float

    def __post_init__(self) -> None:
        if self.role not in ROLE_VOCABULARY or not math.isfinite(self.share) or not 0.0 <= self.share <= 1.0:
            raise ValueError("invalid immutable role share")


@dataclass(frozen=True)
class FlankShare:
    flank: Flank
    share: float

    def __post_init__(self) -> None:
        if not isinstance(self.flank, Flank) or not math.isfinite(self.share) or not 0.0 <= self.share <= 1.0:
            raise ValueError("invalid immutable flank share")


@dataclass(frozen=True)
class RoleWindowSummary:
    window_segment: str
    eligible_starts: int
    mapped_starts: int
    unmapped_starts: int
    modal_role: str | None
    role_change_comparable: bool
    role_mapping_version: str
    role_basis: SignalBasis


@dataclass(frozen=True)
class RoleDistributionRow:
    window_segment: str
    role: str
    flank: str
    formation_depth: str
    role_count: int
    role_share: float
    role_mapping_version: str
    role_basis: SignalBasis


@dataclass(frozen=True)
class TacticalRoleInput:
    fixture_id: str
    team_id: str
    player_id: str
    calculated_at: str
    feature_registry_version: str | None
    feature_build_id: str | None
    feature_built_at: str | None
    nominal_position: str | None
    nominal_position_input_version: str = NOMINAL_POSITION_INPUT_VERSION
    summaries: tuple[RoleWindowSummary, ...] = ()
    distribution: tuple[RoleDistributionRow, ...] = ()

    def __post_init__(self) -> None:
        _utc(self.calculated_at, "calculated_at")
        if self.nominal_position_input_version != NOMINAL_POSITION_INPUT_VERSION:
            raise UnsupportedFeatureContractError("unsupported_feature_contract: unsupported nominal-position input version")
        if self.nominal_position is not None and self.nominal_position not in NOMINAL_POSITIONS:
            raise FeatureV2ValidationError("unknown FPL nominal position")
        if not isinstance(self.summaries, tuple) or not isinstance(self.distribution, tuple):
            raise TypeError("tactical-role rows must be immutable tuples")


@dataclass(frozen=True)
class TacticalRoleResult(ModuleResult):
    player_id: str
    role_mapping_version: str
    nominal_position_input_version: str
    role_basis: SignalBasis
    primary_role: str | None
    role_distribution: tuple[RoleShare, ...]
    primary_flank: Flank | None
    flank_distribution: tuple[FlankShare, ...]
    formation_depth: FormationDepth | None
    role_stability: float | None
    role_change_detected: bool | None
    out_of_position_score: float | None


def _missing_input(fixture_id, team_id, player_id, calculated_at, nominal_position, input_version):
    return TacticalRoleInput(
        fixture_id=fixture_id,
        team_id=team_id,
        player_id=player_id,
        calculated_at=calculated_at,
        feature_registry_version=None,
        feature_build_id=None,
        feature_built_at=None,
        nominal_position=nominal_position,
        nominal_position_input_version=input_version,
    )


def _basis(value) -> SignalBasis:
    try:
        return SignalBasis(str(value))
    except ValueError as exc:
        raise FeatureV2ValidationError("unknown role basis") from exc


def load_tactical_role_input(
    feature_build: Path | None,
    base,
    context_build: Path | None,
    *,
    fixture_id: str,
    team_id: str,
    player_id: str,
    nominal_position: str | None,
    calculated_at: str,
    nominal_position_input_version: str = NOMINAL_POSITION_INPUT_VERSION,
) -> TacticalRoleInput:
    """Validate a bound FI-5b v2 build and select exact governed M2 rows."""
    if feature_build is None or not Path(feature_build).is_dir():
        return _missing_input(fixture_id, team_id, player_id, calculated_at, nominal_position, nominal_position_input_version)
    build = Path(feature_build)
    manifest_path = build / "manifest.json"
    if not manifest_path.is_file():
        if (build / "_features_latest.json").exists() or (build / "_features_v2_latest.json").exists():
            raise UnsupportedFeatureContractError("unsupported_feature_contract: unversioned feature root is not accepted")
        return _missing_input(fixture_id, team_id, player_id, calculated_at, nominal_position, nominal_position_input_version)
    try:
        candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeatureV2ValidationError("invalid v2 feature manifest") from exc
    if not isinstance(candidate, dict):
        raise FeatureV2ValidationError("invalid v2 feature manifest")
    if candidate.get("schema_version") == 1:
        raise UnsupportedFeatureContractError("unsupported_feature_contract: FI-6 requires feature schema 2")
    if candidate.get("build_family") not in (None, BUILD_FAMILY):
        raise UnsupportedFeatureContractError("unsupported_feature_contract: unsupported feature family")
    if candidate.get("feature_registry_version") not in (None, FEATURE_REGISTRY_VERSION):
        raise UnsupportedFeatureContractError("unsupported_feature_contract: FI-6 requires fi5-registry-v2")
    if base is None or context_build is None:
        raise FeatureV2ValidationError("FI-6 requires validated v2 source bindings")

    manifest = validate_feature_build_v2(build, base, context_build)
    if manifest["build_family"] != BUILD_FAMILY or manifest["feature_registry_version"] != FEATURE_REGISTRY_VERSION:
        raise UnsupportedFeatureContractError("unsupported_feature_contract: FI-6 requires module-enablement features v2")

    summary_frame = pd.read_parquet(build / manifest["output_files"]["player_role_window_summary"])
    distribution_frame = pd.read_parquet(build / manifest["output_files"]["player_role_distribution"])
    key = (
        (summary_frame.fixture_id.astype(str) == fixture_id)
        & (summary_frame.team_id.astype(str) == team_id)
        & (summary_frame.player_id.astype(str) == player_id)
    )
    selected = summary_frame[key]
    if selected.empty:
        return _missing_input(fixture_id, team_id, player_id, calculated_at, nominal_position, nominal_position_input_version)
    dkey = (
        (distribution_frame.fixture_id.astype(str) == fixture_id)
        & (distribution_frame.team_id.astype(str) == team_id)
        & (distribution_frame.player_id.astype(str) == player_id)
    )
    selected_distribution = distribution_frame[dkey]
    summaries = tuple(RoleWindowSummary(
        window_segment=str(row.window_segment),
        eligible_starts=int(row.eligible_starts),
        mapped_starts=int(row.mapped_starts),
        unmapped_starts=int(row.unmapped_starts),
        modal_role=None if pd.isna(row.modal_role) else str(row.modal_role),
        role_change_comparable=bool(row.role_change_comparable),
        role_mapping_version=str(row.role_mapping_version),
        role_basis=_basis(row.role_basis),
    ) for row in selected.itertuples(index=False))
    distribution = tuple(RoleDistributionRow(
        window_segment=str(row.window_segment),
        role=str(row.role), flank=str(row.flank), formation_depth=str(row.formation_depth),
        role_count=int(row.role_count), role_share=float(row.role_share),
        role_mapping_version=str(row.role_mapping_version), role_basis=_basis(row.role_basis),
    ) for row in selected_distribution.itertuples(index=False))
    item = TacticalRoleInput(
        fixture_id=fixture_id, team_id=team_id, player_id=player_id,
        calculated_at=calculated_at,
        feature_registry_version=manifest["feature_registry_version"],
        feature_build_id=manifest["feature_build_id"],
        feature_built_at=manifest["built_at"],
        nominal_position=nominal_position,
        nominal_position_input_version=nominal_position_input_version,
        summaries=summaries, distribution=distribution,
    )
    _validate_input(item)
    return item


def _validate_input(item: TacticalRoleInput):
    if item.feature_registry_version is None:
        return {}
    if item.feature_registry_version != FEATURE_REGISTRY_VERSION:
        raise UnsupportedFeatureContractError("unsupported_feature_contract: FI-6 requires fi5-registry-v2")
    if item.feature_build_id is None or item.feature_built_at is None:
        raise FeatureV2ValidationError("incomplete feature-build provenance")
    age_hours = (_utc(item.calculated_at, "calculated_at") - _utc(item.feature_built_at, "built_at")).total_seconds() / 3600
    if age_hours < 0:
        raise FeatureV2ValidationError("built_at must not be later than calculated_at")
    by_segment = {}
    for summary in item.summaries:
        if summary.window_segment not in WINDOW_SEGMENTS or summary.window_segment in by_segment:
            raise FeatureV2ValidationError("duplicate or unknown role summary segment")
        if any(not isinstance(value, Integral) or value < 0 for value in (
            summary.eligible_starts, summary.mapped_starts, summary.unmapped_starts,
        )):
            raise FeatureV2ValidationError("role summary counts must be nonnegative integers")
        if summary.mapped_starts + summary.unmapped_starts != summary.eligible_starts:
            raise FeatureV2ValidationError("contradictory role summary counts")
        if summary.modal_role is not None and summary.modal_role not in ROLE_VOCABULARY:
            raise FeatureV2ValidationError("unknown modal role")
        if summary.role_mapping_version != ROLE_MAPPING_VERSION:
            raise UnsupportedFeatureContractError("unsupported_feature_contract: unsupported role mapping version")
        if not isinstance(summary.role_basis, SignalBasis):
            raise FeatureV2ValidationError("unknown role basis")
        by_segment[summary.window_segment] = summary
    if set(by_segment) != set(WINDOW_SEGMENTS):
        raise FeatureV2ValidationError("missing required role summary segment")
    expected_comparable = bool(by_segment["last_3"].eligible_starts and by_segment["prior_7"].eligible_starts)
    if (
        by_segment["last_10"].eligible_starts
        != by_segment["last_3"].eligible_starts + by_segment["prior_7"].eligible_starts
        or by_segment["last_10"].mapped_starts
        != by_segment["last_3"].mapped_starts + by_segment["prior_7"].mapped_starts
    ):
        raise FeatureV2ValidationError("role windows contradict their non-overlapping partition")
    flags = {row.role_change_comparable for row in item.summaries}
    if len(flags) != 1 or flags != {expected_comparable}:
        raise FeatureV2ValidationError("invalid role-change metadata")

    rows_by_segment = {segment: [] for segment in WINDOW_SEGMENTS}
    for row in item.distribution:
        if row.window_segment not in rows_by_segment:
            raise FeatureV2ValidationError("unknown role distribution segment")
        if row.role not in ROLE_VOCABULARY or row.flank not in STORE_FLANK_VOCABULARY or row.formation_depth not in STORE_DEPTH_VOCABULARY:
            raise FeatureV2ValidationError("unknown role, flank, or formation-depth vocabulary")
        if row.role_mapping_version != ROLE_MAPPING_VERSION:
            raise UnsupportedFeatureContractError("unsupported_feature_contract: unsupported role mapping version")
        if not isinstance(row.role_basis, SignalBasis):
            raise FeatureV2ValidationError("unknown role basis")
        if not isinstance(row.role_count, Integral) or row.role_count <= 0:
            raise FeatureV2ValidationError("role counts must be positive integers")
        if not math.isfinite(row.role_share) or not 0.0 <= row.role_share <= 1.0:
            raise FeatureV2ValidationError("role shares must be finite fractions")
        rows_by_segment[row.window_segment].append(row)
    for segment, summary in by_segment.items():
        rows = rows_by_segment[segment]
        if sum(row.role_count for row in rows) != summary.mapped_starts:
            raise FeatureV2ValidationError("distribution counts contradict mapped starts")
        for row in rows:
            expected_share = row.role_count / summary.eligible_starts if summary.eligible_starts else 0.0
            if not math.isclose(row.role_share, expected_share, abs_tol=FLOAT_TOLERANCE):
                raise FeatureV2ValidationError("governed role share has wrong denominator")
        counts = Counter()
        for row in rows:
            counts[row.role] += row.role_count
        modal = _lexical_mode(counts)
        if modal != summary.modal_role:
            raise FeatureV2ValidationError("governed modal role contradicts distribution")
    return {"summary": by_segment, "distribution": rows_by_segment, "age_hours": age_hours}


def _freshness(hours: float) -> float:
    if hours <= FRESH_24H:
        return 1.0
    if hours <= FRESH_72H:
        return 0.8
    if hours <= FRESH_168H:
        return 0.5
    return 0.25


def _oop_distance(nominal: str, role: str) -> int:
    role_class = ROLE_NOMINAL_CLASS.get(role)
    if role_class is None:
        raise FeatureV2ValidationError("unsupported out-of-position mapping")
    if nominal == role_class:
        return 0
    if nominal == "GK" or role_class == "GK":
        return MAX_ROLE_DISTANCE
    return min(MAX_ROLE_DISTANCE, abs(OUTFIELD_AXIS[nominal] - OUTFIELD_AXIS[role_class]))


def _evidence(item, code, label, summary, confidence, basis, sources):
    return EvidenceItem(
        code=code, label=label, subject_type=SubjectType.PLAYER,
        subject_id=item.player_id, fixture_id=item.fixture_id,
        impact=0.0, direction=EvidenceDirection.NEUTRAL,
        confidence=confidence, basis=basis, summary=summary,
        source_features=tuple(sources), model_version=MODEL_VERSION,
        calculated_at=item.calculated_at,
    )


def evaluate_tactical_role(item: TacticalRoleInput) -> TacticalRoleResult:
    """Evaluate M2 without I/O, global state, a wall clock, or provider knowledge."""
    validated = _validate_input(item)
    if not validated or validated["summary"]["last_10"].mapped_starts < MIN_MAPPED_STARTS:
        return TacticalRoleResult(
            status=ModuleStatus.MISSING_CONTEXT, model_version=MODEL_VERSION,
            feature_registry_version=item.feature_registry_version,
            feature_build_id=item.feature_build_id, fixture_id=item.fixture_id,
            team_id=item.team_id, player_id=item.player_id, confidence=0.0,
            reason_codes=("insufficient_role_history",), evidence=(),
            role_mapping_version=ROLE_MAPPING_VERSION,
            nominal_position_input_version=item.nominal_position_input_version,
            role_basis=SignalBasis.OBSERVED, primary_role=None,
            role_distribution=(), primary_flank=None, flank_distribution=(),
            formation_depth=None, role_stability=None,
            role_change_detected=None, out_of_position_score=None,
        )

    summaries = validated["summary"]
    rows = validated["distribution"]
    last = summaries["last_10"]
    primary_role = last.modal_role
    role_counts = Counter()
    flank_counts = Counter()
    for row in rows["last_10"]:
        role_counts[row.role] += row.role_count
        flank_counts[row.flank] += row.role_count
    mapped_total = sum(role_counts.values())
    role_distribution = tuple(RoleShare(role, count / mapped_total) for role, count in sorted(
        role_counts.items(), key=lambda item: (-item[1] / mapped_total, item[0])))
    flank_distribution = tuple(FlankShare(FLANK_MAP[flank], count / mapped_total) for flank, count in sorted(
        flank_counts.items(), key=lambda item: (-item[1] / mapped_total, FLANK_MAP[item[0]].value)))
    primary_flank = FLANK_MAP[_lexical_mode(flank_counts)]

    primary_depth_counts = Counter()
    for row in rows["last_10"]:
        if row.role == primary_role:
            primary_depth_counts[row.formation_depth] += row.role_count
    modal_depth = _lexical_mode(primary_depth_counts)
    formation_depth = DEPTH_MAP[modal_depth]
    ambiguous_depth = len(primary_depth_counts) > 1 and len(set(primary_depth_counts.values())) == 1
    role_stability = role_counts[primary_role] / mapped_total

    recent = summaries["last_3"]
    prior = summaries["prior_7"]
    comparable = (
        last.role_change_comparable
        and recent.mapped_starts >= ROLE_CHANGE_MIN_STARTS
        and prior.mapped_starts >= ROLE_CHANGE_MIN_STARTS
        and recent.modal_role is not None and prior.modal_role is not None
    )
    role_change = recent.modal_role != prior.modal_role if comparable else None
    oop_score = None
    if item.nominal_position is not None:
        oop_score = _oop_distance(item.nominal_position, primary_role) / MAX_ROLE_DISTANCE

    bases = {summary.role_basis for summary in item.summaries}
    role_basis = SignalBasis.INFERRED_PROXY if SignalBasis.INFERRED_PROXY in bases else SignalBasis.OBSERVED
    sample_quality = min(mapped_total / FULL_SAMPLE_STARTS, 1.0)
    coverage = mapped_total / last.eligible_starts
    basis_quality = OBSERVED_BASIS_QUALITY if role_basis is SignalBasis.OBSERVED else PROXY_BASIS_QUALITY
    confidence = _clamp(
        SAMPLE_WEIGHT * sample_quality
        + COVERAGE_WEIGHT * coverage
        + FRESHNESS_WEIGHT * _freshness(validated["age_hours"])
        + BASIS_WEIGHT * basis_quality
        + NOMINAL_WEIGHT * float(item.nominal_position is not None)
    )

    reasons = []
    if mapped_total <= SPARSE_HISTORY_MAX:
        reasons.append("sparse_role_history")
    if last.unmapped_starts:
        reasons.append("partial_role_mapping")
    if validated["age_hours"] > STALE_REASON_AFTER_HOURS:
        reasons.append("stale_feature_build")
    if role_basis is SignalBasis.INFERRED_PROXY:
        reasons.append("proxy_role_basis")
    if item.nominal_position is None:
        reasons.append("nominal_position_missing")
    if role_change is None:
        reasons.append("role_change_not_comparable")
    if ambiguous_depth:
        reasons.append("ambiguous_formation_depth")

    evidence = []
    if mapped_total >= STABLE_MIN_STARTS and role_stability >= STABLE_THRESHOLD:
        evidence.append(_evidence(item, "ROLE_STABLE", "Stable tactical role",
            "Recent deployment is concentrated in one tactical role.", confidence, role_basis,
            ("modal_role", "role_count", "role_share")))
    if role_change is True:
        evidence.append(_evidence(item, "ROLE_CHANGED", "Changed tactical role",
            "Recent deployment differs from the preceding role window.", confidence, role_basis,
            ("modal_role", "role_change_comparable", "role_count")))
    if oop_score is not None and oop_score >= OOP_EVIDENCE_THRESHOLD:
        evidence.append(_evidence(item, "OUT_OF_POSITION", "Nominal-role mismatch",
            "Deployment role differs materially from the nominal fantasy classification without implying fantasy value.",
            confidence, role_basis, ("modal_role", "fpl_nominal_position")))
    evidence.sort(key=lambda value: (-abs(value.impact) * value.confidence, value.code))

    return TacticalRoleResult(
        status=ModuleStatus.OK, model_version=MODEL_VERSION,
        feature_registry_version=item.feature_registry_version,
        feature_build_id=item.feature_build_id, fixture_id=item.fixture_id,
        team_id=item.team_id, player_id=item.player_id, confidence=confidence,
        reason_codes=tuple(reasons), evidence=tuple(evidence),
        role_mapping_version=ROLE_MAPPING_VERSION,
        nominal_position_input_version=item.nominal_position_input_version,
        role_basis=role_basis, primary_role=primary_role,
        role_distribution=role_distribution, primary_flank=primary_flank,
        flank_distribution=flank_distribution, formation_depth=formation_depth,
        role_stability=role_stability, role_change_detected=role_change,
        out_of_position_score=oop_score,
    )

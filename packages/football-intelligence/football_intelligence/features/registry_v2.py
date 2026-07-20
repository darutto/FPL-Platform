"""Closed FI-5b(b) module-enablement feature registry."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import asdict
import hashlib
import json

FEATURE_REGISTRY_VERSION = "fi5-registry-v2"
ENGINE_VERSION = "fi5-engine-v2"
CUTOFF_POLICY_VERSION = "strictly-before-kickoff-v2"
MANIFEST_SCHEMA_VERSION = 2
RECENCY_WEIGHT_VERSION = "m1-recency-weights-v1"
ROLE_MAPPING_VERSION = "role-map-v2"
COMPETITION_WEIGHT_VERSION = "competition-weights-v1"
COMPETITION_WEIGHTS = {"league": 1.0, "domestic_cup": 1.0, "continental": 1.25}
WINDOW_SEGMENTS = frozenset({"last_10", "last_3", "prior_7"})
ROLE_BASIS = frozenset({"observed", "inferred_proxy"})
ROLE_VOCABULARY = frozenset({"goalkeeper", "center_back", "full_back", "wing_back", "central_midfield", "wide_midfield", "winger", "forward"})
FLANK_VOCABULARY = frozenset({"left", "right", "center"})
FORMATION_DEPTH_VOCABULARY = frozenset({"goalkeeper", "defense", "midfield", "attack"})


@dataclass(frozen=True)
class FeatureV2Spec:
    name: str
    family: str
    grain: tuple[str, ...]
    dtype: str
    nullable: bool
    window: str
    missing_policy: str
    consumer: str
    unit: str
    vocabulary: tuple[str, ...]
    source_datasets: tuple[str, ...]
    cutoff: str
    minimum_evidence: int


PLAYER_GRAIN = ("fixture_id", "team_id", "player_id")
TEAM_GRAIN = ("fixture_id", "team_id")
ROLE_SUMMARY_GRAIN = PLAYER_GRAIN + ("window_segment",)
ROLE_DISTRIBUTION_GRAIN = ROLE_SUMMARY_GRAIN + ("role", "flank", "formation_depth")


SOURCES = {
    "m1": ("base.fixtures", "base.squads", "base.lineups", "context.fixtures", "context.fixture_schedule_snapshots"),
    "m2": ("base.fixtures", "base.squads", "base.lineups", "context.fixtures", "context.fixture_schedule_snapshots"),
    "m3": ("base.fixtures", "context.fixtures", "context.competition_memberships", "context.fixture_schedule_snapshots", "context.team_standing_snapshots"),
}
GRAINS = frozenset({PLAYER_GRAIN, TEAM_GRAIN, ROLE_SUMMARY_GRAIN, ROLE_DISTRIBUTION_GRAIN})
DTYPES = frozenset({"string", "Int64", "Float64", "boolean"})
ALLOWED_SOURCES = frozenset(value for sources in SOURCES.values() for value in sources)


def _spec(name, family, grain, dtype, nullable, window, missing, consumer, *, unit="category", vocabulary=(), minimum=0):
    return FeatureV2Spec(name, family, grain, dtype, nullable, window, missing, consumer, unit, tuple(vocabulary),
        SOURCES[family], CUTOFF_POLICY_VERSION, minimum)


FEATURE_SPECS_V2 = (
    _spec("weighted_start_share_last_6", "m1", PLAYER_GRAIN, "Float64", True, "last_6_team_league_fixtures", "null_without_evidence", "M1", unit="fraction_0_1", minimum=1),
    _spec("weighted_start_numerator_last_6", "m1", PLAYER_GRAIN, "Float64", False, "last_6_team_league_fixtures", "zero", "audit/M1", unit="weight_0_21"),
    _spec("weighted_start_denominator_last_6", "m1", PLAYER_GRAIN, "Float64", False, "last_6_team_league_fixtures", "zero", "audit/M1", unit="weight_0_21"),
    _spec("starts_last_6", "m1", PLAYER_GRAIN, "Int64", False, "last_6_team_league_fixtures", "zero", "M1", unit="count_0_6"),
    _spec("appearances_last_6", "m1", PLAYER_GRAIN, "Int64", False, "last_6_team_league_fixtures", "zero", "sufficiency", unit="count_0_6"),
    _spec("cameo_appearances_last_6", "m1", PLAYER_GRAIN, "Int64", False, "last_6_team_league_fixtures", "zero", "M1", unit="count_0_6"),
    _spec("mean_minutes_when_started_last_6", "m1", PLAYER_GRAIN, "Float64", True, "last_6_team_league_fixtures", "null_without_starts", "M1", unit="minutes_0_120", minimum=1),
    _spec("mean_minutes_when_cameo_last_6", "m1", PLAYER_GRAIN, "Float64", True, "last_6_team_league_fixtures", "null_without_cameos", "M1", unit="minutes_0_120", minimum=1),
    _spec("recency_weight_version", "m1", PLAYER_GRAIN, "string", True, "last_6_team_league_fixtures", "null_without_evidence", "audit/M1", vocabulary=(RECENCY_WEIGHT_VERSION,), minimum=1),
    _spec("eligible_starts", "m2", ROLE_SUMMARY_GRAIN, "Int64", False, "role_window", "zero", "M2"),
    _spec("mapped_starts", "m2", ROLE_SUMMARY_GRAIN, "Int64", False, "role_window", "zero", "M2"),
    _spec("unmapped_starts", "m2", ROLE_SUMMARY_GRAIN, "Int64", False, "role_window", "zero", "M2"),
    _spec("modal_role", "m2", ROLE_SUMMARY_GRAIN, "string", True, "role_window", "null_without_mapped_starts", "M2", vocabulary=tuple(sorted(ROLE_VOCABULARY)), minimum=1),
    _spec("role_change_comparable", "m2", ROLE_SUMMARY_GRAIN, "boolean", False, "last_3_and_prior_7", "false_without_both_windows", "M2"),
    _spec("role_mapping_version", "m2", ROLE_SUMMARY_GRAIN, "string", False, "role_window", "required", "audit/M2", vocabulary=(ROLE_MAPPING_VERSION,)),
    _spec("role_basis", "m2", ROLE_SUMMARY_GRAIN, "string", False, "role_window", "required", "audit/M2", vocabulary=tuple(sorted(ROLE_BASIS))),
    _spec("role_count", "m2", ROLE_DISTRIBUTION_GRAIN, "Int64", False, "role_window", "row_absent_for_empty_window", "M2", unit="count_1_10", minimum=1),
    _spec("role_share", "m2", ROLE_DISTRIBUTION_GRAIN, "Float64", False, "role_window", "row_absent_for_empty_window", "M2", unit="fraction_0_1", minimum=1),
    _spec("weighted_trailing_congestion_21d", "m3", TEAM_GRAIN, "Float64", False, "prior_21_days", "zero", "M3"),
    _spec("weighted_leading_congestion_21d", "m3", TEAM_GRAIN, "Float64", False, "leading_21_days_as_known", "zero", "M3"),
    _spec("trailing_fixtures_considered", "m3", TEAM_GRAIN, "Int64", False, "prior_21_days", "zero", "audit/M3", unit="count"),
    _spec("leading_fixtures_considered", "m3", TEAM_GRAIN, "Int64", False, "leading_21_days_as_known", "zero", "audit/M3", unit="count"),
    _spec("previous_rest_days", "m3", TEAM_GRAIN, "Float64", True, "previous_completed_fixture", "null_without_prior_fixture", "M3", unit="days_0_365", minimum=1),
    _spec("next_rest_days", "m3", TEAM_GRAIN, "Float64", True, "next_known_fixture", "null_without_next_fixture", "M3", unit="days_0_365", minimum=1),
    _spec("target_competition_tier", "m3", TEAM_GRAIN, "string", True, "target_as_known", "null_missing_context", "M3", vocabulary=("league", "domestic_cup", "continental", "unknown")),
    _spec("target_competition_stage", "m3", TEAM_GRAIN, "string", False, "target_canonical", "unknown_missing_context", "M3", vocabulary=("league", "qualification", "group", "league_phase", "round_of_32", "round_of_16", "quarter_final", "semi_final", "final", "replay", "unknown")),
    _spec("league_position_band", "m3", TEAM_GRAIN, "string", False, "latest_complete_table_before_cutoff", "unknown_missing_context", "M3", vocabulary=("top", "upper_mid", "lower_mid", "bottom", "unknown")),
    _spec("schedule_context_as_of_utc", "m3", TEAM_GRAIN, "string", True, "leading_21_days_as_known", "null_without_leading_context", "audit/M3", unit="utc_iso"),
    _spec("standing_context_as_of_utc", "m3", TEAM_GRAIN, "string", True, "latest_complete_table_before_cutoff", "null_missing_context", "audit/M3", unit="utc_iso"),
    _spec("competition_weight_version", "m3", TEAM_GRAIN, "string", False, "prior_and_leading_21_days", "required", "audit/M3", vocabulary=(COMPETITION_WEIGHT_VERSION,)),
)


def validate_registry_v2(specs=FEATURE_SPECS_V2):
    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise ValueError("duplicate v2 feature name")
    forbidden = ("sportmonks", "understat", "vaastav", "expected_minutes", "probability", "recommendation", "confidence")
    if any(token in name for name in names for token in forbidden):
        raise ValueError("provider or intelligence output leaked into v2 registry")
    if set(COMPETITION_WEIGHTS) != {"league", "domestic_cup", "continental"}:
        raise ValueError("competition weight registry is not closed")
    for spec in specs:
        if spec.grain not in GRAINS or spec.dtype not in DTYPES: raise ValueError("unsupported v2 feature contract")
        if not spec.source_datasets or not set(spec.source_datasets).issubset(ALLOWED_SOURCES): raise ValueError("undeclared v2 feature dependency")
        if spec.cutoff != CUTOFF_POLICY_VERSION or spec.minimum_evidence < 0: raise ValueError("unsupported v2 cutoff or evidence policy")
        if spec.dtype in {"string", "boolean"} and spec.unit == "category" and spec.dtype == "string" and not spec.vocabulary:
            raise ValueError("uncontrolled v2 vocabulary")
    return specs


def registry_payload_v2(specs=FEATURE_SPECS_V2):
    validate_registry_v2(specs)
    return {"registry_version": FEATURE_REGISTRY_VERSION, "features": [asdict(spec) for spec in specs]}


def registry_hash_v2(specs=FEATURE_SPECS_V2):
    encoded = json.dumps(registry_payload_v2(specs), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


validate_registry_v2()

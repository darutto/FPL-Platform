"""Closed FI-5 feature specification registry."""
from __future__ import annotations
import re
from dataclasses import dataclass

GRAINS = frozenset({"player_as_of_fixture"})
DTYPES = frozenset({"string", "Int64", "Float64"})
MISSING_POLICIES = frozenset({"null", "zero", "not_applicable", "excluded", "insufficient_history"})


@dataclass(frozen=True)
class FeatureSpec:
    name: str; version: str; grain: str; inputs: tuple[str, ...]; required_columns: tuple[str, ...]
    dtype: str; nullable: bool; unit: str; valid_range: tuple[float, float] | None
    window: str; cutoff: str; missing_policy: str; minimum_sample: int
    provenance_fields: tuple[str, ...]; description: str; assumption_status: str
    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.name): raise ValueError("invalid feature name")
        if not re.fullmatch(r"v[1-9][0-9]*", self.version): raise ValueError("invalid feature version")
        if self.grain not in GRAINS or self.dtype not in DTYPES: raise ValueError("unsupported feature contract")
        if not self.window or self.window == "unbounded" or self.cutoff != "strictly_before_kickoff_v1": raise ValueError("ambiguous window/cutoff")
        if self.missing_policy not in MISSING_POLICIES or self.minimum_sample < 0 or not self.provenance_fields: raise ValueError("invalid missing/provenance policy")


COMMON = {
    "fixtures": ("fixture_id", "season_id", "competition_id", "home_team_id", "away_team_id", "kickoff_utc", "status"),
    "squads": ("team_id", "player_id", "valid_from", "valid_to"),
}
ROLE = {**COMMON, "lineups": ("fixture_id", "player_id", "started", "detailed_position")}
PARTICIPATION = {**COMMON, "lineups": ("fixture_id", "player_id", "started", "minutes")}
REST = {**COMMON, "lineups": ("fixture_id", "player_id")}
CONGESTION = COMMON
AVAILABILITY = {**COMMON,
    "injuries": ("player_id", "recorded_at_utc", "resolved_at_utc"),
    "suspensions": ("player_id", "recorded_at_utc", "ends_on")}


def _columns(requirements):
    return tuple(f"{dataset}.{column}" for dataset, columns in requirements.items() for column in columns)


def _spec(name, dtype, unit, bounds, window, requirements=ROLE, missing="insufficient_history", minimum=1):
    return FeatureSpec(name, "v1", "player_as_of_fixture", tuple(requirements),
        _columns(requirements), dtype, True, unit, bounds, window,
        "strictly_before_kickoff_v1", missing, minimum,
        ("canonical_build_id", "canonical_manifest_hash", "target_fixture_id", "cutoff_utc", "eligible_observations"),
        name.replace("_", " "), "mock_validated")


FEATURE_SPECS = (
    _spec("primary_role", "string", "category", None, "last_10_starts"),
    _spec("role_stability", "Float64", "fraction_0_1", (0, 1), "last_10_starts"),
    _spec("flank", "string", "category", None, "last_10_starts"),
    _spec("flank_distribution", "string", "canonical_json", None, "last_10_starts"),
    _spec("formation_depth", "string", "category", None, "last_10_starts"),
    _spec("out_of_position_score", "Float64", "fraction_0_1", (0, 1), "last_10_starts", {**ROLE, "players": ("player_id", "positions_nominal")}),
    _spec("start_share_last_5", "Float64", "fraction_0_1", (0, 1), "last_5_appearances", PARTICIPATION),
    _spec("mean_minutes_last_5", "Float64", "minutes", (0, 120), "last_5_appearances", PARTICIPATION),
    _spec("cameo_share_last_5", "Float64", "fraction_0_1", (0, 1), "last_5_appearances", PARTICIPATION),
    _spec("rotation_tendency", "Float64", "fraction_0_1", (0, 1), "last_5_appearances", PARTICIPATION),
    _spec("rest_days", "Float64", "days", (0, 365), "previous_appearance", REST, "null", 1),
    _spec("fixture_congestion_index", "Int64", "fixtures_in_prior_21_days", (0, 20), "prior_21_days", CONGESTION, "zero", 0),
    _spec("availability_multiplier", "Float64", "fraction_0_1", (0, 1), "effective_records_at_cutoff", AVAILABILITY, "not_applicable", 0),
)
FEATURE_REGISTRY_VERSION = "fi5-registry-v1"


def validate_registry(specs=FEATURE_SPECS):
    names = [s.name for s in specs]
    if len(names) != len(set(names)): raise ValueError("duplicate feature/output column")
    if any(token in name for name in names for token in ("sportmonks", "understat", "vaastav", "fpl_")): raise ValueError("provider-specific feature name")
    for spec in specs:
        datasets = {column.split(".", 1)[0] for column in spec.required_columns if "." in column}
        if not spec.inputs or len(datasets) == 0 or datasets != set(spec.inputs): raise ValueError(f"inaccurate required columns for {spec.name}")
    return specs

validate_registry()

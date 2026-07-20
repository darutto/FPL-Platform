"""Immutable feature-contract-v2 builds, validation, and replay."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

import pandas as pd

from football_intelligence.distribution.runtime import RuntimeBuildHandle
from football_intelligence.ingestion.builder_v2 import validate_context_build
from football_intelligence.ingestion.context_v2 import BANDS, STAGES, TIERS
from .engine_v2 import compute_features_v2
from .registry_v2 import (
    CUTOFF_POLICY_VERSION, ENGINE_VERSION, FEATURE_REGISTRY_VERSION,
    FLANK_VOCABULARY, FORMATION_DEPTH_VOCABULARY, MANIFEST_SCHEMA_VERSION,
    ROLE_BASIS, ROLE_VOCABULARY, WINDOW_SEGMENTS, registry_hash_v2,
)

BUILD_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
BUILD_FAMILY = "module-enablement-features-v2"
POINTER = "_features_v2_latest.json"
COMMON = (
    "feature_build_id", "canonical_build_id", "canonical_manifest_hash", "context_build_id", "context_manifest_hash",
    "feature_engine_version", "feature_registry_version", "cutoff_policy_version", "assumption_status",
)
SCHEMAS = {
    "player_fixture_module_inputs": (
        ("fixture_id", "string"), ("team_id", "string"), ("player_id", "string"), ("cutoff_utc", "string"),
        ("window_start_utc", "string"), ("eligible_team_fixtures_last_6", "Int64"),
        ("weighted_start_share_last_6", "Float64"), ("weighted_start_numerator_last_6", "Float64"),
        ("weighted_start_denominator_last_6", "Float64"), ("starts_last_6", "Int64"),
        ("appearances_last_6", "Int64"), ("cameo_appearances_last_6", "Int64"),
        ("mean_minutes_when_started_last_6", "Float64"), ("mean_minutes_when_cameo_last_6", "Float64"),
        ("recency_weight_version", "string"), *((name, "string") for name in COMMON),
    ),
    "player_role_window_summary": (
        ("fixture_id", "string"), ("team_id", "string"), ("player_id", "string"), ("window_segment", "string"),
        ("cutoff_utc", "string"), ("eligible_starts", "Int64"), ("mapped_starts", "Int64"),
        ("unmapped_starts", "Int64"), ("modal_role", "string"), ("role_change_comparable", "boolean"),
        ("role_mapping_version", "string"), ("role_basis", "string"), *((name, "string") for name in COMMON),
    ),
    "player_role_distribution": (
        ("fixture_id", "string"), ("team_id", "string"), ("player_id", "string"), ("window_segment", "string"),
        ("role", "string"), ("flank", "string"), ("formation_depth", "string"), ("cutoff_utc", "string"),
        ("role_count", "Int64"), ("role_share", "Float64"), ("role_mapping_version", "string"),
        ("role_basis", "string"), *((name, "string") for name in COMMON),
    ),
    "team_fixture_context_v2": (
        ("fixture_id", "string"), ("team_id", "string"), ("cutoff_utc", "string"),
        ("weighted_trailing_congestion_21d", "Float64"), ("weighted_leading_congestion_21d", "Float64"),
        ("trailing_fixtures_considered", "Int64"), ("leading_fixtures_considered", "Int64"),
        ("previous_rest_days", "Float64"), ("next_rest_days", "Float64"),
        ("target_competition_tier", "string"), ("target_competition_stage", "string"),
        ("league_position_band", "string"), ("schedule_context_as_of_utc", "string"),
        ("standing_context_as_of_utc", "string"), ("competition_weight_version", "string"),
        *((name, "string") for name in COMMON),
    ),
}
KEYS = {
    "player_fixture_module_inputs": ("fixture_id", "team_id", "player_id"),
    "player_role_window_summary": ("fixture_id", "team_id", "player_id", "window_segment"),
    "player_role_distribution": ("fixture_id", "team_id", "player_id", "window_segment", "role", "flank", "formation_depth"),
    "team_fixture_context_v2": ("fixture_id", "team_id"),
}
NULLABLE = {
    "player_fixture_module_inputs": {"window_start_utc", "weighted_start_share_last_6", "mean_minutes_when_started_last_6", "mean_minutes_when_cameo_last_6", "recency_weight_version"},
    "player_role_window_summary": {"modal_role"},
    "player_role_distribution": set(),
    "team_fixture_context_v2": {"previous_rest_days", "next_rest_days", "target_competition_tier", "schedule_context_as_of_utc", "standing_context_as_of_utc"},
}


class FeatureV2ValidationError(ValueError):
    pass


def _hash(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic(frame):
    records = frame.astype(object).where(pd.notna(frame), None).to_dict("records")
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _validate_id(value):
    if not isinstance(value, str) or BUILD_ID.fullmatch(value) is None: raise FeatureV2ValidationError("invalid feature build ID")
    return value


def _utc(value, label):
    if not isinstance(value, str) or not value.endswith("Z"): raise FeatureV2ValidationError(f"{label} must be UTC ISO")
    try: parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc: raise FeatureV2ValidationError(f"{label} must be UTC ISO") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed): raise FeatureV2ValidationError(f"{label} must be UTC")


def _resolve(build, name, relative):
    expected = f"datasets/{name}.parquet"
    if relative != expected or "\\" in relative or PurePosixPath(relative).is_absolute() or PureWindowsPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
        raise FeatureV2ValidationError("invalid v2 dataset path")
    path = (build / Path(*relative.split("/"))).resolve()
    try: path.relative_to(build.resolve())
    except ValueError as exc: raise FeatureV2ValidationError("v2 dataset path escapes") from exc
    if not path.is_file() or path.is_symlink(): raise FeatureV2ValidationError("v2 dataset is not a regular file")
    return path


def _source_binding(base, context_build):
    base_manifest = base.manifest(); base_path = base.cache_root / "builds" / base_manifest["build_id"] / "manifest.json"
    context_manifest = validate_context_build(context_build); context_path = context_build / "manifest.json"
    return base_manifest, _hash(base_path), context_manifest, _hash(context_path)


def validate_feature_build_v2(build: Path, base: RuntimeBuildHandle | None = None, context_build: Path | None = None):
    manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
    fields = {"schema_version", "build_family", "feature_build_id", "canonical_source", "context_source", "feature_engine_version",
        "feature_registry_version", "feature_registry_hash", "cutoff_policy_version", "output_files", "row_counts", "schemas", "content_hashes",
        "parquet_byte_hashes", "warning_counts", "exclusion_counts", "assumption_status", "built_at"}
    if set(manifest) != fields or manifest["schema_version"] != MANIFEST_SCHEMA_VERSION or manifest["build_family"] != BUILD_FAMILY:
        raise FeatureV2ValidationError("unsupported feature manifest schema")
    if set(manifest["canonical_source"]) != {"build_id", "manifest_hash", "schema_version"} or set(manifest["context_source"]) != {"build_id", "manifest_hash", "build_family", "canonical_schema_version", "manifest_schema_version"}:
        raise FeatureV2ValidationError("unsupported feature source binding")
    if (manifest["feature_engine_version"], manifest["feature_registry_version"], manifest["cutoff_policy_version"]) != (ENGINE_VERSION, FEATURE_REGISTRY_VERSION, CUTOFF_POLICY_VERSION):
        raise FeatureV2ValidationError("unsupported feature contract version")
    if manifest["feature_registry_hash"] != registry_hash_v2(): raise FeatureV2ValidationError("feature registry hash mismatch")
    _validate_id(manifest["feature_build_id"]); _utc(manifest["built_at"], "built_at")
    if base is not None and context_build is not None:
        base_manifest, base_hash, context_manifest, context_hash = _source_binding(base, context_build)
        if manifest["canonical_source"] != {"build_id": base_manifest["build_id"], "manifest_hash": base_hash, "schema_version": 1} or manifest["context_source"] != {"build_id": context_manifest["build_id"], "manifest_hash": context_hash, "build_family": "canonical-context-v2", "canonical_schema_version": 2, "manifest_schema_version": 2}:
            raise FeatureV2ValidationError("v2 source binding mismatch")
    if set(manifest["output_files"]) != set(SCHEMAS) or set(manifest["row_counts"]) != set(SCHEMAS) or set(manifest["schemas"]) != set(SCHEMAS) or set(manifest["content_hashes"]) != set(SCHEMAS) or set(manifest["parquet_byte_hashes"]) != set(SCHEMAS):
        raise FeatureV2ValidationError("v2 dataset registry mismatch")
    frames = {}
    for name, schema in SCHEMAS.items():
        path = _resolve(build, name, manifest["output_files"][name])
        if _hash(path) != manifest["parquet_byte_hashes"][name]: raise FeatureV2ValidationError("v2 parquet hash mismatch")
        frame = pd.read_parquet(path); expected_columns = tuple(column for column, _ in schema)
        if tuple(frame.columns) != expected_columns or frame.duplicated(list(KEYS[name])).any(): raise FeatureV2ValidationError("v2 schema/key mismatch")
        if any(str(frame[column].dtype) != dtype for column, dtype in schema): raise FeatureV2ValidationError("v2 dtype mismatch")
        required = [column for column, _ in schema if column not in NULLABLE[name]]
        if frame[required].isna().any().any(): raise FeatureV2ValidationError("v2 required value is null")
        numeric = frame.select_dtypes(include=["number"])
        if any(not math.isfinite(float(value)) for value in numeric.to_numpy().ravel() if pd.notna(value)): raise FeatureV2ValidationError("v2 numeric value is not finite")
        if len(frame) != manifest["row_counts"][name] or _semantic(frame) != manifest["content_hashes"][name]: raise FeatureV2ValidationError("v2 content mismatch")
        frames[name] = frame
    player = frames["player_fixture_module_inputs"]
    if ((player["weighted_start_share_last_6"].dropna() < 0).any() or (player["weighted_start_share_last_6"].dropna() > 1).any()
        or (player["weighted_start_denominator_last_6"] < 0).any() or (player["weighted_start_denominator_last_6"] > 21).any()):
        raise FeatureV2ValidationError("M1 range mismatch")
    for row in player.itertuples(index=False):
        if row.eligible_team_fixtures_last_6 < 0 or row.eligible_team_fixtures_last_6 > 6 or row.starts_last_6 < 0 or row.appearances_last_6 < 0 or row.cameo_appearances_last_6 < 0: raise FeatureV2ValidationError("M1 count mismatch")
        if row.weighted_start_denominator_last_6 == 0:
            if pd.notna(row.weighted_start_share_last_6) or pd.notna(row.recency_weight_version): raise FeatureV2ValidationError("M1 missingness mismatch")
        elif abs(row.weighted_start_share_last_6 - row.weighted_start_numerator_last_6 / row.weighted_start_denominator_last_6) > 1e-12:
            raise FeatureV2ValidationError("M1 ratio mismatch")
    summary = frames["player_role_window_summary"]
    if not set(summary.window_segment).issubset(WINDOW_SEGMENTS) or not set(summary.role_basis).issubset(ROLE_BASIS) or not set(summary.modal_role.dropna()).issubset(ROLE_VOCABULARY): raise FeatureV2ValidationError("M2 vocabulary mismatch")
    distribution = frames["player_role_distribution"]
    if (not set(distribution.role).issubset(ROLE_VOCABULARY) or not set(distribution.flank).issubset(FLANK_VOCABULARY)
        or not set(distribution.formation_depth).issubset(FORMATION_DEPTH_VOCABULARY)
        or ((distribution.role_share < 0).any() or (distribution.role_share > 1).any())): raise FeatureV2ValidationError("M2 distribution mismatch")
    team = frames["team_fixture_context_v2"]
    if not set(team.target_competition_tier.dropna()).issubset(TIERS) or not set(team.target_competition_stage).issubset(STAGES) or not set(team.league_position_band).issubset(set(BANDS) | {"unknown"}): raise FeatureV2ValidationError("M3 vocabulary mismatch")
    for name, frame in frames.items():
        for column in ("cutoff_utc", "window_start_utc", "schedule_context_as_of_utc", "standing_context_as_of_utc"):
            if column in frame:
                for value in frame[column].dropna(): _utc(value, column)
        expected = {"feature_build_id": manifest["feature_build_id"], "canonical_build_id": manifest["canonical_source"]["build_id"],
            "canonical_manifest_hash": manifest["canonical_source"]["manifest_hash"],
            "context_build_id": manifest["context_source"]["build_id"],
            "context_manifest_hash": manifest["context_source"]["manifest_hash"],
            "feature_engine_version": ENGINE_VERSION, "feature_registry_version": FEATURE_REGISTRY_VERSION,
            "cutoff_policy_version": CUTOFF_POLICY_VERSION, "assumption_status": manifest["assumption_status"]}
        if any(set(frame[column].dropna()) != {value} for column, value in expected.items() if len(frame)): raise FeatureV2ValidationError("v2 row version binding mismatch")
    return manifest


def build_features_v2(base, context_build, root, *, feature_build_id, built_at, fail_before_pointer=False):
    _validate_id(feature_build_id); _utc(built_at, "built_at")
    base_manifest, base_hash, context_manifest, context_hash = _source_binding(base, context_build)
    frames, _ = compute_features_v2(base, context_build)
    staging = root / ".staging-v2"; staging.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=feature_build_id + "-", dir=staging))
    try:
        datasets = stage / "datasets"; reports = stage / "reports"; datasets.mkdir(); reports.mkdir()
        output_files, row_counts, schemas, content_hashes, parquet_hashes = {}, {}, {}, {}, {}
        for name, schema in SCHEMAS.items():
            columns = [column for column, _ in schema]; dtypes = {column: dtype for column, dtype in schema}
            frames[name]["feature_build_id"] = feature_build_id
            value = frames[name].reindex(columns=columns).astype(dtypes)
            path = datasets / f"{name}.parquet"; value.to_parquet(path, index=False, compression="zstd")
            reread = pd.read_parquet(path)
            output_files[name] = f"datasets/{name}.parquet"; row_counts[name] = len(reread)
            schemas[name] = f"fi5b-{name}-v2"; content_hashes[name] = _semantic(reread); parquet_hashes[name] = _hash(path)
        (reports / "warnings.json").write_text("[]\n", encoding="utf-8"); (reports / "exclusions.json").write_text("[]\n", encoding="utf-8")
        manifest = {"schema_version": 2, "build_family": BUILD_FAMILY, "feature_build_id": feature_build_id,
            "canonical_source": {"build_id": base_manifest["build_id"], "manifest_hash": base_hash, "schema_version": 1},
            "context_source": {"build_id": context_manifest["build_id"], "manifest_hash": context_hash, "build_family": "canonical-context-v2", "canonical_schema_version": 2, "manifest_schema_version": 2},
            "feature_engine_version": ENGINE_VERSION, "feature_registry_version": FEATURE_REGISTRY_VERSION,
            "feature_registry_hash": registry_hash_v2(), "cutoff_policy_version": CUTOFF_POLICY_VERSION, "output_files": output_files, "row_counts": row_counts,
            "schemas": schemas, "content_hashes": content_hashes, "parquet_byte_hashes": parquet_hashes,
            "warning_counts": {"total": 0}, "exclusion_counts": {"total": 0}, "assumption_status": "mock_validated", "built_at": built_at}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validate_feature_build_v2(stage, base, context_build)
        builds = root / "builds-v2"; builds.mkdir(parents=True, exist_ok=True); final = builds / feature_build_id
        if final.exists(): raise FileExistsError("feature v2 build already exists")
        os.replace(stage, final)
        if fail_before_pointer: raise RuntimeError("seeded v2 pointer failure")
        pointer = root / POINTER; temporary = root / f".{POINTER}.tmp"
        temporary.write_text(json.dumps({"schema_version": 2, "build_family": BUILD_FAMILY, "feature_build_id": feature_build_id}, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, pointer)
        return manifest
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def replay_feature_build_v2(source_build, base, context_build, destination):
    original = validate_feature_build_v2(source_build, base, context_build)
    replay = build_features_v2(base, context_build, destination, feature_build_id=original["feature_build_id"], built_at=original["built_at"])
    if (replay["content_hashes"], replay["parquet_byte_hashes"]) != (original["content_hashes"], original["parquet_byte_hashes"]): raise FeatureV2ValidationError("v2 replay mismatch")
    return replay


def validate_active_features_v2(root, base, context_build):
    pointer = json.loads((root / POINTER).read_text(encoding="utf-8"))
    if set(pointer) != {"schema_version", "build_family", "feature_build_id"} or pointer["schema_version"] != 2 or pointer["build_family"] != BUILD_FAMILY: raise FeatureV2ValidationError("invalid v2 feature pointer")
    build_id = _validate_id(pointer["feature_build_id"]); build = (root / "builds-v2" / build_id).resolve()
    try: build.relative_to((root / "builds-v2").resolve())
    except ValueError as exc: raise FeatureV2ValidationError("v2 pointer escapes") from exc
    return validate_feature_build_v2(build, base, context_build)

"""Atomic immutable local FI-5 feature builds and validation."""
from __future__ import annotations
import hashlib, json, os, re, shutil, tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
import pandas as pd
from football_intelligence.distribution.runtime import RuntimeBuildHandle
from .engine import CUTOFF_POLICY_VERSION, ENGINE_VERSION, compute_features
from .registry import FEATURE_REGISTRY_VERSION, FEATURE_SPECS

MANIFEST_SCHEMA_VERSION = 1; BUILD_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
DATASET_COLUMNS = ("fixture_id", "team_id", "player_id", "cutoff_utc", "window_start_utc", "eligible_observations",
 "canonical_build_id", "canonical_manifest_hash", "feature_engine_version", "feature_registry_version",
 *(s.name for s in FEATURE_SPECS), "missing_reason")
OUTPUT_DTYPES = {name: "string" for name in DATASET_COLUMNS}
OUTPUT_DTYPES.update({s.name: s.dtype for s in FEATURE_SPECS})
OUTPUT_DTYPES["eligible_observations"] = "Int64"

class FeatureValidationError(ValueError): pass
def _hash(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def _records(frame):
    value = frame.astype(object).where(pd.notna(frame), None).to_dict("records")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
def validate_feature_build_id(value):
    if not isinstance(value, str) or BUILD_ID.fullmatch(value) is None: raise FeatureValidationError("invalid feature build ID")
    return value
def _validate_utc(value):
    if not isinstance(value,str) or not value.endswith("Z"): raise FeatureValidationError("built_at must be UTC ISO")
    try: datetime.fromisoformat(value[:-1]+"+00:00")
    except ValueError as exc: raise FeatureValidationError("built_at must be UTC ISO") from exc
    return value
def resolve_dataset(root: Path, relative):
    if not isinstance(relative, str) or relative != "datasets/player_fixture_features.parquet" or "\\" in relative: raise FeatureValidationError("invalid feature dataset path")
    if PurePosixPath(relative).is_absolute() or PureWindowsPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts: raise FeatureValidationError("feature dataset path escapes")
    candidate = (root / Path(*relative.split("/"))).resolve()
    try: candidate.relative_to(root.resolve())
    except ValueError as exc: raise FeatureValidationError("feature dataset path escapes") from exc
    if not candidate.is_file(): raise FeatureValidationError("feature dataset is not a regular file")
    return candidate

def validate_feature_build(build_dir: Path, canonical: RuntimeBuildHandle | None = None):
    manifest = json.loads((build_dir / "manifest.json").read_text())
    allowed = {"schema_version","feature_build_id","canonical_build_id","canonical_manifest_hash","feature_engine_version","feature_registry_version","included_feature_families","output_files","row_counts","schemas","content_hashes","parquet_byte_hashes","warning_counts","exclusion_counts","cutoff_policy_version","assumption_status","built_at"}
    if set(manifest) != allowed or manifest["schema_version"] != 1 or manifest["feature_engine_version"] != ENGINE_VERSION or manifest["feature_registry_version"] != FEATURE_REGISTRY_VERSION or manifest["cutoff_policy_version"] != CUTOFF_POLICY_VERSION: raise FeatureValidationError("unsupported feature manifest")
    validate_feature_build_id(manifest["feature_build_id"]); path = resolve_dataset(build_dir, manifest["output_files"]["player_fixture_features"])
    _validate_utc(manifest["built_at"])
    if _hash(path) != manifest["parquet_byte_hashes"]["player_fixture_features"]: raise FeatureValidationError("feature parquet hash mismatch")
    frame = pd.read_parquet(path)
    if tuple(frame.columns) != DATASET_COLUMNS or frame.duplicated(["fixture_id","team_id","player_id"]).any(): raise FeatureValidationError("feature schema/key mismatch")
    if any(str(frame[name].dtype) != dtype for name, dtype in OUTPUT_DTYPES.items()): raise FeatureValidationError("feature dtype mismatch")
    if len(frame) != manifest["row_counts"]["player_fixture_features"] or _records(frame) != manifest["content_hashes"]["player_fixture_features"]: raise FeatureValidationError("feature content mismatch")
    for spec in FEATURE_SPECS:
        numeric = pd.to_numeric(frame[spec.name], errors="coerce") if spec.dtype != "string" else None
        if spec.valid_range and numeric is not None and ((numeric.dropna() < spec.valid_range[0]).any() or (numeric.dropna() > spec.valid_range[1]).any()): raise FeatureValidationError("feature range mismatch")
    if canonical is not None:
        source = canonical.manifest(); source_path = canonical.cache_root / "builds" / source["build_id"] / "manifest.json"
        if source["build_id"] != manifest["canonical_build_id"] or _hash(source_path) != manifest["canonical_manifest_hash"]: raise FeatureValidationError("canonical source binding mismatch")
    return manifest

def build_features(canonical: RuntimeBuildHandle, root: Path, *, feature_build_id: str, built_at: str, fail_before_pointer=False):
    validate_feature_build_id(feature_build_id); _validate_utc(built_at); source = canonical.manifest(); source_path = canonical.cache_root / "builds" / source["build_id"] / "manifest.json"
    stage_root = root / ".staging"; stage_root.mkdir(parents=True, exist_ok=True); stage = Path(tempfile.mkdtemp(prefix=feature_build_id+"-", dir=stage_root))
    try:
        dataset_dir = stage / "datasets"; report_dir = stage / "reports"; dataset_dir.mkdir(); report_dir.mkdir()
        frame = compute_features(canonical).reindex(columns=DATASET_COLUMNS).astype(OUTPUT_DTYPES); dataset = dataset_dir / "player_fixture_features.parquet"; frame.to_parquet(dataset, index=False, compression="zstd")
        reread = pd.read_parquet(dataset); warnings = []; exclusions = []
        (report_dir / "warnings.json").write_text(json.dumps(warnings)+"\n"); (report_dir / "exclusions.json").write_text(json.dumps(exclusions)+"\n")
        manifest = {"schema_version":1,"feature_build_id":feature_build_id,"canonical_build_id":source["build_id"],"canonical_manifest_hash":_hash(source_path),"feature_engine_version":ENGINE_VERSION,"feature_registry_version":FEATURE_REGISTRY_VERSION,"included_feature_families":["role","participation","congestion","availability"],"output_files":{"player_fixture_features":"datasets/player_fixture_features.parquet"},"row_counts":{"player_fixture_features":len(reread)},"schemas":{"player_fixture_features":"fi5-player-as-of-fixture-v1"},"content_hashes":{"player_fixture_features":_records(reread)},"parquet_byte_hashes":{"player_fixture_features":_hash(dataset)},"warning_counts":{"total":0},"exclusion_counts":{"total":0},"cutoff_policy_version":CUTOFF_POLICY_VERSION,"assumption_status":"mock_validated","built_at":built_at}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n"); validate_feature_build(stage, canonical)
        (report_dir / "build.json").write_text(json.dumps({"schema_version":1,"feature_build_id":feature_build_id,"status":"validated","row_counts":manifest["row_counts"]},sort_keys=True,indent=2)+"\n")
        builds = root / "builds"; builds.mkdir(parents=True, exist_ok=True); final = builds / feature_build_id
        if final.exists(): raise FileExistsError("feature build already exists")
        os.replace(stage, final)
        if fail_before_pointer: raise RuntimeError("seeded pointer failure")
        pointer = root / "_features_latest.json"; tmp = root / "._features_latest.tmp"; tmp.write_text(json.dumps({"schema_version":1,"feature_build_id":feature_build_id}, sort_keys=True)+"\n"); os.replace(tmp,pointer)
        return manifest
    finally: shutil.rmtree(stage, ignore_errors=True)

def replay_feature_build(source_build: Path, canonical: RuntimeBuildHandle, destination: Path):
    original = validate_feature_build(source_build, canonical)
    replay = build_features(canonical, destination, feature_build_id=original["feature_build_id"], built_at=original["built_at"])
    if replay["content_hashes"] != original["content_hashes"] or replay["parquet_byte_hashes"] != original["parquet_byte_hashes"]: raise FeatureValidationError("feature replay mismatch")
    return replay

def validate_active_features(root: Path, canonical: RuntimeBuildHandle):
    pointer=json.loads((root/"_features_latest.json").read_text())
    if set(pointer)!={"schema_version","feature_build_id"} or pointer["schema_version"]!=1: raise FeatureValidationError("invalid feature pointer")
    build_id=validate_feature_build_id(pointer["feature_build_id"]); build=(root/"builds"/build_id).resolve()
    try: build.relative_to((root/"builds").resolve())
    except ValueError as exc: raise FeatureValidationError("feature pointer escapes") from exc
    return validate_feature_build(build,canonical)

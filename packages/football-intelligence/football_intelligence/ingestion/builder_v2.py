"""Immutable offline canonical context-v2 build/store and replay."""
from __future__ import annotations
import hashlib, json, os, re, shutil, tempfile
from pathlib import Path
import pandas as pd
from .context_v2 import MANIFEST_SCHEMA_VERSION, SCHEMA_VERSION, SCHEMAS, frame, normalize_context, semantic_hash, validate_tables

def _hash(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()

def build_context_v2(source: Path, destination: Path, *, build_id: str, built_at: str | None = None, fail_after_write: bool = False) -> dict:
    if not isinstance(build_id, str) or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", build_id) is None:
        raise ValueError("build_id must match [a-z0-9]+(?:-[a-z0-9]+)*")
    payload = json.loads(source.read_text(encoding="utf-8")); tables, warnings = normalize_context(payload["canonical"])
    frames = {name: frame(name, tables[name]) for name in SCHEMAS}
    staging = destination / ".staging-v2"; staging.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=build_id + "-", dir=staging))
    try:
        canonical = stage / "canonical"; reports = stage / "reports"; canonical.mkdir(); reports.mkdir()
        files = {}; content = {}; parquet = {}
        for name, value in frames.items():
            path = canonical / f"{name}.parquet"; value.to_parquet(path, index=False, engine="pyarrow", compression="zstd")
            files[name] = f"canonical/{name}.parquet"; content[name] = semantic_hash(value); parquet[name] = _hash(path)
        (reports / "warnings.json").write_text(json.dumps(warnings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest = {"schema_version": MANIFEST_SCHEMA_VERSION, "canonical_schema_version": SCHEMA_VERSION,
            "build_family": "canonical-context-v2", "build_id": build_id, "built_at": built_at or payload["captured_at"],
            "source": {"source_kind": "checked-in-fixture", "source_version": payload["version"], "source_content_hash": _hash(source)},
            "normalizer_versions": {"mock_adapter": "fi5ba-v1"}, "entity_files": files,
            "row_counts": {k: len(v) for k,v in frames.items()}, "content_hashes": content,
            "parquet_byte_hashes": parquet, "warning_count": len(warnings), "assumption_status": "mock_validated"}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validate_context_build(stage)
        if fail_after_write: raise RuntimeError("seeded publication failure")
        builds = destination / "builds-v2"; builds.mkdir(parents=True, exist_ok=True); published = builds / build_id
        if published.exists(): raise FileExistsError(f"build already exists: {build_id}")
        os.replace(stage, published)
        pointer = destination / "_football_v2_latest.json"; tmp = destination / "_football_v2_latest.json.tmp"
        tmp.write_text(json.dumps({"schema_version": 2, "build_id": build_id, "manifest": f"builds-v2/{build_id}/manifest.json"}, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, pointer); return manifest
    except Exception:
        shutil.rmtree(stage, ignore_errors=True); raise

def validate_context_build(build: Path) -> dict:
    manifest = json.loads((build / "manifest.json").read_text())
    if manifest.get("canonical_schema_version") != 2 or manifest.get("build_family") != "canonical-context-v2": raise ValueError("unsupported canonical context contract")
    tables = {}
    if set(manifest["entity_files"]) != set(SCHEMAS): raise ValueError("dataset registry mismatch")
    for name, relative in manifest["entity_files"].items():
        if relative != f"canonical/{name}.parquet": raise ValueError("ungoverned entity path")
        path = (build / relative).resolve(); path.relative_to(build.resolve())
        if _hash(path) != manifest["parquet_byte_hashes"][name]: raise ValueError("parquet hash mismatch")
        value = frame(name, tuple(pd.read_parquet(path).astype(object).where(lambda x: pd.notna(x), None).to_dict("records")))
        if semantic_hash(value) != manifest["content_hashes"][name]: raise ValueError("semantic hash mismatch")
        tables[name] = tuple(value.astype(object).where(lambda x: pd.notna(x), None).to_dict("records"))
    validate_tables(tables); return manifest

def replay_context_v2(manifest_path: Path, source: Path, destination: Path) -> dict:
    original = json.loads(manifest_path.read_text());
    if _hash(source) != original["source"]["source_content_hash"]: raise ValueError("source content hash mismatch")
    replay = build_context_v2(source, destination, build_id=original["build_id"], built_at=original["built_at"])
    if (replay["content_hashes"], replay["parquet_byte_hashes"]) != (original["content_hashes"], original["parquet_byte_hashes"]): raise ValueError("deterministic replay mismatch")
    return replay

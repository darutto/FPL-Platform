"""Deterministic parquet build, validation, atomic publication, and replay."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd

from .normalizers import normalize_fixture
from .schemas import PRIMARY_KEYS, SCHEMAS, SCHEMA_VERSION
from .team_registry import load_team_registry

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_TEAM_SEED = PACKAGE_ROOT / "team_registry_seed.json"


def football_root() -> Path:
    return Path(os.environ.get("FPL_FOOTBALL_ROOT", "data/football"))


def _frame(name: str, rows: tuple[dict, ...]) -> pd.DataFrame:
    schema = SCHEMAS[name]
    frame = pd.DataFrame(list(rows), columns=[item[0] for item in schema])
    for column, dtype, nullable in schema:
        frame[column] = frame[column].astype(dtype)
        if not nullable and frame[column].isna().any():
            raise ValueError(f"non-nullable column contains null: {name}.{column}")
    if frame.duplicated(list(PRIMARY_KEYS[name])).any():
        raise ValueError(f"duplicate canonical primary key: {name}")
    return frame.sort_values(list(PRIMARY_KEYS[name]), kind="mergesort").reset_index(drop=True)


def _records_hash(frame: pd.DataFrame) -> str:
    normalized = frame.astype(object).where(pd.notna(frame), None).to_dict("records")
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_references(frames: dict[str, pd.DataFrame]) -> None:
    ids = {"competition": set(frames["competitions"]["competition_id"]),
           "season": set(frames["seasons"]["season_id"]),
           "team": set(frames["teams"]["team_id"]),
           "fixture": set(frames["fixtures"]["fixture_id"]),
           "player": set(frames["players"]["player_id"])}
    checks = [
        ("seasons", "competition_id", "competition"),
        ("fixtures", "competition_id", "competition"), ("fixtures", "season_id", "season"),
        ("fixtures", "home_team_id", "team"), ("fixtures", "away_team_id", "team"),
        ("squads", "team_id", "team"), ("squads", "player_id", "player"),
        ("lineups", "fixture_id", "fixture"), ("lineups", "team_id", "team"), ("lineups", "player_id", "player"),
        ("formations", "fixture_id", "fixture"), ("formations", "team_id", "team"),
        ("substitutions", "fixture_id", "fixture"), ("substitutions", "team_id", "team"),
        ("substitutions", "player_off_id", "player"), ("substitutions", "player_on_id", "player"),
        ("injuries", "player_id", "player"), ("suspensions", "player_id", "player"),
        ("coaches", "team_id", "team"), ("referees", "fixture_id", "fixture"),
        ("team_fixture_statistics", "fixture_id", "fixture"), ("team_fixture_statistics", "team_id", "team"),
        ("player_fixture_statistics", "fixture_id", "fixture"), ("player_fixture_statistics", "team_id", "team"),
        ("player_fixture_statistics", "player_id", "player"),
    ]
    for table, column, target in checks:
        missing = set(frames[table][column].dropna()) - ids[target]
        if missing:
            raise ValueError(f"missing foreign key: {table}.{column}")


def build_from_fixture(source: Path, destination: Path | None = None, *, build_id: str,
                       built_at: str | None = None, fail_after_write: bool = False) -> dict:
    root = destination or football_root()
    registry = load_team_registry(DEFAULT_TEAM_SEED)
    result = normalize_fixture(source, registry, build_id)
    frames = {name: _frame(name, result.tables[name]) for name in SCHEMAS}
    _validate_references(frames)
    staging_root = root / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f"{build_id}-", dir=staging_root))
    try:
        entity_dir = stage / "canonical"; report_dir = stage / "reports"
        entity_dir.mkdir(); report_dir.mkdir()
        row_hashes: dict[str, str] = {}; file_hashes: dict[str, str] = {}; entity_files: dict[str, str] = {}
        for name, frame in frames.items():
            path = entity_dir / f"{name}.parquet"
            frame.to_parquet(path, index=False, engine="pyarrow", compression="zstd")
            reread = pd.read_parquet(path).astype({column: dtype for column, dtype, _ in SCHEMAS[name]})
            if _records_hash(reread) != _records_hash(frame):
                raise ValueError(f"parquet round-trip changed canonical rows: {name}")
            entity_files[name] = f"canonical/{name}.parquet"
            row_hashes[name] = _records_hash(frame); file_hashes[name] = _file_hash(path)
        (report_dir / "warnings.json").write_text(json.dumps(result.warnings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (report_dir / "quarantine.json").write_text(json.dumps(result.quarantine, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        warning_counts = dict(sorted(Counter(item["reason"] for item in result.warnings).items()))
        warning_counts["total"] = len(result.warnings)
        quarantine_counts = dict(sorted(Counter(item["reason"] for item in result.quarantine).items()))
        quarantine_counts["total"] = len(result.quarantine)
        manifest = {
            "schema_version": SCHEMA_VERSION, "build_id": build_id,
            "built_at": built_at or result.captured_at,
            "input_fixture_or_snapshot_versions": [result.source_version],
            "source_fixture": str(source.resolve()),
            "normalizer_versions": {"sportmonks_adapter": "fi4a-v1"},
            "identity_registry_version": "team-seed-v1/player-precedence-v1",
            "entity_files": entity_files,
            "row_counts": {name: len(frame) for name, frame in frames.items()},
            "content_hashes": row_hashes, "parquet_byte_hashes": file_hashes,
            "warning_counts": warning_counts,
            "quarantine_counts": quarantine_counts,
            "assumption_status_summary": {result.assumption_status: 1},
        }
        (report_dir / "build_report.json").write_text(json.dumps({
            "schema_version": SCHEMA_VERSION, "build_id": build_id, "status": "validated",
            "row_counts": manifest["row_counts"], "warning_counts": warning_counts,
            "quarantine_counts": quarantine_counts,
            "assumption_status_summary": manifest["assumption_status_summary"],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if fail_after_write:
            raise RuntimeError("seeded publication failure")
        validate_build(stage)
        builds = root / "builds"; builds.mkdir(parents=True, exist_ok=True)
        published = builds / build_id
        if published.exists():
            raise FileExistsError(f"build already exists: {build_id}")
        os.replace(stage, published)
        pointer = root / "_football_latest.json"; tmp = pointer.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"schema_version": 1, "build_id": build_id, "manifest": f"builds/{build_id}/manifest.json"}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, pointer)
        return manifest
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def validate_build(build_dir: Path) -> dict:
    manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
    frames = {}
    for name, relative in manifest["entity_files"].items():
        path = build_dir / relative
        if _file_hash(path) != manifest["parquet_byte_hashes"][name]:
            raise ValueError(f"parquet byte hash mismatch: {name}")
        frames[name] = _frame(name, tuple(pd.read_parquet(path).astype(object).where(lambda value: pd.notna(value), None).to_dict("records")))
        if _records_hash(frames[name]) != manifest["content_hashes"][name]:
            raise ValueError(f"canonical content hash mismatch: {name}")
    _validate_references(frames)
    return manifest


def validate_active(root: Path | None = None) -> dict:
    target = root or football_root()
    pointer = json.loads((target / "_football_latest.json").read_text(encoding="utf-8"))
    return validate_build(target / "builds" / pointer["build_id"])


def replay_manifest(manifest_path: Path, destination: Path) -> dict:
    original = json.loads(manifest_path.read_text(encoding="utf-8"))
    replay = build_from_fixture(Path(original["source_fixture"]), destination,
                                build_id=original["build_id"], built_at=original["built_at"])
    if replay["content_hashes"] != original["content_hashes"] or replay["row_counts"] != original["row_counts"]:
        raise ValueError("deterministic replay mismatch")
    return replay

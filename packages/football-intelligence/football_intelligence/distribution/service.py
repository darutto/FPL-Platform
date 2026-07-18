"""Immutable publication, bounded verification, and atomic local synchronization."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from football_intelligence.ingestion.builder import (MANIFEST_SCHEMA_VERSION,
    resolve_contained_build_directory, validate_build, validate_build_id)

from .config import DownloadLimits
from .errors import (ArtifactSizeError, DistributionError, PointerRaceError,
                     RemoteValidationError, SyncLockError)
from .keys import artifact_key, manifest_key, pointer_key
from .store import ArtifactStore

POINTER_SCHEMA_VERSION = 1
PUBLISHER_VERSION = "fi4b-v1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_json(data: bytes, label: str) -> dict[str, Any]:
    try:
        def pairs(items):
            out = {}
            for key, value in items:
                if key in out:
                    raise ValueError("duplicate key")
                out[key] = value
            return out
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RemoteValidationError(f"{label} is malformed") from exc
    if not isinstance(value, dict):
        raise RemoteValidationError(f"{label} must be an object")
    return value


def encode_pointer(build_id: str, manifest_hash: str, published_at: str | None = None) -> bytes:
    validate_build_id(build_id)
    if len(manifest_hash) != 64 or any(c not in "0123456789abcdef" for c in manifest_hash):
        raise RemoteValidationError("pointer manifest hash is invalid")
    value = {"schema_version": POINTER_SCHEMA_VERSION, "build_id": build_id,
             "manifest_hash": manifest_hash,
             "published_at": published_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
             "publisher_version": PUBLISHER_VERSION}
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def parse_pointer(data: bytes) -> dict[str, Any]:
    value = _strict_json(data, "remote pointer")
    expected = {"schema_version", "build_id", "manifest_hash", "published_at", "publisher_version"}
    if set(value) != expected or value["schema_version"] != POINTER_SCHEMA_VERSION or value["publisher_version"] != PUBLISHER_VERSION:
        raise RemoteValidationError("remote pointer version or fields are unsupported")
    validate_build_id(value["build_id"])
    if not isinstance(value["published_at"], str):
        raise RemoteValidationError("remote pointer timestamp is invalid")
    encode_pointer(value["build_id"], value["manifest_hash"], value["published_at"])
    return value


def _artifact_paths(manifest: dict[str, Any]) -> tuple[str, ...]:
    entities = manifest.get("entity_files")
    reports = manifest.get("report_files")
    if not isinstance(entities, dict) or not isinstance(reports, dict):
        raise RemoteValidationError("manifest artifact registries are missing")
    return tuple(sorted([*entities.values(), *reports.values()]))


def _expected_hash(manifest: dict[str, Any], relative: str) -> str:
    for name, path in manifest["entity_files"].items():
        if path == relative:
            return manifest["parquet_byte_hashes"][name]
    for name, path in manifest["report_files"].items():
        if path == relative:
            return manifest["report_byte_hashes"][name]
    raise RemoteValidationError("manifest references an ungoverned artifact")


def read_bounded(store: ArtifactStore, key: str, limit: int, total: list[int] | None = None,
                 total_limit: int | None = None) -> bytes:
    remote = store.open_read(key)
    try:
        if remote.metadata.size > limit:
            raise ArtifactSizeError("remote artifact exceeds its declared size cap")
        chunks, size = [], 0
        while True:
            chunk = remote.stream.read(min(65_536, limit - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ArtifactSizeError("remote artifact exceeds its streamed size cap")
            if total is not None:
                if total_limit is not None and total[0] + len(chunk) > total_limit:
                    raise ArtifactSizeError("remote build exceeds total size cap")
                total[0] += len(chunk)
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        remote.stream.close()


@dataclass(frozen=True)
class PublicationReport:
    build_id: str
    files_uploaded: int
    bytes_uploaded: int
    manifest_hash: str


def publish_build(store: ArtifactStore, prefix: str, build_dir: Path, *, dry_run: bool = False) -> PublicationReport:
    manifest = validate_build(build_dir)
    build_id = validate_build_id(manifest.get("build_id"))
    manifest_bytes = (build_dir / "manifest.json").read_bytes()
    manifest_hash = _sha(manifest_bytes)
    paths = _artifact_paths(manifest)
    payloads = []
    for relative in paths:
        key = artifact_key(prefix, build_id, relative)
        data = (build_dir / Path(*relative.split("/"))).read_bytes()
        if _sha(data) != _expected_hash(manifest, relative):
            raise RemoteValidationError("local artifact hash changed after validation")
        payloads.append((key, data))
    if dry_run:
        return PublicationReport(build_id, 0, 0, manifest_hash)
    old = store.head(pointer_key(prefix))
    for key, data in payloads:
        meta = store.put_immutable(key, data, _sha(data))
        if meta.sha256 != _sha(data):
            raise RemoteValidationError("remote artifact metadata hash mismatch")
    store.put_immutable(manifest_key(prefix, build_id), manifest_bytes, manifest_hash)
    remote_manifest = read_bounded(store, manifest_key(prefix, build_id), 1_048_576)
    if _sha(remote_manifest) != manifest_hash:
        raise RemoteValidationError("remote manifest verification failed")
    store.put_pointer(pointer_key(prefix), encode_pointer(build_id, manifest_hash), old.etag if old else None)
    return PublicationReport(build_id, len(payloads) + 1, sum(len(d) for _, d in payloads) + len(manifest_bytes), manifest_hash)


class SyncLock:
    def __init__(self, root: Path, timeout: float = 5.0, stale_after: float = 300.0):
        self.path = root / ".sync.lock"; self.timeout = timeout; self.stale_after = stale_after
        self.owner = f"{uuid.uuid4()}:{time.time()}"
    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True); deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as handle: handle.write(self.owner)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale_after:
                        self.path.unlink(); continue
                except FileNotFoundError: continue
                if time.monotonic() >= deadline: raise SyncLockError("local synchronization lock timed out")
                time.sleep(0.02)
    def __exit__(self, *_):
        try:
            if self.path.read_text() == self.owner: self.path.unlink()
        except FileNotFoundError: pass


@dataclass(frozen=True)
class SyncReport:
    build_id: str
    changed: bool
    files_transferred: int
    bytes_transferred: int


def sync_build(store: ArtifactStore, prefix: str, cache_root: Path, limits: DownloadLimits = DownloadLimits()) -> SyncReport:
    with SyncLock(cache_root):
        total = [0]
        pointer_data = read_bounded(store, pointer_key(prefix), limits.pointer, total, limits.total)
        pointer = parse_pointer(pointer_data); build_id = pointer["build_id"]
        local_pointer = cache_root / "_football_latest.json"
        if local_pointer.is_file():
            try:
                current = parse_pointer(local_pointer.read_bytes())
                if current["build_id"] == build_id and current["manifest_hash"] == pointer["manifest_hash"]:
                    validate_build(resolve_contained_build_directory(cache_root / "builds", build_id))
                    return SyncReport(build_id, False, 0, 0)
            except (OSError, DistributionError, ValueError, KeyError): pass
        manifest_data = read_bounded(store, manifest_key(prefix, build_id), limits.manifest, total, limits.total)
        if _sha(manifest_data) != pointer["manifest_hash"]:
            raise RemoteValidationError("pointer manifest hash mismatch")
        manifest = _strict_json(manifest_data, "remote manifest")
        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION or manifest.get("build_id") != build_id:
            raise RemoteValidationError("remote manifest version or build ID is incompatible")
        staging_root = cache_root / ".staging"; staging_root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f"{build_id}-", dir=staging_root))
        try:
            (stage / "manifest.json").write_bytes(manifest_data)
            count = 0
            for relative in _artifact_paths(manifest):
                key = artifact_key(prefix, build_id, relative)
                cap = limits.parquet if relative.endswith(".parquet") else limits.report
                data = read_bounded(store, key, cap, total, limits.total)
                if _sha(data) != _expected_hash(manifest, relative): raise RemoteValidationError("remote artifact hash mismatch")
                target = stage / Path(*relative.split("/")); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data); count += 1
            validate_build(stage)
            builds = cache_root / "builds"; builds.mkdir(parents=True, exist_ok=True); final = builds / build_id
            if final.exists():
                shutil.rmtree(stage)
            else: os.replace(stage, final)
            tmp = cache_root / f".{uuid.uuid4()}.pointer.tmp"; tmp.write_bytes(pointer_data); os.replace(tmp, local_pointer)
            return SyncReport(build_id, True, count, total[0])
        finally:
            shutil.rmtree(stage, ignore_errors=True)


def verify_remote(store: ArtifactStore, prefix: str, limits: DownloadLimits = DownloadLimits()) -> SyncReport:
    """Fully download and validate the active remote build without retaining it."""
    with tempfile.TemporaryDirectory(prefix="fi4b-verify-") as target:
        return sync_build(store, prefix, Path(target), limits)

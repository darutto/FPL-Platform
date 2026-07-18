"""Fail-soft runtime capability and read-only active-build handle."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from football_intelligence.ingestion.builder import resolve_contained_build_directory, validate_build

from .config import RemoteStoreConfig
from .errors import DistributionError
from .service import parse_pointer
from .service import sync_build
from .store import S3ArtifactStore


@dataclass(frozen=True)
class RuntimeStatus:
    state: str
    reason_code: str
    local_build_id: str | None = None
    remote_build_id: str | None = None


class RuntimeBuildHandle:
    def __init__(self, cache_root: Path): self.cache_root = cache_root
    def manifest(self) -> dict:
        pointer = parse_pointer((self.cache_root / "_football_latest.json").read_bytes())
        return validate_build(resolve_contained_build_directory(self.cache_root / "builds", pointer["build_id"]))
    def dataset_path(self, entity: str) -> Path:
        manifest = self.manifest()
        if entity not in manifest["entity_files"]: raise KeyError(entity)
        return (self.cache_root / "builds" / manifest["build_id"] / manifest["entity_files"][entity]).resolve()


def startup_status(env: dict[str, str] | None = None) -> RuntimeStatus:
    values = os.environ if env is None else env
    try:
        config = RemoteStoreConfig.from_env(values)
        if config is None: return RuntimeStatus("disabled", "not_configured")
        cache = Path(values.get("FPL_FOOTBALL_CACHE_ROOT", "data/football-runtime"))
        try:
            local = RuntimeBuildHandle(cache).manifest()
            return RuntimeStatus("degraded", "refresh_not_attempted", local_build_id=local["build_id"])
        except Exception:
            return RuntimeStatus("unavailable", "no_valid_local_build")
    except DistributionError as exc:
        return RuntimeStatus("unavailable", exc.reason_code)


def startup_sync(env: dict[str, str] | None = None) -> RuntimeStatus:
    values = os.environ if env is None else env
    config = None
    try:
        config = RemoteStoreConfig.from_env(values)
        if config is None: return RuntimeStatus("disabled", "not_configured")
        cache = Path(values.get("FPL_FOOTBALL_CACHE_ROOT", "data/football-runtime"))
        report = sync_build(S3ArtifactStore(config), config.prefix, cache, config.limits)
        return RuntimeStatus("ready", "synchronized" if report.changed else "already_current",
                             local_build_id=report.build_id, remote_build_id=report.build_id)
    except Exception as exc:
        reason = exc.reason_code if isinstance(exc, DistributionError) else "sync_failed"
        local = None
        try: local = RuntimeBuildHandle(Path(values.get("FPL_FOOTBALL_CACHE_ROOT", "data/football-runtime"))).manifest()["build_id"]
        except Exception: pass
        return RuntimeStatus("degraded" if local else "unavailable", reason, local_build_id=local)

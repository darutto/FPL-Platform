"""Read-only runtime for the licensed matchday family (B4): a fail-soft startup sync and a validated handle.

The canonical runtime (``runtime.py``) syncs ``CANONICAL_V1`` and cannot reach this family: the prefixes are
reserved apart (``keys.RESERVED_PREFIX_SEGMENTS``) and each family has its own pointer. This module is the licensed
twin, with three differences that are decisions, not accidents:

* **Off unless asked.** ``FPL_FOOTBALL_LICENSED_SYNC_ENABLED`` must be truthy; the remote credentials alone do not
  turn it on, because the same ``FPL_FOOTBALL_REMOTE_*`` variables already serve the canonical sync.
* **Licensed or nothing.** The handle accepts only a build stamped ``licensed_starter`` and re-runs the shared
  trial refusal, so a ``live_trial_local`` build can neither be synced (shared path) nor read (here).
* **Read-only.** There is no publish here. Tables come back as frames of derived rows keyed by FPL ids; nothing
  returns a path to the store, a raw payload or a provider id (the ``crosswalk`` table is not readable through the
  handle at all).

Nothing in this module logs or returns a row. Its status carries a state and a reason code only.
"""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Mapping

import pandas as pd

from football_intelligence.ingestion.builder import resolve_contained_build_directory
from football_intelligence.ingestion.licensed.store import (
    LICENSED_V1, PREFIX_SEGMENT, TABLES, LicensedStoreError, validate_build,
)
from football_intelligence.provenance import LICENSED_STARTER, refuse_live_trial

from .config import DownloadLimits, RemoteStoreConfig
from .errors import DistributionError
from .runtime import RuntimeStatus
from .service import parse_pointer, sync_build
from .store import ArtifactStore, S3ArtifactStore

LICENSED_SYNC_ENABLED_ENV = "FPL_FOOTBALL_LICENSED_SYNC_ENABLED"
LICENSED_CACHE_ROOT_ENV = "FPL_FOOTBALL_LICENSED_CACHE_ROOT"
DEFAULT_LICENSED_CACHE_ROOT = "data/football-licensed-runtime"
#: Tables a reader may ask for. The crosswalk holds provider ids and is stored, never served.
READABLE_TABLES = tuple(name for name in TABLES if name != "crosswalk")


class LicensedTableRefused(KeyError):
    """A table was asked for that the handle does not serve."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"1", "true", "yes"}


def _cache_root(values: Mapping[str, str]) -> Path:
    return Path(values.get(LICENSED_CACHE_ROOT_ENV) or DEFAULT_LICENSED_CACHE_ROOT)


def handle_from_env(env: Mapping[str, str] | None = None) -> "LicensedRuntimeHandle":
    """The handle over the cache this process syncs into (``FPL_FOOTBALL_LICENSED_CACHE_ROOT``)."""
    return LicensedRuntimeHandle(_cache_root(os.environ if env is None else env))


class LicensedRuntimeHandle:
    """The synced licensed build, validated on every read. Construct with the cache root it was synced into."""

    def __init__(self, cache_root: Path):
        self.cache_root = Path(cache_root)

    def manifest(self) -> dict:
        pointer = parse_pointer((self.cache_root / LICENSED_V1.pointer_name).read_bytes())
        build = resolve_contained_build_directory(self.cache_root / "builds", pointer["build_id"])
        manifest = validate_build(build)
        refuse_live_trial(manifest, "LicensedRuntimeHandle")
        if manifest["assumption_status"] != LICENSED_STARTER:  # validate_build already pins this; belt and braces
            raise LicensedStoreError("licensed handle serves licensed_starter builds only")
        return manifest

    def build_id(self) -> str:
        return self.manifest()["build_id"]

    def table(self, name: str) -> pd.DataFrame:
        if name not in READABLE_TABLES:
            raise LicensedTableRefused(name)
        manifest = self.manifest()
        build = resolve_contained_build_directory(self.cache_root / "builds", manifest["build_id"])
        return pd.read_parquet(build / f"datasets/{name}.parquet")


def licensed_startup_sync(env: Mapping[str, str] | None = None, *, store: ArtifactStore | None = None) -> RuntimeStatus:
    """Bounded, fail-soft synchronization of the licensed family into the local cache. Never raises.

    ``store`` is for tests; in production it is built from the same ``FPL_FOOTBALL_REMOTE_*`` configuration the
    canonical sync reads, pointed at the licensed prefix.
    """
    values = os.environ if env is None else env
    cache = _cache_root(values)

    def local_build() -> str | None:
        try:
            return LicensedRuntimeHandle(cache).build_id()
        except Exception:
            return None

    if not _truthy(values.get(LICENSED_SYNC_ENABLED_ENV)):
        return RuntimeStatus("disabled", "sync_not_enabled")
    try:
        config = RemoteStoreConfig.from_env(dict(values))
        if config is None and store is None:
            return RuntimeStatus("disabled", "not_configured")
        limits = config.limits if config else DownloadLimits()
        backend = store or S3ArtifactStore(replace(config, prefix=PREFIX_SEGMENT))
        report = sync_build(backend, PREFIX_SEGMENT, cache, limits, LICENSED_V1)
        return RuntimeStatus("ready", "synchronized" if report.changed else "already_current",
                             local_build_id=report.build_id, remote_build_id=report.build_id)
    except Exception as exc:
        reason = exc.reason_code if isinstance(exc, DistributionError) else "sync_failed"
        local = local_build()
        return RuntimeStatus("degraded" if local else "unavailable", reason, local_build_id=local)

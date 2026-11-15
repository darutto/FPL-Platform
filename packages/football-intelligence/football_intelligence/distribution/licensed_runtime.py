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

Staying current: the ingestion publishes a new build every day and every few minutes on a match day, and a process
that syncs only at start would not see them until a restart. :class:`LicensedResync` repeats the same sync in a
background thread. Each pass reads the small remote pointer first and downloads only when the build id changed
(``sync_build``), stages into a new directory and swaps the local pointer last, so a reader sees the old build or
the new one, never a half-written one, and any failure keeps the build already in use.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from dataclasses import replace
from pathlib import Path
from typing import Mapping

import pandas as pd

from football_intelligence.ingestion.builder import resolve_contained_build_directory
from football_intelligence.ingestion.licensed.store import (
    LICENSED_V1, PREFIX_SEGMENT, TABLES, LicensedStoreError, read_table, validate_build,
)
from football_intelligence.provenance import LICENSED_STARTER, refuse_live_trial

from .config import DownloadLimits, RemoteStoreConfig
from .errors import DistributionError
from .runtime import RuntimeStatus
from .service import parse_pointer, sync_build
from .store import ArtifactStore, S3ArtifactStore

LICENSED_SYNC_ENABLED_ENV = "FPL_FOOTBALL_LICENSED_SYNC_ENABLED"
LICENSED_CACHE_ROOT_ENV = "FPL_FOOTBALL_LICENSED_CACHE_ROOT"
LICENSED_RESYNC_SECONDS_ENV = "FPL_FOOTBALL_LICENSED_RESYNC_SECONDS"
DEFAULT_RESYNC_SECONDS = 600.0
MIN_RESYNC_SECONDS = 60.0
#: Builds kept in the cache: the one in use and the most recent others. Older ones are removed after a successful sync.
KEEP_BUILDS = 3
_LOG = logging.getLogger(__name__)
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
        return read_table(build, name)


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


def resync_interval(env: Mapping[str, str] | None = None) -> float:
    """Seconds between re-syncs; 0 disables. Malformed -> the default; never below the minimum."""
    raw = ((os.environ if env is None else env).get(LICENSED_RESYNC_SECONDS_ENV) or "").strip()
    if not raw:
        return DEFAULT_RESYNC_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_RESYNC_SECONDS
    return 0.0 if value <= 0 else max(value, MIN_RESYNC_SECONDS)


def prune_old_builds(cache_root: Path, keep: int = KEEP_BUILDS) -> int:
    """Remove all but the ``keep`` newest build directories under ``cache_root/builds``, never the one the local pointer
    names. Only direct children that are real directories are touched. Returns how many were removed."""
    builds = Path(cache_root) / "builds"
    try:
        current = parse_pointer((Path(cache_root) / LICENSED_V1.pointer_name).read_bytes())["build_id"]
        children = [p for p in builds.iterdir() if p.is_dir() and not p.is_symlink()]
    except Exception:
        return 0
    children.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for path in [p for p in children if p.name != current][max(0, keep - 1):]:
        shutil.rmtree(path, ignore_errors=True)
        removed += 1
    return removed


class LicensedResync:
    """Periodic, bounded, never-raising re-sync of the licensed family. Off unless the sync flag is on."""

    def __init__(self, env: Mapping[str, str] | None = None, *, store: ArtifactStore | None = None,
                 interval_seconds: float | None = None) -> None:
        self.env = os.environ if env is None else env
        self.store = store
        self.interval = resync_interval(self.env) if interval_seconds is None else interval_seconds
        self.status: RuntimeStatus = RuntimeStatus("disabled", "sync_not_enabled")
        self.runs = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> RuntimeStatus:
        """One pass: the same sync as startup. Never raises; a failure leaves the build in use untouched."""
        try:
            status = licensed_startup_sync(self.env, store=self.store)
            if status.reason_code == "synchronized":
                prune_old_builds(_cache_root(self.env))
        except Exception:  # licensed_startup_sync already swallows; this is the backstop for the loop itself
            status = RuntimeStatus("unavailable", "resync_failed")
        self.runs += 1
        previous, self.status = self.status, status
        quiet = status.reason_code == "already_current" and previous.state == "ready"   # the common case: nothing new
        if not quiet and (previous.state, previous.reason_code, previous.local_build_id) != (status.state, status.reason_code, status.local_build_id):
            # State and reason only: nothing about the build's content is logged.
            _LOG.info("football licensed resync: state=%s reason=%s", status.state, status.reason_code)
        return status

    def start(self) -> bool:
        """Start the background loop. False (and no thread) when the flag is off, the interval is 0 or it already runs."""
        if not _truthy(self.env.get(LICENSED_SYNC_ENABLED_ENV)) or self.interval <= 0:
            return False
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="football-licensed-resync", daemon=True)
        self._thread.start()
        return True

    def _loop(self) -> None:
        # Wait first: the startup sync has just run.
        while not self._stop.wait(self.interval):
            self.run_once()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

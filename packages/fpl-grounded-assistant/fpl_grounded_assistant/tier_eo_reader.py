"""Reads the published tier-EO files (``eo/{season}/gw{N}/{tier}.json``) from R2.

The writer is ``scripts/tier_eo_top10k.py`` (a scheduled GitHub workflow). This reader is the app's
side: one small GET per file, in-process cache, fail-soft (any problem is "not found", never an exception).

* Keys are built here from a validated season, an integer gameweek and a whitelisted tier, and always
  start with ``{prefix}eo/``: the reader cannot be pointed anywhere else in the bucket.
* The client, bucket and prefix come from the same ``OWNED_STORE_R2_*`` variables, and the same
  prefix normalisation, as ``owned_store_sync`` (so the reader and the writer agree by construction when
  those variables match the workflow's secrets). Nothing about them is ever returned or logged.
* A published file is immutable (the scheduled run skips existing keys), so a hit is kept for a day. A miss
  is kept for ``MISS_TTL_S`` so a file published by the cron appears within minutes.
* The client has its own short timeouts (a timeout is "not found"); ``latest_cached`` never does a GET.
* ``latest`` looks at the requested gameweek and at most ONE gameweek back; older is "not found".
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Callable

TIERS = ("top10k",)           # the tiers the app reads today (top100k is written, not read yet)
HIT_TTL_S = 86_400.0
MISS_TTL_S = 600.0
MAX_GW_BACK = 1

_SEASON_RE = re.compile(r"^\d{4}-\d{4}$")

Fetch = Callable[[str], "bytes | None"]


def object_key(prefix: str, season: str, gw: int, tier: str) -> str:
    """``{prefix}eo/{season}/gw{gw}/{tier}.json``; ValueError for anything that is not exactly that shape."""
    if not _SEASON_RE.match(season or "") or tier not in TIERS or not isinstance(gw, int) or isinstance(gw, bool) or gw < 1:
        raise ValueError("invalid tier-EO key parts")
    return f"{prefix}eo/{season}/gw{gw}/{tier}.json"


#: A read happens on a user's turn (and, cache-only, never on /healthz), so it must fail fast: a timeout is
#: "not found" and is cached as a miss. ``owned_store_sync._make_r2_client`` keeps boto3's defaults on purpose
#: (the startup sync downloads big files); this reader has its own client.
CONNECT_TIMEOUT_S = 3
READ_TIMEOUT_S = 5
MAX_ATTEMPTS = 2

_CLIENT: Any = None
_CLIENT_LOCK = threading.Lock()


def _client_config(total_attempts: int | None = None) -> Any:
    """The short timeouts. ``total_attempts`` (1 = no retry) replaces this reader's own retry setting for a
    caller that must not retry; left out, the config is this reader's."""
    from botocore.config import Config  # noqa: PLC0415  (lazy, like boto3)

    retries = ({"max_attempts": MAX_ATTEMPTS, "mode": "standard"} if total_attempts is None
               else {"total_max_attempts": total_attempts, "mode": "standard"})
    return Config(connect_timeout=CONNECT_TIMEOUT_S, read_timeout=READ_TIMEOUT_S, retries=retries)


def _make_client(total_attempts: int | None = None) -> Any:
    """A boto3 S3 client for R2 from the same ``OWNED_STORE_R2_*`` variables as ``owned_store_sync``, with short timeouts."""
    from . import owned_store_sync as sync  # noqa: PLC0415

    values = {name: os.environ.get(name, "").strip() for name in (
        sync.ENV_R2_ENDPOINT, sync.ENV_R2_BUCKET, sync.ENV_R2_ACCESS_KEY_ID, sync.ENV_R2_SECRET_ACCESS_KEY)}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"missing required R2 env vars: {', '.join(missing)}")
    import boto3  # noqa: PLC0415

    return boto3.client(
        "s3", endpoint_url=values[sync.ENV_R2_ENDPOINT], aws_access_key_id=values[sync.ENV_R2_ACCESS_KEY_ID],
        aws_secret_access_key=values[sync.ENV_R2_SECRET_ACCESS_KEY], region_name="auto",
        config=_client_config(total_attempts))


def _get_client() -> Any:
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = _make_client()
        return _CLIENT


def _r2_fetch(key: str) -> bytes | None:
    """One GET from R2 with the owned-store credentials and short timeouts. None when the object does not exist; raises otherwise."""
    from . import owned_store_sync as sync  # noqa: PLC0415  (lazy: boto3 only when a read is made)

    client = _get_client()
    bucket = os.environ.get(sync.ENV_R2_BUCKET, "").strip()
    try:
        obj = client.get_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        if "NoSuchKey" in type(exc).__name__ or "NoSuchKey" in str(exc) or "404" in str(exc):
            return None
        raise
    return obj["Body"].read()


def _r2_prefix() -> str:
    from . import owned_store_sync as sync  # noqa: PLC0415

    return sync._r2_prefix()


class TierEOReader:
    def __init__(self, fetch: Fetch | None = None, prefix: Callable[[], str] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self._fetch = fetch or _r2_fetch
        self._prefix = prefix or _r2_prefix
        self._clock = clock
        self._cache: dict[tuple[str, int, str], tuple[float, dict[str, Any] | None]] = {}
        self._lock = threading.Lock()                       # guards the cache
        self._flight: dict[tuple[str, int, str], threading.Lock] = {}

    def read(self, season: str, gw: int, tier: str = "top10k") -> dict[str, Any] | None:
        """The published file's content, or None (missing, unreadable, malformed, or the wrong season/gw/tier)."""
        cache_key = (season, gw, tier)
        now = self._clock()
        with self._lock:
            hit = self._cache.get(cache_key)
            if hit and hit[0] > now:
                return hit[1]
            flight = self._flight.setdefault(cache_key, threading.Lock())
        with flight:                                        # single-flight: one GET per key at a time
            with self._lock:
                hit = self._cache.get(cache_key)
                if hit and hit[0] > self._clock():
                    return hit[1]
            data = self._load(season, gw, tier)
            ttl = HIT_TTL_S if data is not None else MISS_TTL_S
            with self._lock:
                self._cache[cache_key] = (self._clock() + ttl, data)
            return data

    def _load(self, season: str, gw: int, tier: str) -> dict[str, Any] | None:
        try:
            raw = self._fetch(object_key(self._prefix(), season, gw, tier))
            body = json.loads(raw.decode("utf-8")) if raw else None
        except Exception:  # noqa: BLE001  (fail-soft: a problem is "not found", never a raise into a turn)
            return None
        if not isinstance(body, dict) or not isinstance(body.get("players"), dict):
            return None
        if body.get("season") != season or body.get("gw") != gw or body.get("tier") != tier:
            return None                                     # a file that does not say what its key says
        return body

    def cached(self, season: str, gw: int, tier: str = "top10k") -> dict[str, Any] | None:
        """What ``read`` would return from the cache, never a GET: None when cold, expired or a cached miss."""
        with self._lock:
            hit = self._cache.get((season, gw, tier))
            return hit[1] if hit and hit[0] > self._clock() else None

    def latest_cached(self, season: str, gw: int, tier: str = "top10k") -> dict[str, Any] | None:
        """``latest`` over the cache only (for /healthz): no GET, so it can never wait on R2."""
        for back in range(MAX_GW_BACK + 1):
            if gw - back < 1:
                break
            data = self.cached(season, gw - back, tier)
            if data is not None:
                return data
        return None

    def latest(self, season: str, gw: int, tier: str = "top10k") -> dict[str, Any] | None:
        """The file for *gw*, else for the gameweek before it (at most ``MAX_GW_BACK`` back), else None."""
        for back in range(MAX_GW_BACK + 1):
            if gw - back < 1:
                break
            data = self.read(season, gw - back, tier)
            if data is not None:
                return data
        return None


_READER: TierEOReader | None = None


def get_reader() -> TierEOReader:
    global _READER
    if _READER is None:
        _READER = TierEOReader()
    return _READER


def set_reader(reader: TierEOReader | None) -> None:
    """Replace the process-wide reader (tests)."""
    global _READER
    _READER = reader

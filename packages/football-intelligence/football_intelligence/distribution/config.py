"""Validated, explicit configuration for canonical artifact distribution."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .errors import DistributionConfigError

_BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _positive(env: dict[str, str], name: str, default: int, ceiling: int = 2_147_483_648) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    if not raw.isascii() or not raw.isdigit() or not 0 < int(raw) <= ceiling:
        raise DistributionConfigError(f"{name} must be a bounded positive integer")
    return int(raw)


@dataclass(frozen=True)
class DownloadLimits:
    pointer: int = 65_536
    manifest: int = 1_048_576
    report: int = 1_048_576
    parquet: int = 134_217_728
    total: int = 536_870_912


@dataclass(frozen=True)
class RemoteStoreConfig:
    endpoint: str
    bucket: str
    prefix: str
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)
    region: str = "auto"
    force_path_style: bool = True
    limits: DownloadLimits = DownloadLimits()

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> RemoteStoreConfig | None:
        values = os.environ if env is None else env
        names = ("FPL_FOOTBALL_REMOTE_ENDPOINT", "FPL_FOOTBALL_REMOTE_BUCKET",
                 "FPL_FOOTBALL_REMOTE_ACCESS_KEY_ID", "FPL_FOOTBALL_REMOTE_SECRET_ACCESS_KEY")
        present = [bool(values.get(name)) for name in names]
        if not any(present):
            return None
        if not all(present):
            raise DistributionConfigError("football remote configuration is incomplete")
        endpoint = values[names[0]]
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise DistributionConfigError("football remote endpoint must be an HTTP(S) origin without credentials")
        bucket = values[names[1]]
        if not _BUCKET.fullmatch(bucket) or ".." in bucket:
            raise DistributionConfigError("football remote bucket is invalid")
        prefix = values.get("FPL_FOOTBALL_REMOTE_PREFIX", "football").strip("/")
        if not prefix or "\\" in prefix or "//" in prefix or any(not _SEGMENT.fullmatch(s) or s in {".", ".."} for s in prefix.split("/")):
            raise DistributionConfigError("football remote prefix is invalid")
        raw_style = values.get("FPL_FOOTBALL_REMOTE_FORCE_PATH_STYLE", "true").casefold()
        if raw_style not in {"true", "false"}:
            raise DistributionConfigError("FPL_FOOTBALL_REMOTE_FORCE_PATH_STYLE must be true or false")
        limits = DownloadLimits(
            pointer=_positive(values, "FPL_FOOTBALL_MAX_POINTER_BYTES", 65_536),
            manifest=_positive(values, "FPL_FOOTBALL_MAX_MANIFEST_BYTES", 1_048_576),
            report=_positive(values, "FPL_FOOTBALL_MAX_REPORT_BYTES", 1_048_576),
            parquet=_positive(values, "FPL_FOOTBALL_MAX_PARQUET_BYTES", 134_217_728),
            total=_positive(values, "FPL_FOOTBALL_MAX_BUILD_BYTES", 536_870_912),
        )
        return cls(endpoint, bucket, prefix, values[names[2]], values[names[3]],
                   values.get("FPL_FOOTBALL_REMOTE_REGION", "auto"), raw_style == "true", limits)

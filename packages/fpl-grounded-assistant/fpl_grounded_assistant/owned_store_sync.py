"""
fpl_grounded_assistant.owned_store_sync
=======================================
Track A H5 — runtime/deploy wiring for the owned-store fallback.

Delivers the owned parquet store to the running server via a startup sync
from Cloudflare R2 (S3-compatible). The owned-store fallback readers in
``owned_store_fallback.py`` read from the local filesystem under
``fpl_historical.paths.historical_root()`` (honouring ``FPL_HISTORICAL_ROOT``).
This module downloads the 6 canonical files into that location so the
fallback can actually serve rows when the live FPL API is unavailable.

Delivery model is FROZEN: startup sync of owned parquet from R2, fail-soft.
Default OFF — when ``OWNED_STORE_SYNC_ENABLED`` is unset/falsy nothing runs
and live-primary behaviour is unchanged.

Environment variables
----------------------
    OWNED_STORE_SYNC_ENABLED       truthy ("1"/"true"/"yes", case-insensitive,
                                   stripped) enables the startup sync. Default OFF.
    OWNED_STORE_R2_ENDPOINT        e.g. https://<accountid>.r2.cloudflarestorage.com
    OWNED_STORE_R2_BUCKET          R2 bucket name
    OWNED_STORE_R2_ACCESS_KEY_ID   R2 access key id
    OWNED_STORE_R2_SECRET_ACCESS_KEY  R2 secret access key
    OWNED_STORE_R2_PREFIX          optional key prefix (no leading slash;
                                   normalised to exactly one trailing slash
                                   when non-empty). Default "".

The local destination is controlled by ``FPL_HISTORICAL_ROOT`` (see paths.py).

CLI usage
---------
    python -m fpl_grounded_assistant.owned_store_sync sync [--season SEASON]
        Download the owned store from R2 (fail-soft; exit 0 if ok else 1).

    python -m fpl_grounded_assistant.owned_store_sync publish [--season SEASON]
        Upload the local owned store to R2 (operator command; loud on failure).
"""
from __future__ import annotations

import logging
import json
import sys
import os
from dataclasses import dataclass
from datetime import datetime, timezone

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# sys.path shim — mirror owned_store_fallback.py's _SIB()-style pattern.
# Insert fpl-historical onto sys.path so its modules are importable.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))        # fpl_grounded_assistant/
_PKG  = os.path.dirname(_HERE)                            # fpl-grounded-assistant/
_PKGS = os.path.dirname(_PKG)                             # packages/
_FPL_HISTORICAL = os.path.join(_PKGS, "fpl-historical")

if _FPL_HISTORICAL not in sys.path:
    sys.path.insert(0, _FPL_HISTORICAL)

try:
    from fpl_historical.paths import (  # type: ignore[import]
        CURRENT_SEASON,
        merged_parquet_dir,
        owned_latest_pointer_path,
    )
    _FPL_HISTORICAL_AVAILABLE = True
except ImportError:
    _FPL_HISTORICAL_AVAILABLE = False
    CURRENT_SEASON = "2025-2026"  # fallback constant so default arg still resolves


# ---------------------------------------------------------------------------
# Env var names (module constants)
# ---------------------------------------------------------------------------
ENV_SYNC_ENABLED          = "OWNED_STORE_SYNC_ENABLED"
ENV_R2_ENDPOINT           = "OWNED_STORE_R2_ENDPOINT"
ENV_R2_BUCKET             = "OWNED_STORE_R2_BUCKET"
ENV_R2_ACCESS_KEY_ID      = "OWNED_STORE_R2_ACCESS_KEY_ID"
ENV_R2_SECRET_ACCESS_KEY  = "OWNED_STORE_R2_SECRET_ACCESS_KEY"
ENV_R2_PREFIX             = "OWNED_STORE_R2_PREFIX"

#: The 5 merged parquet table names (pointer is handled separately).
_PARQUET_NAMES = ("players", "teams", "events", "fixtures", "player_gw_stats")

#: Same parse format as owned_store_fallback._parse_merged_at (§10.6).
_MERGED_AT_FORMAT = "%Y-%m-%dT%H-%M-%SZ"


# ---------------------------------------------------------------------------
# Frozen public type
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SyncResult:
    ok: bool
    season: str
    files_synced: int
    merged_at: str | None
    staleness_hours: float | None
    error: str | None


#: Records the most recent sync result, read by /healthz. None until a sync runs.
_LAST_SYNC_RESULT: "SyncResult | None" = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def sync_enabled() -> bool:
    """Return True iff ``OWNED_STORE_SYNC_ENABLED`` is truthy.

    Truthy = "1"/"true"/"yes" (case-insensitive, stripped). Default OFF.
    """
    raw = os.environ.get(ENV_SYNC_ENABLED, "")
    return raw.strip().lower() in ("1", "true", "yes")


def get_last_sync_result() -> "SyncResult | None":
    """Return the most recent SyncResult, or None if no sync has run."""
    return _LAST_SYNC_RESULT


def _r2_prefix() -> str:
    """Return the normalised R2 key prefix.

    Empty when unset; otherwise stripped of leading slashes and ending in
    exactly one trailing slash.
    """
    raw = os.environ.get(ENV_R2_PREFIX, "") or ""
    raw = raw.strip().lstrip("/")
    if not raw:
        return ""
    return raw.rstrip("/") + "/"


def _season_transfer_plan(season: str) -> list[tuple["object", str]]:
    """Return a list of (local_path, r2_key) tuples for the 6 canonical files.

    Order: pointer first, then the 5 merged parquet tables. The local paths
    are ``pathlib.Path`` instances; r2 keys are str.
    """
    prefix = _r2_prefix()
    merged_dir = merged_parquet_dir(season)

    plan: list[tuple[object, str]] = [
        (
            owned_latest_pointer_path(season),
            f"{prefix}seasons/{season}/_owned_latest.json",
        ),
    ]
    for name in _PARQUET_NAMES:
        plan.append((
            merged_dir / f"{name}.parquet",
            f"{prefix}seasons/{season}/parquet_merged/{name}.parquet",
        ))
    return plan


def _make_r2_client():
    """Build a boto3 S3 client pointed at R2.

    Imports boto3 lazily so this module imports even when boto3 is absent.
    Raises RuntimeError if any required env var is missing or boto3 fails
    to import — callers catch it.
    """
    endpoint   = os.environ.get(ENV_R2_ENDPOINT, "").strip()
    access_key = os.environ.get(ENV_R2_ACCESS_KEY_ID, "").strip()
    secret_key = os.environ.get(ENV_R2_SECRET_ACCESS_KEY, "").strip()
    bucket     = os.environ.get(ENV_R2_BUCKET, "").strip()

    missing = [
        name for name, val in (
            (ENV_R2_ENDPOINT, endpoint),
            (ENV_R2_BUCKET, bucket),
            (ENV_R2_ACCESS_KEY_ID, access_key),
            (ENV_R2_SECRET_ACCESS_KEY, secret_key),
        )
        if not val
    ]
    if missing:
        raise RuntimeError(
            f"missing required R2 env vars: {', '.join(missing)}"
        )

    try:
        import boto3  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(f"boto3 not available: {exc}") from exc

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",  # R2 convention
    )


def _read_merged_at_and_staleness(season: str) -> "tuple[str | None, float | None]":
    """Read the local pointer to extract merged_at and compute staleness_hours.

    Returns (None, None) on any failure — never raises.
    """
    try:
        pointer_path = owned_latest_pointer_path(season)
        pointer = json.loads(pointer_path.read_text("utf-8"))
        merged_at = pointer.get("merged_at")
        if not merged_at:
            return (None, None)
        merged_at_dt = datetime.strptime(merged_at, _MERGED_AT_FORMAT).replace(
            tzinfo=timezone.utc
        )
        now_utc = datetime.now(tz=timezone.utc)
        staleness = round((now_utc - merged_at_dt).total_seconds() / 3600.0, 2)
        return (merged_at, staleness)
    except Exception:  # noqa: BLE001 — freshness is best-effort, never fatal
        return (None, None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def sync_owned_store_from_r2(season: str = CURRENT_SEASON) -> SyncResult:
    """Download the owned store from R2 into the local filesystem. FAIL-SOFT.

    Never raises. On any exception the failure is logged, ``_LAST_SYNC_RESULT``
    is set to a failed SyncResult, and that result is returned.

    ok=True iff the pointer + all 5 parquet files downloaded with no exception.
    Otherwise ok=False with an error describing which files were missing.
    """
    global _LAST_SYNC_RESULT

    if not _FPL_HISTORICAL_AVAILABLE:
        result = SyncResult(
            ok=False, season=season, files_synced=0,
            merged_at=None, staleness_hours=None,
            error="fpl-historical not available",
        )
        _LOGGER.error(
            "owned_store_sync event=sync_failed season=%s err=%s",
            season, result.error,
        )
        _LAST_SYNC_RESULT = result
        return result

    try:
        client = _make_r2_client()
        bucket = os.environ.get(ENV_R2_BUCKET, "").strip()
        plan = _season_transfer_plan(season)

        # Ensure the merged parquet dir exists before downloading into it.
        merged_parquet_dir(season).mkdir(parents=True, exist_ok=True)
        # Ensure the pointer's parent dir exists too.
        owned_latest_pointer_path(season).parent.mkdir(parents=True, exist_ok=True)

        files_synced = 0
        missing: list[str] = []
        for local_path, r2_key in plan:
            try:
                client.download_file(bucket, r2_key, str(local_path))
                files_synced += 1
            except Exception as exc:  # noqa: BLE001 — record miss, keep going
                missing.append(r2_key)
                _LOGGER.warning(
                    "owned_store_sync event=file_missing season=%s key=%s err=%s",
                    season, r2_key, exc,
                )

        # Read freshness from the now-local pointer (best-effort).
        merged_at, staleness_hours = _read_merged_at_and_staleness(season)

        expected = len(plan)
        ok = files_synced == expected and not missing
        error = None if ok else f"missing files: {', '.join(missing)}"

        result = SyncResult(
            ok=ok, season=season, files_synced=files_synced,
            merged_at=merged_at, staleness_hours=staleness_hours,
            error=error,
        )

        if ok:
            # WARNING level so freshness is always visible in logs.
            _LOGGER.warning(
                "owned_store_sync event=sync_ok season=%s files=%d "
                "merged_at=%s staleness_hours=%s",
                season, files_synced, merged_at, staleness_hours,
            )
        else:
            _LOGGER.error(
                "owned_store_sync event=sync_incomplete season=%s files=%d "
                "merged_at=%s staleness_hours=%s err=%s",
                season, files_synced, merged_at, staleness_hours, error,
            )

        _LAST_SYNC_RESULT = result
        return result

    except Exception as exc:  # noqa: BLE001 — FAIL-SOFT: never raise
        result = SyncResult(
            ok=False, season=season, files_synced=0,
            merged_at=None, staleness_hours=None,
            error=str(exc),
        )
        _LOGGER.error(
            "owned_store_sync event=sync_failed season=%s err=%s",
            season, exc,
        )
        _LAST_SYNC_RESULT = result
        return result


def publish_owned_store_to_r2(season: str = CURRENT_SEASON) -> SyncResult:
    """Upload the local owned store to R2 (operator command).

    Reverse of :func:`sync_owned_store_from_r2`. Uploads the same 6 files.
    Files that don't exist locally are skipped, but the pointer is mandatory
    (raises if missing locally). MAY raise on hard errors (loud failure is
    good for an operator command). Returns a SyncResult with ok=True on success.
    """
    global _LAST_SYNC_RESULT

    if not _FPL_HISTORICAL_AVAILABLE:
        raise RuntimeError("fpl-historical not available")

    client = _make_r2_client()
    bucket = os.environ.get(ENV_R2_BUCKET, "").strip()
    plan = _season_transfer_plan(season)

    # Pointer is the first entry and is mandatory.
    pointer_local, _ = plan[0]
    if not pointer_local.exists():
        raise RuntimeError(
            f"owned-store pointer missing locally: {pointer_local}"
        )

    files_synced = 0
    for local_path, r2_key in plan:
        if not local_path.exists():
            _LOGGER.warning(
                "owned_store_sync event=publish_skip season=%s key=%s "
                "reason=local_missing",
                season, r2_key,
            )
            continue
        client.upload_file(str(local_path), bucket, r2_key)
        files_synced += 1

    merged_at, staleness_hours = _read_merged_at_and_staleness(season)

    result = SyncResult(
        ok=True, season=season, files_synced=files_synced,
        merged_at=merged_at, staleness_hours=staleness_hours,
        error=None,
    )
    _LOGGER.warning(
        "owned_store_sync event=publish_ok season=%s files=%d "
        "merged_at=%s staleness_hours=%s",
        season, files_synced, merged_at, staleness_hours,
    )
    _LAST_SYNC_RESULT = result
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: "list[str] | None" = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m fpl_grounded_assistant.owned_store_sync",
        description="Sync/publish the owned parquet store to/from Cloudflare R2.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="Download owned store from R2 (fail-soft).")
    p_sync.add_argument("--season", default=CURRENT_SEASON)

    p_pub = sub.add_parser("publish", help="Upload owned store to R2 (operator).")
    p_pub.add_argument("--season", default=CURRENT_SEASON)

    args = parser.parse_args(argv)

    if args.command == "sync":
        result = sync_owned_store_from_r2(args.season)
        print(result)
        return 0 if result.ok else 1

    if args.command == "publish":
        result = publish_owned_store_to_r2(args.season)
        print(result)
        return 0 if result.ok else 1

    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(_main())

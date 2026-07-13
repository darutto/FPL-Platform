"""
fpl_tactical.publish
====================
R2 publish/sync for the tactical store, mirroring
``fpl_grounded_assistant.owned_store_sync`` conventions.

Reuses the same R2 env vars as the FPL owned store
(``OWNED_STORE_R2_ENDPOINT/BUCKET/ACCESS_KEY_ID/SECRET_ACCESS_KEY/PREFIX``)
but under a distinct ``tactical/`` key segment so tactical objects can never
collide with the FPL owned store:

    r2://<bucket>/<OWNED_STORE_R2_PREFIX><tactical/><season>/understat_shots.parquet
    r2://<bucket>/<OWNED_STORE_R2_PREFIX><tactical/><season>/_tactical_latest.json

CLI usage
---------
    python -m fpl_tactical.publish publish [--season SEASON]
        Upload the local tactical store to R2 (operator/workflow; loud on failure).

    python -m fpl_tactical.publish sync [--season SEASON]
        Download the tactical store from R2 (fail-soft; exit 0 if ok else 1).
        This is the serving-side delivery path: the server reads the parquet,
        it never installs soccerdata.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from fpl_tactical.paths import (
    CURRENT_SEASON,
    latest_pointer_path,
    season_dir,
    shots_parquet_path,
)

_LOGGER = logging.getLogger(__name__)

#: Startup-sync gate — tactical analogue of owned_store_sync's
#: OWNED_STORE_SYNC_ENABLED so the two syncs toggle independently.
#: Truthy = "1"/"true"/"yes" (case-insensitive, stripped). Default OFF.
ENV_TACTICAL_SYNC_ENABLED = "TACTICAL_STORE_SYNC_ENABLED"

# Same env var names as owned_store_sync — one set of R2 credentials.
ENV_R2_ENDPOINT          = "OWNED_STORE_R2_ENDPOINT"
ENV_R2_BUCKET            = "OWNED_STORE_R2_BUCKET"
ENV_R2_ACCESS_KEY_ID     = "OWNED_STORE_R2_ACCESS_KEY_ID"
ENV_R2_SECRET_ACCESS_KEY = "OWNED_STORE_R2_SECRET_ACCESS_KEY"
ENV_R2_PREFIX            = "OWNED_STORE_R2_PREFIX"

#: Distinct key segment — keeps tactical objects out of the FPL owned store's
#: ``seasons/...`` namespace even when OWNED_STORE_R2_PREFIX is shared.
_TACTICAL_SEGMENT = "tactical/"


@dataclass(frozen=True)
class TacticalSyncResult:
    ok: bool
    season: str
    files_synced: int
    error: str | None


#: Records the most recent sync/publish result, read by /healthz.
#: None until a sync runs (default-off).
_LAST_TACTICAL_SYNC_RESULT: "TacticalSyncResult | None" = None


def tactical_sync_enabled() -> bool:
    """Return True iff ``TACTICAL_STORE_SYNC_ENABLED`` is truthy.

    Truthy = "1"/"true"/"yes" (case-insensitive, stripped). Default OFF —
    mirrors ``owned_store_sync.sync_enabled()``.
    """
    raw = os.environ.get(ENV_TACTICAL_SYNC_ENABLED, "")
    return raw.strip().lower() in ("1", "true", "yes")


def get_last_tactical_sync_result() -> "TacticalSyncResult | None":
    """Return the most recent TacticalSyncResult, or None if no sync has run."""
    return _LAST_TACTICAL_SYNC_RESULT


def _r2_prefix() -> str:
    """Normalised base prefix: empty, or ending in exactly one trailing slash."""
    raw = (os.environ.get(ENV_R2_PREFIX, "") or "").strip().lstrip("/")
    if not raw:
        return ""
    return raw.rstrip("/") + "/"


def _season_transfer_plan(season: str) -> list[tuple[Path, str]]:
    """Return (local_path, r2_key) pairs — pointer first, then the parquet."""
    base = f"{_r2_prefix()}{_TACTICAL_SEGMENT}{season}"
    return [
        (latest_pointer_path(season), f"{base}/_tactical_latest.json"),
        (shots_parquet_path(season), f"{base}/understat_shots.parquet"),
    ]


def _make_r2_client():
    """Build a boto3 S3 client pointed at R2 (lazy boto3 import).

    Raises RuntimeError if any required env var is missing or boto3 is absent.
    """
    endpoint   = os.environ.get(ENV_R2_ENDPOINT, "").strip()
    bucket     = os.environ.get(ENV_R2_BUCKET, "").strip()
    access_key = os.environ.get(ENV_R2_ACCESS_KEY_ID, "").strip()
    secret_key = os.environ.get(ENV_R2_SECRET_ACCESS_KEY, "").strip()

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
        raise RuntimeError(f"missing required R2 env vars: {', '.join(missing)}")

    try:
        import boto3  # noqa: PLC0415 — lazy so the module imports without it
    except ImportError as exc:
        raise RuntimeError(f"boto3 not available: {exc}") from exc

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",  # R2 convention
    )


def publish_tactical_store_to_r2(season: str = CURRENT_SEASON) -> TacticalSyncResult:
    """Upload the local tactical store to R2. Loud on failure (operator path).

    Both files are mandatory — a parquet without its provenance pointer (or
    vice versa) is not a valid publish.
    """
    client = _make_r2_client()
    bucket = os.environ.get(ENV_R2_BUCKET, "").strip()
    plan = _season_transfer_plan(season)

    for local_path, _ in plan:
        if not local_path.exists():
            raise RuntimeError(f"tactical store file missing locally: {local_path}")

    for local_path, r2_key in plan:
        client.upload_file(str(local_path), bucket, r2_key)
        _LOGGER.warning(
            "tactical_publish event=upload_ok season=%s key=%s", season, r2_key
        )
    global _LAST_TACTICAL_SYNC_RESULT
    result = TacticalSyncResult(ok=True, season=season, files_synced=len(plan), error=None)
    _LAST_TACTICAL_SYNC_RESULT = result
    return result


def sync_tactical_store_from_r2(season: str = CURRENT_SEASON) -> TacticalSyncResult:
    """Download the tactical store from R2 into the local store. FAIL-SOFT.

    Never raises — the zonal engine degrades to ``missing_context`` when the
    store is absent, so a failed sync must not take the server down.
    """
    try:
        client = _make_r2_client()
        bucket = os.environ.get(ENV_R2_BUCKET, "").strip()
        plan = _season_transfer_plan(season)
        season_dir(season).mkdir(parents=True, exist_ok=True)

        missing: list[str] = []
        files_synced = 0
        for local_path, r2_key in plan:
            try:
                client.download_file(bucket, r2_key, str(local_path))
                files_synced += 1
            except Exception as exc:  # noqa: BLE001 — record miss, keep going
                missing.append(r2_key)
                _LOGGER.warning(
                    "tactical_sync event=file_missing season=%s key=%s err=%s",
                    season, r2_key, exc,
                )
        ok = not missing
        result = TacticalSyncResult(
            ok=ok, season=season, files_synced=files_synced,
            error=None if ok else f"missing files: {', '.join(missing)}",
        )
    except Exception as exc:  # noqa: BLE001 — FAIL-SOFT: never raise
        result = TacticalSyncResult(ok=False, season=season, files_synced=0, error=str(exc))
    global _LAST_TACTICAL_SYNC_RESULT
    _LAST_TACTICAL_SYNC_RESULT = result
    if result.ok:
        _LOGGER.warning(
            "tactical_sync event=sync_ok season=%s files=%d",
            season, result.files_synced,
        )
    else:
        _LOGGER.error(
            "tactical_sync event=sync_failed season=%s err=%s", season, result.error
        )
    return result


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m fpl_tactical.publish",
        description="Publish/sync the tactical store to/from Cloudflare R2.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("publish", "Upload tactical store to R2 (operator/workflow)."),
        ("sync", "Download tactical store from R2 (fail-soft)."),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--season", default=CURRENT_SEASON)

    args = parser.parse_args(argv)
    if args.command == "publish":
        result = publish_tactical_store_to_r2(args.season)
    else:
        result = sync_tactical_store_from_r2(args.season)
    print(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(_main())

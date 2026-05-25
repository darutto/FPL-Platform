"""
fpl_historical.capture
======================
Core capture logic: fetches FPL bootstrap-static, all fixtures, and
per-player element summaries; gzip-writes raw payloads; writes _manifest.json.

Public API:
    capture_season(season, *, allow_missing_summaries) -> Manifest
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from fpl_historical._io import _fetch_raw, _write_gz

from fpl_api_client.fpl_client import (
    BOOTSTRAP_URL,
    ELEMENT_SUMMARY_URL,
    ALL_FIXTURES_URL,
)

from fpl_historical.manifest import (
    Manifest,
    sha256_bytes,
    write_manifest,
)
from fpl_historical.paths import (
    CURRENT_SEASON,
    new_raw_dir,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_git_sha() -> str:
    """Return short git SHA of HEAD, or ``"unknown"`` on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def capture_season(
    season: str = CURRENT_SEASON,
    *,
    allow_missing_summaries: int = 0,
    element_summary_timeout: int = 20,
) -> Manifest:
    """Capture a full season snapshot and return the resulting :class:`Manifest`.

    Steps:
    1. Fetch bootstrap-static.
    2. Fetch all fixtures (no event filter).
    3. For each player in bootstrap.elements, fetch element-summary with a
       50 ms sleep between calls to be polite to the FPL API.
    4. Gzip-write each payload; write ``_manifest.json``.

    Status determination follows CONTRACT §2 canonical algorithm.

    Parameters
    ----------
    season:
        Season key, e.g. ``"2025-2026"``.
    allow_missing_summaries:
        Maximum number of element-summary failures before status is
        downgraded from ``complete_with_gaps`` to ``failed``.
    """
    run_start = time.monotonic()
    captured_at_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    git_sha = _get_git_sha()

    raw_dir = new_raw_dir(season)

    # ------------------------------------------------------------------
    # 1. Bootstrap-static
    # ------------------------------------------------------------------
    bs_status, bs_bytes = _fetch_raw(BOOTSTRAP_URL)
    if bs_bytes:
        _write_gz(raw_dir / "bootstrap-static.json.gz", bs_bytes)
    bs_sha = sha256_bytes(bs_bytes) if bs_bytes else ""
    bs_endpoint: dict[str, Any] = {
        "url": BOOTSTRAP_URL,
        "status": bs_status,
        "bytes": len(bs_bytes),
        "sha256": bs_sha,
    }

    if bs_status != 200:
        elapsed = time.monotonic() - run_start
        m = Manifest(
            schema_version=1,
            season=season,
            status="failed",
            captured_at_utc=captured_at_utc,
            git_sha=git_sha,
            fpl_endpoints={
                "bootstrap-static": bs_endpoint,
                "fixtures": {"url": ALL_FIXTURES_URL, "status": None, "bytes": 0, "sha256": ""},
                "element-summary": {"count": 0, "failures": [], "sha256_aggregate": ""},
            },
            current_event_id=None,
            elapsed_seconds=round(elapsed, 2),
        )
        write_manifest(raw_dir, m)
        return m

    # Parse bootstrap for player list and current event
    bootstrap = json.loads(bs_bytes.decode("utf-8"))
    elements = bootstrap.get("elements", [])
    events = bootstrap.get("events", [])
    current_event_id: int | None = None
    for ev in events:
        if ev.get("is_current"):
            current_event_id = int(ev["id"])
            break
    if current_event_id is None:
        for ev in events:
            if ev.get("is_next"):
                current_event_id = int(ev["id"])
                break

    # ------------------------------------------------------------------
    # 2. All fixtures
    # ------------------------------------------------------------------
    fx_status, fx_bytes = _fetch_raw(ALL_FIXTURES_URL)
    if fx_bytes:
        _write_gz(raw_dir / "fixtures.json.gz", fx_bytes)
    fx_sha = sha256_bytes(fx_bytes) if fx_bytes else ""
    fx_endpoint: dict[str, Any] = {
        "url": ALL_FIXTURES_URL,
        "status": fx_status,
        "bytes": len(fx_bytes),
        "sha256": fx_sha,
    }

    if fx_status != 200:
        elapsed = time.monotonic() - run_start
        m = Manifest(
            schema_version=1,
            season=season,
            status="failed",
            captured_at_utc=captured_at_utc,
            git_sha=git_sha,
            fpl_endpoints={
                "bootstrap-static": bs_endpoint,
                "fixtures": fx_endpoint,
                "element-summary": {"count": 0, "failures": [], "sha256_aggregate": ""},
            },
            current_event_id=current_event_id,
            elapsed_seconds=round(elapsed, 2),
        )
        write_manifest(raw_dir, m)
        return m

    # ------------------------------------------------------------------
    # 3. Per-player element summaries
    # ------------------------------------------------------------------
    es_failures: list[dict[str, Any]] = []
    es_sha256s: list[str] = []
    es_count = 0

    for element in elements:
        element_id: int = element["id"]
        url = ELEMENT_SUMMARY_URL.format(element_id=element_id)
        es_status, es_bytes = _fetch_raw(url, timeout=element_summary_timeout)

        if es_status == 200 and es_bytes:
            _write_gz(
                raw_dir / "element-summary" / f"{element_id}.json.gz",
                es_bytes,
            )
            es_sha256s.append(sha256_bytes(es_bytes))
            es_count += 1
        else:
            es_failures.append({
                "element_id": element_id,
                "status": es_status if es_status != 0 else None,
                "error": f"HTTP {es_status}" if es_status else "network error",
            })

        time.sleep(0.05)

    # SHA-256 aggregate: hash of concatenated individual hashes (sorted for stability)
    aggregate_input = "".join(sorted(es_sha256s)).encode("utf-8")
    sha256_aggregate = sha256_bytes(aggregate_input) if es_sha256s else ""

    es_endpoint: dict[str, Any] = {
        "count": es_count,
        "failures": es_failures,
        "sha256_aggregate": sha256_aggregate,
    }

    # ------------------------------------------------------------------
    # 4. Status determination (CONTRACT §2 canonical algorithm)
    # ------------------------------------------------------------------
    n_failures = len(es_failures)
    if n_failures == 0:
        status: str = "complete"
    elif n_failures <= allow_missing_summaries:
        status = "complete_with_gaps"
    else:
        status = "failed"

    elapsed = time.monotonic() - run_start
    m = Manifest(
        schema_version=1,
        season=season,
        status=status,  # type: ignore[arg-type]
        captured_at_utc=captured_at_utc,
        git_sha=git_sha,
        fpl_endpoints={
            "bootstrap-static": bs_endpoint,
            "fixtures": fx_endpoint,
            "element-summary": es_endpoint,
        },
        current_event_id=current_event_id,
        elapsed_seconds=round(elapsed, 2),
    )
    write_manifest(raw_dir, m)
    return m

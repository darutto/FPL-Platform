"""
fpl_historical.incremental
==========================
Per-gameweek anchor capture (CONTRACT §9).

Fetches bootstrap-static, all-fixtures, and event/{gw}/live/ for a single
gameweek.  Writes three gzipped JSON files plus a v2 _manifest.json under
``incremental/gw{NN}/{captured_at_utc}/``.

Public API:
    capture_gameweek(gw, season, *, force, mode, bootstrap) -> Manifest | None
        Returns None when the skip rule fires (caller treats as "skipped").
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from fpl_api_client.fpl_client import (
    ALL_FIXTURES_URL,
    BOOTSTRAP_URL,
    EVENT_LIVE_URL,
)

from fpl_historical._io import _fetch_raw, _write_gz
from fpl_historical.manifest import (
    Manifest,
    read_manifest,
    sha256_bytes,
    write_manifest,
)
from fpl_historical.paths import (
    CURRENT_SEASON,
    gw_dir,
    list_incremental_dirs,
    new_incremental_dir,
)


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


def _should_skip(season: str, gw: int, current_event: dict) -> bool:
    """Return True if the §9.3 skip rule applies.

    Skip iff:
    - A ``complete`` snapshot exists under ``incremental/gw{NN}/``
    - That snapshot's ``gw_state.data_checked`` is True
    - The live bootstrap event also reports ``data_checked`` as True
    """
    if not current_event.get("data_checked"):
        return False
    for inc_dir in list_incremental_dirs(season, gw):
        try:
            m = read_manifest(inc_dir)
        except Exception:
            continue
        if (
            m.status == "complete"
            and m.gw_state is not None
            and m.gw_state.get("data_checked") is True
        ):
            return True
    return False


def capture_gameweek(
    gw: int | None = None,
    season: str = CURRENT_SEASON,
    *,
    force: bool = False,
    mode: str = "explicit",
    bootstrap: dict | None = None,
) -> Manifest | None:
    """Capture a per-gameweek anchor snapshot and return the resulting Manifest.

    Returns ``None`` when the §9.3 skip rule fires (the caller treats this as
    a clean skip, not a failure).

    Parameters
    ----------
    gw:
        Gameweek number to capture.  Must be present in ``bootstrap["events"]``
        (resolved by ``id`` lookup, never by positional indexing — CONTRACT §9.3).
    season:
        Season key, e.g. ``"2025-2026"``.
    force:
        If True, override the §9.3 skip rule and always write a new snapshot.
    mode:
        Informational; one of ``"explicit"``, ``"current"``, ``"auto"``.
        Not used in the skip rule — kept for future observability.
    bootstrap:
        Pre-fetched bootstrap dict.  If None, one network fetch is performed.
        Passing a pre-fetched bootstrap is the pattern for ``--auto`` mode
        (single fetch shared across the loop).
    """
    run_start = time.monotonic()
    captured_at_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    git_sha = _get_git_sha()

    # ------------------------------------------------------------------
    # 1. Bootstrap fetch (or reuse caller-supplied dict)
    # ------------------------------------------------------------------
    if bootstrap is None:
        bs_status, bs_bytes = _fetch_raw(BOOTSTRAP_URL)
        if bs_status != 200 or not bs_bytes:
            # Bootstrap failed — write a failed manifest with no incremental dir yet
            # We still need a dir to write the manifest into
            inc_dir = new_incremental_dir(season, gw if gw is not None else 0)
            elapsed = time.monotonic() - run_start
            m = Manifest(
                schema_version=2,
                season=season,
                status="failed",
                captured_at_utc=captured_at_utc,
                git_sha=git_sha,
                fpl_endpoints={
                    "bootstrap-static": {
                        "url": BOOTSTRAP_URL,
                        "status": bs_status,
                        "bytes": len(bs_bytes),
                        "sha256": "",
                    },
                    "fixtures": {"url": ALL_FIXTURES_URL, "status": None, "bytes": 0, "sha256": ""},
                    "event-live": {
                        "url": EVENT_LIVE_URL.format(gameweek=gw),
                        "status": None,
                        "bytes": 0,
                        "sha256": "",
                    },
                },
                current_event_id=None,
                elapsed_seconds=round(elapsed, 2),
                kind="incremental",
                gameweek=gw,
                gw_state=None,
            )
            write_manifest(inc_dir, m)
            return m
        bootstrap_dict = json.loads(bs_bytes.decode("utf-8"))
        bs_sha = sha256_bytes(bs_bytes)
    else:
        # Re-fetch raw bytes for writing to disk even when bootstrap dict is provided
        bs_status, bs_bytes = _fetch_raw(BOOTSTRAP_URL)
        if bs_status != 200 or not bs_bytes:
            inc_dir = new_incremental_dir(season, gw if gw is not None else 0)
            elapsed = time.monotonic() - run_start
            m = Manifest(
                schema_version=2,
                season=season,
                status="failed",
                captured_at_utc=captured_at_utc,
                git_sha=git_sha,
                fpl_endpoints={
                    "bootstrap-static": {
                        "url": BOOTSTRAP_URL,
                        "status": bs_status,
                        "bytes": 0,
                        "sha256": "",
                    },
                    "fixtures": {"url": ALL_FIXTURES_URL, "status": None, "bytes": 0, "sha256": ""},
                    "event-live": {
                        "url": EVENT_LIVE_URL.format(gameweek=gw),
                        "status": None,
                        "bytes": 0,
                        "sha256": "",
                    },
                },
                current_event_id=None,
                elapsed_seconds=round(elapsed, 2),
                kind="incremental",
                gameweek=gw,
                gw_state=None,
            )
            write_manifest(inc_dir, m)
            return m
        # Use the caller-supplied dict for event lookup (more up-to-date)
        bootstrap_dict = bootstrap
        bs_sha = sha256_bytes(bs_bytes)

    # ------------------------------------------------------------------
    # 2. Resolve target event by id lookup (CONTRACT §9.3 — never by index)
    # ------------------------------------------------------------------
    events: list[dict[str, Any]] = bootstrap_dict.get("events", [])
    event: dict[str, Any] | None = next(
        (e for e in events if e["id"] == gw), None
    )

    if event is None:
        # No matching event — write a failed manifest
        inc_dir = new_incremental_dir(season, gw if gw is not None else 0)
        elapsed = time.monotonic() - run_start
        m = Manifest(
            schema_version=2,
            season=season,
            status="failed",
            captured_at_utc=captured_at_utc,
            git_sha=git_sha,
            fpl_endpoints={
                "bootstrap-static": {
                    "url": BOOTSTRAP_URL,
                    "status": bs_status,
                    "bytes": len(bs_bytes),
                    "sha256": bs_sha,
                },
                "fixtures": {
                    "url": ALL_FIXTURES_URL,
                    "status": None,
                    "bytes": 0,
                    "sha256": "",
                    "error": f"Skipped: event id={gw} not found in bootstrap.events",
                },
                "event-live": {
                    "url": EVENT_LIVE_URL.format(gameweek=gw),
                    "status": None,
                    "bytes": 0,
                    "sha256": "",
                    "error": f"Skipped: event id={gw} not found in bootstrap.events",
                },
            },
            current_event_id=None,
            elapsed_seconds=round(elapsed, 2),
            kind="incremental",
            gameweek=gw,
            gw_state=None,
        )
        write_manifest(inc_dir, m)
        return m

    # ------------------------------------------------------------------
    # 3. Build gw_state from the resolved event
    # ------------------------------------------------------------------
    gw_state: dict[str, Any] = {
        "finished": event.get("finished"),
        "data_checked": event.get("data_checked"),
        "is_current": event.get("is_current"),
        "deadline_time": event.get("deadline_time"),
    }

    # ------------------------------------------------------------------
    # 4. Apply skip rule (CONTRACT §9.3) unless force=True
    # ------------------------------------------------------------------
    if not force and _should_skip(season, gw, event):
        return None

    # ------------------------------------------------------------------
    # 5. Write snapshot
    # ------------------------------------------------------------------
    inc_dir = new_incremental_dir(season, gw)

    # 5a. Write bootstrap bytes (already fetched above)
    _write_gz(inc_dir / "bootstrap-static.json.gz", bs_bytes)
    bs_endpoint: dict[str, Any] = {
        "url": BOOTSTRAP_URL,
        "status": bs_status,
        "bytes": len(bs_bytes),
        "sha256": bs_sha,
    }

    # 5b. Fetch and write all fixtures
    fx_status, fx_bytes = _fetch_raw(ALL_FIXTURES_URL)
    fx_sha = sha256_bytes(fx_bytes) if fx_bytes else ""
    if fx_bytes:
        _write_gz(inc_dir / "fixtures.json.gz", fx_bytes)
    fx_endpoint: dict[str, Any] = {
        "url": ALL_FIXTURES_URL,
        "status": fx_status,
        "bytes": len(fx_bytes),
        "sha256": fx_sha,
    }

    # 5c. Fetch and write event-live
    event_live_url = EVENT_LIVE_URL.format(gameweek=gw)
    el_status, el_bytes = _fetch_raw(event_live_url)
    el_sha = sha256_bytes(el_bytes) if el_bytes else ""
    if el_bytes:
        _write_gz(inc_dir / "event-live.json.gz", el_bytes)
    el_endpoint: dict[str, Any] = {
        "url": event_live_url,
        "status": el_status,
        "bytes": len(el_bytes),
        "sha256": el_sha,
    }

    # ------------------------------------------------------------------
    # 6. Determine status: complete iff all three returned 200 + non-empty body
    # ------------------------------------------------------------------
    if (
        bs_status == 200 and bs_bytes
        and fx_status == 200 and fx_bytes
        and el_status == 200 and el_bytes
    ):
        status = "complete"
    else:
        status = "failed"

    elapsed = time.monotonic() - run_start
    m = Manifest(
        schema_version=2,
        season=season,
        status=status,  # type: ignore[arg-type]
        captured_at_utc=captured_at_utc,
        git_sha=git_sha,
        fpl_endpoints={
            "bootstrap-static": bs_endpoint,
            "fixtures": fx_endpoint,
            "event-live": el_endpoint,
        },
        current_event_id=None,
        elapsed_seconds=round(elapsed, 2),
        kind="incremental",
        gameweek=gw,
        gw_state=gw_state,
    )
    write_manifest(inc_dir, m)
    return m

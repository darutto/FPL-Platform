"""
fpl_historical.cli
==================
Command-line interface for the fpl-historical capture pipeline.

Subcommands:
    capture     Full-season baseline capture (CONTRACT §4)
    capture-gw  Per-gameweek incremental capture (CONTRACT §9)

Usage:
    python -m fpl_historical.cli capture [flags]
    python -m fpl_historical.cli capture-gw (--gw N | --current | --auto) [--force] [--season S]

capture flags (CONTRACT §4):
    --season SEASON             Season key (default: 2025-2026)
    --skip-parquet              Raw capture only; skip parquet promotion
    --skip-if-fresh N           Exit 0 if newest complete snapshot < N hours old
    --allow-missing-summaries N Tolerance for ES failures (default: 0)
    --promote-with-gaps         Allow parquet promotion for complete_with_gaps

capture-gw flags (CONTRACT §9.5):
    --gw N          Explicit single gameweek (fails fast if N not in bootstrap)
    --current       Pull the gameweek where is_current==True (fallback: most recent finished)
    --auto          Iterate all finished+data_checked events; skip rule applies
    --force         Override the §9.3 skip rule; always write a new snapshot
    --season SEASON Season key (default: 2025-2026)

Exit codes (CONTRACT §4 for capture, §9.4 for capture-gw):
    0  complete  (or complete_with_gaps + --promote-with-gaps, or skip)
    1  failed
    2  complete_with_gaps  (without --promote-with-gaps)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fpl_historical.capture import capture_season
from fpl_historical.incremental import capture_gameweek
from fpl_historical._io import _fetch_raw
from fpl_historical.manifest import read_manifest
from fpl_historical.paths import (
    CURRENT_SEASON,
    list_raw_dirs,
    latest_pointer_path,
    parquet_dir,
)
from fpl_historical.projections import build_parquet_from_raw
from fpl_api_client.fpl_client import BOOTSTRAP_URL


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m fpl_historical.cli",
        description="FPL historical data capture pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    capture_cmd = sub.add_parser("capture", help="Capture a season snapshot")
    capture_cmd.add_argument(
        "--season",
        default=CURRENT_SEASON,
        help="Season key, e.g. 2025-2026 (default: %(default)s)",
    )
    capture_cmd.add_argument(
        "--skip-parquet",
        action="store_true",
        help="Capture raw data only; do not promote to parquet",
    )
    capture_cmd.add_argument(
        "--skip-if-fresh",
        type=int,
        metavar="N",
        default=None,
        help="Exit 0 without writing if newest complete snapshot is < N hours old",
    )
    capture_cmd.add_argument(
        "--allow-missing-summaries",
        type=int,
        metavar="N",
        default=0,
        help="Tolerance for element-summary failures before status → failed (default: 0)",
    )
    capture_cmd.add_argument(
        "--promote-with-gaps",
        action="store_true",
        help="Allow parquet promotion when status is complete_with_gaps",
    )
    capture_cmd.add_argument(
        "--element-summary-timeout",
        type=int,
        metavar="SECONDS",
        default=20,
        help="Per-request timeout for element-summary fetches (default: %(default)ss)",
    )
    # ------------------------------------------------------------------
    # capture-gw subcommand (CONTRACT §9.5)
    # ------------------------------------------------------------------
    cgw_cmd = sub.add_parser(
        "capture-gw",
        help="Capture a per-gameweek incremental snapshot",
    )
    cgw_mode = cgw_cmd.add_mutually_exclusive_group(required=True)
    cgw_mode.add_argument(
        "--gw",
        type=int,
        metavar="N",
        help="Explicit single gameweek number",
    )
    cgw_mode.add_argument(
        "--current",
        action="store_true",
        help="Pull the gameweek where is_current==True (fallback: most recent finished)",
    )
    cgw_mode.add_argument(
        "--auto",
        action="store_true",
        help="Capture all finished+data_checked gameweeks (skip rule applies)",
    )
    cgw_cmd.add_argument(
        "--force",
        action="store_true",
        help="Override the §9.3 skip rule; always write a new snapshot",
    )
    cgw_cmd.add_argument(
        "--season",
        default=CURRENT_SEASON,
        help="Season key (default: %(default)s)",
    )

    return parser.parse_args(argv)


def _newest_complete_snapshot_age_hours(season: str) -> float | None:
    """Return age in hours of the newest *complete* raw snapshot, or None."""
    raw_dirs = list_raw_dirs(season)
    for raw_dir in reversed(raw_dirs):
        try:
            m = read_manifest(raw_dir)
        except Exception:
            continue
        if m.status == "complete":
            # Parse captured_at_utc to compute age
            try:
                captured = datetime.fromisoformat(
                    m.captured_at_utc.replace("Z", "+00:00")
                )
                age = datetime.now(tz=timezone.utc) - captured
                return age.total_seconds() / 3600.0
            except Exception:
                continue
    return None


def _exit_code_for_status(
    status: str,
    promote_with_gaps: bool,
) -> int:
    """Return exit code per CONTRACT §4 table."""
    if status == "complete":
        return 0
    if status == "complete_with_gaps":
        return 0 if promote_with_gaps else 2
    # failed
    return 1


def cmd_capture(args: argparse.Namespace) -> int:
    """Run the capture sub-command. Returns exit code."""
    season: str = args.season
    skip_parquet: bool = args.skip_parquet
    skip_if_fresh: int | None = args.skip_if_fresh
    allow_missing: int = args.allow_missing_summaries
    promote_with_gaps: bool = args.promote_with_gaps

    # --skip-if-fresh check
    if skip_if_fresh is not None:
        age_hours = _newest_complete_snapshot_age_hours(season)
        if age_hours is not None and age_hours < skip_if_fresh:
            print(
                f"[fpl-historical] Skipping capture: newest complete snapshot is "
                f"{age_hours:.1f}h old (< {skip_if_fresh}h threshold)."
            )
            return 0

    # Run capture
    manifest = capture_season(
        season,
        allow_missing_summaries=allow_missing,
        element_summary_timeout=args.element_summary_timeout,
    )
    status = manifest.status

    should_promote = (
        not skip_parquet
        and (status == "complete" or (status == "complete_with_gaps" and promote_with_gaps))
    )
    if should_promote:
        raw_dirs = list_raw_dirs(season)
        # The most recently created raw dir is the one just captured
        current_raw_dir = raw_dirs[-1] if raw_dirs else None
        if current_raw_dir is not None:
            p_dir = parquet_dir(season)
            build_parquet_from_raw(
                current_raw_dir,
                p_dir,
                promote_with_gaps=promote_with_gaps,
            )
            # _latest.json is updated inside build_parquet_from_raw

    exit_code = _exit_code_for_status(status, promote_with_gaps if not skip_parquet else False)

    es = manifest.fpl_endpoints.get("element-summary", {})
    n_players = es.get("count", 0)
    n_failures = len(es.get("failures", []))
    print(
        f"[fpl-historical] capture {season}: status={status} "
        f"players={n_players} failures={n_failures} "
        f"elapsed={manifest.elapsed_seconds}s -> exit {exit_code}"
    )
    return exit_code


def _fetch_bootstrap_dict() -> dict | None:
    """Fetch and parse bootstrap-static.  Returns None on failure."""
    status, body = _fetch_raw(BOOTSTRAP_URL)
    if status != 200 or not body:
        return None
    return json.loads(body.decode("utf-8"))


def cmd_capture_gw(args: argparse.Namespace) -> int:
    """Run the capture-gw sub-command.  Returns exit code per CONTRACT §9.4."""
    season: str = args.season
    force: bool = args.force

    if args.gw is not None:
        # --gw N mode: single explicit gameweek
        manifest = capture_gameweek(args.gw, season, force=force, mode="explicit")
        if manifest is None:
            print(
                f"[fpl-historical] capture-gw gw={args.gw}: skipped (skip rule fired)"
            )
            return 0
        status = manifest.status
        print(
            f"[fpl-historical] capture-gw gw={args.gw}: status={status} "
            f"elapsed={manifest.elapsed_seconds}s -> exit {'0' if status == 'complete' else '1'}"
        )
        return 0 if status == "complete" else 1

    elif args.current:
        # --current mode: find the current (or fallback) gameweek from bootstrap
        bootstrap = _fetch_bootstrap_dict()
        if bootstrap is None:
            print(
                "[fpl-historical] capture-gw --current: bootstrap fetch failed",
                file=sys.stderr,
            )
            return 1

        events = bootstrap.get("events", [])
        # Primary: is_current==True
        event = next((e for e in events if e.get("is_current")), None)
        if event is None:
            # Fallback: most recent finished event (max id among finished)
            finished = [e for e in events if e.get("finished")]
            if finished:
                event = max(finished, key=lambda e: e["id"])

        if event is None:
            print(
                "[fpl-historical] capture-gw --current: no current or finished event found "
                "in bootstrap; cannot determine gameweek.",
                file=sys.stderr,
            )
            return 1

        gw_id = event["id"]
        manifest = capture_gameweek(gw_id, season, force=force, mode="current", bootstrap=bootstrap)
        if manifest is None:
            print(
                f"[fpl-historical] capture-gw --current gw={gw_id}: skipped (skip rule fired)"
            )
            return 0
        status = manifest.status
        print(
            f"[fpl-historical] capture-gw --current gw={gw_id}: status={status} "
            f"elapsed={manifest.elapsed_seconds}s -> exit {'0' if status == 'complete' else '1'}"
        )
        return 0 if status == "complete" else 1

    else:
        # --auto mode: fetch bootstrap once; iterate all finished+data_checked events
        bootstrap = _fetch_bootstrap_dict()
        if bootstrap is None:
            print(
                "[fpl-historical] capture-gw --auto: bootstrap fetch failed",
                file=sys.stderr,
            )
            return 1

        events = bootstrap.get("events", [])
        targets = [
            e for e in events
            if e.get("finished") and e.get("data_checked")
        ]

        any_failed = False
        for event in targets:
            gw_id = event["id"]
            manifest = capture_gameweek(
                gw_id, season, force=force, mode="auto", bootstrap=bootstrap
            )
            if manifest is None:
                print(f"[fpl-historical] capture-gw --auto gw={gw_id}: skipped")
            elif manifest.status == "complete":
                print(
                    f"[fpl-historical] capture-gw --auto gw={gw_id}: written "
                    f"elapsed={manifest.elapsed_seconds}s"
                )
            else:
                print(
                    f"[fpl-historical] capture-gw --auto gw={gw_id}: failed "
                    f"elapsed={manifest.elapsed_seconds}s"
                )
                any_failed = True

        return 1 if any_failed else 0


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.command == "capture":
        sys.exit(cmd_capture(args))
    elif args.command == "capture-gw":
        sys.exit(cmd_capture_gw(args))
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

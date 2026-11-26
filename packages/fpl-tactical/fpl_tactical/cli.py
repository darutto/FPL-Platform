"""
fpl_tactical.cli
================
Command-line interface for the fpl-tactical ingest pipeline.

Subcommands:
    ingest   Pull one season of Understat shots into the owned parquet store
    verify   Print row counts + provenance for a stored season
    strikerapi-sync   Daily: fetch only matches due (>= 36 h past full time) and not stored
    strikerapi-load   One time, explicit: whole season by team (202 credits)
    strikerapi-activate   Copy the StrikerAPI working store to the serving paths (local compare)

Usage:
    python -m fpl_tactical.cli ingest --season 2025-2026
    python -m fpl_tactical.cli verify --season 2025-2026

Exit codes (match fpl-historical conventions):
    0  ok
    1  failed
"""

from __future__ import annotations

import argparse
import json
import sys

from fpl_tactical import PENALTY_SITUATION
from fpl_tactical import store
from fpl_tactical.paths import CURRENT_SEASON, shots_parquet_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m fpl_tactical.cli",
        description="FPL tactical (Understat zonal) data pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("ingest", "Ingest a season of Understat shots into the owned store"),
        ("verify", "Print row counts + provenance for a stored season"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument(
            "--season",
            default=CURRENT_SEASON,
            help="Season key, e.g. 2025-2026 (default: %(default)s)",
        )
    sync = sub.add_parser("strikerapi-sync", help="Fetch only what is due, within a credit ceiling")
    sync.add_argument("--season", default=CURRENT_SEASON)
    sync.add_argument("--max-credits", type=int, default=130, help="hard ceiling per run (default %(default)s)")
    load = sub.add_parser("strikerapi-load", help="First load by team: list_games + 20 team calls = 202 credits")
    load.add_argument("--season", default=CURRENT_SEASON)
    load.add_argument("--backup-parquet", required=True,
                      help="the other source's rows for this season; the first-load canary compares against it")
    load.add_argument("--yes-spend-credits", action="store_true", required=True,
                      help="required: this command spends 202 of the monthly credits")
    for cmd in (sync, load):
        cmd.add_argument("--require-r2", action="store_true",
                         help="refuse to run unless paid responses can be kept on R2 (CI)")
    euro = sub.add_parser("europe-calendar",
                          help="UCL/UEL/UECL calendar from list_games (about 6 credits), shared credit budget")
    euro.add_argument("--season", default=CURRENT_SEASON)
    euro.add_argument("--max-credits", type=int, default=20, help="hard ceiling per run (default %(default)s)")
    euro.add_argument("--require-r2", action="store_true",
                      help="refuse to run unless paid responses can be kept on R2 (CI)")
    euro.add_argument("--publish", action="store_true",
                      help="also upload the converted calendar to its private R2 object (operator decision)")
    act = sub.add_parser("strikerapi-activate", help="Copy the StrikerAPI working store onto the serving paths")
    act.add_argument("--season", default=CURRENT_SEASON)
    return parser.parse_args(argv)


def _cmd_ingest(season: str) -> int:
    from fpl_tactical.ingest import ingest_season  # lazy: pulls soccerdata

    try:
        pointer = ingest_season(season)
    except Exception as exc:  # fail loudly but with a clean exit code
        print(f"ingest FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(pointer, indent=2))
    print(f"wrote {shots_parquet_path(season)}")
    return 0


def _cmd_verify(season: str) -> int:
    shots = store.read_shots(season)
    pointer = store.read_pointer(season)
    if shots is None or pointer is None:
        print(f"verify FAILED: no store for season {season}", file=sys.stderr)
        return 1
    n_pen = int((shots["situation"] == PENALTY_SITUATION).sum())
    print(json.dumps(pointer, indent=2))
    print(
        f"rows={len(shots)} non_penalty={len(shots) - n_pen} penalties={n_pen} "
        f"matches={shots['match_id'].nunique()} teams={shots['conceding_team'].nunique()}"
    )
    return 0


def _cmd_strikerapi(args: argparse.Namespace) -> int:
    from fpl_tactical import strikerapi_ingest as si  # lazy: network helpers
    from fpl_tactical.strikerapi_client import StrikerApiClient, StrikerApiError
    from fpl_tactical.strikerapi_raw import RawCacheError

    try:
        if args.command == "strikerapi-activate":
            return _activate(args.season)
        cache = _raw_cache(args.season, args.require_r2)
        fixtures = si.fetch_fpl_fixtures()
        client = StrikerApiClient()
        if args.command == "strikerapi-sync":
            report = si.sync(args.season, client, fixtures, max_credits=args.max_credits, cache=cache)
        else:
            import pandas as pd

            report = si.load_by_team(args.season, client, fixtures, pd.read_parquet(args.backup_parquet),
                                     cache=cache)
    except si.SyncRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3
    except (si.IngestError, StrikerApiError, RawCacheError, KeyError, OSError) as exc:
        print(f"{args.command} FAILED, nothing published: {exc}", file=sys.stderr)
        return 1
    import dataclasses

    print(json.dumps(dataclasses.asdict(report), indent=2, default=str))
    if report.missing_alerts:
        for line in report.missing_alerts:
            print(f"ALERT: {line}", file=sys.stderr)
        return 4
    return 0


def _raw_cache(season: str, require_r2: bool):
    """Paid responses go to R2 when it is configured; otherwise local only (a developer machine)."""
    from fpl_tactical.publish import strikerapi_raw_location
    from fpl_tactical.strikerapi_raw import RawCache, RawCacheError

    try:
        r2, bucket, key_base = strikerapi_raw_location(season)
    except RuntimeError as exc:
        if require_r2:
            raise RawCacheError(f"paid responses cannot be kept on R2: {exc}") from None
        print(f"raw responses are kept on this machine only ({exc})", file=sys.stderr)
        return RawCache(season)
    return RawCache(season, r2, bucket, key_base)


def _activate(season: str) -> int:
    import os
    from fpl_tactical.paths import (SOURCE_STRIKERAPI, latest_pointer_path, source_pointer_path,
                                    source_shots_path)
    from fpl_tactical.publish import _check_strikerapi_pair

    sp, pp = source_shots_path(season, SOURCE_STRIKERAPI), source_pointer_path(season, SOURCE_STRIKERAPI)
    _check_strikerapi_pair(pp, sp)
    for src, dst in ((pp, latest_pointer_path(season)), (sp, shots_parquet_path(season))):
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        tmp.write_bytes(src.read_bytes())
        os.replace(str(tmp), str(dst))
    print(f"serving paths now hold the StrikerAPI store for {season}")
    return 0


def _cmd_europe_calendar(args: argparse.Namespace) -> int:
    import dataclasses
    import json
    from datetime import datetime, timezone

    from fpl_tactical import europe_calendar as euro
    from fpl_tactical.publish import calendar_location
    from fpl_tactical.strikerapi_client import StrikerApiClient
    from fpl_tactical.strikerapi_raw import RawCacheError

    try:
        cache = _raw_cache(args.season, args.require_r2)
        location: tuple = ()
        if args.require_r2 or args.publish:
            location = calendar_location()
        previous = euro.read_previous(args.season, *location)
        payload, report = euro.build(
            args.season, StrikerApiClient(), cache, datetime.now(tz=timezone.utc),
            previous=previous, max_credits=args.max_credits,
        )
        if payload is not None:
            euro.write(payload, args.season, *(location if args.publish else ()))
    except (RawCacheError, RuntimeError, OSError, ValueError) as exc:
        print(f"europe-calendar FAILED, nothing published: {exc}", file=sys.stderr)
        return 1
    out = dataclasses.asdict(report)
    out["published"] = bool(args.publish and payload is not None)
    print(json.dumps(out, indent=2))
    if report.alerts:
        for line in report.alerts:
            print(f"ALERT: {line}", file=sys.stderr)
        return 4
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "europe-calendar":
        return _cmd_europe_calendar(args)
    if args.command.startswith("strikerapi-"):
        return _cmd_strikerapi(args)
    if args.command == "ingest":
        return _cmd_ingest(args.season)
    if args.command == "verify":
        return _cmd_verify(args.season)
    return 1


if __name__ == "__main__":
    sys.exit(main())

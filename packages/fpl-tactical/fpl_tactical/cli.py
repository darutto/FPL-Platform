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

    try:
        if args.command == "strikerapi-activate":
            return _activate(args.season)
        fixtures = si.fetch_fpl_fixtures()
        client = StrikerApiClient()
        if args.command == "strikerapi-sync":
            report = si.sync(args.season, client, fixtures, max_credits=args.max_credits)
        else:
            import pandas as pd

            report = si.load_by_team(args.season, client, fixtures, pd.read_parquet(args.backup_parquet))
    except si.SyncRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3
    except (si.IngestError, StrikerApiError, KeyError, OSError) as exc:
        print(f"{args.command} FAILED, nothing published: {exc}", file=sys.stderr)
        return 1
    import dataclasses

    print(json.dumps(dataclasses.asdict(report), indent=2, default=str))
    if report.missing_alerts:
        for line in report.missing_alerts:
            print(f"ALERT: {line}", file=sys.stderr)
        return 4
    return 0


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


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command.startswith("strikerapi-"):
        return _cmd_strikerapi(args)
    if args.command == "ingest":
        return _cmd_ingest(args.season)
    if args.command == "verify":
        return _cmd_verify(args.season)
    return 1


if __name__ == "__main__":
    sys.exit(main())

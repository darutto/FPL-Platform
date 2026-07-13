"""
fpl_tactical.cli
================
Command-line interface for the fpl-tactical ingest pipeline.

Subcommands:
    ingest   Pull one season of Understat shots into the owned parquet store
    verify   Print row counts + provenance for a stored season

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


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "ingest":
        return _cmd_ingest(args.season)
    if args.command == "verify":
        return _cmd_verify(args.season)
    return 1


if __name__ == "__main__":
    sys.exit(main())

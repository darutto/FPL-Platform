"""Convert Leo's hand-compiled European list (text) to the local ``manual_curated`` JSON layer.

    python convert_manual_calendar.py IN.txt OUT.json --list-date 2026-10-27

Both paths live under ``data/calendar-manual/`` (git-ignored). Prints only counts, never a row.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for sibling in ("football-intelligence", "football-data-contract"):  # run from anywhere, no install needed
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / sibling))

from football_intelligence.manual_calendar import parse_manual_europe  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--list-date", required=True, help="YYYY-MM-DD the list was compiled (the visible stamp)")
    ap.add_argument("--unverified", action="append", default=[], metavar="CLUB:YYYY-MM-DD",
                    help="a match whose time sources disagree (kept, flagged hora por verificar); repeatable")
    args = ap.parse_args()
    unverified = frozenset(tuple(u.split(":", 1)) for u in args.unverified)
    layer = parse_manual_europe(args.source.read_text(encoding="utf-8"), list_date=args.list_date,
                                unverified=unverified)
    args.out.write_text(json.dumps(layer, ensure_ascii=False, indent=1), encoding="utf-8")
    for w in layer["warnings"]:
        print(f"WARNING line {w['line']}: {w['reason']}")
    print(f"{len(layer['matches'])} matches, competitions {layer['competitions']}, list_date {layer['list_date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

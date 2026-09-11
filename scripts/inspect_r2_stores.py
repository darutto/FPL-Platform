#!/usr/bin/env python3
"""
inspect_r2_stores.py -- report what the R2 copies of the owned and tactical
stores actually contain. Read-only: never writes to R2.

Why this exists: during the 2026-07/08 owned-store incident, and again while
planning the 2026-2027 season rollover, several conclusions about "what the
store contains" were drawn from the local working copy on a developer
machine. That copy can be months stale -- the tactical pointer on this repo's
disk reads 2026-07-07 while the refresh cron has published ten times since.
Production reads R2, not anyone's disk, so any claim about the store's state
has to be measured against R2 or it is an argument, not a measurement.

This script assumes a prior step has already synced the stores from R2 into
a scratch root (via owned_store_sync.py sync / fpl_tactical.publish sync).
It only reads what landed and prints it.

Usage:
    python scripts/inspect_r2_stores.py --owned-root DIR --tactical-root DIR \
        --season 2025-2026 [--season 2026-2027 ...]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import pandas as pd

OWNED_TABLES = ("players", "teams", "events", "fixtures", "player_gw_stats")


def _fmt_pointer(path: pathlib.Path) -> str:
    if not path.exists():
        return "  pointer: ABSENT"
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 -- report, don't crash the report
        return f"  pointer: UNREADABLE ({exc})"
    keys = ("season", "merged_at", "ingested_at", "source", "n_matches", "n_shots")
    shown = {k: p[k] for k in keys if k in p}
    return "  pointer: " + json.dumps(shown, ensure_ascii=False)


def _date_range(df: pd.DataFrame) -> str:
    for col in ("date", "kickoff_time", "captured_at"):
        if col in df.columns:
            try:
                s = pd.to_datetime(df[col], errors="coerce", utc=True).dropna()
                if len(s):
                    return f"{col} {s.min()} .. {s.max()}"
            except Exception:  # noqa: BLE001
                continue
    return "no usable date column"


def inspect_owned(root: pathlib.Path, season: str) -> None:
    print(f"\n--- OWNED STORE · {season} ---")
    sdir = root / "seasons" / season
    if not sdir.exists():
        print(f"  season dir ABSENT at {sdir}")
        return
    print(_fmt_pointer(sdir / "_owned_latest.json"))
    merged = sdir / "parquet_merged"
    for name in OWNED_TABLES:
        f = merged / f"{name}.parquet"
        if not f.exists():
            print(f"  {name:<18} ABSENT")
            continue
        df = pd.read_parquet(f)
        extra = ""
        if name == "player_gw_stats" and "event_id" in df.columns:
            gws = sorted(int(g) for g in df["event_id"].dropna().unique())
            extra = f" | gws {gws[:3]}..{gws[-3:]} ({len(gws)} total)"
        if "season" in df.columns:
            extra += f" | season col: {sorted(df['season'].dropna().unique().tolist())}"
        print(f"  {name:<18} {len(df):>6} rows | {_date_range(df)}{extra}")


def inspect_tactical(root: pathlib.Path, season: str) -> None:
    print(f"\n--- TACTICAL STORE · {season} ---")
    sdir = root / "seasons" / season
    if not sdir.exists():
        print(f"  season dir ABSENT at {sdir}")
        return
    print(_fmt_pointer(sdir / "_tactical_latest.json"))
    f = sdir / "understat_shots.parquet"
    if not f.exists():
        print("  understat_shots   ABSENT")
        return
    df = pd.read_parquet(f)
    extra = ""
    if "season" in df.columns:
        extra = f" | season col: {sorted(df['season'].dropna().unique().tolist())}"
    if "match_id" in df.columns:
        extra += f" | matches: {df['match_id'].nunique()}"
    print(f"  understat_shots   {len(df):>6} rows | {_date_range(df)}{extra}")
    if "shooting_team" in df.columns and "conceding_team" in df.columns:
        teams = sorted(set(df["shooting_team"]) | set(df["conceding_team"]))
        print(f"  teams present ({len(teams)}): {teams}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--owned-root", required=True)
    ap.add_argument("--tactical-root", required=True)
    ap.add_argument("--season", action="append", required=True,
                    help="Season key to inspect; repeatable.")
    args = ap.parse_args()

    owned = pathlib.Path(args.owned_root)
    tactical = pathlib.Path(args.tactical_root)

    print("R2 STORE INSPECTION (read-only; nothing was written to R2)")
    print(f"owned root:    {owned}")
    print(f"tactical root: {tactical}")

    for season in args.season:
        inspect_owned(owned, season)
        inspect_tactical(tactical, season)

    print("\nReminder: a season dir reported ABSENT here means R2 has no copy "
          "for that key -- which is the expected state for a season that has "
          "never been captured, and the blocking state for a rollover that "
          "assumes it exists.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

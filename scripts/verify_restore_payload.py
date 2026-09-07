#!/usr/bin/env python3
"""
verify_restore_payload.py -- second, independent gate on the 2025-2026
restore payload before it is published to R2.

This re-runs the same checks that were done locally before the payload was
committed to the transport branch (restore-payload/2025-2026-backup), but
from inside the CI runner, against the actual checked-out files -- so a
transport mistake (wrong branch, stale checkout, wrong season directory)
gets caught here instead of being trusted blindly.

Exits non-zero and prints exactly what disagreed if any check fails. The
calling workflow must treat that as fatal and must not publish.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import pandas as pd

EXPECTED = {
    "events_rows": 38,
    "fixtures_rows": 380,
    "players_rows": 841,
    "teams_rows": 20,
    "player_gw_stats_rows": 29747,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Dir containing _owned_latest.json + parquet_merged/*.parquet")
    args = parser.parse_args()

    source = pathlib.Path(args.source)
    failures: list[str] = []

    pointer_path = source / "_owned_latest.json"
    if not pointer_path.exists():
        print(f"FATAL: no pointer file at {pointer_path}", file=sys.stderr)
        return 1
    pointer = json.loads(pointer_path.read_text("utf-8"))
    if pointer.get("season") != "2025-2026":
        failures.append(f"pointer season is {pointer.get('season')!r}, expected '2025-2026'")
    if pointer.get("merged_at") != "2026-06-01T00-40-44Z":
        failures.append(f"pointer merged_at is {pointer.get('merged_at')!r}, expected '2026-06-01T00-40-44Z'")

    merged_dir = source / "parquet_merged"

    def load(name: str) -> pd.DataFrame:
        return pd.read_parquet(merged_dir / f"{name}.parquet")

    events = load("events")
    fixtures = load("fixtures")
    players = load("players")
    teams = load("teams")
    pg = load("player_gw_stats")

    counts = {
        "events_rows": len(events),
        "fixtures_rows": len(fixtures),
        "players_rows": len(players),
        "teams_rows": len(teams),
        "player_gw_stats_rows": len(pg),
    }
    for key, expected in EXPECTED.items():
        actual = counts[key]
        if actual != expected:
            failures.append(f"{key}: expected {expected}, got {actual}")

    if "event_id" in pg.columns:
        gws = sorted(pg["event_id"].unique().tolist())
        if gws != list(range(1, 39)):
            failures.append(f"player_gw_stats event_id coverage is not exactly 1..38: {gws[:5]}...{gws[-5:]}")

    if "player_id" in players.columns:
        n_unique = players["player_id"].nunique()
        if n_unique != len(players):
            failures.append(f"players.player_id has {len(players) - n_unique} duplicate id(s)")

    if {"player_id", "event_id"}.issubset(pg.columns):
        n_dupe = int(pg.duplicated(["player_id", "event_id"]).sum())
        if n_dupe:
            failures.append(f"player_gw_stats has {n_dupe} duplicate (player_id, event_id) row(s)")

    if "minutes" in pg.columns:
        bad = int(((pg["minutes"] < 0) | (pg["minutes"] > 120)).sum())
        if bad:
            failures.append(f"player_gw_stats has {bad} row(s) with minutes outside [0, 120]")

    if failures:
        print("RESTORE PAYLOAD VERIFICATION FAILED -- refusing to publish:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("Restore payload verification passed:")
    for key, val in counts.items():
        print(f"  {key}: {val}")
    print(f"  pointer: season={pointer['season']} merged_at={pointer['merged_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

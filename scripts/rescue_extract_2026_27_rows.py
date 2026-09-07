#!/usr/bin/env python3
"""
rescue_extract_2026_27_rows.py -- pull the 2026-2027 rows out of the
contaminated owned-store table published under the "2025-2026" key, and
save them separately with the correct season label.

Context: the owned-store weekly refresh (.github/workflows/owned-store-refresh.yml,
paused as of PR #218) has been overwriting the 2025-2026 season table with
live 2026-2027 captures every Monday since 2026-07-27. The table currently
published to R2 under "2025-2026" is (per manual measurement) 100%
2026-2027 data, including the ``season`` column value itself.

This script does NOT touch R2. It only reads the parquet files that a prior
CI step already downloaded locally (via owned_store_sync.sync), retags them
as 2026-2027, and writes them to an output directory for upload as a build
artifact. The restore of 2025-2026 (from the known-good local backup) and
any decision to formally publish these 2026-2027 rows under a new season key
happen separately, after the owner decides.

Usage:
    python scripts/rescue_extract_2026_27_rows.py --source DIR --out DIR
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import pandas as pd


PARQUET_NAMES = ("players", "teams", "events", "fixtures", "player_gw_stats")

# Season start (per project memory: 2026-07-23). Any captured_at at or after
# this date could only be 2026-2027 data -- used as a cross-check, not the
# primary basis for the retag (the primary basis is: the whole table is
# contaminated, confirmed by manual inspection before this script existed).
SEASON_2026_27_START = pd.Timestamp("2026-07-23", tz="UTC")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Dir containing the downloaded 2025-2026 parquet_merged/*.parquet + _owned_latest.json")
    parser.add_argument("--out", required=True, help="Dir to write the retagged 2026-2027 rescue files into")
    args = parser.parse_args()

    source = pathlib.Path(args.source)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    pointer_path = source / "_owned_latest.json"
    if not pointer_path.exists():
        print(f"FATAL: no pointer file at {pointer_path} -- did the sync step run first?", file=sys.stderr)
        return 1

    pointer = json.loads(pointer_path.read_text("utf-8"))
    print(f"Source pointer: season={pointer.get('season')!r} merged_at={pointer.get('merged_at')!r}")

    merged_dir = source / "parquet_merged"
    summary = {}
    tables: dict[str, pd.DataFrame] = {}

    # Pass 1: load + cross-check every table BEFORE writing anything. This is
    # a one-shot incident-response script running against a live production
    # bucket -- it must never partially retag a source it hasn't fully
    # verified. A disagreement here means the assumption behind this whole
    # script (the table is 100% mislabeled 2026-2027 data) does not hold for
    # this source, and the honest move is to stop, not proceed with a
    # best-effort relabel.
    for name in PARQUET_NAMES:
        path = merged_dir / f"{name}.parquet"
        if not path.exists():
            print(f"  {name}: MISSING at {path} -- skipping", file=sys.stderr)
            summary[name] = {"status": "missing"}
            continue

        df = pd.read_parquet(path)
        total_rows = len(df)

        if "captured_at" in df.columns and total_rows > 0:
            captured = pd.to_datetime(df["captured_at"], utc=True, errors="coerce")
            post_season_start = int((captured >= SEASON_2026_27_START).sum())
            if post_season_start != total_rows:
                print(
                    f"FATAL: {name} has {post_season_start}/{total_rows} rows with "
                    f"captured_at >= {SEASON_2026_27_START.date()} -- this source is NOT "
                    f"wholly 2026-2027 data, so blindly retagging it would destroy correct "
                    f"season labels. Stopping without writing any output. Re-verify the "
                    f"source before re-running.",
                    file=sys.stderr,
                )
                return 1

        tables[name] = df
        summary[name] = {"status": "ok", "rows": total_rows}

    # Pass 2: only now that every table has passed the cross-check, retag and write.
    for name, df in tables.items():
        if "season" in df.columns:
            before_labels = sorted(df["season"].dropna().unique().tolist())
            df["season"] = "2026-2027"
        else:
            before_labels = None

        out_path = out / f"{name}.parquet"
        df.to_parquet(out_path, index=False)

        summary[name]["season_labels_before"] = before_labels
        print(f"  {name}: {len(df)} rows -> {out_path} (season retagged to 2026-2027)")

    manifest = {
        "rescue_extracted_at_utc": pd.Timestamp.now("UTC").isoformat(),
        "source_pointer": pointer,
        "retagged_season": "2026-2027",
        "note": (
            "Extracted from data published under the 2025-2026 key by the "
            "contaminated weekly refresh. NOT published to R2 by this script. "
            "Owner must decide whether/how to formally publish under the "
            "2026-2027 season key."
        ),
        "tables": summary,
    }
    (out / "_rescue_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(f"\nManifest written: {out / '_rescue_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

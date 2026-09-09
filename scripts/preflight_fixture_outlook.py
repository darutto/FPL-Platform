#!/usr/bin/env python3
"""Refuse to regenerate the /fixtures bundle from inputs that cannot separate
the two axes.

The 2026-27 bundle shipped with `attack` and `defence` collapsed onto one
signal and nothing in it said so. The failure mode is quiet by construction:
`_defence_overlay_bands` blends FDR with the opponent's rolling attacking
form, and when no form exists the blend degrades to FDR alone, producing a
perfectly well-formed bundle whose axis switcher does nothing.

So this checks the two things the recipe genuinely needs, BEFORE anything is
written, and fails loudly rather than emitting a plausible file:

  * fixtures.parquet carries FINAL results (both scores present, `finished`
    true where the column exists) for at least one gameweek -- the same rule
    compute_rolling_strength applies, so a pass here means it has data.
  * teams.parquet carries FPL's four captured strength ratings, which are the
    cold-start fallback the rolling model blends against in rank space.

Exit 0 = safe to build. Exit 1 = stop and report.
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "packages", "fpl-historical"))

from fpl_historical.rolling_strength import STRENGTH_FIELDS  # noqa: E402

_REQUIRED_FIXTURE_COLUMNS = {
    "event_id", "team_h", "team_a", "team_h_score", "team_a_score",
    "team_h_difficulty", "team_a_difficulty",
}


def _merged_dir(season: str) -> str:
    root = os.environ.get("FPL_HISTORICAL_ROOT") or os.path.join(
        _REPO_ROOT, "packages", "fpl-historical", "data", "historical"
    )
    return os.path.join(root, "seasons", season, "parquet_merged")


def preflight(season: str) -> list[str]:
    """Return a list of blocking problems; empty means the season can build."""
    problems: list[str] = []
    root = _merged_dir(season)
    print(f"preflight: {season}")
    print(f"  merged parquet dir: {root}")

    teams_path = os.path.join(root, "teams.parquet")
    fixtures_path = os.path.join(root, "fixtures.parquet")
    for path in (teams_path, fixtures_path):
        if not os.path.exists(path):
            problems.append(f"missing {path}")
    if problems:
        return problems

    teams_df = pd.read_parquet(teams_path)
    fixtures_df = pd.read_parquet(fixtures_path)
    print(f"  teams:    {len(teams_df)} rows")
    print(f"  fixtures: {len(fixtures_df)} rows")

    missing_strength = [f for f in STRENGTH_FIELDS if f not in teams_df.columns]
    if missing_strength:
        problems.append(
            "teams.parquet is missing the cold-start strength fallback: "
            + ", ".join(missing_strength)
        )
    elif teams_df[list(STRENGTH_FIELDS)].isna().any().any():
        problems.append("teams.parquet has null values in the strength fields")

    missing_columns = _REQUIRED_FIXTURE_COLUMNS - set(fixtures_df.columns)
    if missing_columns:
        problems.append(
            "fixtures.parquet is missing required columns: "
            + ", ".join(sorted(missing_columns))
        )
        return problems

    scored = fixtures_df["team_h_score"].notna() & fixtures_df["team_a_score"].notna()
    if "finished" in fixtures_df.columns:
        scored &= fixtures_df["finished"].fillna(False).astype(bool)
    played = sorted(int(g) for g in fixtures_df.loc[scored, "event_id"].unique())
    print(f"  gameweeks with final results: {len(played)} {played[:12]}")
    print(f"  finished fixtures: {int(scored.sum())}")

    if not played:
        problems.append(
            "no finished, fully-scored fixtures -- the defence axis would collapse "
            "back onto FDR and the axis switcher would keep doing nothing"
        )
    elif len(played) < 3:
        # Not blocking: the owner decided a short sample ships, declared.
        print(
            f"  NOTE: only {len(played)} gameweek(s) of results. The bundle will "
            "carry that count and the card declares the thin sample."
        )
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True, help="Season key, e.g. 2026-2027")
    args = parser.parse_args()

    problems = preflight(args.season)
    if problems:
        print("\nPREFLIGHT FAILED — not building:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)
    print("\npreflight OK — the recipe has what it needs.")


if __name__ == "__main__":
    main()

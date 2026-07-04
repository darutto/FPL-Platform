#!/usr/bin/env python3
"""Export a real-season FixtureOutlookMeta bundle for the /fixtures UI.

Track D interim step (off-season, before the new FPL season's fixtures are
live): runs the SAME fixture_outlook.py engine the live tool uses, fed with
real captured team strengths + real finished fixtures from fpl-historical,
instead of the frontend's synthetic RNG mock. Real opponents, real venues,
real gameweek order — same predictive band/run logic, zero duplication of
the algorithm (it's the actual engine module, loaded directly).

Output feeds packages/fpl-ui/lib/fixture-outlook-real.ts, which the
FixturesBoard component reads in place of the old fixture-outlook-mock.ts.

Track D Step 2 (validate-only): with --as-of-gw N, team strength comes from
fpl_historical.rolling_strength.compute_rolling_strength() instead of the
raw single end-of-season snapshot — a walk-forward, decaying estimate using
only matches before GW N, for comparing against the same real outcomes
already logged in project_track_d_backtest_findings. This mode requires
--out (it never overwrites the committed baseline JSON that /fixtures
reads) and projects the horizon forward from GW N rather than from GW1.

Usage:
    # Default (unchanged behavior) — the committed /fixtures baseline:
    python export_real_season_fixture_outlook.py

    # Step 2 validation — walk-forward strength as of GW4, written elsewhere:
    python export_real_season_fixture_outlook.py --as-of-gw 4 --out /tmp/asof-gw4.json
"""
from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import os
import sys

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_PACKAGES = os.path.dirname(os.path.dirname(_HERE))

# Load fixture_outlook.py directly from its file, bypassing
# fpl_grounded_assistant/__init__.py (heavy dispatcher/harness import chain).
# Mirrors tests/test_fixture_outlook.py's import pattern.
_ENGINE_PATH = os.path.join(
    _PACKAGES, "fpl-grounded-assistant", "fpl_grounded_assistant", "fixture_outlook.py"
)
_spec = _ilu.spec_from_file_location("fixture_outlook", _ENGINE_PATH)
fixture_outlook = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(fixture_outlook)

# fpl-historical is a sibling package (not pip-installed) — add it to
# sys.path so rolling_strength can be imported normally, mirroring how the
# repo's other cross-package scripts/tests resolve siblings.
sys.path.insert(0, os.path.join(_PACKAGES, "fpl-historical"))
from fpl_historical.rolling_strength import compute_rolling_strength  # noqa: E402

SEASON = "2025-2026"
_DATA_ROOT = os.path.join(
    _PACKAGES, "fpl-historical", "data", "historical", "seasons", SEASON, "parquet_merged"
)
_OUT_PATH = os.path.join(
    _PACKAGES, "fpl-ui", "lib", "data", "fixture-outlook-2025-26.json"
)

# Mirrors FixturesBoard's HORIZONS selector — precomputed per-horizon so each
# window is a genuine independent run() + run-detection pass, not a client-side
# slice of a longer series (which would desync avg_band/runs from a true
# "recompute for exactly N GWs" result).
HORIZONS = (5, 8, 10)
AXES = ("attack", "defence")


def build_bootstrap(as_of_gw: int | None) -> dict:
    """Reshape the captured parquet tables into the dict shape
    fixture_outlook.py expects (the same shape as a live FPL bootstrap).

    as_of_gw=None (default): raw single end-of-season strength snapshot,
    current_gw stays unset so the horizon walks from each team's GW1 — the
    committed /fixtures baseline, byte-identical to Step 1.

    as_of_gw=N: strength comes from the walk-forward rolling model (only
    matches before GW N), and "events" marks GW N as current so the horizon
    projects forward from there instead of from GW1.
    """
    teams_df = pd.read_parquet(os.path.join(_DATA_ROOT, "teams.parquet"))
    fixtures_df = pd.read_parquet(os.path.join(_DATA_ROOT, "fixtures.parquet"))

    rolling = compute_rolling_strength(SEASON, as_of_gw) if as_of_gw is not None else None

    teams: list[dict] = []
    for _, row in teams_df.iterrows():
        team_id = int(row["team_id"])
        strengths = rolling[team_id] if rolling is not None else {
            "strength_attack_home": int(row["strength_attack_home"]),
            "strength_attack_away": int(row["strength_attack_away"]),
            "strength_defence_home": int(row["strength_defence_home"]),
            "strength_defence_away": int(row["strength_defence_away"]),
        }
        teams.append({
            "id": team_id,
            "short_name": row["short_name"],
            "name": row["name"],
            **strengths,
        })

    team_fixtures: dict[int, list[dict]] = {int(t["id"]): [] for t in teams}
    for _, row in fixtures_df.sort_values("event_id").iterrows():
        gw = int(row["event_id"])
        home_id, away_id = int(row["team_h"]), int(row["team_a"])
        team_fixtures[home_id].append({
            "gameweek": gw,
            "opponent_team": away_id,
            "is_home": True,
            "difficulty": int(row["team_h_difficulty"]),
        })
        team_fixtures[away_id].append({
            "gameweek": gw,
            "opponent_team": home_id,
            "is_home": False,
            "difficulty": int(row["team_a_difficulty"]),
        })

    events = [{"id": as_of_gw, "is_current": True}] if as_of_gw is not None else []
    return {"teams": teams, "team_fixtures": team_fixtures, "events": events}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of-gw", type=int, default=None,
        help="Use walk-forward rolling strength computed from matches before this GW, "
             "and project the horizon forward from it. Omit for the committed baseline.",
    )
    parser.add_argument(
        "--out", type=str, default=None,
        help="Output path. Required with --as-of-gw (never overwrites the committed "
             "baseline JSON that /fixtures reads). Defaults to the committed path otherwise.",
    )
    args = parser.parse_args()
    if args.as_of_gw is not None and args.out is None:
        parser.error("--out is required when --as-of-gw is given")
    return args


def main() -> None:
    args = parse_args()
    out_path = args.out or _OUT_PATH

    bootstrap = build_bootstrap(args.as_of_gw)
    out: dict = {}
    for axis in AXES:
        out[axis] = {}
        for horizon in HORIZONS:
            out[axis][str(horizon)] = fixture_outlook.get_all_team_outlooks(
                bootstrap, axis=axis, horizon=horizon
            )

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(out_path) / 1024
    print(f"wrote {out_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()

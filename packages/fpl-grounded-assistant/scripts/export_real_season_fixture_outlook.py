#!/usr/bin/env python3
"""Export the real-season FixtureOutlookMeta bundle for the /fixtures UI.

Track D interim surface (off-season, before the new FPL season's fixtures are
live): renders the real, finished 2025-26 fixtures through the same run/verdict
machinery the live tool uses, feeding lib/data/fixture-outlook-2025-26.json →
lib/fixture-outlook-real.ts → FixturesBoard.

Difficulty signal — the ASYMMETRIC RECIPE (default), chosen by the ML0
evaluation harness (backtest_fixture_difficulty.py) as the best-validated
signal across all ~760 team-fixtures vs xG:
  * attack axis  = FPL's own FDR. Nothing we derived beats it, and adding form
    only dilutes it (harness: fdr +0.281 vs fdr+form +0.236).
  * defence axis = FDR anchored + refined by the opponent's WALK-FORWARD rolling
    attacking form (compute_rolling_strength as of each fixture's GW), blended
    0.6 FDR / 0.4 form in rank space, quantile-bucketed to 1-5. This is the
    first signal to BEAT FDR on any axis (harness: +0.316 vs +0.307).

Implementation reuses the engine wholesale rather than reimplementing runs /
verdicts / DGW handling / sorting: fixture_outlook._fixture_band already falls
back to a fixture's `difficulty` field when strength thresholds are absent, so
we strip strength and inject the recipe band as `difficulty`. get_all_team_
outlooks then produces a fully recipe-banded outlook for free.

Legacy analysis mode: --as-of-gw N instead uses the raw walk-forward rolling
STRENGTH snapshot through the engine's quintile bucketing (the Step-2
comparison path); requires --out and never overwrites the shipped JSON.

Usage:
    # Default — regenerate the shipped /fixtures bundle (asymmetric recipe):
    python export_real_season_fixture_outlook.py

    # Legacy Step-2 comparison — rolling strength as of GW4, elsewhere:
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
_ENGINE_PATH = os.path.join(
    _PACKAGES, "fpl-grounded-assistant", "fpl_grounded_assistant", "fixture_outlook.py"
)
_spec = _ilu.spec_from_file_location("fixture_outlook", _ENGINE_PATH)
fixture_outlook = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(fixture_outlook)

# fpl-historical is a sibling package (not pip-installed).
sys.path.insert(0, os.path.join(_PACKAGES, "fpl-historical"))
from fpl_historical.rolling_strength import compute_rolling_strength  # noqa: E402

# fpl-api-client is a sibling package (not pip-installed) — used only by the
# --season-start live path.
sys.path.insert(0, os.path.join(_PACKAGES, "fpl-api-client"))

SEASON = "2025-2026"
NEW_SEASON = "2026-27"
_DATA_ROOT = os.path.join(
    _PACKAGES, "fpl-historical", "data", "historical", "seasons", SEASON, "parquet_merged"
)
_OUT_PATH = os.path.join(
    _PACKAGES, "fpl-ui", "lib", "data", "fixture-outlook-2025-26.json"
)
# --season-start writes here (new-season live schedule), keeping the finished
# 2025-26 bundle untouched.
_OUT_PATH_NEW = os.path.join(
    _PACKAGES, "fpl-ui", "lib", "data", "fixture-outlook-2026-27.json"
)

HORIZONS = (5, 8, 10)
AXES = ("attack", "defence")

# Overlay blend weights (rank space) — must match the validated harness values.
_W_FDR = 0.6
_W_FORM = 0.4


def _load_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    teams_df = pd.read_parquet(os.path.join(_DATA_ROOT, "teams.parquet"))
    fixtures_df = pd.read_parquet(os.path.join(_DATA_ROOT, "fixtures.parquet"))
    return teams_df, fixtures_df


def _load_live_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """teams_df + fixtures_df pulled from the LIVE FPL API (new season).

    Team ids are re-assigned every season (promotions/relegations), so both the
    team roster and the fixture schedule must come from the live bootstrap /
    fixtures endpoints — never reuse last season's parquet. Fixtures whose
    ``event`` is null (season tail not yet scheduled at launch) are dropped.
    """
    from fpl_api_client.fpl_client import get_bootstrap, get_all_fixtures  # noqa: E402

    boot = get_bootstrap()
    teams_df = pd.DataFrame(
        [
            {"team_id": int(t["id"]), "short_name": t["short_name"], "name": t["name"]}
            for t in boot["teams"]
        ]
    )

    rows = []
    for f in get_all_fixtures():
        ev = f.get("event")
        if ev is None:
            continue  # unscheduled tail — no GW assigned yet
        rows.append(
            {
                "event_id": int(ev),
                "team_h": int(f["team_h"]),
                "team_a": int(f["team_a"]),
                "team_h_difficulty": int(f["team_h_difficulty"]),
                "team_a_difficulty": int(f["team_a_difficulty"]),
            }
        )
    fixtures_df = pd.DataFrame(rows)
    return teams_df, fixtures_df


def _teams_min(teams_df: pd.DataFrame) -> list[dict]:
    """Teams WITHOUT strength fields — this forces the engine's thresholds to
    None so _fixture_band reads each fixture's injected `difficulty` band."""
    return [
        {"id": int(r["team_id"]), "short_name": r["short_name"], "name": r["name"]}
        for _, r in teams_df.iterrows()
    ]


def _base_team_fixtures(fixtures_df: pd.DataFrame) -> dict[int, list[dict]]:
    """Per-team fixture list with `difficulty` = FPL FDR (the attack recipe)."""
    tf: dict[int, list[dict]] = {}
    for _, row in fixtures_df.sort_values("event_id").iterrows():
        gw = int(row["event_id"])
        home_id, away_id = int(row["team_h"]), int(row["team_a"])
        tf.setdefault(home_id, []).append({
            "gameweek": gw, "opponent_team": away_id, "is_home": True,
            "difficulty": int(row["team_h_difficulty"]),
        })
        tf.setdefault(away_id, []).append({
            "gameweek": gw, "opponent_team": home_id, "is_home": False,
            "difficulty": int(row["team_a_difficulty"]),
        })
    return tf


def _defence_overlay_bands(fixtures_df: pd.DataFrame) -> dict[tuple[int, int, bool], int]:
    """Walk-forward FDR+form overlay band (1-5) per (gw, team_id, is_home) for
    the defence axis. FDR anchored, refined by the opponent's rolling attacking
    strength as of the fixture's GW, blended in rank space and quantile-bucketed
    over the whole season (population-relative, mirroring the harness)."""
    gws = sorted(int(g) for g in fixtures_df["event_id"].unique())
    rolling_by_gw = {g: compute_rolling_strength(SEASON, g) for g in gws}

    rows = []
    for _, r in fixtures_df.iterrows():
        gw = int(r["event_id"])
        h, a = int(r["team_h"]), int(r["team_a"])
        for team_id, opp, is_home, fdr in (
            (h, a, True, int(r["team_h_difficulty"])),
            (a, h, False, int(r["team_a_difficulty"])),
        ):
            # defence difficulty reads the opponent's ATTACK strength at the
            # opponent's venue (opp plays the opposite venue to this team).
            field = fixture_outlook._STRENGTH_FIELDS[("defence", not is_home)]
            form = rolling_by_gw.get(gw, {}).get(opp, {}).get(field, 1200.0)
            rows.append((gw, team_id, is_home, fdr, form))

    df = pd.DataFrame(rows, columns=["gw", "team_id", "is_home", "fdr", "form"])
    score = _W_FDR * df["fdr"].rank(pct=True) + _W_FORM * df["form"].rank(pct=True)
    df["band"] = pd.qcut(score, 5, labels=[1, 2, 3, 4, 5], duplicates="drop").astype(int)
    return {(int(t.gw), int(t.team_id), bool(t.is_home)): int(t.band) for t in df.itertuples()}


def build_recipe_bootstraps(teams_df: pd.DataFrame, fixtures_df: pd.DataFrame) -> tuple[dict, dict]:
    """(attack_boot, defence_boot) — strength stripped, `difficulty` carrying
    the recipe band so the engine bands each fixture from it."""
    teams_min = _teams_min(teams_df)
    base_tf = _base_team_fixtures(fixtures_df)  # difficulty = FDR (attack recipe)
    overlay = _defence_overlay_bands(fixtures_df)

    attack_boot = {"teams": teams_min, "team_fixtures": base_tf, "events": []}

    def_tf: dict[int, list[dict]] = {}
    for tid, fixtures in base_tf.items():
        def_tf[tid] = [
            {**f, "difficulty": overlay.get((f["gameweek"], tid, f["is_home"]), f["difficulty"])}
            for f in fixtures
        ]
    defence_boot = {"teams": teams_min, "team_fixtures": def_tf, "events": []}
    return attack_boot, defence_boot


def build_season_start_bootstraps(
    teams_df: pd.DataFrame, fixtures_df: pd.DataFrame
) -> tuple[dict, dict]:
    """(attack_boot, defence_boot) for a freshly-launched season.

    At launch zero games have been played, so ``compute_rolling_strength`` has
    no data and the defence-axis form overlay is undefined. Both axes therefore
    band from FPL's own FDR (``difficulty``); the defence axis upgrades to the
    validated FDR+form recipe (build_recipe_bootstraps) once real results exist.
    ``events`` is empty so the engine walks the earliest ``horizon`` GWs (GW1+).
    """
    teams_min = _teams_min(teams_df)
    base_tf = _base_team_fixtures(fixtures_df)  # difficulty = FDR
    boot = {"teams": teams_min, "team_fixtures": base_tf, "events": []}
    return boot, boot


def build_rolling_bootstrap(as_of_gw: int) -> dict:
    """Legacy Step-2 comparison: raw walk-forward rolling STRENGTH snapshot fed
    through the engine's quintile bucketing, horizon projected from GW N."""
    teams_df, fixtures_df = _load_frames()
    rolling = compute_rolling_strength(SEASON, as_of_gw)
    teams = [
        {"id": int(r["team_id"]), "short_name": r["short_name"], "name": r["name"], **rolling[int(r["team_id"])]}
        for _, r in teams_df.iterrows()
    ]
    return {
        "teams": teams,
        "team_fixtures": _base_team_fixtures(fixtures_df),
        "events": [{"id": as_of_gw, "is_current": True}],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of-gw", type=int, default=None,
        help="Legacy analysis: rolling STRENGTH snapshot before this GW through the "
             "engine's quintile bucketing (not the recipe). Omit for the shipped recipe.",
    )
    parser.add_argument(
        "--out", type=str, default=None,
        help="Output path. Required with --as-of-gw (never overwrites the shipped JSON). "
             "Defaults to the committed /fixtures path otherwise.",
    )
    parser.add_argument(
        "--season-start", action="store_true",
        help="Pull the new season's live schedule + FDR from the FPL API and write "
             "the 2026-27 bundle (both axes = FDR; no results exist yet). Defaults "
             f"its output to {os.path.basename(_OUT_PATH_NEW)}.",
    )
    args = parser.parse_args()
    if args.as_of_gw is not None and args.out is None:
        parser.error("--out is required when --as-of-gw is given")
    if args.season_start and args.as_of_gw is not None:
        parser.error("--season-start and --as-of-gw are mutually exclusive")
    return args


def main() -> None:
    args = parse_args()

    if args.season_start:
        out_path = args.out or _OUT_PATH_NEW
        teams_df, fixtures_df = _load_live_frames()
        attack_boot, defence_boot = build_season_start_bootstraps(teams_df, fixtures_df)
        boots = {"attack": attack_boot, "defence": defence_boot}
    elif args.as_of_gw is not None:
        out_path = args.out or _OUT_PATH
        boot = build_rolling_bootstrap(args.as_of_gw)
        boots = {"attack": boot, "defence": boot}
    else:
        out_path = args.out or _OUT_PATH
        teams_df, fixtures_df = _load_frames()
        attack_boot, defence_boot = build_recipe_bootstraps(teams_df, fixtures_df)
        boots = {"attack": attack_boot, "defence": defence_boot}

    out: dict = {}
    for axis in AXES:
        out[axis] = {}
        for horizon in HORIZONS:
            out[axis][str(horizon)] = fixture_outlook.get_all_team_outlooks(
                boots[axis], axis=axis, horizon=horizon
            )

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(out_path) / 1024
    print(f"wrote {out_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()

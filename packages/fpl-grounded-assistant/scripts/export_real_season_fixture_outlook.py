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

--season-start is the LAUNCH-DAY path only: at kickoff no results exist, so
compute_rolling_strength has nothing to work with and both axes fall back to
FDR. That output is a degraded mode -- the Ataque / Porteria a cero switcher
re-renders identical data -- and it stays degraded until the recipe path is
re-run over played gameweeks. Which is why every bundle now carries a
`generation` block whose `axes_separated` is MEASURED from the rendered
output: the 2026-27 bundle sat collapsed for six weeks without saying so.

Legacy analysis mode: --as-of-gw N instead uses the raw walk-forward rolling
STRENGTH snapshot through the engine's quintile bucketing (the Step-2
comparison path); requires --out and never overwrites the shipped JSON.

Usage:
    # Default — regenerate the shipped /fixtures bundle (asymmetric recipe):
    python export_real_season_fixture_outlook.py

    # Recipe over a different season (output filename derives from --season):
    python export_real_season_fixture_outlook.py --season 2026-2027

    # Legacy Step-2 comparison — rolling strength as of GW4, elsewhere:
    python export_real_season_fixture_outlook.py --as-of-gw 4 --out /tmp/asof-gw4.json
"""
from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import os
import sys
from datetime import datetime, timezone

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

# Intentionally NOT read from fpl_data_core.season_registry.CURRENT_SEASON:
# this constant must NOT follow the rollover — that would silently repoint
# this script at another season's data mid-run. Excluded from the Task 1
# single-source consolidation for that reason.
#
# It is the DEFAULT for --season, not a hard target. To regenerate another
# season's bundle, pass --season <key>: the input parquet dir and the output
# filename both derive from it (out_path_for), so the pin stays put and the
# default behaviour is unchanged.
SEASON = "2025-2026"
NEW_SEASON = "2026-2027"


def season_label(season: str) -> str:
    """Season key -> the short display/filename form ('2025-2026' -> '2025-26')."""
    start, end = season.split("-")
    return f"{start}-{end[-2:]}"


def data_root(season: str) -> str:
    """Merged-parquet dir for a season. Mirrors fpl_historical.paths.
    merged_parquet_dir, including its FPL_HISTORICAL_ROOT override, so a
    workflow that syncs R2 into a scratch root feeds BOTH this script's frames
    and compute_rolling_strength from the same place."""
    root = os.environ.get("FPL_HISTORICAL_ROOT") or os.path.join(
        _PACKAGES, "fpl-historical", "data", "historical"
    )
    return os.path.join(root, "seasons", season, "parquet_merged")


def out_path_for(season: str) -> str:
    """The shipped /fixtures bundle for a season."""
    return os.path.join(
        _PACKAGES, "fpl-ui", "lib", "data", f"fixture-outlook-{season_label(season)}.json"
    )


_OUT_PATH = out_path_for(SEASON)
# --season-start writes here (new-season live schedule), keeping the finished
# 2025-26 bundle untouched.
_OUT_PATH_NEW = out_path_for(NEW_SEASON)

# The bundle ships ONE bucket per axis, covering every scheduled gameweek.
#
# It used to ship three (5, 8, 10) and the UI read only the largest, windowing
# it down for whichever selector was active. Two problems with that. The 5 and
# 8 buckets were prefixes of the 10 -- stored twice, read never. And because
# every bucket started at gameweek 1 and ran for `horizon`, coverage was
# measured from the START of the season while the screen's window advances with
# the CURRENT gameweek. The two drift apart at one gameweek per week: at GW4 the
# "10" selector could only show 7 columns, and from GW10 the board froze on a
# single column of GW10 -- a match already played -- for the rest of the season.
#
# Full-season coverage removes the dependency on when the file was built. The
# horizon is derived from the schedule itself rather than pinned, so a season
# with a different number of gameweeks needs no edit here.
AXES = ("attack", "defence")

#: Refuse to emit a bundle covering fewer than this many gameweeks past the
#: first one. Sized off the UI's largest selector (10) plus slack; the real
#: assertion lives in scripts/preflight_fixture_outlook.py, which knows the
#: live gameweek. This is only a floor against a truncated schedule.
MIN_EXPORTED_GAMEWEEKS = 12


def full_season_horizon(fixtures_df: pd.DataFrame) -> int:
    """How many gameweeks the schedule actually spans.

    Derived, never pinned: read off the fixture rows so the export follows a
    38-gameweek season, a shortened one, or a partially-published launch-day
    schedule without an edit here.
    """
    return int(fixtures_df["event_id"].nunique())

# Overlay blend weights (rank space) — must match the validated harness values.
_W_FDR = 0.6
_W_FORM = 0.4


def _load_frames(season: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    root = data_root(season)
    teams_df = pd.read_parquet(os.path.join(root, "teams.parquet"))
    fixtures_df = pd.read_parquet(os.path.join(root, "fixtures.parquet"))
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
                # Carried purely so gameweeks_played (below) is measured from
                # the same frame on every path -- a season-start run must be
                # able to say "0 played" as a fact, not as an assumption.
                "team_h_score": f.get("team_h_score"),
                "team_a_score": f.get("team_a_score"),
                "finished": bool(f.get("finished")),
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


def _defence_overlay_bands(fixtures_df: pd.DataFrame, season: str) -> dict[tuple[int, int, bool], int]:
    """Walk-forward FDR+form overlay band (1-5) per (gw, team_id, is_home) for
    the defence axis. FDR anchored, refined by the opponent's rolling attacking
    strength as of the fixture's GW, blended in rank space and quantile-bucketed
    over the whole season (population-relative, mirroring the harness)."""
    gws = sorted(int(g) for g in fixtures_df["event_id"].unique())
    rolling_by_gw = {g: compute_rolling_strength(season, g) for g in gws}

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


def build_recipe_bootstraps(
    teams_df: pd.DataFrame, fixtures_df: pd.DataFrame, season: str
) -> tuple[dict, dict]:
    """(attack_boot, defence_boot) — strength stripped, `difficulty` carrying
    the recipe band so the engine bands each fixture from it."""
    teams_min = _teams_min(teams_df)
    base_tf = _base_team_fixtures(fixtures_df)  # difficulty = FDR (attack recipe)
    overlay = _defence_overlay_bands(fixtures_df, season)

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


def build_rolling_bootstrap(as_of_gw: int, season: str) -> tuple[dict, pd.DataFrame]:
    """Legacy Step-2 comparison: raw walk-forward rolling STRENGTH snapshot fed
    through the engine's quintile bucketing, horizon projected from GW N."""
    teams_df, fixtures_df = _load_frames(season)
    rolling = compute_rolling_strength(season, as_of_gw)
    teams = [
        {"id": int(r["team_id"]), "short_name": r["short_name"], "name": r["name"], **rolling[int(r["team_id"])]}
        for _, r in teams_df.iterrows()
    ]
    boot = {
        "teams": teams,
        "team_fixtures": _base_team_fixtures(fixtures_df),
        "events": [{"id": as_of_gw, "is_current": True}],
    }
    return boot, fixtures_df


def gameweeks_played(fixtures_df: pd.DataFrame) -> int:
    """How many gameweeks have at least one finished, fully-scored fixture.

    Read off the same frame the bands were built from, using the same "final
    results only" rule as compute_rolling_strength -- so the number stamped on
    the bundle describes the data that actually shaped it.
    """
    columns = set(fixtures_df.columns)
    if not {"event_id", "team_h_score", "team_a_score"} <= columns:
        return 0
    scored = fixtures_df["team_h_score"].notna() & fixtures_df["team_a_score"].notna()
    if "finished" in columns:
        scored &= fixtures_df["finished"].fillna(False).astype(bool)
    if not scored.any():
        return 0
    return int(fixtures_df.loc[scored, "event_id"].nunique())


def axis_separation(out: dict) -> dict[str, int]:
    """Per horizon: how many teams get a DIFFERENT avg_band on the two axes.

    Measured from the rendered buckets, never inferred from which code path
    ran. That distinction is the whole point: the 2026-27 bundle shipped for
    six weeks with both axes collapsed onto one and said nothing about it,
    because nothing in it was derived from the output. 0 here means the
    Ataque/Porteria a cero switcher is re-rendering identical data; the
    2025-26 recipe bundle scores 14 of 20.
    """
    counts: dict[str, int] = {}
    for key in out["attack"]:
        attack = {t["team_short"]: t["avg_band"] for t in out["attack"][key]["teams"]}
        defence = {t["team_short"]: t["avg_band"] for t in out["defence"][key]["teams"]}
        counts[key] = sum(1 for short, band in attack.items() if defence.get(short) != band)
    return counts


def build_generation_meta(out: dict, *, season: str, source: str, played: int) -> dict:
    """The provenance block the /fixtures card stamps itself from.

    ``axes_separated`` is the field that turns "degraded mode" from a secret
    into a datum, and it is computed from ``out`` rather than from ``source``
    so that a path which is SUPPOSED to separate the axes but fails to still
    reports the truth.
    """
    # Shape first: a stale multi-bucket bundle must fail by name here, not with
    # a KeyError from whichever measurement happens to touch it first.
    bucket = out["attack"][_bucket_key(out)]
    separation = axis_separation(out)
    gameweeks = [cell["gameweek"] for cell in bucket["teams"][0]["series"]]
    return {
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": season,
        "season_label": season_label(season),
        "source": source,
        "gameweeks_played": played,
        "axes_separated": any(count > 0 for count in separation.values()),
        "axis_separation_by_horizon": separation,
        "teams": len(bucket["teams"]),
        # Coverage is READ BACK OFF the emitted series, not copied from the
        # horizon we asked for. The engine clamps, drops gameweeks with no
        # fixtures, and stops early on a partial schedule -- so the number we
        # requested and the number we shipped are different questions, and only
        # the second one protects the screen.
        "source_horizon": int(bucket["horizon"]),
        "covers_gameweeks": [min(gameweeks), max(gameweeks)] if gameweeks else [],
        "gameweek_columns": len(gameweeks),
    }


def _bucket_key(out: dict) -> str:
    """The single exported bucket's key."""
    keys = list(out["attack"])
    if len(keys) != 1:
        raise AssertionError(f"expected exactly one exported bucket, got {keys}")
    return keys[0]


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
        "--season", type=str, default=None,
        help="Season key driving the recipe path's input parquet AND its derived "
             f"output filename (default {SEASON}). Lets the validated FDR+form recipe "
             "target another season without moving the SEASON pin, which is "
             "deliberately decoupled from the season-registry rollover.",
    )
    parser.add_argument(
        "--require-separated-axes", action="store_true",
        help="Exit non-zero if the finished bundle's two axes are NOT separated. "
             "Closes the loop the input-side preflight can only approximate: the "
             "preflight judges the inputs, this judges the artifact that shipped.",
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
    if args.season_start and args.season is not None:
        # --season-start reads the LIVE API, which only ever serves the current
        # season; honouring --season here would write one season's name onto
        # another season's data. Refuse rather than silently ignore.
        parser.error(
            "--season-start always targets the live season and cannot be combined "
            "with --season"
        )
    return args


def main() -> None:
    args = parse_args()

    if args.season_start:
        season, source = NEW_SEASON, "season_start"
        out_path = args.out or _OUT_PATH_NEW
        teams_df, fixtures_df = _load_live_frames()
        attack_boot, defence_boot = build_season_start_bootstraps(teams_df, fixtures_df)
        boots = {"attack": attack_boot, "defence": defence_boot}
    elif args.as_of_gw is not None:
        season, source = args.season or SEASON, "rolling"
        out_path = args.out or out_path_for(season)
        boot, fixtures_df = build_rolling_bootstrap(args.as_of_gw, season)
        boots = {"attack": boot, "defence": boot}
    else:
        season, source = args.season or SEASON, "recipe"
        out_path = args.out or out_path_for(season)
        teams_df, fixtures_df = _load_frames(season)
        attack_boot, defence_boot = build_recipe_bootstraps(teams_df, fixtures_df, season)
        boots = {"attack": attack_boot, "defence": defence_boot}

    horizon = full_season_horizon(fixtures_df)
    out: dict = {}
    for axis in AXES:
        # _max_horizon is the engine's explicit opt-in past the rail that
        # bounds live chat input (fixture_outlook._MAX_HORIZON = 15). A static
        # file read for months is not user input, and 15 gameweeks of coverage
        # would put the same cliff four months out instead of six weeks out.
        out[axis] = {
            str(horizon): fixture_outlook.get_all_team_outlooks(
                boots[axis], axis=axis, horizon=horizon, _max_horizon=horizon
            )
        }

    out["generation"] = build_generation_meta(
        out, season=season, source=source, played=gameweeks_played(fixtures_df)
    )

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    meta = out["generation"]
    covers = meta["covers_gameweeks"]
    if meta["gameweek_columns"] < MIN_EXPORTED_GAMEWEEKS:
        print(
            f"\nREFUSING TO SHIP: the bundle covers only {meta['gameweek_columns']} "
            f"gameweek(s) (J{covers[0]}-J{covers[-1]}). The screen's largest "
            "selector asks for 10, so this would start truncating immediately. "
            "Check the schedule in the source parquet.",
            file=sys.stderr,
        )
        sys.exit(1)

    size_kb = os.path.getsize(out_path) / 1024
    print(f"wrote {out_path} ({size_kb:.1f} KB)")
    print(f"  covers J{covers[0]}-J{covers[-1]} "
          f"({meta['gameweek_columns']} gameweek columns)")
    print(f"  season={meta['season']} source={meta['source']} "
          f"gameweeks_played={meta['gameweeks_played']}")
    print(f"  axes_separated={meta['axes_separated']} -- teams with a different "
          f"avg_band, of {meta['teams']}: "
          + ", ".join(f"J{h}={n}" for h, n in meta["axis_separation_by_horizon"].items()))

    if args.require_separated_axes and not meta["axes_separated"]:
        # The preflight gates the INPUTS; this gates the OUTPUT. Without it a
        # run can satisfy every precondition, produce a collapsed bundle anyway,
        # print axes_separated=False, exit 0, and be uploaded -- which is the
        # shape of the original incident.
        print(
            "\nFAILED --require-separated-axes: both axes produced identical "
            "avg_band for every team at every horizon. The bundle was written to "
            f"{out_path} for inspection but must not be shipped.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Shared loader for the FPL-only historical backtests (plan: trial-reports/live/2026-10-18-historical-backtests-fpl-PLAN.md).
Reads the owned FPL store (fpl-historical parquet_merged), reconstructs for every player row its team, fixture, kickoff and side,
and defines the 'started' target. No Sportmonks, no LLM, nothing from after a cut point is used by the callers."""
from __future__ import annotations
import sys, pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[4]
import os
_REL = "packages/fpl-historical/data/historical/seasons"
# the owned store is git-ignored: a worktree has none, so fall back to the shared checkout (or HB_STORE)
STORE = next((c for c in [pathlib.Path(os.environ["HB_STORE"]) if os.environ.get("HB_STORE") else None, ROOT / _REL,
                          *(pp / _REL for pp in ROOT.parents)] if c is not None and c.is_dir()), None)
if STORE is None:
    STORE = pathlib.Path("C:/Users/thera/fpl-platform") / _REL
PKG = ROOT / "packages"
for p in ("football-intelligence", "football-data-contract"):
    sys.path.insert(0, str(PKG / p))
SEASONS = ["2019-2020", "2020-2021", "2021-2022", "2022-2023", "2023-2024", "2024-2025", "2025-2026"]
SEED = 20261018


def load_season(season: str):
    """Return (rows, fixtures, drops) for one season.
    rows: one row per player per fixture with team, fixture_id, kick (UTC), home, minutes, started, started_real, value, ..."""
    d = STORE / season / "parquet_merged"
    g = pd.read_parquet(d / "player_gw_stats.parquet")
    f = pd.read_parquet(d / "fixtures.parquet")
    p = pd.read_parquet(d / "players.parquet")[["player_id", "team_id", "element_type"]]
    f = f.copy()
    f["kick"] = pd.to_datetime(f.kickoff_time, utc=True)
    f = f.sort_values(["kick", "fixture_id"]).reset_index(drop=True)
    drops = {"rows": len(g), "no_team_or_fixture": 0, "side_mismatch": 0, "count_mismatch": 0}
    if "fixture" in g.columns:  # 2025-26 shape: the row carries its fixture id
        g = g.rename(columns={"fixture": "fixture_id"})
        g = g.merge(f[["fixture_id", "team_h", "team_a", "kick"]], on="fixture_id", how="left", suffixes=("", "_f"))
        g["team"] = np.where(g.was_home, g.team_h, g.team_a)
        g["kick"] = g.kick_f if "kick_f" in g else g.kick
        rows = g
        rows["started_real"] = (rows.starts > 0).astype(int)
    else:  # vaastav shape: no fixture id; rebuild from team + event (+ order for double gameweeks)
        g = g.merge(p, on="player_id", how="left")
        g["order"] = np.arange(len(g))
        side = pd.concat([
            f[["fixture_id", "event_id", "kick", "team_h"]].rename(columns={"team_h": "team"}).assign(home=True),
            f[["fixture_id", "event_id", "kick", "team_a"]].rename(columns={"team_a": "team"}).assign(home=False)])
        side = side.sort_values(["team", "event_id", "kick", "fixture_id"])
        side["k"] = side.groupby(["team", "event_id"]).cumcount()
        nfx = side.groupby(["team", "event_id"]).size().rename("nfx")
        g = g.rename(columns={"team_id": "team"})
        g["k"] = g.sort_values("order").groupby(["player_id", "event_id"]).cumcount()
        g["nrows"] = g.groupby(["player_id", "event_id"]).order.transform("size")
        g = g.join(nfx, on=["team", "event_id"])
        drops["no_team_or_fixture"] = int(g.nfx.isna().sum())
        bad_count = g.nfx.notna() & (g.nfx != g.nrows)
        drops["count_mismatch"] = int(bad_count.sum())
        g = g[g.nfx.notna() & ~bad_count]
        g = g.merge(side, on=["team", "event_id", "k"], how="left", suffixes=("", "_s"))
        bad_side = g.home != g.was_home
        drops["side_mismatch"] = int(bad_side.sum())
        rows = g[~bad_side].copy()
        rows["started_real"] = np.nan
    n0 = len(rows)
    rows = rows[rows.team.notna() & rows.kick.notna() & rows.minutes.notna()].copy()
    drops["no_team_or_fixture"] += n0 - len(rows)
    rows["team"] = rows.team.astype(int)
    rows["started_proxy"] = (rows.minutes >= 60).astype(int)
    rows["started"] = rows.started_real if season == "2025-2026" else rows.started_proxy
    rows["season"] = season
    rows = rows.rename(columns={"home": "home_flag"}) if "home" in rows else rows
    keep = ["season", "player_id", "team", "event_id", "fixture_id", "kick", "was_home", "minutes", "started", "started_real", "started_proxy", "value",
            "expected_goals", "expected_assists", "total_points"]
    rows = rows[keep].sort_values(["player_id", "kick"]).reset_index(drop=True)
    rows["expected_goals"] = pd.to_numeric(rows.expected_goals, errors="coerce")
    rows["expected_assists"] = pd.to_numeric(rows.expected_assists, errors="coerce")
    return rows, f, drops


def load_all():
    out, fx, dr = {}, {}, {}
    for s in SEASONS:
        out[s], fx[s], dr[s] = load_season(s)
    return out, fx, dr


def cut_points(rows_by_season, n=200, seed=SEED):
    """Eligible (season, event) with event >= 4 and rows; seeded sample without replacement (plan)."""
    import random
    elig = sorted((s, int(e)) for s, r in rows_by_season.items() for e in r.event_id.unique() if e >= 4)
    rng = random.Random(seed)
    return elig, sorted(rng.sample(elig, min(n, len(elig))))


def cluster_bootstrap(diff: np.ndarray, cluster: np.ndarray, reps=2000, seed=7):
    """Mean of paired differences with a bootstrap over clusters (team-match). Returns (mean, lo, hi)."""
    codes, inv = np.unique(cluster, return_inverse=True)
    s = np.bincount(inv, weights=diff); n = np.bincount(inv)
    rng = np.random.default_rng(seed); m = len(codes)
    idx = rng.integers(0, m, size=(reps, m))
    means = s[idx].sum(1) / n[idx].sum(1)
    return float(diff.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


if __name__ == "__main__":
    rows, fx, dr = load_all()
    for s in SEASONS:
        r = rows[s]; d = dr[s]
        print(s, "rows kept", len(r), "of", d["rows"], {k: v for k, v in d.items() if k != "rows"}, "events", r.event_id.min(), "-", r.event_id.max(),
              "| started rate %.3f" % r.started.mean(), "| xG nn %.2f" % r.expected_goals.notna().mean())
    elig, cp = cut_points(rows); print("eligible cut points", len(elig), "sampled", len(cp), cp[:5])
    # start-inference error on the one season with real starts (plan: report it)
    r = rows["2025-2026"]
    for th in (46, 60):
        pred = (r.minutes >= th); act = r.started_real == 1
        print("2025-26 minutes>=%d vs real starts: accuracy %.4f, false starters %d, false subs %d (rows %d); among minutes>0: accuracy %.4f" % (
            th, (pred == act).mean(), ((pred) & (~act)).sum(), ((~pred) & (act)).sum(), len(r), (pred == act)[r.minutes > 0].mean()))

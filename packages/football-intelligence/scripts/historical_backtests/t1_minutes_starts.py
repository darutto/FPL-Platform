"""T1: FPL simple rule vs M1 fed with FPL history, rolling cut points over 2019-20..2025-26 (plan 2026-10-18-historical-backtests-fpl-PLAN.md).
No coefficient is tuned. History = rows with event < cut event."""
from __future__ import annotations
import sys, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from hb_data import load_all, cut_points, cluster_bootstrap, SEASONS
from football_intelligence.modules.expected_minutes import ExpectedMinutesInput, evaluate_expected_minutes
from football_intelligence.features.registry_v2 import FEATURE_REGISTRY_VERSION


def m1(num, den, n_el, cam, mst, mcam, tr, le):
    r = evaluate_expected_minutes(ExpectedMinutesInput(
        fixture_id="f", team_id="t", player_id="p", calculated_at="2026-01-01T00:00:00Z", feature_registry_version=FEATURE_REGISTRY_VERSION, feature_build_id="b",
        weighted_start_share_last_6=(num / den if den else None), weighted_start_denominator_last_6=den, eligible_team_fixtures_last_6=n_el,
        cameo_appearances_last_6=cam, mean_minutes_when_started_last_6=mst, mean_minutes_when_cameo_last_6=mcam,
        weighted_trailing_congestion_21d=tr, weighted_leading_congestion_21d=le))
    return (r.start_probability, r.expected_minutes) if r.start_probability is not None else None


def run(rows, fx, points):
    out = []
    for season, g in points:
        r, f = rows[season], fx[season]
        cur = r[r.event_id == g]
        if cur.empty: continue
        # team league schedule (kick, event) for the congestion counts
        sched = {}
        for t, grp in pd.concat([f[["team_h", "kick", "event_id"]].rename(columns={"team_h": "t"}), f[["team_a", "kick", "event_id"]].rename(columns={"team_a": "t"})]).groupby("t"):
            sched[t] = (grp.kick.values.astype("datetime64[ns]"), grp.event_id.values)
        hist = r[r.event_id < g]
        byp = {p: x for p, x in hist.groupby("player_id")}
        for c in cur.itertuples():
            h = byp.get(c.player_id)
            if h is None: continue
            h = h.tail(6)
            if h.started.sum() < 1: continue                      # starters list fixed before the cut
            st = h.started.values; mi = h.minutes.values
            last3 = slice(-3, None)
            p1 = float(st[last3].mean()); m1_ = float(mi[last3].mean())
            w = np.arange(7 - len(h), 7); den = float(w.sum()); num = float(w[st == 1].sum())
            starts = mi[st == 1]; cam = mi[(st == 0) & (mi > 0)]
            ks, es = sched[c.team]; k = np.datetime64(c.kick.tz_convert(None) if c.kick.tzinfo else c.kick)
            tr = float(((ks < k) & (ks >= k - np.timedelta64(21, "D")) & (es < g)).sum())
            le = float(((ks > k) & (ks <= k + np.timedelta64(21, "D"))).sum())
            v = m1(num, den, len(h), len(cam), float(starts.mean()) if len(starts) else None, float(cam.mean()) if len(cam) else None, tr, le)
            if v is None: continue
            out.append((season, g, c.fixture_id, c.team, c.player_id, c.started, c.minutes, c.started_proxy, p1, m1_, v[0], v[1], len(h)))
    return pd.DataFrame(out, columns=["season", "event", "fixture", "team", "player", "y", "ymin", "y_proxy", "p1", "m1_", "p2", "m2", "nhist"])


def summarize(D, label):
    cl = (D.season + "|" + D.fixture.astype(str) + "|" + D.team.astype(str)).values
    b1, b2 = (D.y - D.p1) ** 2, (D.y - D.p2) ** 2
    a1, a2 = (D.ymin - D.m1_).abs(), (D.ymin - D.m2).abs()
    res = {}
    for name, diff in {"Brier M1 - simple": (b2 - b1).values, "MAE M1 - simple": (a2 - a1).values}.items():
        res[name] = cluster_bootstrap(diff, cl)
    print(f"\n== {label}: n rows {len(D)}, clusters {len(set(cl))}, base start rate {D.y.mean():.3f}")
    print(f"Brier simple {b1.mean():.4f} | M1 {b2.mean():.4f} | base {((D.y - D.y.mean())**2).mean():.4f}")
    print(f"MAE simple {a1.mean():.2f} | M1 {a2.mean():.2f} | base {(D.ymin - D.ymin.mean()).abs().mean():.2f}")
    for k, (m, lo, hi) in res.items(): print(f"  {k}: {m:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]")
    return res


if __name__ == "__main__":
    rows, fx, dr = load_all()
    elig, sample = cut_points(rows)
    D = run(rows, fx, elig)
    D["in200"] = list(zip(D.season, D.event))
    s200 = set(sample); D["in200"] = [x in s200 for x in D.in200]
    D.to_pickle("t1_rows.pkl")
    P = D[D.in200]
    summarize(P, "PRIMARY: 200 sampled cut points, pooled")
    summarize(D, "SENSITIVITY: all 244 eligible cut points, pooled")
    print("\n-- per season (primary 200)")
    wins_b = wins_m = 0
    for s in SEASONS:
        x = P[P.season == s]
        if x.empty: continue
        r = summarize(x, s); wins_b += r["Brier M1 - simple"][0] < 0; wins_m += r["MAE M1 - simple"][0] > 0
    print(f"\nseasons where M1 better on starts: {wins_b}/7 ; seasons where simple better on minutes: {wins_m}/7")
    print("\n-- by gameweek range (primary 200)")
    for lo, hi in ((4, 10), (11, 25), (26, 99)):
        summarize(P[(P.event >= lo) & (P.event <= hi)], f"GW {lo}-{hi}")
    print("\n-- 2025-26 with the minutes>=60 proxy as target (inference sensitivity)")
    x = P[P.season == "2025-2026"].copy(); x["y"] = x.y_proxy; summarize(x, "2025-26 proxy target")

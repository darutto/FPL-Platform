"""T2: league-only congestion. Does a regular starter's start rate drop when the rest since the team's previous LEAGUE match is <=3 whole days
vs >=6? Each team compared with itself (plan 2026-10-18-historical-backtests-fpl-PLAN.md). FPL only knows league matches: Europe/cups are invisible here."""
from __future__ import annotations
import sys, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from hb_data import load_all, SEASONS


def regular_matches(rows, f, season):
    out = []
    r = rows[rows.team.notna()]
    starters = {fid: set(x.player_id[x.started == 1]) for fid, x in r.groupby("fixture_id")}
    present = {fid: set(x.player_id) for fid, x in r.groupby("fixture_id")}
    tf = pd.concat([f[["fixture_id", "team_h", "kick", "event_id"]].rename(columns={"team_h": "team"}), f[["fixture_id", "team_a", "kick", "event_id"]].rename(columns={"team_a": "team"})])
    for team, g in tf.groupby("team"):
        g = g.sort_values("kick").reset_index(drop=True)
        for m in range(3, len(g)):
            prior = g.iloc[max(0, m - 4):m]
            n = len(prior)
            cnt = {}
            for fid in prior.fixture_id:
                for p in starters.get(fid, ()): cnt[p] = cnt.get(p, 0) + 1
            regs = [p for p, c in cnt.items() if c >= 0.75 * n]
            cur = g.iloc[m]
            here = present.get(cur.fixture_id, set()); st = starters.get(cur.fixture_id, set())
            rest_days = int((cur.kick - g.iloc[m - 1].kick).total_seconds() // 86400)
            regs = [p for p in regs if p in here]       # the regular has a row in this match (squad member)
            if not regs: continue
            out.append(dict(season=season, team=team, fixture=cur.fixture_id, event=cur.event_id, rest=rest_days, n_regs=len(regs), kept=sum(p in st for p in regs)))
    return pd.DataFrame(out)


def paired(M, label):
    M = M.copy(); M["grp"] = np.where(M.rest <= 3, "short", np.where(M.rest >= 6, "long", "mid"))
    M = M[M.grp != "mid"]
    agg = M.groupby(["season", "team", "grp"]).agg(n=("n_regs", "sum"), kept=("kept", "sum"), matches=("fixture", "nunique")).unstack("grp").dropna()
    ts = pd.DataFrame({"n_s": agg[("n", "short")], "n_l": agg[("n", "long")], "p_s": agg[("kept", "short")] / agg[("n", "short")],
                       "p_l": agg[("kept", "long")] / agg[("n", "long")], "m_s": agg[("matches", "short")], "m_l": agg[("matches", "long")]})
    ts["d"] = ts.p_s - ts.p_l
    w = ts.n_s
    mean = float((ts.d * w).sum() / w.sum())
    rng = np.random.default_rng(11); idx = rng.integers(0, len(ts), size=(2000, len(ts)))
    boots = [(ts.d.values[i] * w.values[i]).sum() / w.values[i].sum() for i in idx]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print(f"{label}: team-seasons with both groups {len(ts)} | short matches {int(ts.m_s.sum())}, long {int(ts.m_l.sum())} | regular-player-matches short {int(ts.n_s.sum())}, long {int(ts.n_l.sum())}"
          f" | start rate short {np.average(ts.p_s, weights=ts.n_s):.3f} long {np.average(ts.p_l, weights=ts.n_s):.3f} | within-team diff {mean*100:+.2f} pp [{lo*100:+.2f}, {hi*100:+.2f}]")
    return ts, mean, lo, hi


if __name__ == "__main__":
    rows, fx, dr = load_all()
    allm = pd.concat([regular_matches(rows[s], fx[s], s) for s in SEASONS], ignore_index=True)
    print("team-matches with regulars:", len(allm), "| rest-days distribution (whole days):", allm.rest.clip(upper=10).value_counts().sort_index().to_dict())
    main = allm[~((allm.season == "2019-2020") & (allm.event > 38))]
    ts, mean, lo, hi = paired(main, "PRIMARY pooled (excl. 2019-20 GW39-47)")
    paired(allm, "SENSITIVITY incl. 2019-20 GW39-47")
    for s in SEASONS: paired(main[main.season == s], s)
    # also unpaired, for reference
    M = main[main.rest != 0].copy()
    sh = M[M.rest <= 3]; lg = M[M.rest >= 6]
    print("unpaired: short %.3f (n=%d regular-player-matches), long %.3f (n=%d)" % (sh.kept.sum() / sh.n_regs.sum(), sh.n_regs.sum(), lg.kept.sum() / lg.n_regs.sum(), lg.n_regs.sum()))
    print("rest-days detail (whole days -> start rate of regulars, n):")
    for r_, x in M.groupby(M.rest.clip(upper=9)): print(" ", r_, "%.3f" % (x.kept.sum() / x.n_regs.sum()), int(x.n_regs.sum()))
    allm.to_pickle("t2_rows.pkl")

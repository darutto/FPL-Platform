"""T3: FPL-only baseline for absence -> replacement (plan 2026-10-18-historical-backtests-fpl-PLAN.md).
A regular starter drops out of the XI at match m (started m-1, not m). Candidates: same-team starters at m with <=1 start in the 3 matches before m
("starts just rose"). FPL-only 'low ownership' rule = cheap (price at that gameweek <= 5.5m), because per-gameweek ownership does not exist before 2025-26.
keep_k = starts each of the next k matches (m+1..m+k)."""
from __future__ import annotations
import sys, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from hb_data import load_all, SEASONS


def events(rows, f, season):
    r = rows
    by_fx = {fid: x.set_index("player_id") for fid, x in r.groupby("fixture_id")}
    tf = pd.concat([f[["fixture_id", "team_h", "kick"]].rename(columns={"team_h": "team"}), f[["fixture_id", "team_a", "kick"]].rename(columns={"team_a": "team"})])
    out, ctrl = [], []
    for team, g in tf.groupby("team"):
        g = g.sort_values("kick").reset_index(drop=True); fids = list(g.fixture_id)
        def st(fid, p):
            x = by_fx.get(fid)
            if x is None or p not in x.index: return None
            v = x.at[p, "started"]; return int(v.iloc[0] if hasattr(v, "iloc") else v)
        for m in range(4, len(fids) - 1):
            prior = fids[m - 4:m]
            cur = by_fx.get(fids[m]);
            if cur is None: continue
            cnt = {}
            for fid in prior:
                x = by_fx.get(fid)
                if x is None: continue
                for p in x.index[x.started == 1]: cnt[p] = cnt.get(p, 0) + 1
            regs = [p for p, c in cnt.items() if c >= 3 and st(fids[m - 1], p) == 1]
            dropped = [p for p in regs if st(fids[m], p) == 0]
            starters_m = list(cur.index[cur.started == 1])
            cands = []
            for q in starters_m:
                if q in dropped: continue
                prev3 = [st(fids[j], q) for j in (m - 3, m - 2, m - 1)]
                if any(v is None for v in prev3): continue
                if sum(prev3) <= 1: cands.append(q)
            for kind, store in (("dropout", out), ("control", ctrl)):
                if (kind == "dropout") != bool(dropped): continue
                for q in cands:
                    keeps = []
                    for k in (1, 2, 3):
                        if m + k >= len(fids): keeps.append(np.nan); continue
                        seq = [st(fids[m + j], q) for j in range(1, k + 1)]
                        keeps.append(np.nan if any(v is None for v in seq) else float(all(v == 1 for v in seq)))
                    still_out = np.nan
                    if dropped:
                        o = [st(fids[m + 1], p) for p in dropped]; still_out = float(all(v == 0 for v in o if v is not None)) if any(v is not None for v in o) else np.nan
                    price = float(cur.at[q, "value"]) if not isinstance(cur.at[q, "value"], pd.Series) else float(cur.at[q, "value"].iloc[0])
                    store.append(dict(season=season, team=team, m=m, fixture=fids[m], cand=q, cheap=price <= 55, k1=keeps[0], k2=keeps[1], k3=keeps[2], still_out=still_out, ndrop=len(dropped)))
    return pd.DataFrame(out), pd.DataFrame(ctrl)


def rate(D, label):
    parts = []
    for k in ("k1", "k2", "k3"):
        x = D[k].dropna(); parts.append(f"keep{k[1]} {x.mean():.3f} (n={len(x)})")
    print(f"  {label:42s} " + " | ".join(parts))


def boot(D, k, reps=2000, seed=3):
    d = D[["fixture", "team", k]].dropna()
    cl = (d.fixture.astype(str) + "|" + d.team.astype(str)).values
    codes, inv = np.unique(cl, return_inverse=True); s = np.bincount(inv, weights=d[k].values); n = np.bincount(inv)
    rng = np.random.default_rng(seed); idx = rng.integers(0, len(codes), size=(reps, len(codes)))
    b = s[idx].sum(1) / n[idx].sum(1)
    return d[k].mean(), np.percentile(b, 2.5), np.percentile(b, 97.5)


if __name__ == "__main__":
    rows, fx, dr = load_all()
    E, C = [], []
    for s in SEASONS:
        e, c = events(rows[s], fx[s], s); E.append(e); C.append(c)
        print(f"{s}: dropout events (team-match with a regular dropped out): {e.fixture.nunique() if len(e) else 0}; candidate rows {len(e)}; control candidate rows (no regular dropped) {len(c)}")
    E = pd.concat(E, ignore_index=True); C = pd.concat(C, ignore_index=True)
    print("\n== Base rate per season: P(candidate keeps starting the next k matches)")
    for s in SEASONS:
        e = E[E.season == s]; print(s)
        rate(e, "all candidates (after a dropout)"); rate(e[e.cheap], "cheap candidates (FPL-only rule)"); rate(e[e.still_out == 1], "all, regular still out at m+1"); rate(e[e.cheap & (e.still_out == 1)], "cheap, regular still out at m+1")
        rate(C[C.season == s], "reference: same kind of starter, NO regular dropped")
    print("\n== Pooled with cluster CI (by team-match)")
    for lab, D in (("all after dropout", E), ("cheap after dropout", E[E.cheap]), ("all, regular still out", E[E.still_out == 1]), ("cheap, regular still out", E[E.cheap & (E.still_out == 1)]), ("reference: no regular dropped", C), ("reference cheap, no dropped", C[C.cheap])):
        out = []
        for k in ("k1", "k2", "k3"):
            m, lo, hi = boot(D, k); out.append(f"{k}: {m:.3f} [{lo:.3f},{hi:.3f}] n={D[k].notna().sum()}")
        print(f"  {lab:34s} " + " | ".join(out))
    E.to_pickle("t3_rows.pkl"); C.to_pickle("t3_ctrl.pkl")

"""H4: simple rule vs M1 fed by FPL vs M1 fed by Sportmonks inputs, scored on Sportmonks league lineups (plan).
Target (same for the three predictors): started / minutes from the Sportmonks lineup. Population fixed before the match: players with >=1 Sportmonks start in their
last <=6 league matches and a lineup row (matchday squad) at the evaluated match, matched to FPL (gate + amendment-3 bridge) so the three see the same rows.
No coefficient is tuned."""
from __future__ import annotations
import sys, collections, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from sm_data import load_matches
from sm_h1 import starts_table
from sm_h3 import other_matches, EURO
from hb_data import load_season, cluster_bootstrap
from t1_minutes_starts import m1


def club_calendar(season, M, pl):
    tag = {"2024-2025": "2425", "2025-2026": "2526"}[season]
    cal = collections.defaultdict(list)
    for r in M.itertuples():
        for t in (r.home, r.away): cal[t].append((r.kick, 1.0, r.match))
    for mid, o in other_matches(tag, pl).items():
        w = 1.25 if o["comp"] in EURO else 1.0
        for t in o["clubs"]: cal[t].append((o["kick"], w, mid))
    return {t: sorted(v) for t, v in cal.items()}


def run(season, bridge):
    M, L, S = starts_table(season); M = M.sort_values("kick").reset_index(drop=True)
    pl = set(M.home) | set(M.away); cal = club_calendar(season, M, pl)
    fin = bridge[season]["final"]
    F, fixF, _ = load_season(season); F = F.sort_values(["player_id", "kick"])
    byF = {p: g for p, g in F.groupby("player_id")}
    fsched = {}
    for t, grp in pd.concat([fixF[["team_h", "kick"]].rename(columns={"team_h": "t"}), fixF[["team_a", "kick"]].rename(columns={"team_a": "t"})]).groupby("t"):
        fsched[t] = grp.kick.values.astype("datetime64[ns]")
    side = {r.match: {(t, p) for (t, p, ty) in r.sidelined} for r in M.itertuples()}
    Ls = L.sort_values(["player", "kick"]); byL = {p: g for p, g in Ls.groupby("player")}
    fpl_team = {}   # FPL team id of the club: infer from matched players of the same SM club
    out = []
    rank = {}
    for t in pl:
        ms = M[(M.home == t) | (M.away == t)].sort_values("kick"); rank[t] = {m: i for i, m in enumerate(ms.match)}
    for r in L.itertuples():                     # candidate rows: one per player-match in the squad
        i = rank[r.team][r.match]
        if i < 3: continue                       # cut point = team's 4th league match or later (history of >= 3 matches)
        pid = r.player
        if pid not in fin: continue
        gp = byL[pid]; hist = gp[(gp.kick < r.kick)].tail(6)
        if hist.started.sum() < 1: continue
        fid = fin[pid]; fh = byF.get(fid)
        if fh is None: continue
        fhist = fh[fh.kick < r.kick - pd.Timedelta(hours=3)].tail(6)
        if fhist.empty or fhist.started.sum() < 0: continue
        # FPL-based predictors
        st = fhist.started.values; mi = fhist.minutes.values
        p1 = float(st[-3:].mean()); m1_ = float(mi[-3:].mean())
        w = np.arange(7 - len(fhist), 7); den = float(w.sum()); num = float(w[st == 1].sum())
        sm_ = mi[st == 1]; cam = mi[(st == 0) & (mi > 0)]
        k = np.datetime64(r.kick.tz_convert(None)); ks = fsched[int(fh.team.iloc[-1])] if int(fh.team.iloc[-1]) in fsched else np.array([], dtype="datetime64[ns]")
        tr = float(((ks < k) & (ks >= k - np.timedelta64(21, "D"))).sum()); le = float(((ks > k) & (ks <= k + np.timedelta64(21, "D"))).sum())
        v2 = m1(num, den, len(fhist), len(cam), float(sm_.mean()) if len(sm_) else None, float(cam.mean()) if len(cam) else None, tr, le)
        # Sportmonks-based M1
        h = hist; st3 = h.started.values; mi3 = np.nan_to_num(h.minutes.values.astype(float), nan=0.0)
        w3 = np.arange(7 - len(h), 7); d3 = float(w3.sum()); n3 = float(w3[st3 == 1].sum())
        s_m = mi3[st3 == 1]; c_m = mi3[(st3 == 0) & (mi3 > 0)]
        cc = cal[r.team]
        tr3 = float(sum(wt for kk, wt, mm in cc if r.kick - pd.Timedelta(days=21) <= kk < r.kick and mm != r.match))
        le3 = float(sum(wt for kk, wt, mm in cc if r.kick < kk <= r.kick + pd.Timedelta(days=21)))
        v3 = m1(n3, d3, len(h), len(c_m), float(s_m.mean()) if len(s_m) else None, float(c_m.mean()) if len(c_m) else None, tr3, le3)
        if v2 is None or v3 is None: continue
        mins = r.minutes if (r.minutes == r.minutes and r.minutes is not None) else 0
        unav = (r.team, pid) in side.get(r.match, set())
        out.append((season, r.match, r.team, pid, r.started, float(mins), unav, p1, m1_, v2[0], v2[1], v3[0], v3[1]))
    return pd.DataFrame(out, columns=["season", "match", "team", "player", "y", "ymin", "unavail", "p1", "m1_", "p2", "m2", "p3", "m3"])


def summarize(D, label):
    cl = (D.season + "|" + D.match.astype(str) + "|" + D.team.astype(str)).values
    b = {k: (D.y - D[k]) ** 2 for k in ("p1", "p2", "p3")}; a = {k: (D.ymin - D[k]).abs() for k in ("m1_", "m2", "m3")}
    print(f"\n== {label}: n rows {len(D)}, clusters {len(set(cl))}, start rate {D.y.mean():.3f}")
    print(f"   Brier: simple {b['p1'].mean():.4f} | M1-FPL {b['p2'].mean():.4f} | M1-Sportmonks {b['p3'].mean():.4f} | base {((D.y-D.y.mean())**2).mean():.4f}")
    print(f"   MAE min: simple {a['m1_'].mean():.2f} | M1-FPL {a['m2'].mean():.2f} | M1-Sportmonks {a['m3'].mean():.2f} | base {(D.ymin-D.ymin.mean()).abs().mean():.2f}")
    for name, diff in {"Brier M1-SM minus M1-FPL": (b["p3"] - b["p2"]).values, "MAE M1-SM minus M1-FPL": (a["m3"] - a["m2"]).values,
                       "Brier M1-FPL minus simple": (b["p2"] - b["p1"]).values, "MAE M1-FPL minus simple": (a["m2"] - a["m1_"]).values,
                       "Brier M1-SM minus simple": (b["p3"] - b["p1"]).values, "MAE M1-SM minus simple": (a["m3"] - a["m1_"]).values}.items():
        m, lo, hi = cluster_bootstrap(diff, cl); print(f"   {name}: {m:+.4f} [{lo:+.4f}, {hi:+.4f}]")


if __name__ == "__main__":
    B = pd.read_pickle("sm_bridge.pkl")
    res = {}
    for s in ("2024-2025", "2025-2026"):
        D = run(s, B); res[s] = D
        print(f"\n######## {s}: rows {len(D)}, players {D.player.nunique()}, of which unavailable (sidelined row, today's) {int(D.unavail.sum())}")
        summarize(D, f"{s} all rows"); summarize(D[~D.unavail], f"{s} without unavailable rows (retrospective filter)")
    pd.to_pickle(res, "sm_h4.pkl")

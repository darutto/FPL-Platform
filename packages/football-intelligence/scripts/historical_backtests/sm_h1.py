"""H1: role-change detector on Sportmonks league starts (plan 2026-10-18-historical-backtests-sportmonks-PLAN.md).
Raw slot = detailedPosition + grid + formation (+ venue); role/flank = role-map-v3 (our estimate). Alert levels: 'posible' (run of 1-2 starts in the new role),
'confirmado' (run of 3). Precision = persistence over the next 3 starts. Baseline = 'same role as the last start'. Team formation changes are kept apart."""
from __future__ import annotations
import sys, collections, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from sm_data import load_matches
from football_intelligence.features.engine_v2 import ROLE_MAP_V3


def starts_table(season):
    M, L = load_matches(season)
    S = L[L.started == 1].copy()
    mp = S.dpos.str.lower().map(lambda x: ROLE_MAP_V3.get(x))
    S["role"] = mp.map(lambda t: None if t is None else f"{t[0]}/{t[1]}")
    # team's formation in its previous league match, for the team-driven flag
    tm = S.groupby(["team", "kick", "match"]).formation.first().reset_index().sort_values(["team", "kick"])
    tm["prev_form"] = tm.groupby("team").formation.shift()
    S = S.merge(tm[["team", "match", "prev_form"]], on=["team", "match"], how="left")
    return M, L, S.sort_values(["player", "kick"]).reset_index(drop=True)


def events(S, season):
    ev = []
    for pid, g in S.groupby("player"):
        g = g.reset_index(drop=True); roles = g.role.tolist(); n = len(g)
        for t in range(n):
            if roles[t] is None: continue
            # run of the same role ending at t
            c = 1
            while t - c >= 0 and roles[t - c] == roles[t]: c += 1
            if c > 3: continue
            o = t - c + 1                                              # onset index of the run
            prior = [r for r in roles[max(0, o - 5):o] if r is not None]
            if len([r for r in roles[max(0, o - 5):o]]) < 3 or len(prior) < 3: continue
            r0 = collections.Counter(prior).most_common(1)[0][0]
            if r0 == roles[t]: continue
            # only count a run once per level; ensure the run does not extend before t beyond c (run length exactly c at t)
            nxt = roles[t + 1:t + 4]
            row = g.iloc[o]
            team_driven = (row.formation != row.prev_form) and pd.notna(row.prev_form)
            ev.append(dict(season=season, player=pid, name=g.pname.iloc[0], team=g.team.iloc[t], onset_match=row.match, onset_kick=row.kick, t_match=g.match.iloc[t], t_kick=g.kick.iloc[t], c=c,
                           level=("posible" if c < 3 else "confirmado"), r0=r0, r1=roles[t], team_driven=bool(team_driven),
                           next3=len(nxt), persist2=(sum(r == roles[t] for r in nxt) >= 2) if len(nxt) == 3 else np.nan,
                           persist3=(sum(r == roles[t] for r in nxt) == 3) if len(nxt) == 3 else np.nan,
                           next_role=nxt[0] if nxt else None, det_pred=(roles[t] if c == 3 else r0)))
    return pd.DataFrame(ev)


def boot_prop(x, cl, reps=2000, seed=5):
    x = np.asarray(x, float); codes, inv = np.unique(np.asarray(cl).astype(str), return_inverse=True)
    s = np.bincount(inv, weights=x); n = np.bincount(inv); rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(codes), size=(reps, len(codes)))
    b = s[idx].sum(1) / n[idx].sum(1)
    return x.mean(), np.percentile(b, 2.5), np.percentile(b, 97.5)


def report(E, label):
    print(f"\n=== {label}")
    for drv, name in ((False, "INDIVIDUAL (same team formation)"), (True, "TEAM-DRIVEN (formation changed)")):
        D = E[E.team_driven == drv]
        print(f" {name}")
        for c, lvl in ((1, "posible c=1"), (2, "posible c=2"), (3, "confirmado c=3")):
            x = D[(D.c == c) & D.persist2.notna()]
            if x.empty: print(f"   {lvl}: n=0"); continue
            cl = x.season + "|" + x.team.astype(str) + "|" + x.onset_match.astype(str)
            m2, lo2, hi2 = boot_prop(x.persist2, cl); m3, lo3, hi3 = boot_prop(x.persist3, cl)
            y = D[(D.c == c) & D.next_role.notna()]
            acc_b = (y.next_role == y.r1).mean(); acc_d = (y.next_role == y.det_pred).mean()
            print(f"   {lvl}: n={len(x)} | persist >=2 of next 3: {m2:.3f} [{lo2:.3f},{hi2:.3f}] | all 3: {m3:.3f} [{lo3:.3f},{hi3:.3f}] | next-start role accuracy: baseline(last role) {acc_b:.3f} vs detector {acc_d:.3f} (n={len(y)})")


if __name__ == "__main__":
    allE = []
    for s in ("2024-2025", "2025-2026"):
        M, L, S = starts_table(s)
        print(s, "starts", len(S), "unmapped dpos starts", int(S.role.isna().sum()), "players", S.player.nunique())
        E = events(S, s); allE.append(E)
        print("  events (all levels):", len(E), "| individual", int((~E.team_driven).sum()), "| team-driven", int(E.team_driven.sum()))
        report(E, s)
    E = pd.concat(allE, ignore_index=True); E.to_pickle("sm_h1_events.pkl")

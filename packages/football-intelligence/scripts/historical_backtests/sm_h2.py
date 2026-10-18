"""H2: slot replacement on Sportmonks league lineups vs the FPL-only baseline of #478 T3 (plan 2026-10-18-historical-backtests-sportmonks-PLAN.md).
Only Sportmonks ids are used. Participation states (i156): started / not_started (came on) / did_not_play (0 min or not in the squad) / unavailable (match-level sidelined row; today's, so retrospective)."""
from __future__ import annotations
import sys, collections, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from sm_data import load_matches
from sm_h1 import starts_table, boot_prop


def run(season):
    M, L, S = starts_table(season)
    M = M.sort_values("kick").reset_index(drop=True)
    side = {r.match: {(t, p) for (t, p, ty) in r.sidelined} for r in M.itertuples()}
    rowsL = {(r.match, r.team, r.player): r for r in L.itertuples()}
    teams = sorted(set(L.team))
    ev, ctl = [], []
    st_by = {m: set(zip(x.team, x.player)) for m, x in S.groupby("match")}
    role_of = {(r.match, r.player): r.role for r in S.itertuples()}
    form_of = {(r.match, r.team): r.formation for r in S.drop_duplicates(["match", "team"]).itertuples()}
    first_squad = L.groupby(["team", "player"]).kick.min().to_dict()
    for team in teams:
        seq = M[(M.home == team) | (M.away == team)].sort_values("kick").reset_index(drop=True)
        mids = list(seq.match); kicks = list(seq.kick)
        def started(m, p): return (team, p) in st_by.get(m, ())
        for i in range(4, len(mids) - 1):
            m = mids[i]; prior = mids[i - 4:i]
            cnt = collections.Counter(p for pm in prior for (t, p) in st_by.get(pm, ()) if t == team)
            regs = [p for p, c in cnt.items() if c >= 3 and started(mids[i - 1], p)]
            drops = [p for p in regs if not started(m, p)]
            starters = [p for (t, p) in st_by.get(m, ()) if t == team]
            cands = []
            fm = form_of.get((m, team))
            for a in drops:
                last3 = [(pm, role_of.get((pm, a))) for pm in prior if started(pm, a)][-3:]
                roles = [r for _, r in last3 if r]
                if len(roles) < 3: continue
                slot = collections.Counter(roles).most_common(1)[0][0]; aform = form_of.get((mids[[pm for pm, _ in last3][-1] and mids.index([pm for pm, _ in last3][-1])], team))
                # absentee state at m
                row = rowsL.get((m, team, a)); sl = (team, a) in side.get(m, set())
                state = "unavailable" if sl else ("not_started" if (row is not None and (row.minutes or 0) > 0) else "did_not_play")
                for q in starters:
                    if q == a or role_of.get((m, q)) != slot or fm != aform: continue
                    if any(started(pm, q) for pm in prior[:0]): pass
                    fs = first_squad.get((team, q))
                    if fs is not None and fs > kicks[i - 4] - pd.Timedelta(seconds=1): continue       # first matchday squad with this club inside the 4 previous matches = new signing
                    prev3 = sum(started(pm, q) for pm in mids[i - 3:i])
                    cands.append((a, q, slot, state, prev3))
            slot_takers = {q for _, q, _, _, _ in cands}
            for a, q, slot, state, prev3 in cands:
                keeps, same = [], []
                for k in (1, 2, 3):
                    if i + k >= len(mids): keeps.append(np.nan); same.append(np.nan); continue
                    nxt = mids[i + 1:i + 1 + k]
                    keeps.append(float(all(started(pm, q) for pm in nxt))); same.append(float(all(started(pm, q) and role_of.get((pm, q)) == slot for pm in nxt)))
                ev.append(dict(season=season, team=team, m=m, absentee=a, cand=q, state=state, prev3=prev3, k1=keeps[0], k2=keeps[1], k3=keeps[2], s1=same[0], s2=same[1], s3=same[2]))
            # comparator: FPL-style candidates on the same lineups (<=1 start in the 3 matches before m), NOT in the absentee's slot, when somebody dropped out
            if drops:
                for q in starters:
                    if q in slot_takers or q in drops: continue
                    fs = first_squad.get((team, q))
                    if fs is not None and fs > kicks[i - 4] - pd.Timedelta(seconds=1): continue
                    if sum(started(pm, q) for pm in mids[i - 3:i]) > 1: continue
                    keeps = []
                    for k in (1, 2, 3):
                        keeps.append(np.nan if i + k >= len(mids) else float(all(started(pm, q) for pm in mids[i + 1:i + 1 + k])))
                    ctl.append(dict(season=season, team=team, m=m, cand=q, k1=keeps[0], k2=keeps[1], k3=keeps[2]))
    return pd.DataFrame(ev), pd.DataFrame(ctl)


def line(D, label, ks=("k1", "k2", "k3")):
    parts = []
    for k in ks:
        x = D[[k, "team", "m"]].dropna()
        if x.empty: parts.append(f"{k}: n=0"); continue
        m, lo, hi = boot_prop(x[k], x.team.astype(str) + "|" + x.m.astype(str))
        parts.append(f"{k[-1]}: {m:.3f} [{lo:.3f},{hi:.3f}] (n={len(x)})")
    print(f"  {label:42s} " + " | ".join(parts))


def diff_ci(A, B, k, reps=2000, seed=9):
    a = A[[k, "team", "m"]].dropna(); b = B[[k, "team", "m"]].dropna()
    ca = (a.team.astype(str) + "|" + a.m.astype(str)).values; cb = (b.team.astype(str) + "|" + b.m.astype(str)).values
    ua, ia = np.unique(ca, return_inverse=True); ub, ib = np.unique(cb, return_inverse=True)
    sa, na = np.bincount(ia, weights=a[k].values), np.bincount(ia); sb, nb = np.bincount(ib, weights=b[k].values), np.bincount(ib)
    rng = np.random.default_rng(seed); xa = rng.integers(0, len(ua), size=(reps, len(ua))); xb = rng.integers(0, len(ub), size=(reps, len(ub)))
    d = sa[xa].sum(1) / na[xa].sum(1) - sb[xb].sum(1) / nb[xb].sum(1)
    return a[k].mean() - b[k].mean(), np.percentile(d, 2.5), np.percentile(d, 97.5)


if __name__ == "__main__":
    FPL_T3 = {"2024-2025": (0.577, 0.395, 0.305), "2025-2026": (0.634, 0.457, 0.364)}
    res = {}
    for s in ("2024-2025", "2025-2026"):
        E, C = run(s); res[s] = (E, C)
        print(f"\n===== {s}: slot-candidate rows {len(E)} (absentees {E.absentee.nunique()}, team-matches with a dropout {E.groupby(['team','m']).ngroups}); comparator rows {len(C)}")
        print("  absentee state of the events:", E.state.value_counts().to_dict())
        line(E, "(a) all slot candidates")
        Eb = E[E.prev3 <= 1]; line(Eb, "(b) slot candidates, <=1 start in prior 3")
        line(C, "comparator: FPL rule on SM lineups, not slot")
        print("  #478 T3 for this season (proxy starts):", FPL_T3[s], "| pooled T3: 0.603 [0.592,0.615] / 0.426 [0.415,0.437] / 0.327 [0.316,0.338]")
        for k in ("k1", "k2", "k3"):
            d, lo, hi = diff_ci(Eb, C, k); print(f"  paired-style diff (b) - comparator, {k}: {d:+.3f} [{lo:+.3f},{hi:+.3f}]")
        line(Eb[Eb.state == "unavailable"], "(b) absentee unavailable (sidelined row)"); line(Eb[Eb.state == "not_started"], "(b) absentee not_started (came on)"); line(Eb[Eb.state == "did_not_play"], "(b) absentee did_not_play")
        line(Eb.rename(columns={"s1": "ks1", "s2": "ks2", "s3": "ks3"}), "(b) keeps the SAME slot", ("ks1", "ks2", "ks3")) if False else None
        sd = Eb.rename(columns={"s1": "k1x", "s2": "k2x", "s3": "k3x"}); line(sd, "(b) keeps the SAME slot", ("k1x", "k2x", "k3x"))
    pd.to_pickle(res, "sm_h2.pkl")

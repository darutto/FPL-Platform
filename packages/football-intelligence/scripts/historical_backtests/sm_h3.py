"""H3: rotation after European matches (plan). Regular starters fixed pre-match; exposure = league match whose previous match (any competition) was UCL/UEL/UECL
within <=3 (main) / <=4 days; control = same team's league matches whose previous match was a league match with >=5 days of rest. Team-season paired difference,
bootstrap by team-season. Sportmonks ids only. Cups (FA/Carabao) are used only to classify the previous match; Carabao 2025-26 was not captured."""
from __future__ import annotations
import sys, glob, json, collections, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from sm_data import load_matches, SM_PATH
from sm_h1 import starts_table

EURO = {"Champions League", "Europa League", "Europa Conference League"}


def other_matches(season_tag, pl_ids):
    out = {}
    pats = [f"eu{season_tag}_*_p1.json", f"cup24_{season_tag}_p*.json", f"cup27_{season_tag}_p*.json"]
    for pat in pats:
        for f in glob.glob(str(SM_PATH / "step2" / pat)):
            for m in json.loads(open(f, encoding="utf-8").read())["data"]:
                nm = m["league"]["name"]
                if nm == "Premier League": continue
                ids = [p["id"] for p in m["participants"] if p["id"] in pl_ids]
                if not ids: continue
                if m["state_id"] not in (5, 7, 8): continue                 # finished (FT, AET, pens)
                out.setdefault(m["id"], dict(kick=pd.Timestamp(m["starting_at"], tz="UTC"), comp=nm, leg=m.get("leg"), clubs=ids))
    return out


def team_matches(season):
    tag = {"2024-2025": "2425", "2025-2026": "2526"}[season]
    M, L, S = starts_table(season)
    pl = set(M.home) | set(M.away)
    oth = other_matches(tag, pl)
    st = {m: x for m, x in S.groupby("match")}
    cal = collections.defaultdict(list)
    for r in M.itertuples():
        for t in (r.home, r.away): cal[t].append((r.kick, "league", "Premier League", None, r.match))
    for mid, o in oth.items():
        for t in o["clubs"]: cal[t].append((o["kick"], "euro" if o["comp"] in EURO else "cup", o["comp"], o["leg"], mid))
    for t in cal: cal[t].sort(key=lambda x: x[0])
    starts_in = {(m, t): set(x[x.team == t].player) for m, x in st.items() for t in x.team.unique()}
    rows = []
    for t, seq in cal.items():
        league = [(i, e) for i, e in enumerate(seq) if e[1] == "league"]
        lm = [e[4] for _, e in league]
        for j in range(3, len(league)):
            i, e = league[j]
            prior = lm[j - 4:j] if j >= 4 else lm[:j]
            cnt = collections.Counter(p for pm in prior for p in starts_in.get((pm, t), ()))
            regs = [p for p, c in cnt.items() if c >= 0.75 * len(prior) and p in starts_in.get((lm[j - 1], t), ())] if len(prior) >= 3 else []
            if not regs: continue
            prev = seq[i - 1] if i > 0 else None
            if prev is None: continue
            rest = (e[0] - prev[0]).total_seconds() / 86400
            kept = sum(p in starts_in.get((e[4], t), ()) for p in regs)
            rows.append(dict(season=season, team=t, m=e[4], rest=rest, prev_type=prev[1], prev_comp=prev[2], prev_leg=prev[3], n_regs=len(regs), kept=kept))
    return pd.DataFrame(rows)


def paired(D, exp_mask, label):
    X = D[exp_mask].groupby(["season", "team"]).agg(n_e=("n_regs", "sum"), k_e=("kept", "sum"), m_e=("m", "nunique"))
    C = D[(D.prev_type == "league") & (D.rest >= 5)].groupby(["season", "team"]).agg(n_c=("n_regs", "sum"), k_c=("kept", "sum"), m_c=("m", "nunique"))
    ts = X.join(C, how="inner")
    if ts.empty: print(f"  {label}: no team-season with both groups"); return None
    ts["d"] = ts.k_e / ts.n_e - ts.k_c / ts.n_c; w = ts.n_e
    mean = float((ts.d * w).sum() / w.sum())
    rng = np.random.default_rng(13); idx = rng.integers(0, len(ts), size=(2000, len(ts)))
    b = [(ts.d.values[i] * w.values[i]).sum() / w.values[i].sum() for i in idx]
    lo, hi = np.percentile(b, [2.5, 97.5])
    print(f"  {label}: team-seasons {len(ts)} | exposure matches {int(ts.m_e.sum())} (regular-player-matches {int(ts.n_e.sum())}), control matches {int(ts.m_c.sum())} ({int(ts.n_c.sum())}) | "
          f"start rate exposure {ts.k_e.sum()/ts.n_e.sum():.3f} vs control {ts.k_c.sum()/ts.n_c.sum():.3f} | within-team diff {mean*100:+.2f} pp [{lo*100:+.2f}, {hi*100:+.2f}]")
    return ts, mean, lo, hi


if __name__ == "__main__":
    allD = {}
    for s in ("2024-2025", "2025-2026"):
        D = team_matches(s); allD[s] = D
        print(f"\n===== {s}: league team-matches with regulars {len(D)}; previous match type {D.prev_type.value_counts().to_dict()}")
        e3 = (D.prev_type == "euro") & (D.rest <= 3.0); e4 = (D.prev_type == "euro") & (D.rest <= 4.0)
        paired(D, e3, "MAIN exposure <=3 days after UCL/UEL/UECL")
        paired(D, e4, "secondary exposure <=4 days")
        # exploratory (labelled): two-legged knockout vs league phase/single-leg of the previous European match
        ko = e4 & (D.prev_leg.isin(["1/2", "2/2"])); lp = e4 & (D.prev_leg == "1/1")
        print(" EXPLORATORY (not part of the pass criteria): high-stakes proxy = previous European match was a two-legged knockout tie")
        paired(D, ko, "knockout (two-legged) <=4 days"); paired(D, lp, "league-phase / single-leg <=4 days")
        # competition tier
        paired(D, e4 & (D.prev_comp == "Champions League"), "UCL <=4 days"); paired(D, e4 & (D.prev_comp != "Champions League"), "UEL/UECL <=4 days")
    pd.to_pickle(allD, "sm_h3.pkl")

"""H3 SENSITIVITY (declared; not a new test): same definitions as sm_h3.py, but the cup calendar is the complete FA Cup + Carabao capture
(clubcups_<CLUB>_p1: fixtureLeagues 24,27, 1 Aug 2024 - 30 Jun 2026, all 20 clubs of 2026-27) so that no league-only control match is preceded by an unseen cup tie.
European matches still come from the eu*_ files."""
from __future__ import annotations
import sys, glob, json, collections, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
import sm_h3
from sm_data import SM_PATH


def other_matches_full(season_tag, pl_ids):
    out = {}
    for f in glob.glob(str(SM_PATH / "step2" / f"eu{season_tag}_*_p1.json")) + glob.glob(str(SM_PATH / "step2" / "clubcups_*_p1.json")):
        for m in json.loads(open(f, encoding="utf-8").read())["data"]:
            nm = m["league"]["name"]
            if nm == "Premier League": continue
            if "clubcups" in f:
                yr = pd.Timestamp(m["starting_at"], tz="UTC")
                lo, hi = {"2425": ("2024-07-15", "2025-06-30"), "2526": ("2025-07-15", "2026-06-30")}[season_tag]
                if not (pd.Timestamp(lo, tz="UTC") <= yr <= pd.Timestamp(hi, tz="UTC")): continue
            ids = [p["id"] for p in m["participants"] if p["id"] in pl_ids]
            if not ids or m["state_id"] not in (5, 7, 8): continue
            out.setdefault(m["id"], dict(kick=pd.Timestamp(m["starting_at"], tz="UTC"), comp=nm, leg=m.get("leg"), clubs=ids))
    return out


if __name__ == "__main__":
    res = {}
    for label, fn in (("ORIGINAL cup calendar", sm_h3.other_matches), ("COMPLETE cup calendar (sensitivity)", other_matches_full)):
        sm_h3.other_matches = fn
        print(f"\n################ {label}")
        for s in ("2024-2025", "2025-2026"):
            D = sm_h3.team_matches(s); res[(label, s)] = D
            n_cup = (D.prev_type == "cup").sum()
            print(f"\n===== {s}: team-matches {len(D)}; previous match type {D.prev_type.value_counts().to_dict()}")
            e3 = (D.prev_type == "euro") & (D.rest <= 3.0); e4 = (D.prev_type == "euro") & (D.rest <= 4.0)
            sm_h3.paired(D, e3, "MAIN exposure <=3 days after UCL/UEL/UECL"); sm_h3.paired(D, e4, "secondary exposure <=4 days")
            ko = e4 & (D.prev_leg.isin(["1/2", "2/2"])); lp = e4 & (D.prev_leg == "1/1")
            print(" EXPLORATORY:"); sm_h3.paired(D, ko, "knockout (two-legged) <=4 days"); sm_h3.paired(D, lp, "league-phase / single-leg <=4 days")
            sm_h3.paired(D, e4 & (D.prev_comp == "Champions League"), "UCL <=4 days")
    pd.to_pickle(res, "sm_h3_sens.pkl")

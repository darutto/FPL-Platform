"""Precondition (plan, amendment 1): identity-match rate per past season, with the registry's own matcher (match_player) and candidate assembly
(trial_mapping.registry_candidates / club_crosswalk). No tier is added. Gate: >= 95 % of FPL players with minutes.

Driver difference from the 2026-27 trial (declared): the past-season capture has no provider full names or birth dates, only the lineup display name,
club and position. So the provider display name is the matcher's full name and known name, pass 1 runs without a club, the club crosswalk is
built from pass-1 pairs exactly as the trial does (unanimous, minimum pairs), and pass 2 re-runs unresolved sources WITH the crosswalked club so
the registry's own team tiers can apply. A pass-2 hit never replaces a pass-1 pair and never takes an FPL player already taken.
Position is audited, not used to resolve."""
from __future__ import annotations
import sys, pathlib, json
import pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[4]
for p in ("football-identity-registry", "football-data-contract", "sportmonks-client", "sportmonks-client/scripts", "football-intelligence"):
    sys.path.insert(0, str(ROOT / "packages" / p))
from football_identity_registry.matcher import match_player
from football_identity_registry.models import SourcePlayer
from football_identity_registry.normalization import normalize_name
import trial_mapping as tm
from hb_data import STORE
from sm_data import load_matches

SM_POS = tm._POSITION  # provider position id -> FPL element_type (the trial's own mapping)


def fpl_people_for(season):
    d = STORE / season / "parquet_merged"
    p = pd.read_parquet(d / "players.parquet"); g = pd.read_parquet(d / "player_gw_stats.parquet")
    mins = g.groupby("player_id").minutes.sum()
    p["minutes"] = p.player_id.map(mins).fillna(0).astype(int)
    return [dict(side="fpl", id=int(r.player_id), full_name=f"{r.first_name or ''} {r.second_name or ''}".strip(), known_name=r.web_name, birth_date=None,
                 team=str(r.team_id), minutes=int(r.minutes), element_type=int(r.element_type)) for r in p.itertuples()]


def run(season):
    M, L = load_matches(season)
    people = fpl_people_for(season)
    rows = [{"full_name": x["full_name"], "known_name": x["known_name"], "birth_date": None, "team_provider_id": x["team"]} for x in people]
    candidates, conflicts = tm.registry_candidates({"candidates": rows})
    by_canon = {}
    for x in people:
        by_canon.setdefault(tm.canonical_player_id(x["full_name"], None), []).append(x)
    last = L.sort_values("kick").groupby("player").tail(1).set_index("player")
    pool = [(int(pid), r.pname, int(r.team), r.pos_id) for pid, r in last.iterrows()]
    hit, pairs, method = {}, {}, {}
    unresolved = []
    for pid, name, team, pos in pool:
        src = SourcePlayer(provider="sportmonks", provider_id=str(pid), full_name=name, team_provider_id=None, birth_date=None, known_name=name)
        if tm.identity_fingerprint(name, None) in conflicts: unresolved.append((pid, name, team, pos, "identity_indistinguishable")); continue
        res = match_player(src, candidates)
        if res.matched and res.canonical_player_id not in hit:
            hit[res.canonical_player_id] = pid; pairs[pid] = res.canonical_player_id; method[pid] = res.match_method
        else: unresolved.append((pid, name, team, pos, res.reason or "taken"))
    cw = tm.club_crosswalk([(team, by_canon[pairs[pid]][0]["team"]) for pid, name, team, pos in pool if pid in pairs and len(by_canon.get(pairs[pid], [])) == 1])
    still = []
    for pid, name, team, pos, why in unresolved:
        t = cw.get(team)
        if t is None or why == "identity_indistinguishable": still.append((pid, name, team, pos, why)); continue
        src = SourcePlayer(provider="sportmonks", provider_id=str(pid), full_name=name, team_provider_id=t, birth_date=None, known_name=name)
        res = match_player(src, candidates)
        if res.matched and res.canonical_player_id not in hit and res.match_method in ("full_name_team", "known_name_team"):
            hit[res.canonical_player_id] = pid; pairs[pid] = res.canonical_player_id; method[pid] = res.match_method + "|pass2"
        else: still.append((pid, name, team, pos, res.reason or ("taken" if res.matched else "tier")))
    with_min = [x for x in people if x["minutes"] > 0]
    matched_fpl = [x for x in with_min if tm.canonical_player_id(x["full_name"], None) in hit]
    # ambiguous canonical (two FPL people share a canonical id) are counted as hit only if the canonical was hit; report separately
    unmatched = [x for x in with_min if tm.canonical_player_id(x["full_name"], None) not in hit]
    pos_mis = sum(1 for pid, c in pairs.items() if len(by_canon.get(c, [])) == 1 and SM_POS.get(next((p for q, n, t, p in pool if q == pid), None)) != by_canon[c][0]["element_type"])
    rate = 100.0 * len(matched_fpl) / len(with_min)
    meth = {}
    for m in method.values(): meth[m] = meth.get(m, 0) + 1
    return dict(season=season, fpl_players=len(people), fpl_with_minutes=len(with_min), matched=len(matched_fpl), rate=rate, gate=rate >= tm.GATE_PERCENT,
                sm_pool=len(pool), sm_matched=len(pairs), methods=meth, club_crosswalk_size=len(cw), position_mismatch_audit=pos_mis,
                unmatched=sorted(unmatched, key=lambda x: -x["minutes"]), pairs=pairs, crosswalk=cw, unresolved=still)


if __name__ == "__main__":
    out = {}
    for s in ("2024-2025", "2025-2026"):
        r = run(s); out[s] = r
        print(f"{s}: FPL players {r['fpl_players']}, with minutes {r['fpl_with_minutes']}, matched {r['matched']} -> {r['rate']:.2f} % | gate >=95: {'PASS' if r['gate'] else 'FAIL'} | provider pool {r['sm_pool']}, matched {r['sm_matched']} | methods {r['methods']} | club crosswalk {r['club_crosswalk_size']}/20 | position audit mismatches {r['position_mismatch_audit']}")
        print("  top unmatched by minutes:", [(x["known_name"], x["team"], x["element_type"], x["minutes"]) for x in r["unmatched"][:12]])
    pd.to_pickle(out, "sm_gate.pkl")

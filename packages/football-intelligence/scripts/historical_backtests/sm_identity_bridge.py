"""Amendment 2: zero-call identity bridge. Sportmonks id -> FPL 2026-27 element (trial mapping) -> FPL `code` -> that season's FPL element (only where the
store has `code`). Applied only where club-on-date and position agree; any conflict (with the gate route too) leaves the player unmatched."""
from __future__ import annotations
import sys, json, urllib.request, pathlib
import pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from sm_identity_gate import run, tm, STORE, SM_POS, fpl_people_for, load_matches

LIVE = pathlib.Path("C:/Users/thera/wt-fi9-live/packages/sportmonks-client/trial-output")


def current_pairs():
    cap = json.loads((LIVE / "runs/gw6-final/capture.json").read_text(encoding="utf-8"))
    pairs = {str(p["sportmonks_id"]): int(p["fpl_id"]) for p in cap["identity_pairs"]}
    man = json.loads((LIVE / "mapping/manual_pairs.json").read_text(encoding="utf-8"))["pairs"]
    for p in man:
        pairs[str(p["sportmonks_id"])] = int(p["fpl_id"])
    return pairs


def bootstrap_codes():
    req = urllib.request.Request("https://fantasy.premierleague.com/api/bootstrap-static/", headers={"User-Agent": "Mozilla/5.0"})
    b = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return {int(e["id"]): int(e["code"]) for e in b["elements"]}, {int(e["id"]): int(e["element_type"]) for e in b["elements"]}


def season_code_table(season):
    f = STORE / season / "parquet" / "players.parquet"
    if not f.exists(): return None
    p = pd.read_parquet(f)
    if "code" not in p.columns: return None
    return {int(c): dict(player_id=int(i), team=str(int(t)), element_type=int(e)) for c, i, t, e in zip(p.code, p.player_id, p.team_id, p.element_type)}


def bridge(season, g, pairs, codes, use_position=False, types27=None):
    table = season_code_table(season)
    people = fpl_people_for(season); by_id = {x["id"]: x for x in people}
    canon_to_id = {}
    for x in people: canon_to_id.setdefault(tm.canonical_player_id(x["full_name"], None), []).append(x["id"])
    gate_fpl = {pid: canon_to_id[c][0] for pid, c in g["pairs"].items() if len(canon_to_id.get(c, [])) == 1}
    M, L = load_matches(season)
    last = L.sort_values("kick").groupby("player").tail(1).set_index("player")
    cw = g["crosswalk"]
    out = dict(season=season, code_in_store=table is not None, bridged=0, rejected_club=0, rejected_position=0, no_2627_pair=0, no_code_in_season=0, conflict_with_gate=0)
    bridge_hit = {}; rejected_pos = []
    if table is not None:
        for pid, r in last.iterrows():
            e27 = pairs.get(str(int(pid)))
            if e27 is None: out["no_2627_pair"] += 1; continue
            code = codes.get(e27)
            tgt = table.get(code) if code is not None else None
            if tgt is None: out["no_code_in_season"] += 1; continue
            if cw.get(int(r.team)) != tgt["team"]: out["rejected_club"] += 1; continue
            lineup_type = SM_POS.get(r.pos_id)
            if lineup_type != tgt["element_type"]:
                out["rejected_position"] += 1
                if types27 is not None: rejected_pos.append(dict(name=r.pname, club=tgt["team"], fpl_type_season=tgt["element_type"], fpl_type_2627=types27.get(e27), lineup_type=lineup_type, dpos=r.dpos))
                if use_position: continue
            bridge_hit[int(pid)] = tgt["player_id"]
    final = {}
    for pid, fid in gate_fpl.items(): final[pid] = fid
    for pid, fid in bridge_hit.items():
        if pid in final and final[pid] != fid:
            out["conflict_with_gate"] += 1; final.pop(pid); continue
        out["bridged"] += 1; final.setdefault(pid, fid)
    # one FPL player taken by two provider ids -> conflict, both dropped
    taken = {}
    for pid, fid in final.items(): taken.setdefault(fid, []).append(pid)
    for fid, pids in taken.items():
        if len(pids) > 1:
            for pid in pids: final.pop(pid, None)
            out["conflict_with_gate"] += 1
    with_min = [x for x in people if x["minutes"] > 0]
    hit_ids = set(final.values())
    matched = [x for x in with_min if x["id"] in hit_ids]
    new_rate = 100.0 * len(matched) / len(with_min)
    base = [x for x in with_min if x["id"] in {v for v in gate_fpl.values()}]
    out.update(rate_gate=100.0 * len(base) / len(with_min), rate_new=new_rate, gate=new_rate >= tm.GATE_PERCENT, fpl_with_minutes=len(with_min), matched=len(matched),
               unmatched=sorted([x for x in with_min if x["id"] not in hit_ids], key=lambda x: -x["minutes"]), final=final, position_flagged=rejected_pos)
    return out


if __name__ == "__main__":
    pairs = current_pairs(); codes, types27 = bootstrap_codes()
    print("2026-27 pairs:", len(pairs), "| bootstrap codes:", len(codes))
    res = {}
    for s in ("2024-2025", "2025-2026"):
        g = run(s)
        b2 = bridge(s, g, pairs, codes, use_position=True, types27=types27); b = bridge(s, g, pairs, codes, use_position=False, types27=types27); res[s] = b
        print(f"{s} AMENDMENT 2 (with lineup-position rule): rate {b2['rate_new']:.2f} % ({b2['matched']}/{b2['fpl_with_minutes']}), position rejections {b2['rejected_position']}")
        print(f"{s}: code in store: {b['code_in_store']} | rate before {b['rate_gate']:.2f} % -> after {b['rate_new']:.2f} % ({b['matched']}/{b['fpl_with_minutes']}) | gate >=95: {'PASS' if b['gate'] else 'FAIL'}")
        print("   bridge counts:", {k: v for k, v in b.items() if k in ("bridged", "rejected_club", "rejected_position", "no_2627_pair", "no_code_in_season", "conflict_with_gate")})
        print("   top unmatched:", [(x["known_name"], x["team"], x["element_type"], x["minutes"]) for x in b["unmatched"][:15]], "| n unmatched", len(b["unmatched"]))
        pf = pd.DataFrame(b["position_flagged"])
        if len(pf):
            mism = pf[pf.fpl_type_season != pf.fpl_type_2627]
            print(f"   players whose lineup position type differs from their FPL type: {len(pf)}; FPL-vs-FPL type differs between season and 2026-27 for {len(mism)}")
            print("   by (FPL type -> lineup type):", pf.groupby(['fpl_type_season', 'lineup_type']).size().to_dict())
            print("   examples:", [(r.name, r.fpl_type_season, r.lineup_type, r.dpos) for r in pf.head(14).itertuples()])
    pd.to_pickle(res, "sm_bridge.pkl")

"""Amendment 4: identity gate with the re-captured provider player records (name, display_name, common_name, date_of_birth), through the trial's own
fpl_side (trial_mapping.py). One route; no code bridge. Local-only inputs: trial-output/past_players."""
from __future__ import annotations
import sys, json, glob, pathlib, types
import pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from sm_identity_gate import tm, STORE, ROOT
PP = ROOT / "packages/sportmonks-client/trial-output/past_players"


def records_for(season):
    seen = {}
    for f in sorted(glob.glob(str(PP / f"{season}_p*.json"))):
        for m in json.loads(open(f, encoding="utf-8").read())["data"]:
            for l in m.get("lineups", []):
                p = l.get("player")
                if not p: continue
                pid = str(p["id"])
                last = seen.get(pid)
                kick = m["starting_at"]
                if last is None or kick > last[0]:
                    seen[pid] = (kick, p, l["team_id"])
    recs = []
    for pid, (kick, p, team) in seen.items():
        recs.append(types.SimpleNamespace(provider_id=pid, raw_fields=dict(name=p.get("name"), display_name=p.get("display_name"), common_name=p.get("common_name"),
                    date_of_birth=(p.get("date_of_birth") or None), team=None, squad_team_id=team, position_id=p.get("position_id"))))
    return recs


def people_for(season):
    d = STORE / season
    pm = pd.read_parquet(d / "parquet_merged/players.parquet"); g = pd.read_parquet(d / "parquet_merged/player_gw_stats.parquet")
    mins = g.groupby("player_id").minutes.sum(); pm["minutes"] = pm.player_id.map(mins).fillna(0).astype(int)
    dob = {}
    raw = d / "parquet/players.parquet"
    if raw.exists():
        r = pd.read_parquet(raw)
        if "birth_date" in r.columns: dob = {int(i): (str(b)[:10] if pd.notna(b) and str(b) else None) for i, b in zip(r.player_id, r.birth_date)}
    return [dict(side="fpl", id=int(x.player_id), full_name=f"{x.first_name or ''} {x.second_name or ''}".strip(), known_name=x.web_name, birth_date=dob.get(int(x.player_id)) or None,
                 team=str(int(x.team_id)), minutes=int(x.minutes), element_type=int(x.element_type), status=None, news=None) for x in pm.itertuples()], bool(dob)


if __name__ == "__main__":
    out = {}
    for s in ("2024-2025", "2025-2026"):
        recs = records_for(s); people, has_dob = people_for(s)
        r = tm.fpl_side(recs, people, second_pass=True)
        rate = 100.0 * r.with_minutes_resolved / r.with_minutes
        out[s] = dict(side=r, people=people, rate=rate)
        print(f"{s}: provider players {len(recs)} (with DOB {sum(1 for x in recs if x.raw_fields['date_of_birth'])}), FPL has DOB: {has_dob} | FPL with minutes {r.with_minutes}, resolved {r.with_minutes_resolved} -> {rate:.2f} % | gate >=95: {'PASS' if rate >= tm.GATE_PERCENT else 'FAIL'}")
        print("   by method:", r.by_method, "| second pass:", r.second_pass, "| fpl causes:", r.fpl_causes)
        um = [u for u in r.unmatched if u["group"] == "fpl_with_minutes"]
        mins = {p["id"]: p["minutes"] for p in people}
        print("   unmatched FPL with minutes:", len(um), [(u["known_name"], u["full_name"], u["cause"]) for u in um[:12]])
    pd.to_pickle(out, "sm_gate2.pkl")

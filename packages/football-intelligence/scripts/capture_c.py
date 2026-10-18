"""Capture C (2026-10-18): per-player stats, cup/European XIs and sidelined history for matchup questions Q9-Q11.

Local-only exploration. Raw responses go to packages/sportmonks-client/trial-output/capture_c/ (git-ignored); only
aggregates leave this script. The token is read from SPORTMONKS_API_TOKEN and never printed.

    python capture_c.py fetch-fixtures <ids.json>   # one call per fixture id (lineups.details etc.)
    python capture_c.py fetch-club-fixtures <team_id> <code> <from> <to>
    python capture_c.py analyse                     # Q9-Q11 aggregates from the raw files

A hard cap on calls is enforced (CALL_CAP) across the process.
"""
from __future__ import annotations

import collections
import glob
import json
import os
import statistics as st
import sys

import requests

BASE = "https://api.sportmonks.com/v3/football"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(ROOT, "packages", "sportmonks-client", "trial-output", "capture_c")
CALL_CAP = 150
CALLS = 0

FIXTURE_INCLUDE = "lineups.details.type;lineups.detailedPosition;formations;participants;sidelined.sideline"
CLUB_INCLUDE = "league;participants;lineups.detailedPosition;formations"
STATS = ("KEY_PASSES", "SUCCESSFUL_DRIBBLES", "TOTAL_CROSSES", "DRIBBLED_PAST", "TACKLES", "SHOTS_TOTAL", "TOUCHES",
         "MINUTES_PLAYED")
FLANK = {"Left Back": "L", "Left Midfield": "L", "Right Back": "R", "Right Midfield": "R"}


def get(path: str, tag: str, **params):
    global CALLS
    if CALLS >= CALL_CAP:
        raise SystemExit("call cap reached")
    CALLS += 1
    os.makedirs(OUT, exist_ok=True)
    params["api_token"] = os.environ["SPORTMONKS_API_TOKEN"]
    r = requests.get(f"{BASE}/{path}", params=params, timeout=60, allow_redirects=False)
    body = r.json()
    with open(os.path.join(OUT, tag + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"status": r.status_code, "path": path, "body": body}, fh)
    return r.status_code, body


def analyse() -> None:
    """Q9-Q11 aggregates. 'Concedes down its left' is OUR derived measure (stats of that flank's full-back and winger
    from detailedPosition), not a provider field."""
    rows = []
    for p in glob.glob(os.path.join(OUT, "fixture_*.json")):
        d = json.load(open(p, encoding="utf-8"))["body"]["data"]
        form = {f["participant_id"]: f["formation"] for f in d["formations"]}
        teams = [x["id"] for x in d["participants"]]
        for l in d["lineups"]:
            if l["type_id"] != 11:
                continue
            det = {x["type"]["developer_name"]: x["data"]["value"] for x in l["details"] if x.get("type")}
            pos = (l.get("detailedposition") or {}).get("name")
            other = [t for t in teams if t != l["team_id"]][0]
            rows.append(dict(fx=d["id"], team=l["team_id"], opp=other, form=form.get(l["team_id"]), oform=form.get(other),
                             pos=pos, flank=FLANK.get(pos), **{k: det.get(k) or 0 for k in STATS}))
    act = lambda r: r["KEY_PASSES"] + r["SUCCESSFUL_DRIBBLES"] + r["TOTAL_CROSSES"]
    opposite = {"L": "R", "R": "L"}
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    by_tm = collections.defaultdict(list)
    for r in rows:
        by_tm[(r["fx"], r["team"])].append(r)
    for (fx, team), pl in by_tm.items():
        opp = [x for x in rows if x["fx"] == fx and x["team"] != team]
        for f in "LR":
            per[(team, f)]["dp"].append(sum(x["DRIBBLED_PAST"] for x in pl if x["flank"] == f))
            per[(team, f)]["att"].append(sum(act(x) for x in opp if x["flank"] == opposite[f]))
    att = [st.mean(v["att"]) for v in per.values()]
    dp = [st.mean(v["dp"]) for v in per.values()]
    print("fixtures", len({r["fx"] for r in rows}), "starter rows", len(rows), "team-flanks", len(per))
    print("corr(opponent wide output, own flank dribbled-past) across team-flanks: %.2f" % st.correlation(att, dp))
    for form in ("4-2-3-1", "3-4-2-1"):
        for pos in ("Left Back", "Right Back", "Left Midfield", "Right Midfield"):
            xs = [act(r) for r in rows if r["form"] == form and r["pos"] == pos]
            if xs:
                print("wide actions per player-match", form, pos, "%.2f (n=%d)" % (st.mean(xs), len(xs)))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "analyse"
    if cmd == "fetch-fixtures":
        for i in json.load(open(sys.argv[2])):
            get(f"fixtures/{i}", f"fixture_{i}", include=FIXTURE_INCLUDE)
    elif cmd == "fetch-club-fixtures":
        get(f"fixtures/between/{sys.argv[4]}/{sys.argv[5]}/{sys.argv[2]}", f"club_{sys.argv[3]}", include=CLUB_INCLUDE, per_page=50)
    else:
        analyse()

"""Guarded re-fetch of the two past Premier League seasons with `lineups.player` (name, display name, date of birth), approved by Leo with a hard cap of 40 calls.
Token: Windows env var SPORTMONKS_API_TOKEN, read here and never printed or written (saved files carry no token). Hard cap enforced by a persistent counter;
stops on the first non-200 response; no redirects; raw pages go to the git-ignored trial-output folder only."""
from __future__ import annotations
import json, os, pathlib, sys
import requests

BASE = "https://api.sportmonks.com/v3/football/fixtures"
CAP = 40
SEASONS = {"2024-2025": 23614, "2025-2026": 25583}      # season ids from trial-output/step1/season_ids.json
LEAGUE = 8
INCLUDE = "lineups.player;participants"
OUT = pathlib.Path(__file__).resolve().parents[4] / "packages/sportmonks-client/trial-output/past_players"


def counter():
    f = OUT / "state.json"
    return json.loads(f.read_text()) if f.exists() else {"calls": 0, "done": []}


def save_counter(st): (OUT / "state.json").write_text(json.dumps(st))


def fetch(season, page, per_page, st):
    if st["calls"] >= CAP: raise SystemExit(f"call cap {CAP} reached; nothing more fetched")
    tag = f"{season}_p{page}"
    if tag in st["done"]: return None
    st["calls"] += 1; save_counter(st)                       # count BEFORE the call
    params = {"filters": f"fixtureSeasons:{SEASONS[season]};fixtureLeagues:{LEAGUE}", "include": INCLUDE, "per_page": per_page, "page": page,
              "api_token": os.environ["SPORTMONKS_API_TOKEN"]}
    r = requests.get(BASE, params=params, timeout=120, allow_redirects=False)
    if r.status_code != 200:
        raise SystemExit(f"stopped: HTTP {r.status_code} on {tag} (calls so far {st['calls']})")
    body = r.json()
    (OUT / f"{tag}.json").write_text(json.dumps(body), encoding="utf-8")
    st["done"].append(tag); save_counter(st)
    return body


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True); st = counter()
    per_page = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    only_first = len(sys.argv) > 2 and sys.argv[2] == "probe"
    for season in SEASONS:
        page = 1
        while True:
            body = fetch(season, page, per_page, st)
            if body is None: page += 1; continue
            pg = body["pagination"]
            n = len(body["data"]); rows = sum(len(m.get("lineups", [])) for m in body["data"])
            with_player = sum(1 for m in body["data"] for l in m.get("lineups", []) if l.get("player"))
            dob = sum(1 for m in body["data"] for l in m.get("lineups", []) if (l.get("player") or {}).get("date_of_birth"))
            print(f"{season} p{page}: fixtures {n} (per_page {pg.get('per_page')}), lineup rows {rows}, with player {with_player}, with date_of_birth {dob}, has_more {pg.get('has_more')}, calls {st['calls']}")
            if only_first: raise SystemExit(0)
            if not pg.get("has_more"): break
            page += 1
    print("done; total calls", st["calls"])

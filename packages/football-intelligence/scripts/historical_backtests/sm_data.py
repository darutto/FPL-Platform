"""Loader for the Sportmonks past-season capture (local, git-ignored). Nothing here is committed with data: callers cache outside git.
State of a lineup row: type_id 11 = starter, 12 = bench. Minutes = detail type 119."""
from __future__ import annotations
import json, os, pathlib, sys
import numpy as np
import pandas as pd

_PKG = pathlib.Path(__file__).resolve().parents[3]
for _p in ("football-intelligence", "football-data-contract"):
    sys.path.insert(0, str(_PKG / _p))

SM_PATH = pathlib.Path(os.environ.get("HB_SM_PATH", "C:/Users/thera/wt-fi9-extras/packages/sportmonks-client/trial-output"))
MINUTES_TYPE = 119
STARTER, BENCH = 11, 12
SEASON_TAGS = {"2024-2025": ["pl2425_p%d" % i for i in range(1, 17)], "2025-2026": ["pl2526_p%d" % i for i in range(2, 17)]}


def _files(season):
    out = []
    for tag in SEASON_TAGS[season]:
        out.append(SM_PATH / "step2" / f"{tag}.json")
    if season == "2025-2026":
        out.insert(0, SM_PATH / "step1" / "fx_page25.json")
    return out


def load_matches(season: str):
    """Return (matches, lineups). matches: one row per league match. lineups: one row per player-match (starter or bench)."""
    ms, ls = [], []
    for f in _files(season):
        d = json.loads(f.read_text(encoding="utf-8"))
        for m in d["data"]:
            if m["league"]["name"] != "Premier League": continue
            loc = {p["id"]: p["meta"]["location"] for p in m["participants"]}
            name = {p["id"]: p["name"] for p in m["participants"]}
            home = next((i for i, l in loc.items() if l == "home"), None); away = next((i for i, l in loc.items() if l == "away"), None)
            form = {x["participant_id"]: x["formation"] for x in m.get("formations", [])}
            ms.append(dict(season=season, match=m["id"], kick=pd.Timestamp(m["starting_at"], tz="UTC"), home=home, away=away, home_name=name.get(home), away_name=name.get(away),
                           state=m.get("state_id"), result=m.get("result_info"), n_lineups=len(m["lineups"]), form_home=form.get(home), form_away=form.get(away),
                           sidelined=[(s["participant_id"], s["player_id"], s["type_id"]) for s in m.get("sidelined", [])]))
            for l in m["lineups"]:
                mins = next((x["data"]["value"] for x in l.get("details", []) if x["type_id"] == MINUTES_TYPE), None)
                dp = (l.get("detailedposition") or {}).get("name")
                team = l["team_id"]
                ls.append(dict(season=season, match=m["id"], kick=pd.Timestamp(m["starting_at"], tz="UTC"), player=l["player_id"], pname=l["player_name"], team=team,
                               opp=(away if team == home else home), venue=("H" if team == home else "A"), kind=l["type_id"], started=int(l["type_id"] == STARTER),
                               minutes=mins, pos_id=l.get("position_id"), dpos=dp, grid=l.get("formation_field"), formation=form.get(team)))
    M = pd.DataFrame(ms).drop_duplicates("match").sort_values("kick").reset_index(drop=True)
    L = pd.DataFrame(ls).drop_duplicates(["match", "player"]).sort_values(["kick", "match"]).reset_index(drop=True)
    return M, L


if __name__ == "__main__":
    for s in SEASON_TAGS:
        M, L = load_matches(s)
        print(s, "matches", len(M), "lineup rows", len(L), "starters", int(L.started.sum()), "bench", int((1 - L.started).sum()), "teams", L.team.nunique(), "players", L.player.nunique(),
              "minutes nn %.3f" % L.minutes.notna().mean(), "dpos nn(starters) %.3f" % L[L.started == 1].dpos.notna().mean(), "grid nn(starters) %.3f" % L[L.started == 1].grid.notna().mean(),
              "state", M.state.value_counts().to_dict(), "kick", M.kick.min().date(), M.kick.max().date())
        print("  starters per team-match:", L[L.started == 1].groupby(["match", "team"]).size().value_counts().to_dict())

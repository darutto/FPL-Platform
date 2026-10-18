import json, sys, pathlib, urllib.request, time
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
P = pathlib.Path("C:/Users/thera/fpl-platform/.worktrees/ab-run/packages")
for p in ("football-intelligence","football-identity-registry","football-data-contract","sportmonks-client"):
    sys.path.insert(0, str(P/p))
TO = pathlib.Path("C:/Users/thera/wt-fi9-live/packages/sportmonks-client/trial-output")
DS = TO/"answer-depth-ab/dev-store"
CANON = DS/"builds/live-trial/canonical"
CACHE = pathlib.Path(__file__).parent/"cache"; CACHE.mkdir(exist_ok=True)
from football_intelligence.features.engine_v2 import ROLE_MAP_V3
from football_intelligence.ingestion import live_trial as lt

def fpl_get(path):
    f = CACHE/(path.strip('/').replace('/','_')+'.json')
    if f.exists(): return json.loads(f.read_text(encoding='utf-8'))
    req = urllib.request.Request("https://fantasy.premierleague.com/api/"+path.strip('/')+"/", headers={"User-Agent":"Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read()); f.write_text(json.dumps(d), encoding='utf-8'); time.sleep(0.15); return d

BS = fpl_get("bootstrap-static")
EL = {e["id"]: e for e in BS["elements"]}
TEAM = {t["id"]: t for t in BS["teams"]}
POS = {1:"GK",2:"DEF",3:"MID",4:"FWD"}

def capture():
    return json.loads((TO/"runs/gw6-final/capture.json").read_text(encoding='utf-8'))

def build():
    cap = capture()
    idn = pd.read_parquet(DS/"identity/player_identity.parquet")
    canon2fpl = {r.canonical_player_id:int(r.provider_id) for r in idn.itertuples()}
    pl = pd.read_parquet(CANON/"players.parquet")
    sm2canon = {str(r.source_provider_id):r.player_id for r in pl.itertuples()}
    tid = pd.read_parquet(DS/"identity/team_identity.parquet")
    canon2fplteam = {r.canonical_team_id:int(r.provider_id) for r in tid.itertuples()}
    fx = pd.read_parquet(CANON/"fixtures.parquet")
    fx = fx[fx.status=="completed"].copy()
    fx["home"] = fx.home_team_id.map(canon2fplteam); fx["away"]=fx.away_team_id.map(canon2fplteam)
    lu = pd.read_parquet(CANON/"lineups.parquet")
    lu = lu.merge(fx[["fixture_id","kickoff_utc","gameweek","home","away"]], on="fixture_id")
    lu["fpl_id"] = lu.player_id.map(canon2fpl); lu["team"]=lu.team_id.map(canon2fplteam)
    lu["opp"] = lu.apply(lambda r: r.away if r.team==r.home else r.home, axis=1)
    lu["venue"] = lu.apply(lambda r: "H" if r.team==r.home else "A", axis=1)
    lu["kick"] = pd.to_datetime(lu.kickoff_utc, utc=True)
    lu["role"] = lu.detailed_position.str.lower().map(lambda x: ROLE_MAP_V3.get(x,(None,None,None))[0] if isinstance(x,str) else None)
    lu["flank"] = lu.detailed_position.str.lower().map(lambda x: ROLE_MAP_V3.get(x,(None,None,None))[1] if isinstance(x,str) else None)
    lu["depth"] = lu.detailed_position.str.lower().map(lambda x: ROLE_MAP_V3.get(x,(None,None,None))[2] if isinstance(x,str) else None)
    lu["name"] = lu.fpl_id.map(lambda i: EL[i]["web_name"] if i in EL else None)
    lu["fpos"] = lu.fpl_id.map(lambda i: POS[EL[i]["element_type"]] if i in EL else None)
    lu["src"]="M0"
    # club calendar, all competitions, from the capture (calendar only: no lineups for cups/Europe)
    sm2fplteam = lt.club_crosswalk(cap)
    rows=[]
    for f in cap["team_fixtures"]:
        for p in f["participants"]:
            if int(p["id"]) in sm2fplteam:
                opp=[q for q in f["participants"] if q is not p][0]
                rows.append(dict(team=sm2fplteam[int(p["id"])], kick=pd.Timestamp(f["starting_at"],tz="UTC"), comp=f["league"]["name"],
                    state=f["state"]["developer_name"], opp_name=opp["name"], venue=("H" if p["meta"]["location"]=="home" else "A")))
    cal = pd.DataFrame(rows).sort_values(["team","kick"]).reset_index(drop=True)
    return lu, cal, canon2fpl, sm2canon, sm2fplteam

def gw7(sm2canon, canon2fpl):
    out={}
    for line in open(TO/"lineup-watch/gw7.ndjson",encoding='utf-8'):
        r=json.loads(line)
        if r.get("lineup_confirmed") and r.get("starters_list"): out[r["fixture_id"]]=r
    return out
if __name__=="__main__":
    lu,cal,c2f,s2c,s2t=build()
    print(lu.shape, lu.fpl_id.isna().sum(), lu.role.isna().sum(), lu.started.sum())
    print(lu.detailed_position.value_counts().head(20))
    print(cal.comp.value_counts()); print(cal[cal.state!="NS"].groupby("comp").size())
    g=gw7(s2c,c2f); print({k:(v["name"],v["kickoff"],v["formations"]) for k,v in g.items()})

def pos_lookup(lu):
    s = lu[lu.started]
    return {k:v for k,v in s.groupby(["formation","grid_slot","venue"]).detailed_position.first().items()}

def gw7_starts(lu, s2c, c2f, s2t, cap):
    look = pos_lookup(lu); g = gw7(s2c, c2f)
    loc = {}
    for f in cap["team_fixtures"]:
        for p in f["participants"]: loc[(f["id"], int(p["id"]))] = p["meta"]["location"]
    rows=[]
    for fid,r in g.items():
        form = {t:fm for t,fm in r["formations"]}
        for team,player,grid in r["starters_list"]:
            venue = "H" if loc.get((fid,team))=="home" else "A"
            pid = s2c.get(str(player)); fpl = c2f.get(pid)
            dp = look.get((form[team],grid,venue))
            opp = [t for t in form if t!=team][0]
            rows.append(dict(fixture_id=fid, kick=pd.Timestamp(r["kickoff"]), gameweek=7, team=s2t.get(team), opp=s2t.get(opp), venue=venue,
                             fpl_id=fpl, started=True, minutes=None, formation=form[team], grid_slot=grid, detailed_position=dp,
                             name=EL[fpl]["web_name"] if fpl in EL else None, fpos=POS[EL[fpl]["element_type"]] if fpl in EL else None, src="GW7-grid"))
    d = pd.DataFrame(rows)
    mp = d.detailed_position.str.lower().map(lambda x: ROLE_MAP_V3.get(x,(None,None,None)) if isinstance(x,str) else (None,None,None))
    d["role"]=mp.map(lambda t:t[0]); d["flank"]=mp.map(lambda t:t[1]); d["depth"]=mp.map(lambda t:t[2])
    return d

def all_starts():
    lu,cal,c2f,s2c,s2t = build(); cap = capture()
    s = lu[lu.started].copy()
    g7 = gw7_starts(lu, s2c, c2f, s2t, cap)
    cols = ["fpl_id","name","fpos","team","opp","venue","kick","gameweek","formation","grid_slot","detailed_position","role","flank","depth","minutes","src"]
    a = pd.concat([s[cols], g7[cols]], ignore_index=True)
    a["kick"] = pd.to_datetime(a.kick, utc=True)
    a = a[a.fpl_id.isin(EL.keys())].sort_values(["fpl_id","kick"]).reset_index(drop=True)
    return a, lu, cal, c2f, s2c, s2t

def history(fid):
    d = fpl_get(f"element-summary/{fid}")
    return pd.DataFrame(d["history"])

def m1(name_or_id):
    import os
    os.environ["FI_DEV_ALLOW_LIVE_TRIAL_LOCAL"]="1"; os.environ["FI_DEV_LIVE_TRIAL_STORE"]=str(DS)
    for k in list(os.environ):
        if k.startswith("RAILWAY"): os.environ.pop(k)
    P2 = pathlib.Path("C:/Users/thera/fpl-platform/.worktrees/ab-run/packages")
    for p in ("fpl-grounded-assistant","fpl-data-core","fpl-api-client","fpl-player-registry","fpl-query-tools","fpl-tool-contract","fpl-tool-runner","fpl-captain-engine"):
        sys.path.insert(0,str(P2/p))
    from fpl_grounded_assistant.football_intelligence_runtime import run_football_intelligence_tool as r
    return r("get_expected_minutes", {"player": name_or_id}, BS)

def m1_batch(ids):
    import os, time
    os.environ["FI_DEV_ALLOW_LIVE_TRIAL_LOCAL"]="1"; os.environ["FI_DEV_LIVE_TRIAL_STORE"]=str(DS)
    P2 = pathlib.Path("C:/Users/thera/fpl-platform/.worktrees/ab-run/packages")
    for p in ("fpl-grounded-assistant","fpl-data-core","fpl-api-client","fpl-player-registry","fpl-query-tools","fpl-tool-contract","fpl-tool-runner","fpl-captain-engine"):
        sys.path.insert(0,str(P2/p))
    from fpl_grounded_assistant import football_intelligence_runtime as rt
    import football_intelligence.modules.expected_minutes as em
    _orig = em.validate_feature_build_v2; _memo = {}
    def _cached(build, base, ctx):  # analysis-only memo: same build, same manifest, validated once
        k = (str(build), str(ctx))
        if k not in _memo: _memo[k] = _orig(build, base, ctx)
        return _memo[k]
    em.validate_feature_build_v2 = _cached
    runtime = rt._load_runtime(); idt = rt._identity_tables(runtime.root, runtime.calculated_at)
    out={}
    for i in ids:
        try:
            res = rt._resolve_player(str(i), BS, idt)
            if res["status"]!="ok": out[i]={"status":res["status"]}; continue
            fx = rt.select_target_fixture(runtime, res["team_id"])
            if fx is None: out[i]={"status":"no_target"}; continue
            r = rt._evaluate_modules(runtime, res, fx, ("expected_minutes",))["expected_minutes"]
            v = rt._serialized(r); v["target_fixture"]=fx; out[i]=v
        except Exception as e:
            out[i]={"status":"error","error":str(e)[:100]}
    return out

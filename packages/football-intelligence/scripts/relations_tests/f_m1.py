from g_check import *
import numpy as np, math
for p in ("fpl-grounded-assistant",):
    sys.path.insert(0,str(pathlib.Path("C:/Users/thera/fpl-platform/.worktrees/ab-run/packages")/p))
from football_intelligence.modules.expected_minutes import ExpectedMinutesInput, evaluate_expected_minutes
from football_intelligence.features.registry_v2 import FEATURE_REGISTRY_VERSION
a,lu,cal,c2f,s2c,s2t,movers=verified_starts()
FB=DS/"features/builds-v2/live-trial/datasets"
pm=pd.read_parquet(FB/"player_fixture_module_inputs.parquet"); tc=pd.read_parquet(FB/"team_fixture_context_v2.parquet")
fxs=pd.read_parquet(CANON/"fixtures.parquet")
idn=pd.read_parquet(DS/"identity/player_identity.parquet"); tid=pd.read_parquet(DS/"identity/team_identity.parquet")
c2fpl={r.canonical_player_id:int(r.provider_id) for r in idn.itertuples()}; t2fpl={r.canonical_team_id:int(r.provider_id) for r in tid.itertuples()}
fxs["kick"]=pd.to_datetime(fxs.kickoff_utc,utc=True); fxs["home"]=fxs.home_team_id.map(t2fpl); fxs["away"]=fxs.away_team_id.map(t2fpl)
FX=fpl_get("fixtures"); NOW=pd.Timestamp.now(tz="UTC")
FXF=[dict(id=f["id"],event=f["event"],kick=pd.Timestamp(f["kickoff_time"]),h=f["team_h"],a=f["team_a"],done=bool(f["finished"] or f["finished_provisional"])) for f in FX if f["kickoff_time"]]
tcx=tc.set_index(["fixture_id","team_id"])
H={}
def hist(i):
    if i not in H:
        h=history(i).assign(kt=lambda x:pd.to_datetime(x.kickoff_time,utc=True)); H[i]=h[h.team_h_score.notna()|(h.kt<NOW)].sort_values("kt").reset_index(drop=True)
    return H[i]
def inp(share_num,den,n_el,cam,mst,mcam,tr,le):
    return ExpectedMinutesInput(fixture_id="f",team_id="t",player_id="p",calculated_at="2026-10-13T00:00:00Z",feature_registry_version=FEATURE_REGISTRY_VERSION,feature_build_id="b",
        weighted_start_share_last_6=(share_num/den if den else None),weighted_start_denominator_last_6=den,eligible_team_fixtures_last_6=n_el,cameo_appearances_last_6=cam,
        mean_minutes_when_started_last_6=mst,mean_minutes_when_cameo_last_6=mcam,weighted_trailing_congestion_21d=tr,weighted_leading_congestion_21d=le)
def m1_fpl(fid,kick,team):
    h=hist(fid); prior=h[(h.kt<kick-pd.Timedelta(hours=3))].tail(6)   # only finished matches before this one
    if prior.empty: return None
    w=list(range(7-len(prior),7)); den=float(sum(w)); num=float(sum(x for x,s in zip(w,prior.starts) if s>0))
    st=prior[prior.starts>0]; cam=prior[(prior.starts==0)&(prior.minutes>0)]
    tr=sum(1 for f in FXF if team in (f["h"],f["a"]) and f["done"] and kick-pd.Timedelta(days=21)<=f["kick"]<kick)
    le=sum(1 for f in FXF if team in (f["h"],f["a"]) and kick<f["kick"]<=kick+pd.Timedelta(days=21))
    r=evaluate_expected_minutes(inp(num,den,len(prior),len(cam),float(st.minutes.mean()) if len(st) else None,float(cam.minutes.mean()) if len(cam) else None,float(tr),float(le)))
    return (r.start_probability,r.expected_minutes) if r.start_probability is not None else None
def simple(fid,kick):
    h=hist(fid); prior=h[(h.kt<kick-pd.Timedelta(hours=3))].tail(3)
    if prior.empty: return None
    return float((prior.starts>0).mean()), float(prior.minutes.mean())
def m1_sm(row,team_c):
    p=row; t=tcx.loc[(row.fixture_id,team_c)] if (row.fixture_id,team_c) in tcx.index else None
    r=evaluate_expected_minutes(ExpectedMinutesInput(fixture_id="f",team_id="t",player_id="p",calculated_at="2026-10-13T00:00:00Z",feature_registry_version=FEATURE_REGISTRY_VERSION,feature_build_id="b",
        weighted_start_share_last_6=None if pd.isna(p.weighted_start_share_last_6) else float(p.weighted_start_share_last_6),weighted_start_denominator_last_6=float(p.weighted_start_denominator_last_6),
        eligible_team_fixtures_last_6=int(p.eligible_team_fixtures_last_6),cameo_appearances_last_6=int(p.cameo_appearances_last_6),
        mean_minutes_when_started_last_6=None if pd.isna(p.mean_minutes_when_started_last_6) else float(p.mean_minutes_when_started_last_6),
        mean_minutes_when_cameo_last_6=None if pd.isna(p.mean_minutes_when_cameo_last_6) else float(p.mean_minutes_when_cameo_last_6),
        weighted_trailing_congestion_21d=None if t is None else float(t.weighted_trailing_congestion_21d),weighted_leading_congestion_21d=None if t is None else float(t.weighted_leading_congestion_21d)))
    return (r.start_probability,r.expected_minutes) if r.start_probability is not None else None
# evaluation fixtures: FPL events 2..7 that are finished; map to store fixtures by teams + kickoff
rows=[]
done=[f for f in FXF if f["done"] and 2<=f["event"]<=7]
fxs["key"]=list(zip(fxs.home,fxs.away))
for f in done:
    m=fxs[(fxs.home==f["h"])&(fxs.away==f["a"])]
    if m.empty: continue
    fr=m.iloc[0]
    sub=pm[pm.fixture_id==fr.fixture_id]
    for r in sub.itertuples():
        pl=c2fpl.get(r.player_id); team_f=t2fpl.get(r.team_id)
        if pl is None or pl not in EL or r.starts_last_6<1: continue   # starters list fixed pre-match: >=1 start in the previous <=6 league matches
        h=hist(pl); act=h[(h.kt-f["kick"]).abs()<pd.Timedelta(hours=6)]
        if act.empty: continue
        act=act.iloc[0]
        v1=simple(pl,f["kick"]); v2=m1_fpl(pl,f["kick"],team_f); v3=m1_sm(r,r.team_id)
        if v1 is None or v2 is None or v3 is None: continue
        rows.append(dict(event=f["event"],fpl_id=pl,started=int(act.starts>0),minutes=int(act.minutes),p1=v1[0],m1_=v1[1],p2=v2[0],m2=v2[1],p3=v3[0],m3=v3[1],mover=pl in movers))
D=pd.DataFrame(rows)
print("rows",len(D),"fixtures GW2-7:",D.event.value_counts().sort_index().to_dict(),"players",D.fpl_id.nunique(),"base start rate %.3f"%D.started.mean())
def ev(df,tag):
    out={}
    for k,(p,m) in {"1 regla simple FPL":("p1","m1_"),"2 M1 con historial FPL":("p2","m2"),"3 M1 con Sportmonks":("p3","m3")}.items():
        out[k]=dict(Brier=((df.started-df[p])**2).mean(),MAE_min=(df.minutes-df[m]).abs().mean())
    out["referencia: tasa base / media"]=dict(Brier=((df.started-df.started.mean())**2).mean(),MAE_min=(df.minutes-df.minutes.mean()).abs().mean())
    print("\n",tag,"n=",len(df)); print(pd.DataFrame(out).T.round(4).to_string())
ev(D,"GW2-7 total"); 
for g in range(2,8): ev(D[D.event==g],f"GW{g}") if len(D[D.event==g])>20 else None
D.to_pickle("f_out.pkl")
print("\nM1-FPL vs M1-SM: max abs diff in p_start %.4f, mean %.4f; rows differing >0.01: %d"%((D.p2-D.p3).abs().max(),(D.p2-D.p3).abs().mean(),((D.p2-D.p3).abs()>0.01).sum()))

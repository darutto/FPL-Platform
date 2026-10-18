from common import *
import numpy as np
a,lu,cal,c2f,s2c,s2t = all_starts()
now=pd.Timestamp.now(tz="UTC")
cal["finished"]=cal.state.isin(["FT","AET","FT_PEN"])
c=cal[(cal.kick<now-pd.Timedelta(hours=3))].sort_values(["team","kick"]).copy()
c["prev_kick"]=c.groupby("team").kick.shift(); c["prev_comp"]=c.groupby("team").comp.shift()
c["rest"]=((c.kick-c.prev_kick).dt.total_seconds()/86400).round(1)
c["after_euro_cup"]=c.prev_comp.isin(["Champions League","Europa League","Europa Conference League","Carabao Cup","UEFA Super Cup"])
pl=c[c.comp=="Premier League"].copy()
print("PL matches with rest<=3.5d:",(pl.rest<=3.5).sum(),"after euro/cup:",pl.after_euro_cup.sum(),"of",len(pl))
print(pl[pl.after_euro_cup].groupby("team").size().rename(lambda x:TEAM[x]["short_name"]).to_dict())
d=pd.read_pickle("q4.pkl")
reg=d[(d.starts_prev/d.n_prev>=0.75)]
# per regular, per match in last 3: minutes, rest, after_euro
recs=[]
for r in reg.itertuples():
    h=history(r.fpl_id).assign(kt=lambda x:pd.to_datetime(x.kickoff_time,utc=True))
    h=h[(h.kt<now)&h.team_h_score.notna()].sort_values("kt")
    last=h.iloc[len(h)-3:]
    team=EL[r.fpl_id]["team"]
    for _,m in last.iterrows():
        x=pl[(pl.team==team)&((pl.kick-m.kt).abs()<pd.Timedelta(hours=6))]
        if len(x): recs.append(dict(fpl_id=r.fpl_id,min=m.minutes,start=m.starts>0,rest=x.rest.iloc[0],after=x.after_euro_cup.iloc[0],prev_comp=x.prev_comp.iloc[0],kick=m.kt))
R=pd.DataFrame(recs); R["tight"]=R.rest<=3.5
print(len(R),"regular-player matches in last3")
print(R.groupby("tight").agg(n=("min","size"),start_rate=("start","mean"),mean_min=("min","mean")).round(2))
print(R.groupby("after").agg(n=("min","size"),start_rate=("start","mean"),mean_min=("min","mean")).round(2))
print(R.groupby("prev_comp").agg(n=("min","size"),start_rate=("start","mean"),mean_min=("min","mean")).round(2))
R.to_pickle("q4R.pkl")

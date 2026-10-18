from common import *
import pickle, numpy as np
m=pickle.load(open("m1.pkl","rb"))
a,lu,cal,c2f,s2c,s2t = all_starts()
rows=[]
for i,v in m.items():
    if v.get("status")!="ok": continue
    e=EL[i]; h=history(i); h6=h[h["round"]<=6]
    app=h6[h6.minutes>0]; k=len(h6)
    rows.append(dict(fpl_id=i,name=e["web_name"],club=TEAM[e["team"]]["short_name"],pos=POS[e["element_type"]],team=e["team"],
        m1_min=v["expected_minutes"],m1_start=v["start_probability"],m1_rot=v["rotation_risk"],
        apps=len(app),starts6=int((h6.starts>0).sum()),k=k,pts=h6.total_points.sum(),ppa=(h6.total_points.sum()/len(app)) if len(app) else np.nan,
        mpa=app.minutes.mean() if len(app) else np.nan,
        last3_min=h6.tail(3).minutes.mean(), last3_starts=int((h6.tail(3).starts>0).sum()),
        status=e["status"],news=e["news"]))
d=pd.DataFrame(rows)
d=d[d.apps>=3].copy()
q75=d.ppa.quantile(.75); print("players apps>=3:",len(d),"pts/app 75th pct:",round(q75,2))
hi=d[d.ppa>=q75]
risk=hi[(hi.m1_min<=60)&(hi.status=="a")].sort_values("m1_min")
pd.set_option("display.width",250)
print("high points per appearance & M1 expected minutes <=60 & FPL 'a':",len(risk),"of",len(hi))
print(risk[["name","club","pos","apps","starts6","k","ppa","mpa","last3_min","last3_starts","m1_min","m1_start","m1_rot"]].round(2).to_string(index=False))
# reverse
rev=d[(d.ppa<d.ppa.median())&(d.m1_min>=80)].sort_values("m1_min",ascending=False)
print("\nlow ppa but secure minutes (M1>=80):",len(rev))
# validation on Saturday teams
g=gw7(s2c,c2f); sat_teams=set()
act={}
for fid,r in g.items():
    for team,player,grid in r["starters_list"]:
        fp=c2f.get(s2c.get(str(player))); 
        if fp: act[fp]=1; sat_teams.add(EL[fp]["team"] if fp in EL else None)
v=d[d.team.isin(sat_teams)].copy(); v["actual"]=v.fpl_id.map(lambda i:1 if i in act else 0)
v["naive"]=v.last3_starts/3
from math import sqrt
br=lambda p:((v.actual-p)**2).mean()
print("\nSaturday validation: players",len(v),"started",v.actual.sum())
print("Brier M1 %.3f | naive (starts last 3 of 3) %.3f | base rate %.3f"%(br(v.m1_start),br(v.naive),br(v.actual.mean())))
# disagreements >0.3
dis=v[(v.m1_start-v.naive).abs()>=0.34]
print("M1 vs naive disagree >=0.34:",len(dis),"-> M1 closer:",((dis.actual-dis.m1_start).abs()<(dis.actual-dis.naive).abs()).sum())
d.to_pickle("q5.pkl")

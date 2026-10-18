from common import *
import numpy as np
a,lu,cal,c2f,s2c,s2t = all_starts()
now=pd.Timestamp.now(tz="UTC")
cal["finished"]=cal.state.isin(["FT","AET","FT_PEN"])
def team_matches(team):
    c=cal[(cal.team==team)&cal.finished&(cal.kick<now)].sort_values("kick")
    return c
ids=sorted(set(a.fpl_id))
# full set of players with any FPL minutes: use all with >=1 start in SM data, plus all bootstrap players with minutes>=200
cand=[i for i,e in EL.items() if e["minutes"]>=150]
rows=[]
for fid in cand:
    e=EL[fid]; h=history(fid)
    h=h.assign(kt=pd.to_datetime(h.kickoff_time,utc=True))
    h=h[(h.kt<now)&h.team_h_score.notna()].sort_values("kt")
    # one row per finished fixture (doubles keep both)
    k=len(h)
    if k<6: continue
    prev,last=h.iloc[:k-3],h.iloc[k-3:]
    ps=(prev.starts>0).mean(); ls=(last.starts>0).mean()
    rows.append(dict(fpl_id=fid,name=e["web_name"],club=TEAM[e["team"]]["short_name"],pos=POS[e["element_type"]],k=k,n_prev=len(prev),n_last=3,
        starts_prev=int((prev.starts>0).sum()),starts_last=int((last.starts>0).sum()),
        min_prev=prev.minutes.mean(),min_last=last.minutes.mean(),
        mps_prev=prev[prev.starts>0].minutes.mean(),mps_last=last[last.starts>0].minutes.mean() if (last.starts>0).any() else np.nan,
        mins_last_seq=" ".join(map(str,last.minutes)),mins_prev_seq=" ".join(map(str,prev.minutes)),
        last_dates=list(last.kt), status=e["status"],news=e["news"],form=e["form"],pts=e["total_points"]))
d=pd.DataFrame(rows)
reg=d[(d.starts_prev/d.n_prev>=0.75)]
lose=reg[(reg.starts_last<=1)|((reg.min_prev-reg.min_last)>=30)].copy()
lose["drop"]=lose.min_prev-lose.min_last
print(len(d),"players k>=6;",len(reg),"regulars (>=75% starts in prev window);",len(lose),"losing")
pd.set_option("display.width",250)
print(lose.sort_values("drop",ascending=False)[["name","club","pos","n_prev","starts_prev","starts_last","min_prev","min_last","mins_prev_seq","mins_last_seq","status","news"]].round(0).to_string(index=False))
d.to_pickle("q4.pkl")

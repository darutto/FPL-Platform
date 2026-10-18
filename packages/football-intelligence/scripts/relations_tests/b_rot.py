from g_check import *
import numpy as np
a,lu,cal,c2f,s2c,s2t,movers=verified_starts()
now=pd.Timestamp.now(tz="UTC")
c=cal[cal.kick<now-pd.Timedelta(hours=3)].sort_values(["team","kick"])
EURO=["Champions League","Europa League","Europa Conference League","UEFA Super Cup"]
# FPL minutes tell us who played (subs included) for "regulars missing" robustness is not needed here: XI-based.
rows=[]
for team,g in a.groupby("team"):
    ks=sorted(g.kick.unique()); cc=c[c.team==team]
    for m in range(3,len(ks)):
        km,kp=ks[m],ks[m-1]
        prior=ks[max(0,m-4):m]                    # regulars fixed BEFORE the match: only matches before it
        cnt=g[g.kick.isin(prior)].groupby("fpl_id").size()
        regs=set(cnt[cnt>=0.75*len(prior)].index)  # >=75% of the up-to-4 previous starts
        if len(regs)<7: continue
        xi=set(g[g.kick==km].fpl_id)
        gap=(km-kp).total_seconds()/86400
        between=cc[(cc.kick>kp)&(cc.kick<km)&(cc.comp!="Premier League")]
        euro=between[between.comp.isin(EURO)]; cup=between[between.comp=="Carabao Cup"]
        bucket="despues_de_Europa" if len(euro) else ("despues_de_copa" if len(cup) else ("tras_parón" if gap>12 else "solo_liga"))
        rows.append(dict(team=team,club=TEAM[team]["short_name"],km=km,gap=round(gap,1),bucket=bucket,n_regs=len(regs),kept=len(regs&xi),
            retention=len(regs&xi)/len(regs),missing=len(regs-xi),regs_known_before=(max(prior)<km)))
R=pd.DataFrame(rows)
print(len(R),"team-matches;",R.bucket.value_counts().to_dict())
print(R.groupby("bucket").agg(n=("retention","size"),teams=("team","nunique"),regs=("n_regs","mean"),retention=("retention","mean"),missing=("missing","mean")).round(2))
# within-team comparison: each team's Europe/cup matches vs its own league-only matches (excluding after the break)
base=R[R.bucket=="solo_liga"].groupby("team").retention.agg(["mean","size"]).rename(columns={"mean":"base","size":"n_base"})
for b in ("despues_de_Europa","despues_de_copa"):
    t=R[R.bucket==b].groupby("team").retention.agg(["mean","size"]).rename(columns={"mean":"b","size":"n_b"}).join(base,how="inner")
    t["diff"]=t.b-t.base
    print("\n",b,"vs the same team's league-only matches: teams",len(t),"| mean diff %.3f | teams lower:"%t["diff"].mean(),(t["diff"]<0).sum(),"higher:",(t["diff"]>0).sum(),"equal:",(t["diff"]==0).sum(),"| n matches",int(t.n_b.sum()),"vs",int(t.n_base.sum()))
    print(t.assign(club=[TEAM[i]["short_name"] for i in t.index]).sort_values("diff")[["club","n_b","b","n_base","base","diff"]].round(2).to_string(index=False))
R.to_pickle("b_rot.pkl")

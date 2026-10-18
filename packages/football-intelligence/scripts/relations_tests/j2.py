from common import *
import numpy as np, collections
a,lu,cal,c2f,s2c,s2t = all_starts()
a=a[a.role.notna()].copy(); a["rk"]=a.apply(lambda r:f"{r.role}/{r.flank}",axis=1)
J=pd.read_pickle("j1.pkl")
print("first fill in the SAME match as the first absence:",(J.t0==J.first_fill).sum(),"of",len(J))
print("absence already known (previous match) before the deadline of the fill GW:",J.absence_known_before_deadline.sum())
print("sub kept starting every later match:",(J.starts_after==J.n_after).sum(),"of",len(J),"| kept the SAME slot every time:",(J.kept_slot==J.n_after).sum())
print(J.groupby("cause").agg(n=("sub","size"),kept_all=("kept_slot",lambda s:0)).n.to_dict())
J["kept_all"]=(J.kept_slot==J.n_after)
print(J.groupby("cause").kept_all.agg(["sum","size"]))
# ---- entrants over the league
DL=[(e["id"],pd.Timestamp(e["deadline_time"])) for e in BS["events"]]
def deadline_for(k): return min([d for g,d in DL if d>k] or [pd.Timestamp("2099-01-01",tz="UTC")])
rows=[]
for team,g in a.groupby("team"):
    ks=sorted(g.kick.unique())
    for m in range(4,len(ks)):
        km,kp=ks[m],ks[m-1]; hist3=ks[m-4:m-1]
        gp=g[g.kick.isin(hist3)]; cnt=gp.groupby("fpl_id").size()
        last=g[g.kick==kp]
        regs=cnt[cnt>=2].index
        absent_prev=[p for p in regs if p not in set(last.fpl_id)]
        slot_of={p:gp[gp.fpl_id==p].rk.value_counts().index[0] for p in absent_prev}
        form_of={p:gp[gp.fpl_id==p].formation.iloc[-1] for p in absent_prev}
        for r in last.itertuples():
            if cnt.get(r.fpl_id,0)<=1:
                explained=any(slot_of[p]==r.rk and form_of[p]==r.formation for p in absent_prev)
                startsm=((g.kick==km)&(g.fpl_id==r.fpl_id)).any()
                hh=history(int(r.fpl_id)); own=None
                x=hh[(pd.to_datetime(hh.kickoff_time,utc=True)<=kp)].tail(1)
                own=float(x.selected.iloc[0])/BS["total_players"]*100 if len(x) else None
                rows.append(dict(fpl_id=r.fpl_id,name=r.name,club=TEAM[team]["short_name"],m=km,explained=explained,starts_next=startsm,own=own,
                    prev_known=(kp+pd.Timedelta(hours=2))<deadline_for(kp+pd.Timedelta(hours=2)) , pre_deadline=(kp+pd.Timedelta(hours=2))<deadline_for(km-pd.Timedelta(days=3))))
E=pd.DataFrame(rows)
E["low_own"]=E.own<5
print("\nentrants:",len(E))
print(E.groupby("explained").starts_next.agg(["sum","size","mean"]).round(2))
print("FPL-only rule (low ownership & starts rose = all entrants with own<5%):",E[E.low_own].starts_next.agg(["sum","size","mean"]).round(2).to_dict())
print(E[E.low_own].groupby("explained").starts_next.agg(["sum","size","mean"]).round(2))
# surprise starters next: of players who start match m with <=1 start in prior 3 (true surprises), how many were flagged at m-1 by each rule
print("not-yet-entrants (never started m-1) who surprise-start m: cannot be flagged by either rule from lineups")
E.to_pickle("j2.pkl")

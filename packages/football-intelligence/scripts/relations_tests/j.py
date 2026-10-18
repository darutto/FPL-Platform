from common import *
import numpy as np, collections
a,lu,cal,c2f,s2c,s2t = all_starts()
a=a[a.role.notna()].copy(); a["rk"]=a.apply(lambda r:f"{r.role}/{r.flank}",axis=1)
O=pd.read_pickle("q8.pkl")
O=O[O.same_slot&(O.pre_starts<=1)&(O.post_starts/O.npost>=0.67)].copy()
DL=[(e["id"],pd.Timestamp(e["deadline_time"])) for e in BS["events"]]
def gw_of(k): return max([g for g,d in DL if d<=k] or [1])
def next_deadline(k): return min([d for g,d in DL if d>k])
st=json.load(open(TO/"sidelined/state.json",encoding='utf-8'))["rows"]
side=collections.defaultdict(list)
for r in st.values():
    fp=c2f.get(s2c.get(str(r["player_id"])))
    if fp: side[fp].append(r)
# FPL history for absentee: minutes in missed matches
H={}
def hist(i):
    if i not in H:
        h=history(i).assign(kt=lambda x:pd.to_datetime(x.kickoff_time,utc=True)); H[i]=h
    return H[i]
rows=[]
for r in O.itertuples():
    ga=a[a.fpl_id==r.dropped_id].sort_values("kick"); gs=a[a.fpl_id==r.q].sort_values("kick")
    T=EL[r.q]["team"]; tk=sorted(a[a.team==T].kick.unique())
    hd=hist(r.dropped_id); hd=hd[(hd.kt<pd.Timestamp.now(tz="UTC")-pd.Timedelta(hours=3))&hd.team_h_score.notna()].sort_values("kt")
    t0=hd.kt.iloc[r.j-1]                      # first missed (not started) match of the absentee
    prior=ga[ga.kick<t0].tail(3)
    if len(prior)<2: continue
    slot=prior.rk.value_counts().index[0]; form=prior.formation.iloc[-1]
    subs=gs[gs.kick>=t0-pd.Timedelta(hours=6)]
    fill=subs[(subs.rk==slot)]
    fill_same=fill[fill.formation==form]
    first=fill_same.iloc[0] if len(fill_same) else None
    first_any=fill.iloc[0] if len(fill) else None
    if first is None and first_any is None: continue
    ref=first if first is not None else first_any
    # after first fill: matches where absentee still not starting; did sub start & same slot?
    after=[k for k in tk if k>=ref.kick]
    sub_started=[(k in set(subs.kick)) for k in after]
    kept=sum(1 for k in after if k in set(subs[subs.rk==slot].kick))
    # cause
    sl=[x for x in side.get(r.dropped_id,[]) if x["category"]=="injury" or x["category"]=="suspended"]
    miss=hd[(hd.kt>=t0-pd.Timedelta(hours=6))]
    appeared_as_sub=bool(((miss.minutes>0)&(miss.starts==0)).any())
    cover=[x for x in sl if x["start_date"]<=str(t0.date()) and (x["end_date"] is None or x["end_date"]>=str(t0.date()))]
    cause=("lesion/sancion registrada" if cover else ("decision tecnica (entra de suplente)" if appeared_as_sub else ("desconocida (registro posterior)" if sl else "desconocida")))
    gwf=gw_of(ref.kick); dl=next_deadline(ref.kick)  # deadline of the GW containing/after
    dl_for_gw=[d for g,d in DL if g==gwf][0]
    prev_info=[k for k in tk if k+pd.Timedelta(hours=2)<dl_for_gw]  # matches whose result was out before the deadline of the fill GW
    t0_before_deadline = (t0+pd.Timedelta(hours=2))<dl_for_gw
    rows.append(dict(absentee=r.dropped,sub=r.gainer,club=r.dclub,slot=slot,form_abs=form,form_fill=ref.formation,same_formation=first is not None,
        t0=t0,first_fill=ref.kick,gw=gwf,deadline=dl_for_gw,absence_known_before_deadline=t0_before_deadline,
        n_after=len(after),starts_after=sum(sub_started),kept_slot=kept,cause=cause,
        sub_own=float(hist(r.q)[hist(r.q).kt<=ref.kick].tail(1).selected.iloc[0])/BS["total_players"]*100 if len(hist(r.q)) else None,
        sub_starts_prev3=int(len(gs[(gs.kick<t0)].tail(3)))))
J=pd.DataFrame(rows)
pd.set_option("display.width",260)
print(len(O),"candidate pairs ->",len(J),"with a fill;",J.same_formation.sum(),"same formation;",(~J.same_formation).sum(),"formation mismatch")
print(J[["absentee","sub","club","slot","form_abs","form_fill","same_formation","t0","first_fill","gw","absence_known_before_deadline","n_after","starts_after","kept_slot","cause","sub_own"]].round(1).to_string(index=False))
J.to_pickle("j1.pkl")

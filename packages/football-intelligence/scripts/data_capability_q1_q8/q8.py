from common import *
import numpy as np
a,lu,cal,c2f,s2c,s2t = all_starts()
a=a[a.role.notna()].copy(); a["rk"]=a.apply(lambda r:f"{r.role}/{r.flank}",axis=1)
now=pd.Timestamp.now(tz="UTC")
H={}
def hist(i):
    if i not in H:
        h=history(i).assign(kt=lambda x:pd.to_datetime(x.kickoff_time,utc=True)); H[i]=h[(h.kt<now-pd.Timedelta(hours=3))&h.team_h_score.notna()].sort_values("kt").reset_index(drop=True)
    return H[i]
d4=pd.read_pickle("q4.pkl")
reg=d4[(d4.starts_prev/d4.n_prev>=0.75)&(d4.starts_last<=1)]   # regulars who lost the XI
squads={}
for i,e in EL.items(): squads.setdefault(e["team"],[]).append(i)
out=[]
for r in reg.itertuples():
    h=hist(r.fpl_id); k=len(h); T=EL[r.fpl_id]["team"]
    # first match index with start==0 followed by <=1 start in the rest, and >=2 matches from there
    j=None
    for x in range(1,k-1):
        if h.starts.iloc[x]==0 and h.starts.iloc[x:].sum()<=1 and h.starts.iloc[:x].sum()>=max(1,x-1):
            j=x; break
    if j is None: continue
    kts=h.kt.tolist()
    for q in squads[T]:
        if q==r.fpl_id: continue
        hq=hist(q); 
        if hq.minutes.sum()<1: continue
        m=hq.set_index("kt").reindex(kts)  # align on team kickoffs
        mins=m.minutes.fillna(0).values; st=(m.starts.fillna(0).values>0)
        pre=slice(max(0,j-3),j); post=slice(j,k)
        npre=len(range(*pre.indices(k))); npost=k-j
        if npre<2 or npost<2: continue
        pr,po=st[pre].mean(),st[post].mean(); dm=mins[post].mean()-mins[pre].mean()
        if (po>=0.67 and pr<=0.34) or dm>=35:
            out.append(dict(dropped=r.name,dclub=r.club,dpos=r.pos,j=j+1,k=k,dstarts_after=int(h.starts.iloc[j:].sum()),gainer=EL[q]["web_name"],gpos=POS[EL[q]["element_type"]],
                pre_starts=int(st[pre].sum()),npre=npre,post_starts=int(st[post].sum()),npost=npost,pre_min=round(mins[pre].mean()),post_min=round(mins[post].mean()),dm=round(dm),
                status=EL[q]["status"],q=q,dropped_id=r.fpl_id,dnews=EL[r.fpl_id]["news"][:40]))
O=pd.DataFrame(out)
pd.set_option("display.width",250)
print(len(reg),"regulars who lost the XI;",O.dropped.nunique(),"with >=1 gainer;",len(O),"gainer rows")
# slot check: gainer's slot in post matches vs dropped's usual slot
def modal(i,before=None,after=None):
    g=a[a.fpl_id==i]
    return g.rk.value_counts().index[0] if len(g) else None
res=[]
for r in O.itertuples():
    gd=a[a.fpl_id==r.dropped_id].sort_values("kick"); ds=gd.head(max(1,r.j-1)).rk.value_counts().index[0] if len(gd) else None
    gg=a[(a.fpl_id==r.q)&(a.kick>pd.Timestamp(H[r.dropped_id].kt.iloc[r.j-1]) - pd.Timedelta(hours=1))].sort_values("kick")
    gs=gg.rk.value_counts().index[0] if len(gg) else None
    res.append((ds,gs,len(gg)))
O["dropped_slot"]=[x[0] for x in res]; O["gainer_slot"]=[x[1] for x in res]; O["g_sm_starts"]=[x[2] for x in res]
O["same_slot"]=O.dropped_slot==O.gainer_slot
print(O.sort_values(["dropped","dm"],ascending=[True,False])[["dropped","dclub","dstarts_after","k","j","gainer","gpos","pre_starts","npre","post_starts","npost","pre_min","post_min","dm","dropped_slot","gainer_slot","dnews"]].to_string(index=False))
O.to_pickle("q8.pkl")

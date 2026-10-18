from common import *
import numpy as np
a,lu,cal,c2f,s2c,s2t = all_starts()
a=a[a.role.notna()].copy()
t2=pd.read_pickle("q2.pkl")
def windows(fid):
    g=a[a.fpl_id==fid].sort_values("kick"); last=g.tail(3); prev=g.iloc[max(0,len(g)-7):len(g)-3]
    h=history(int(fid)); h=h.assign(kt=pd.to_datetime(h.kickoff_time,utc=True)); out={}
    for nm,w in (("prev",prev),("last",last)):
        # match starts to history rows by kickoff date (same team, same day)
        rows=[]
        for k in w.kick:
            m=h[(h.kt-k).abs()<pd.Timedelta(hours=6)]; rows.append(m)
        hh=pd.concat(rows) if rows else h.iloc[0:0]
        mins=hh.minutes.sum()
        f=lambda c:(hh[c].astype(float).sum()/mins*90) if mins else np.nan
        out[nm]=dict(n=len(w),mins=mins,xg90=f("expected_goals"),xa90=f("expected_assists"),xgi90=f("expected_goal_involvements"),threat90=f("threat"),creat90=f("creativity"))
    return out
rows=[]
for r in t2.itertuples():
    w=windows(r.fpl_id)
    rows.append(dict(fpl_id=r.fpl_id,name=r.name,club=r.club,changed=r.changed,
        **{f"{k}_{nm}":w[nm][k] for nm in("prev","last") for k in w[nm]}))
d=pd.DataFrame(rows)
for m in ("xgi90","threat90","creat90"): d["d_"+m]=d[m+"_last"]-d[m+"_prev"]
ctrl=d[~d.changed]
print("control n",len(ctrl),"delta xGI/90 median %.3f IQR [%.3f,%.3f]"%(ctrl.d_xgi90.median(),*ctrl.d_xgi90.quantile([.25,.75])),
      "| threat90 median %.1f IQR [%.1f,%.1f]"%(ctrl.d_threat90.median(),*ctrl.d_threat90.quantile([.25,.75])))
pd.set_option("display.width",250)
ch=d[d.changed].copy()
# percentile of each changed delta within control
for m in ("xgi90","threat90"):
    ch["pct_"+m]=ch["d_"+m].map(lambda v:(ctrl["d_"+m]<v).mean()*100)
print(ch[["name","club","mins_prev","mins_last","xgi90_prev","xgi90_last","d_xgi90","pct_xgi90","threat90_prev","threat90_last","d_threat90","pct_threat90"]].round(2).to_string(index=False))
d.to_pickle("q3.pkl")

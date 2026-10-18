from common import *
import collections
a,lu,cal,c2f,s2c,s2t = all_starts()
st=json.load(open(TO/"sidelined/state.json",encoding='utf-8'))
rows=st["rows"]; print(len(rows), st["at"], collections.Counter(r["category"] for r in rows.values()))
side=collections.defaultdict(list)
for r in rows.values():
    fp=c2f.get(s2c.get(str(r["player_id"])))
    if fp: side[fp].append(r)
print("sidelined players mapped to FPL:",len(side))
a=a[a.role.notna()].copy(); a["rk"]=a.apply(lambda r:f"{r.role}/{r.flank}",axis=1)
res=[]; base=[]
for team,g in a.groupby("team"):
    ms=sorted(g.kick.unique())
    for j in range(4,len(ms)):
        cur=ms[j]; prior=ms[max(0,j-4):j]
        gp=g[g.kick.isin(prior)]
        starts=gp.groupby("fpl_id").size(); regular=set(starts[starts>=3].index)  # >=3 of last 4 PL matches
        cx=set(g[g.kick==cur].fpl_id)
        absent=[p for p in regular if p not in cx]
        # absentee must not have appeared at all? use lineups minutes
        if cur<pd.Timestamp("2026-10-16",tz="UTC"):
            played=set(lu[(lu.team==team)&(lu.kick==cur)&(lu.minutes>0)].fpl_id)   # Sportmonks lineup minutes
        else:  # GW7 Saturday: Sportmonks has only the XI; use FPL minutes so a sub is not "absent"
            played=set(cx)
            for p in absent:
                hh=history(int(p)); hh=hh.assign(kt=pd.to_datetime(hh.kickoff_time,utc=True))
                if hh[((hh.kt-cur).abs()<pd.Timedelta(hours=6))].minutes.sum()>0: played.add(p)
        absent=[p for p in absent if p not in played]
        # teammates who started cur AND have >=3 prior starts: role change vs modal of prior starts
        changed=[]
        for p in cx:
            pr=gp[gp.fpl_id==p].sort_values("kick").tail(3)
            if len(pr)<3: continue
            modal=pr.rk.value_counts().index[0]
            now_rk=g[(g.kick==cur)&(g.fpl_id==p)].rk.iloc[0]
            if now_rk!=modal: changed.append((p,modal,now_rk))
        elig=sum(1 for p in cx if len(gp[gp.fpl_id==p])>=3)
        res.append(dict(team=team,club=TEAM[team]["short_name"],cur=cur,absent=absent,changed=changed,elig=elig,
            formation_changed=(g[g.kick==cur].formation.iloc[0]!=g[g.kick==ms[j-1]].formation.iloc[0])))
R=pd.DataFrame(res)
R["has_abs"]=R.absent.map(len)>0
R["n_changed"]=R.changed.map(len)
print(len(R),"team-matches;",R.has_abs.sum(),"with a regular absent")
print(R.groupby(["has_abs"]).agg(n=("n_changed","size"),mean_changed=("n_changed","mean"),mean_elig=("elig","mean")).round(2))
print(R.groupby(["has_abs","formation_changed"]).agg(n=("n_changed","size"),mean_changed=("n_changed","mean")).round(2))
nm=lambda i:EL[i]["web_name"]
pd.set_option("display.width",250)
for r in R[R.has_abs&(R.n_changed>0)].sort_values("cur").itertuples():
    sd=[ (nm(p), side[p][0]["category"] if p in side else "-") for p in r.absent]
    print(f"{r.club} {r.cur:%d-%b} formchg={r.formation_changed}: absent {sd} | changed: "+"; ".join(f"{nm(p)} {m}->{n}" for p,m,n in r.changed))
R.to_pickle("q7.pkl")

print("\n---- slot-fill check")
fill=[]
for r in R[R.has_abs&(R.n_changed>0)].itertuples():
    g=a[a.team==r.team]
    for p in r.absent:
        pr=g[(g.fpl_id==p)&(g.kick<r.cur)].sort_values("kick").tail(3)
        if len(pr)<3: continue
        slot=pr.rk.value_counts().index[0]
        for q,m,n in r.changed:
            if n==slot:
                fill.append((r.club,r.cur,nm(p),side[p][0]["category"] if p in side else "-",slot,nm(q),m,len(pr)))
for f in fill: print(f"{f[0]} {f[1]:%d-%b}: {f[2]} (absent, sidelined={f[3]}, usual slot {f[4]}, n={f[7]}) -> {f[5]} moves {f[6]} -> {f[4]}")

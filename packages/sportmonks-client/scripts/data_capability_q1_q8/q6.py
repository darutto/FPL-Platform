from common import *
a,lu,cal,c2f,s2c,s2t = all_starts()
now=pd.Timestamp.now(tz="UTC")
c=cal[cal.kick<now-pd.Timedelta(hours=3)].sort_values(["team","kick"])
EURO=["Champions League","Europa League","Europa Conference League","UEFA Super Cup"]
rows=[]; moves=[]
for team,g in a.groupby("team"):
    ms=sorted(g.kick.unique())
    cc=c[c.team==team]
    for prev,cur in zip(ms[:-1],ms[1:]):
        px=set(g[g.kick==prev].fpl_id); cx=set(g[g.kick==cur].fpl_id)
        between=cc[(cc.kick>prev)&(cc.kick<cur)&(cc.comp!="Premier League")]
        euro=between[between.comp.isin(EURO)]; cup=between[between.comp=="Carabao Cup"]
        before=cc[cc.kick<cur]; last=before.iloc[-1] if len(before) else None
        rest=(cur-last.kick).total_seconds()/86400 if last is not None else None
        kind="Europe" if len(euro) else ("Carabao" if len(cup) else "league only")
        rows.append(dict(team=team,club=TEAM[team]["short_name"],cur=cur,changes=len(px-cx),n_prev=len(px),n_cur=len(cx),kind=kind,
            rest=round(rest,1) if rest else None,euro_comp=",".join(euro.comp.str[:3]) if len(euro) else "",
            out=sorted(px-cx),inn=sorted(cx-px)))
R=pd.DataFrame(rows)
R=R[(R.n_prev==11)&(R.n_cur==11)]
print(len(R),"consecutive-match pairs")
print(R.groupby("kind").agg(pairs=("changes","size"),mean_changes=("changes","mean"),median=("changes","median"),max=("changes","max")).round(2))
# break confound: pair spanning int'l break (gap > 12 days)
R["gap"]=R.apply(lambda r:(r.cur-max(a[(a.team==r.team)&(a.kick<r.cur)].kick)).days,axis=1)
print("by kind, excluding pairs after the >12d break:")
x=R[R.gap<=12]; print(x.groupby("kind").agg(pairs=("changes","size"),mean_changes=("changes","mean"),median=("changes","median")).round(2))
# euro clubs: league only vs Europe pairs
EU=["ARS","MUN","LIV","AVL","MCI","CRY","SUN","BOU","BHA"]
y=x[x.club.isin(EU)]; print("European clubs only, gap<=12d:"); print(y.groupby("kind").agg(pairs=("changes","size"),mean_changes=("changes","mean")).round(2))
pd.set_option("display.width",250)
print(R[(R.kind=="Europe")].sort_values("changes",ascending=False)[["club","cur","euro_comp","rest","gap","changes"]].to_string(index=False))
R.to_pickle("q6.pkl")

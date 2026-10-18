from common import *
a,lu,cal,c2f,s2c,s2t = all_starts()
a=a[a.role.notna()].copy()
def key(r): return f"{r.role}/{r.flank}" if r.role not in("goalkeeper",) else "goalkeeper"
a["rk"]=a.apply(key,axis=1)
rows=[]
for fid,g in a.groupby("fpl_id"):
    g=g.sort_values("kick")
    if len(g)<6: continue
    last=g.tail(3); prev=g.iloc[max(0,len(g)-7):len(g)-3]
    def modal(x): vc=x.rk.value_counts(); return vc.index[0], vc.iloc[0]/len(x)
    (lm,ls),(pm,ps)=modal(last),modal(prev)
    rows.append(dict(fpl_id=fid,name=g.name.iloc[-1],club=TEAM[g.team.iloc[-1]]["short_name"],fpos=g.fpos.iloc[-1],n_last=len(last),n_prev=len(prev),
        prev=pm,prev_share=round(ps,2),last=lm,last_share=round(ls,2),last_seq=" > ".join(last.rk),prev_seq=" > ".join(prev.rk),
        last_depth=",".join(last.depth), changed=(lm!=pm)))
t=pd.DataFrame(rows); print(len(t),"players with >=6 starts;",t.changed.sum(),"changed")
ch=t[t.changed].copy()
print(ch.groupby("club").size().sort_values(ascending=False).to_dict())
pd.set_option("display.width",250)
print(ch[["name","club","fpos","n_prev","prev","prev_share","n_last","last","last_share","last_seq"]].to_string(index=False))
t.to_pickle("q2.pkl")
# team formation per match (last 7)
tf=a.groupby(["team","kick"]).formation.first().reset_index()
print(tf.groupby("team").formation.agg(lambda s:" ".join(s.map(lambda x:x[:5]).tolist()[-7:])).rename(lambda x:TEAM[x]["short_name"]).to_string())

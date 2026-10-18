from common import *
a,lu,cal,c2f,s2c,s2t = all_starts()
def cat(r):
    dp=r.detailed_position; f=r.formation
    if dp=="Centre Back": return "CB"
    if dp in("Left Back","Right Back"): return "FB"
    if dp in("Left Midfield","Right Midfield"): return "WB(back3)" if f in("3-4-2-1","3-5-2") else "WideMid"
    if dp in("Central Midfield","Defensive Midfield"): return "CM"
    if dp=="Attacking Midfield": return "AM"
    if dp=="Attacker": return "ST"
    return dp
a["cat"]=a.apply(cat,axis=1)
d=a[a.fpos=="DEF"]
t=d.groupby(["fpl_id","name","team"]).cat.value_counts().unstack(fill_value=0)
for c in ("CB","FB","WB(back3)","WideMid","CM","AM","ST"):
    if c not in t: t[c]=0
t["n"]=t[["CB","FB","WB(back3)","WideMid","CM","AM","ST"]].sum(axis=1)
t["adv"]=t[["WB(back3)","WideMid","CM","AM","ST"]].sum(axis=1)
t["adv_share"]=(t.adv/t.n).round(2)
t=t.reset_index(); t["club"]=t.team.map(lambda x:TEAM[x]["short_name"])
print("DEF starters:",len(t), " with >=1 non-CB/FB start:",(t.adv>0).sum())
print(t[t.adv>0].sort_values(["adv","adv_share"],ascending=False)[["name","club","n","CB","FB","WB(back3)","WideMid","CM","AM","adv","adv_share"]].to_string(index=False))
print(d.cat.value_counts().to_dict())
# context: formations per club of those
print(a.groupby(["team"]).formation.agg(lambda s: s.value_counts().to_dict()).rename(lambda x:TEAM[x]["short_name"]).to_string())

print("-----FPL view")
def per90(fid):
    h=history(int(fid)); h=h[h["round"]<=7]; m=h.minutes.sum()
    return pd.Series(dict(min=m, xgi90=(h.expected_goal_involvements.astype(float).sum()/m*90) if m else None,
        threat90=(h.threat.astype(float).sum()/m*90) if m else None, dc90=(h.defensive_contribution.sum()/m*90) if m else None,
        pts=h.total_points.sum()))
t["grp"]=t.apply(lambda r: "stable_adv" if (r.adv>=3 and r.adv_share>=0.5) else ("one_off" if r.adv>0 else "back_line"),axis=1)
f=t.set_index("fpl_id") if "fpl_id" in t else None
t2=t.copy()
ids=t2.index

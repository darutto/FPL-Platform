from common import *
a,lu,cal,c2f,s2c,s2t = all_starts()
now=pd.Timestamp.now(tz="UTC")
short={t["id"]:t["short_name"] for t in BS["teams"]}
def fid(web,club): 
    c=[i for i,e in EL.items() if e["web_name"]==web and short[e["team"]]==club]; assert len(c)==1,c; return c[0]
def audit(web,club,watch=None):
    i=fid(web,club); team=EL[i]["team"]
    h=history(i).assign(kt=lambda x:pd.to_datetime(x.kickoff_time,utc=True)); h=h[(h.kt<now-pd.Timedelta(hours=3))&h.team_h_score.notna()]
    g=a[a.fpl_id==i]
    c=cal[(cal.team==team)&(cal.kick>pd.Timestamp("2026-08-15",tz="UTC"))&(cal.kick<now-pd.Timedelta(hours=3))].sort_values("kick")
    tm=a[a.team==team]
    rows=[]
    for r in c.itertuples():
        row=dict(date=r.kick.strftime("%d-%b"),comp={"Premier League":"PL","Carabao Cup":"EFL","Champions League":"UCL","Europa League":"UEL","Europa Conference League":"UECL","UEFA Super Cup":"SC"}.get(r.comp,r.comp),opp=r.opp_name[:14],v=r.venue)
        if r.comp=="Premier League":
            m=h[(h.kt-r.kick).abs()<pd.Timedelta(hours=6)]
            s=g[(g.kick-r.kick).abs()<pd.Timedelta(hours=6)]
            if len(m):
                mm=m.iloc[0]; row.update(gw=int(mm["round"]),min=int(mm.minutes),start=int(mm.starts),xG=float(mm.expected_goals),xA=float(mm.expected_assists),pts=int(mm.total_points))
            if len(s): row.update(form=s.formation.iloc[0],slot=s.detailed_position.iloc[0],role=f"{s.role.iloc[0]}/{s.flank.iloc[0]}")
            if watch:
                xi=tm[(tm.kick-r.kick).abs()<pd.Timedelta(hours=6)]
                row["watch"]="; ".join(f"{EL[p]['web_name']}{'+' if p in set(xi.fpl_id) else '-'}" for p in watch)
        else: row.update(note="sin alineacion en la captura")
        rows.append(row)
    return pd.DataFrame(rows)
pd.set_option("display.width",250); pd.set_option("display.max_columns",30)
if __name__=="__main__":
    ded=fid("Dedić","NEW") if any(e["web_name"]=="Dedić" and short[e["team"]]=="NEW" for e in EL.values()) else None
    out={}
    for web,club,watch in (("L.Miley","NEW",[ded] if ded else None),("Iwobi","FUL",None),("Kamada","CRY",None)):
        d=audit(web,club,watch); out[web]=d; print("=====",web,club); print(d.to_string(index=False))
    pd.to_pickle(out,"a_audit.pkl")

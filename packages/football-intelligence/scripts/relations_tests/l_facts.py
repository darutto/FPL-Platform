from common import *
import collections
CUT = pd.Timestamp("2026-10-17T10:00:00Z")   # GW7 deadline: only what was public before it
PLAYERS = [("De Cuyper","BHA"),("Iwobi","FUL"),("L.Miley","NEW"),("Barcola","LIV"),("Matheus N.","MCI")]
a,lu,cal,c2f,s2c,s2t = all_starts()
a=a[a.kick<CUT].copy(); a["rk"]=a.apply(lambda r:f"{r.role}/{r.flank}" if r.role else None,axis=1)
fix=fpl_get("fixtures")
short={t["id"]:t["short_name"] for t in BS["teams"]}
def find(web,club):
    c=[i for i,e in EL.items() if e["web_name"]==web and short[e["team"]]==club]; assert len(c)==1,(web,club,c); return c[0]
ES={"center_back":"central","full_back":"lateral","winger":"extremo","central_midfield":"centrocampista central","attacking_midfield":"mediapunta","forward":"delantero","goalkeeper":"portero"}
FL={"left":"izquierda","right":"derecha","center":"centro"}
def role_es(rk): 
    r,f=rk.split("/"); return f"{ES.get(r,r)} {FL.get(f,f)}".replace(" centro","")
def build_facts(fid):
    e=EL[fid]; team=e["team"]; club=short[team]
    h=history(fid).assign(kt=lambda x:pd.to_datetime(x.kickoff_time,utc=True)); h=h[(h.kt<CUT)&h.team_h_score.notna()].sort_values("kt")
    f1={"jugador":e["web_name"],"club":club,"posicion_fpl":POS[e["element_type"]],"precio":e["now_cost"]/10,"propiedad_pct":float(e["selected_by_percent"]),
        "partidos_liga":[{"jornada":int(r["round"]),"rival":short[r.opponent_team],"sede":"local" if r.was_home else "visitante","minutos":int(r.minutes),
          "titular":bool(r.starts>0),"puntos":int(r.total_points),"goles":int(r.goals_scored),"asistencias":int(r.assists),"xG":float(r.expected_goals),"xA":float(r.expected_assists)} for _,r in h.iterrows()]}
    f1["totales"]={"minutos":int(h.minutes.sum()),"titularidades":int((h.starts>0).sum()),"puntos":int(h.total_points.sum()),"xG":round(float(h.expected_goals.astype(float).sum()),2),"xA":round(float(h.expected_assists.astype(float).sum()),2)}
    nxt=[x for x in fix if x["event"] in (7,8) and team in (x["team_h"],x["team_a"])]
    f1["proximos_partidos_fpl"]=[{"jornada":x["event"],"rival":short[x["team_a"] if x["team_h"]==team else x["team_h"]],"sede":"local" if x["team_h"]==team else "visitante",
        "dificultad_fpl":x["team_h_difficulty"] if x["team_h"]==team else x["team_a_difficulty"],"fecha":x["kickoff_time"]} for x in sorted(nxt,key=lambda x:x["event"])]
    # --- Sportmonks section
    g=a[a.fpl_id==fid].sort_values("kick")
    sm={"partidos":[{"jornada":int(gw),"formacion_equipo":r.formation,"posicion_detallada":r.detailed_position,"rol_banda":role_es(r.rk) if r.rk else None} for gw,(_,r) in zip(range(1,99),g.iterrows())]}
    # use real gameweek numbers from FPL history by kickoff
    rounds={pd.Timestamp(k).floor("h"):int(r) for k,r in zip(h.kt,h["round"])}
    for p,(_,r) in zip(sm["partidos"],g.iterrows()):
        m=h[(h.kt-r.kick).abs()<pd.Timedelta(hours=6)]; p["jornada"]=int(m["round"].iloc[0]) if len(m) else None
    seq=list(g.rk.dropna()); cur=collections.Counter(seq[-3:]).most_common(1)[0][0] if seq else None
    prev=collections.Counter(seq[:-3][-4:]).most_common(1)[0][0] if len(seq)>3 else None
    sm["hueco_ultimos_3"]=role_es(cur) if cur else None; sm["hueco_3_4_anteriores"]=role_es(prev) if prev else None
    # relations: habitual teammates (>=3 of previous 4 team matches) not in the XI in matches where he started in his current slot
    gt=a[a.team==team]; ks=sorted(gt.kick.unique()); rel=[]
    for k in g[g.rk==cur].kick:
        j=ks.index(k)
        if j<4: continue
        prior=gt[gt.kick.isin(ks[j-4:j])].groupby("fpl_id").size(); regs=[p for p in prior[prior>=3].index if p not in set(gt[gt.kick==k].fpl_id)]
        rel.append({"fecha":str(k.date()),"habituales_ausentes_del_once":[EL[p]["web_name"] for p in regs]})
    sm["relaciones_en_partidos_en_su_hueco_actual"]=rel
    # calendar incl. cups/Europe (calendar only)
    c=cal[(cal.team==team)&(cal.kick<CUT)&(cal.kick>pd.Timestamp("2026-08-15",tz="UTC"))&(cal.comp!="Premier League")]
    sm["partidos_copas_europa_equipo"]=[{"fecha":str(r.kick.date()),"competicion":r.comp,"rival":r.opp_name} for r in c.itertuples()]
    return f1,sm
if __name__=="__main__":
    out={}
    for web,club in PLAYERS:
        fid=find(web,club); f1,sm=build_facts(fid); out[web]={"fpl":f1,"sm":sm}
        print(web,club,"matches",len(f1["partidos_liga"]),"| SM slots",sm["hueco_3_4_anteriores"],"->",sm["hueco_ultimos_3"],"| rel",sm["relaciones_en_partidos_en_su_hueco_actual"][:3],"| cups",len(sm["partidos_copas_europa_equipo"]))
    pathlib.Path(TO/"relations").mkdir(exist_ok=True)
    (TO/"relations/l_facts.json").write_text(json.dumps(out,ensure_ascii=False,indent=1),encoding="utf-8")

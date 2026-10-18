"""Reusable check: is each player on the right club ON THE DATE of each match?
Independent sources: (1) FPL fixtures (history.fixture -> team_h/team_a of that fixture gives the team the player was playing for),
(2) Sportmonks squad validity windows. Compared with the club the analysis frame assigns the player in that match."""
from common import *
def fpl_team_on_match(fpl_id, kick):
    fx = {f["id"]: f for f in fpl_get("fixtures")}
    h = history(fpl_id).assign(kt=lambda x: pd.to_datetime(x.kickoff_time, utc=True))
    m = h[(h.kt - kick).abs() < pd.Timedelta(hours=6)]
    if m.empty: return None
    r = m.iloc[0]; f = fx.get(int(r.fixture))
    if f is None: return None
    return f["team_h"] if r.was_home else f["team_a"]
def club_on_date_check(frame, squads=None):
    """frame needs fpl_id, team, kick. Returns mismatches (FPL fixture side or SM squad window disagree with frame.team)."""
    bad = []
    for r in frame.drop_duplicates(["fpl_id", "kick"]).itertuples():
        t_fpl = fpl_team_on_match(int(r.fpl_id), r.kick)
        if t_fpl is not None and t_fpl != r.team:
            bad.append(dict(fpl_id=r.fpl_id, name=EL[r.fpl_id]["web_name"], kick=r.kick, frame_team=TEAM[r.team]["short_name"], fpl_team=TEAM[t_fpl]["short_name"], source="fpl_fixture"))
    return pd.DataFrame(bad)
def squad_window_check(frame, canon_by_fpl, squads, team_canon):
    bad = []
    for r in frame.drop_duplicates(["fpl_id", "kick"]).itertuples():
        pid = canon_by_fpl.get(int(r.fpl_id)); tid = team_canon.get(r.team)
        s = squads[(squads.player_id == pid) & (squads.team_id == tid)]
        ok = any(pd.Timestamp(x.valid_from, tz="UTC") <= r.kick and (pd.isna(x.valid_to) or pd.Timestamp(x.valid_to, tz="UTC") >= r.kick) for x in s.itertuples())
        if not ok: bad.append(dict(fpl_id=r.fpl_id, name=EL[r.fpl_id]["web_name"], kick=r.kick, team=TEAM[r.team]["short_name"], source="sm_squad_window", rows=len(s)))
    return pd.DataFrame(bad)
def verified_starts():
    """all_starts() with the club-on-date check enforced; also returns the set of mid-season movers (fpl_id) so analyses can exclude arrival effects."""
    a, lu, cal, c2f, s2c, s2t = all_starts()
    rows = a[["fpl_id", "team", "kick"]].drop_duplicates()
    bad = club_on_date_check(rows)
    assert bad.empty, f"club-on-date mismatches: {bad.head()}"
    movers = set(rows.groupby("fpl_id").team.nunique().loc[lambda s: s > 1].index)
    return a, lu, cal, c2f, s2c, s2t, movers

if __name__ == "__main__":
    a, lu, cal, c2f, s2c, s2t = all_starts()
    allrows = pd.concat([lu[lu.fpl_id.notna()][["fpl_id", "team", "kick"]], a[["fpl_id", "team", "kick"]]]).drop_duplicates()
    allrows = allrows[allrows.fpl_id.isin(EL.keys())]
    allrows["fpl_id"] = allrows.fpl_id.astype(int)
    print("player-matches checked:", len(allrows), "players:", allrows.fpl_id.nunique())
    b1 = club_on_date_check(allrows); print("FPL-fixture side mismatches:", len(b1)); print(b1.to_string(index=False) if len(b1) else "")
    sq = pd.read_parquet(CANON / "squads.parquet"); idn = pd.read_parquet(DS / "identity/player_identity.parquet"); tid = pd.read_parquet(DS / "identity/team_identity.parquet")
    canon_by_fpl = {int(r.provider_id): r.canonical_player_id for r in idn.itertuples()}
    team_canon = {int(r.provider_id): r.canonical_team_id for r in tid.itertuples()}
    b2 = squad_window_check(allrows, canon_by_fpl, sq, team_canon); print("Sportmonks squad-window mismatches:", len(b2)); print(b2.head(30).to_string(index=False) if len(b2) else "")
    mun = [i for i, e in EL.items() if e["web_name"] == "Muñoz"]; print("Muñoz in bootstrap:", [(i, TEAM[EL[i]["team"]]["short_name"]) for i in mun])
    for i in mun:
        x = allrows[allrows.fpl_id == i].sort_values("kick"); print(i, [(k.strftime("%d-%b"), TEAM[t]["short_name"]) for k, t in zip(x.kick, x.team)])
    pd.to_pickle((b1, b2), "g_out.pkl")

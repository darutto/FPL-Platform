"""The numeric golden's second opinion: answers worked out from ``world.json`` WITHOUT the query engine.

    python oracle.py        (rewrites golden.json)

It must never import ``fpl_grounded_assistant``. Each case is written out by hand with plain loops, so a
mistake in the engine's shared logic cannot also be the expected answer.

Rows are ``[name, value]`` in the order shown: by value, then more minutes, then name. A tie at the tenth
row (or the case's ``top_n``) keeps every tied row up to 15.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
WORLD = json.loads((HERE / "world.json").read_text(encoding="utf-8"))
ELEMENTS = {e["id"]: e for e in WORLD["bootstrap"]["elements"]}
TEAMS = {t["id"]: t for t in WORLD["bootstrap"]["teams"]}
ALL_GWS = list(range(1, 9))
SUBJECT = 106


def stat(pid, gw, key):
    return WORLD["gameweeks"][str(gw)]["rows"].get(str(pid), {}).get(key, 0)


def total(pid, gws, key):
    return round(sum(stat(pid, gw, key) for gw in gws), 6)


def mins(pid, gw, fixture):
    return WORLD["gameweeks"][str(gw)]["fixture_minutes"].get(str(pid), {}).get(str(fixture), 0)


def appearances(pid, gws):
    return sum(len(WORLD["gameweeks"][str(gw)]["fixture_minutes"].get(str(pid), {})) for gw in gws)


def team_matches(team, gws=ALL_GWS):
    out = []
    for gw in gws:
        for f in WORLD["gameweeks"][str(gw)]["fixtures"]:
            if team in (f["team_h"], f["team_a"]):
                home = f["team_h"] == team
                out.append({"gw": gw, "id": f["id"], "home": home, "kickoff": f["kickoff_time"][:10],
                            "opp": f["team_a"] if home else f["team_h"],
                            "gf": f["team_h_score"] if home else f["team_a_score"],
                            "ga": f["team_a_score"] if home else f["team_h_score"],
                            "fdr": f["team_h_difficulty"] if home else f["team_a_difficulty"]})
    return sorted(out, key=lambda m: (m["kickoff"], m["id"]))


def team_xg(match):
    """The commonest xG-conceded among the opponents who played this match, and only it, for 90 minutes."""
    seen = []
    for pid, element in ELEMENTS.items():
        played = WORLD["gameweeks"][str(match["gw"])]["fixture_minutes"].get(str(pid), {})
        if element["team"] == match["opp"] and played == {str(match["id"]): 90}:
            seen.append(stat(pid, match["gw"], "expected_goals_conceded"))
    counts = Counter(seen)
    return max(counts, key=lambda v: (counts[v], v))


def ranked(entries, top_n=10, ascending=False):
    """entries: (name, value, minutes)."""
    entries = [(n, round(v, 6), m) for n, v, m in entries]
    entries.sort(key=lambda e: (e[1] if ascending else -e[1], -e[2], e[0]))
    end = min(top_n, len(entries))
    while end < len(entries) and entries[end][1] == entries[end - 1][1]:
        end += 1
    return [[n, v] for n, v, _ in entries[:min(end, max(top_n, 15))]]


def players(value, gws=ALL_GWS, keep=lambda e: True, floor=0, top_n=10, ascending=False):
    entries = []
    for pid, e in ELEMENTS.items():
        played = total(pid, gws, "minutes")
        if keep(e) and played >= floor:
            v = value(pid)
            if v is not None:
                entries.append((e["web_name"], v, played))
    return {"state": "complete", "rows": ranked(entries, top_n, ascending)}


def teams(value, matches=lambda t: team_matches(t), per_match=False, ascending=False, top_n=10):
    entries = []
    for tid, t in TEAMS.items():
        ms = matches(tid)
        if ms:
            v = sum(value(m) for m in ms)
            entries.append((t["name"], v / len(ms) if per_match else v, 0))
    return {"state": "complete", "rows": ranked(entries, top_n, ascending)}


def side(matches, value):
    values = [round(value(m), 6) for m in matches]
    return {"n": len(values), "total": round(sum(values), 6), "per_match": round(sum(values) / len(values), 6),
            "home": sum(m["home"] for m in matches),
            "mean_fdr": round(sum(m["fdr"] for m in matches) / len(matches), 2),
            "gameweeks": sorted({m["gw"] for m in matches})}


def comparison(first, second, value, mixed=()):
    return {"state": "complete", "sides": [side(first, value), side(second, value)], "mixed": [list(x) for x in mixed]}


def p(metric, **kw):
    return {"metric": metric, **kw}


def pred(name, value):
    return {"pred": name, "value": value}


def flt(field, op, value):
    return {"field": field, "op": op, "value": value}


def cases():
    last5 = [4, 5, 6, 7, 8]
    club1 = team_matches(1)
    with_s = [m for m in club1 if mins(SUBJECT, m["gw"], m["id"]) >= 60]
    without_s = [m for m in club1 if mins(SUBJECT, m["gw"], m["id"]) == 0]
    mixed = [(m["gw"], mins(SUBJECT, m["gw"], m["id"])) for m in club1
             if 0 < mins(SUBJECT, m["gw"], m["id"]) < 60]
    without_gws = [m["gw"] for m in without_s]

    yield "g01", p("total_points"), players(lambda i: total(i, ALL_GWS, "total_points"))
    yield ("g02", p("total_points", match_set=[pred("last_n", 5)], filters=[flt("owned_now", "lt", 10)]),
           players(lambda i: total(i, last5, "total_points"), last5,
                   keep=lambda e: float(e["selected_by_percent"]) < 10))
    yield ("g03", p("goals_scored", match_set=[pred("gw", 4)], top_n=5),
           players(lambda i: total(i, [4], "goals_scored"), [4], top_n=5))
    yield ("g04", p("expected_goals", match_set=[pred("gw_range", [2, 5])],
                    filters=[flt("position", "eq", "FWD")]),
           players(lambda i: total(i, [2, 3, 4, 5], "expected_goals"), [2, 3, 4, 5],
                   keep=lambda e: e["element_type"] == 4))
    yield ("g05", p("goals_scored", operator="minus", metric_minus="expected_goals"),
           players(lambda i: total(i, ALL_GWS, "goals_scored") - total(i, ALL_GWS, "expected_goals")))
    yield ("g06", p("goals_scored", operator="plus", metric_plus="assists", filters=[flt("position", "eq", "MID")]),
           players(lambda i: total(i, ALL_GWS, "goals_scored") + total(i, ALL_GWS, "assists"),
                   keep=lambda e: e["element_type"] == 3))
    # per 90, whole season of 8 gameweeks: floor 270 minutes
    yield ("g07", p("expected_goals", operator="per_90"),
           players(lambda i: total(i, ALL_GWS, "expected_goals") * 90 / total(i, ALL_GWS, "minutes"), floor=270))
    # per 90 over 5 gameweeks: floor is half of 450 minutes
    yield ("g08", p("threat", operator="per_90", match_set=[pred("last_n", 5)]),
           players(lambda i: total(i, last5, "threat") * 90 / total(i, last5, "minutes"), last5, floor=225))
    yield ("g09", p("total_points", operator="per_match", filters=[flt("price", "le", 7)]),
           players(lambda i: total(i, ALL_GWS, "total_points") / appearances(i, ALL_GWS) if appearances(i, ALL_GWS)
                   else None, floor=270, keep=lambda e: e["now_cost"] <= 70))
    yield ("g10", p("total_points", operator="per_million"),
           players(lambda i: total(i, ALL_GWS, "total_points") / (ELEMENTS[i]["now_cost"] / 10)))
    # ascending: one full match is the floor
    yield ("g11", p("expected_goals_conceded", order="asc", filters=[flt("position", "eq", "DEF")]),
           players(lambda i: total(i, ALL_GWS, "expected_goals_conceded"), floor=60, ascending=True,
                   keep=lambda e: e["element_type"] == 2))
    yield ("g12", p("saves", filters=[flt("club", "in", ["Alder Town", "BIR"])], top_n=3),
           players(lambda i: total(i, ALL_GWS, "saves"), keep=lambda e: e["team"] in (1, 2), top_n=3))
    yield ("g13", p("bonus", filters=[flt("set_piece", "eq", "penalties")]),
           players(lambda i: total(i, ALL_GWS, "bonus"), keep=lambda e: e["penalties_order"] == 1))
    yield ("g14", p("tackles", filters=[flt("minutes_in_window", "ge", 600)]),
           players(lambda i: total(i, ALL_GWS, "tackles"), floor=600))
    # since the GW6 weekend: the date is GW6's first day, so GW6-8 whole
    yield ("g15", p("defensive_contribution", match_set=[pred("since_date", "2026-09-19")]),
           players(lambda i: total(i, [6, 7, 8], "defensive_contribution"), [6, 7, 8]))
    yield ("g16", p("team_goals"), teams(lambda m: m["gf"]))
    yield ("g17", p("team_goals_conceded", order="asc", match_set=[pred("venue", "home")]),
           teams(lambda m: m["ga"], lambda t: [m for m in team_matches(t) if m["home"]], ascending=True))
    yield ("g18", p("team_clean_sheets", match_set=[pred("last_n", 6)]),
           teams(lambda m: int(m["ga"] == 0), lambda t: team_matches(t, [3, 4, 5, 6, 7, 8])))
    yield ("g19", p("team_goals", operator="per_match", match_set=[pred("last_n", 4)]),
           teams(lambda m: m["gf"], lambda t: team_matches(t, [5, 6, 7, 8]), per_match=True))
    yield ("g20", p("team_expected_goals", match_set=[pred("gw_range", [1, 5])]),
           teams(team_xg, lambda t: team_matches(t, [1, 2, 3, 4, 5])))
    yield ("g21", p("team_goals", operator="minus", metric_minus="team_expected_goals",
                    match_set=[pred("gw_range", [1, 5])]),
           teams(lambda m: m["gf"] - team_xg(m), lambda t: team_matches(t, [1, 2, 3, 4, 5])))
    both = [pred("player_played_60", "SubjectAld")], [pred("player_absent", "SubjectAld")]
    # without: GW4-6; GW7 (13') is mixed
    yield ("g22", p("team_goals", shape="comparison", operator="per_match",
                    filters=[flt("club", "eq", "Alder Town")], match_set=both[0], compare_to=both[1]),
           comparison(with_s, without_s, lambda m: m["gf"], mixed)
           if min(len(with_s), len(without_s)) >= 3 else
           {"state": "data_unavailable", "reason": "too_few_matches"})
    yield ("g23", p("team_goals_conceded", shape="comparison", filters=[flt("club", "eq", "ALD")],
                    match_set=[pred("gw_range", [1, 4])], compare_to=[pred("gw_range", [5, 8])]),
           comparison(team_matches(1, [1, 2, 3, 4]), team_matches(1, [5, 6, 7, 8]), lambda m: m["ga"]))
    yield ("g24", p("expected_assists", match_set=[pred("player_absent", "SubjectAld")], top_n=3),
           players(lambda i: total(i, without_gws, "expected_assists"), sorted(set(without_gws)),
                   keep=lambda e: e["team"] == 1, top_n=3))
    yield ("g25", p("team_goals", match_set=[pred("gw", 3)]),
           teams(lambda m: m["gf"], lambda t: team_matches(t, [3])))


def main():
    golden = [{"id": i, "spec": spec, "expect": expect} for i, spec, expect in cases()]
    text = "[\n" + ",\n".join(json.dumps(c, ensure_ascii=False) for c in golden) + "\n]\n"
    (HERE / "golden.json").write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

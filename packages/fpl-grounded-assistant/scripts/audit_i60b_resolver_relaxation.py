"""i60 B matcher-relaxation audit: what NEWLY resolves, and is it the right player?

Rule (a) makes "first second" / "first second web" an exact match and rule
(b) accepts a lone substring match the named club confirms. Loosening a
matcher can turn a visible ambiguity into a fluent wrong answer, so this
compares the resolver BEFORE (a git ref) and AFTER (the working tree) on a
real population: every player of the live FPL bootstrap (first/second/web
names, clubs, real homonyms), each queried as web name, second name, first
name, full name, "first second web", and "full name (CLUB)" -- the shape the
historical chip sends back.

Reports every query whose result changed, and fails (exit 1) if any changed
query now resolves to a player whose name does not match it.

Usage: python audit_i60b_resolver_relaxation.py [--before-ref origin/main]
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
import requests

PKG = Path(__file__).resolve().parents[1]
REL = "packages/fpl-grounded-assistant/fpl_grounded_assistant/get_player_season_points.py"
for rel in [".", "../fpl-data-core", "../fpl-api-client", "../fpl-player-registry", "../fpl-query-tools",
            "../fpl-tool-contract", "../fpl-tool-runner", "../fpl-captain-engine", "../football-data-contract"]:
    sys.path.insert(0, str((PKG / rel).resolve()))


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before-ref", default="origin/main")
    a = ap.parse_args()
    repo = PKG.parents[1]
    before_src = subprocess.run(["git", "show", f"{a.before_ref}:{REL}"], cwd=repo, capture_output=True,
                                text=True, encoding="utf-8", check=True).stdout
    tmp = Path(tempfile.mkdtemp()) / "gpsp_before.py"
    tmp.write_text(before_src, encoding="utf-8")
    before = _load(tmp, "_gpsp_before")
    after = _load(PKG / "fpl_grounded_assistant" / "get_player_season_points.py", "_gpsp_after")

    bs = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/", timeout=60).json()
    teams = {t["id"]: t["short_name"] for t in bs["teams"]}
    df = pd.DataFrame([{
        "player_id": e["id"], "first_name": e["first_name"], "second_name": e["second_name"],
        "web_name": e["web_name"], "team_id": e["team"], "element_type": e["element_type"],
        "total_points": e.get("total_points", 0),
    } for e in bs["elements"]])
    rows = df[df["element_type"].isin([1, 2, 3, 4])].to_dict(orient="records")

    queries: list[tuple[str, str]] = []
    for r in rows:
        full = f"{r['first_name']} {r['second_name']}"
        for q in (r["web_name"], r["second_name"], r["first_name"], full, f"{full} {r['web_name']}",
                  f"{full} ({teams[r['team_id']]})"):
            queries.append((q, ""))
    queries = list(dict.fromkeys(queries))

    norm = after._normalize_name
    changed = wrong = 0
    for q, _ in queries:
        b = before._resolve_player_in_season(q, df, teams)
        n = after._resolve_player_in_season(q, df, teams)
        key = lambda r: (r["status"], r.get("player_id"), tuple(c.get("id") for c in r.get("candidates", [])))
        if key(b) == key(n):
            continue
        changed += 1
        line = f"{q!r}: {b['status']}{'' if b['status'] != 'ambiguous' else len(b['candidates'])} -> {n['status']}"
        if n["status"] == "ok":
            rec = df.set_index("player_id").loc[n["player_id"]]
            name_q, _club = after.split_club_from_query(q)
            target = {norm(f"{rec['first_name']} {rec['second_name']}"),
                      norm(f"{rec['first_name']} {rec['second_name']} {rec['web_name']}")}
            ok_name = norm(name_q) in target or norm(name_q) in norm(f"{rec['first_name']} {rec['second_name']} {rec['web_name']}")
            club_ok = _club is None or teams[int(rec["team_id"])] == _club
            line += f" {rec['first_name']} {rec['second_name']} ({teams[int(rec['team_id'])]})"
            if not (ok_name and club_ok):
                wrong += 1
                line += "   <-- WRONG PLAYER"
        print(line)
    print(f"\nqueries: {len(queries)}  changed: {changed}  resolved to a wrong player: {wrong}")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())

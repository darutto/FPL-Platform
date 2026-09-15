"""i93 evidence, step 1: which player source composes cleanly with one match?

NO LLM. Runs the two candidate tools through ``run_tool`` exactly as the
orchestrator would, for real upcoming matches, and prints what each returns
for "the players of TEAM relevant to THIS match against OPPONENT":

* ``get_team_snapshot(team_name, top_n_players)`` -- team-scoped, ordered by
  season points; what the row carries is what the model could cite.
* ``get_zonal_opportunity(opponent)`` -- exploiters of the opponent's weak
  zones from owned Understat data. The LLM schema only declares ``opponent``;
  the handler infers the subject team from the question (i86/i89) when one is
  given, otherwise scopes to the fixture calendar (i90). Both shapes are run
  so the read-out shows what a cell-tap question would get.

Read-outs are the produced rows (team_short, web_name, the numeric fields),
never a summary typed by hand. The PR quotes this output verbatim.

Usage (from packages/fpl-grounded-assistant; needs a tactical store for the
season the bootstrap is in -- point FPL_TACTICAL_ROOT at one if the default
location holds an older season):
    python scripts/evidence_i93_player_source.py --gw 5 --teams "Arsenal,Newcastle,Liverpool,Man City,Spurs"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
for _p in [PACKAGE_ROOT, *sorted((REPO_ROOT / "packages").iterdir())]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import requests  # noqa: E402

import fpl_grounded_assistant  # noqa: E402,F401
from fpl_tool_runner import run_tool  # noqa: E402
from fpl_api_client import get_current_gameweek  # noqa: E402
from fpl_grounded_assistant.orchestrator import QUESTION_CONTEXT_KEY  # noqa: E402


def live_bootstrap() -> dict[str, Any]:
    """bootstrap-static + team_fixtures, the shape the server hands the tools."""
    boot = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/", timeout=30).json()
    fixtures = requests.get("https://fantasy.premierleague.com/api/fixtures/", timeout=30).json()
    team_fixtures: dict[int, list[dict[str, Any]]] = {t["id"]: [] for t in boot["teams"]}
    for f in fixtures:
        if f.get("event") is None:
            continue
        team_fixtures[f["team_h"]].append({"gameweek": f["event"], "opponent_team": f["team_a"],
                                            "is_home": True, "difficulty": f.get("team_h_difficulty")})
        team_fixtures[f["team_a"]].append({"gameweek": f["event"], "opponent_team": f["team_h"],
                                            "is_home": False, "difficulty": f.get("team_a_difficulty")})
    boot["team_fixtures"] = team_fixtures
    return boot


def match_for(boot: dict[str, Any], team_name: str, gw: int) -> dict[str, Any] | None:
    teams = {t["id"]: t for t in boot["teams"]}
    team = next((t for t in boot["teams"] if t["name"].lower() == team_name.lower()
                 or t["short_name"].lower() == team_name.lower()), None)
    if team is None:
        return None
    fx = [f for f in boot["team_fixtures"][team["id"]] if f["gameweek"] == gw]
    if not fx:
        return None
    opp = teams[fx[0]["opponent_team"]]
    return {"team": team, "opponent": opp, "is_home": fx[0]["is_home"], "gw": gw}


def snapshot_rows(out: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for p in out.get("top_players") or []:
        rows.append({k: p.get(k) for k in ("web_name", "position", "total_points", "form",
                                            "expected_goals", "expected_assists", "ict_index",
                                            "minutes", "now_cost") if k in p})
    return rows


def zonal_rows(out: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for e in out.get("exploiters") or []:
        rows.append({k: e.get(k) for k in ("web_name", "team_short", "position", "zone",
                                            "fit_score", "n_shots", "zone_shots", "zone_share",
                                            "gameweek", "club_source") if k in e})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gw", type=int, default=None, help="gameweek to inspect (default: next)")
    ap.add_argument("--teams", default="Arsenal,Newcastle,Liverpool,Man City,Spurs")
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--json-out", default=None, help="also dump every raw output here")
    args = ap.parse_args(argv)

    boot = live_bootstrap()
    current = get_current_gameweek(boot)
    gw = args.gw or (current + 1 if current else 1)
    print(f"bootstrap: {len(boot['elements'])} elements, current GW {current}, inspecting GW{gw}")
    dump: dict[str, Any] = {"gw": gw, "current_gw": current, "matches": []}

    for name in [t.strip() for t in args.teams.split(",") if t.strip()]:
        m = match_for(boot, name, gw)
        if m is None:
            print(f"\n### {name}: no fixture in GW{gw}")
            continue
        team, opp = m["team"], m["opponent"]
        venue = "en casa" if m["is_home"] else "a domicilio"
        question = (f"{team['name']} vs {opp['short_name']} ({venue}), J{gw}: "
                    f"¿qué tal pinta ofensivamente para el {team['name']}?")
        print(f"\n### {team['name']} vs {opp['short_name']} ({venue}) J{gw}")
        print(f"    question: {question}")

        snap = run_tool("get_team_snapshot", {"team_name": team["name"], "top_n_players": args.top_n}, boot)
        s_rows = snapshot_rows(snap)
        print(f"  [get_team_snapshot] status={snap.get('status')} top_players={len(s_rows)}")
        for r in s_rows:
            print(f"      {r}")

        # Shape A: what the orchestrator passes when the model copies the schema
        # (opponent only). The handler infers the subject team from the
        # question text, which the orchestrator injects into the BOOTSTRAP
        # under QUESTION_CONTEXT_KEY (orchestrator.py: actual_bootstrap[...] =
        # question) -- not into the args. Same channel here.
        boot_q = dict(boot)
        boot_q[QUESTION_CONTEXT_KEY] = question
        zon_a = run_tool("get_zonal_opportunity", {"opponent": opp["name"]}, boot_q)
        z_rows_a = zonal_rows(zon_a)
        teams_a = sorted({r.get("team_short") for r in z_rows_a})
        print(f"  [get_zonal_opportunity opponent-only] status={zon_a.get('status')} "
              f"scope={zon_a.get('scope_resolution')} horizon={zon_a.get('horizon')} "
              f"exploiters={len(z_rows_a)} teams={teams_a}")
        for r in z_rows_a[:args.top_n]:
            print(f"      {r}")

        # Shape B: explicit team scope (what a future schema change could expose).
        zon_b = run_tool("get_zonal_opportunity", {"opponent": opp["name"], "team": team["name"]}, boot)
        z_rows_b = zonal_rows(zon_b)
        teams_b = sorted({r.get("team_short") for r in z_rows_b})
        print(f"  [get_zonal_opportunity team-scoped] status={zon_b.get('status')} "
              f"scope={zon_b.get('scope_resolution')} exploiters={len(z_rows_b)} teams={teams_b}")
        for r in z_rows_b[:args.top_n]:
            print(f"      {r}")

        dump["matches"].append({"question": question, "team": team["short_name"], "opponent": opp["short_name"],
                                "snapshot": snap, "zonal_opponent_only": zon_a, "zonal_team_scoped": zon_b})

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(dump, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"\nraw outputs -> {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

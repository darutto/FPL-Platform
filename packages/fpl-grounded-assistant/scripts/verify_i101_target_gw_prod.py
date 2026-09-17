"""i101 prod check: a /fixtures cell tap on a gameweek at least 2 ahead of the
current one is answered about THAT gameweek.

Runs against a deployed backend (before the fix it documents the failure;
after, it must pass). Nothing is asserted from the phrase that was sent:

* the expected gameweek/opponent/venue come from the LIVE FPL API
  (bootstrap-static + fixtures) for the team and the gameweek asked, so the
  yardstick is independent of both the phrase and the model;
* the observed values come from the /ask debug blob: ``tool_input`` (did
  ``target_gw`` arrive?) and ``raw_output.series`` (which gameweek and
  opponent did the tool describe?).

The composer text is rebuilt the way ``fixtureCellQuestion`` builds it
(``packages/fpl-ui/lib/fixture-chat-links.ts``) from the live fixture, so the
phrase sent IS the phrase a tap would insert for that cell today.

Usage:
    python scripts/verify_i101_target_gw_prod.py \
        --url https://fpl-backend-production-4151.up.railway.app \
        --user-id i101-verify-$(date +%Y%m%d%H%M) \
        --team "Crystal Palace" --lead 2 --reps 3

Exit 0 when every rep has tool_input.target_gw == asked GW AND the produced
series is exactly that GW with the live opponent; exit 1 otherwise. The
per-rep lines are the evidence either way.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

import requests

FPL = "https://fantasy.premierleague.com/api"
TOOL = "get_fixture_outlook"


def live_cell(team_name: str, lead: int) -> dict[str, Any]:
    """The (team, current+lead) cell from the live FPL API."""
    boot = requests.get(f"{FPL}/bootstrap-static/", timeout=30).json()
    fixtures = requests.get(f"{FPL}/fixtures/", timeout=30).json()
    teams = {t["id"]: t for t in boot["teams"]}
    team = next((t for t in boot["teams"]
                 if t["name"].lower() == team_name.lower() or t["short_name"].lower() == team_name.lower()), None)
    if team is None:
        raise SystemExit(f"team not found in live bootstrap: {team_name!r}")
    current = next((e["id"] for e in boot["events"] if e.get("is_current")), None)
    if current is None:
        current = next(e["id"] for e in boot["events"] if e.get("is_next"))
    gw = current + lead
    cell = [f for f in fixtures if f.get("event") == gw and team["id"] in (f["team_h"], f["team_a"])]
    if not cell:
        raise SystemExit(f"{team['name']} has no fixture in GW{gw} (current GW{current})")
    parts = []
    for f in cell:
        is_home = f["team_h"] == team["id"]
        opp = teams[f["team_a"] if is_home else f["team_h"]]
        parts.append({"opponent_short": opp["short_name"], "is_home": is_home})
    matchup = " y ".join(
        f"{team['name']} vs {p['opponent_short']} ({'en casa' if p['is_home'] else 'a domicilio'})" for p in parts
    )
    jornada = f"J{gw} (doble jornada)" if len(parts) >= 2 else f"J{gw}"
    # i93-b: the cell tap asks both sides of the match (fixtureCellQuestion).
    question = f"{matchup}, {jornada}: ¿qué tal pinta ofensivamente y defensivamente para el {team['name']}?"
    return {"team": team["name"], "current_gw": current, "gw": gw, "fixtures": parts, "question": question}


def ask(url: str, user_id: str, question: str) -> dict[str, Any]:
    resp = requests.post(
        f"{url.rstrip('/')}/ask",
        headers={"Content-Type": "application/json", "X-User-Id": user_id},
        json={"question": question, "debug": True},
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()


def judge(body: dict[str, Any], cell: dict[str, Any]) -> tuple[bool, str]:
    dbg = body.get("debug") or {}
    tool = dbg.get("selected_tool")
    tool_input = dbg.get("tool_input") or {}
    raw = dbg.get("raw_output") or {}
    series = raw.get("series") or []
    gws = [e.get("gameweek") for e in series]
    opps = sorted(f.get("opponent_short") for e in series for f in (e.get("fixtures") or []))
    want_opps = sorted(p["opponent_short"] for p in cell["fixtures"])
    # i93-b: the both-sides phrase runs the calendar tool twice (one axis
    # each); every executed calendar call must carry the literal gameweek,
    # not only the one promoted to the singular slot.
    rt = dbg.get("routing_trace") or {}
    seq = list(rt.get("tool_sequence") or [])
    args_seq = list(rt.get("tool_args_sequence") or [])
    cal_gws = [(a or {}).get("target_gw") for n, a in zip(seq, args_seq) if n == TOOL]
    every_call_on_gw = (not cal_gws) or all(g == cell["gw"] for g in cal_gws)
    ok = (
        tool == TOOL
        and tool_input.get("target_gw") == cell["gw"]
        and gws == [cell["gw"]]
        and opps == want_opps
        and every_call_on_gw
    )
    line = (f"selected_tool={tool!r} tool_input={tool_input} series_gws={gws} opponents={opps} "
            f"calendar_calls_target_gw={cal_gws} (live: GW{cell['gw']} vs {want_opps}) status={raw.get('status')!r}")
    return ok, line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--user-id", required=True, help="a FRESH id per run (5 orchestrated turns per id)")
    parser.add_argument("--team", default="Crystal Palace")
    parser.add_argument("--lead", type=int, default=2, help="gameweeks ahead of the current one (default 2)")
    parser.add_argument("--reps", type=int, default=3)
    args = parser.parse_args(argv)

    cell = live_cell(args.team, args.lead)
    print(f"[i101] live cell: {cell['team']} GW{cell['gw']} (current GW{cell['current_gw']}) "
          f"fixtures={cell['fixtures']}")
    print(f"[i101] question: {cell['question']!r}")
    all_ok = True
    for rep in range(args.reps):
        body = ask(args.url, args.user_id, cell["question"])
        ok, line = judge(body, cell)
        all_ok &= ok
        print(f"  rep {rep}: {'OK ' if ok else 'BAD'} {line}")
        print(f"         final_text: {(body.get('final_text') or '')[:160]!r}")
    print(f"[i101] {'OK' if all_ok else 'FAIL'}: {args.reps} reps, target_gw and series must match the live GW{cell['gw']} cell")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

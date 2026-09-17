"""i93 prod check: the /fixtures cell tap composes calendar + real players.

Runs against a deployed backend. Before the fix it documents the gap;
after, it must pass. Nothing is asserted from the phrase sent or from the
model's own words:

* the composer text is rebuilt the way ``fixtureCellQuestion`` builds it
  from the LIVE fixture of (team, current+lead);
* the players that count as REAL are the team's top-N by total_points read
  from the LIVE bootstrap (the same ordering get_team_snapshot uses) -- an
  independent yardstick, not the tool's own output and not a hardcoded list;
* the trace (``debug.routing_trace.tool_sequence``, i80) must show BOTH
  get_fixture_outlook and get_team_snapshot in the round;
* i93-b: the cell phrase asks both sides of the match, so
  ``debug.routing_trace.tool_args_sequence`` (parallel to tool_sequence)
  must show get_fixture_outlook executed with axis='attack' AND with
  axis='defence' -- the clean-sheet read comes from the tool, not from the
  model. A backend without that field (pre-i93-b) fails this check;
* ``final_text`` must mention at least one of those real web_names and
  contain no transaction/urgency vocabulary (opportunity_framing);
* ``debug.selected_tool`` must be get_fixture_outlook (the composed turn's
  singular slot is the calendar call, whatever order the model used).

Usage:
    python scripts/verify_i93_composed_prod.py \
        --url https://fpl-backend-production-4151.up.railway.app \
        --user-id i93-verify-$(date +%Y%m%d%H%M) --team Arsenal --lead 1 --reps 3

Exit 0 when every rep satisfies all five; exit 1 otherwise. Fresh --user-id
per run (5 orchestrated turns per id, i99).
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path
from typing import Any

import requests

# opportunity_framing is pure stdlib; load it by path so this script runs
# with nothing but ``requests`` installed (the package __init__ pulls the
# whole tool graph, which a prod check does not need).
import importlib.util as _ilu  # noqa: E402

_OF_PATH = Path(__file__).resolve().parents[1] / "fpl_grounded_assistant" / "opportunity_framing.py"
_spec = _ilu.spec_from_file_location("opportunity_framing", _OF_PATH)
_of = _ilu.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_of)
transaction_hits = _of.transaction_hits

FPL = "https://fantasy.premierleague.com/api"


#: Letters NFKD does not decompose (they are letters of their own, not
#: base + accent): Ødegaard must match "Odegaard" in prose.
_LATIN_FOLD = str.maketrans({"ø": "o", "æ": "ae", "ß": "ss", "đ": "d", "ł": "l", "œ": "oe", "þ": "th"})


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).translate(_LATIN_FOLD)


def live_cell(team_name: str, lead: int, top_n: int) -> dict[str, Any]:
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
        raise SystemExit(f"{team['name']} has no fixture in GW{gw}")
    parts = []
    for f in cell:
        is_home = f["team_h"] == team["id"]
        opp = teams[f["team_a"] if is_home else f["team_h"]]
        parts.append({"opponent_short": opp["short_name"], "is_home": is_home})
    matchup = " y ".join(f"{team['name']} vs {p['opponent_short']} ({'en casa' if p['is_home'] else 'a domicilio'})"
                         for p in parts)
    jornada = f"J{gw} (doble jornada)" if len(parts) >= 2 else f"J{gw}"
    question = f"{matchup}, {jornada}: ¿qué tal pinta ofensivamente y defensivamente para el {team['name']}?"
    squad = sorted((e for e in boot["elements"] if e["team"] == team["id"]),
                   key=lambda e: int(e.get("total_points") or 0), reverse=True)
    real = [e["web_name"] for e in squad[:top_n]]
    return {"team": team["name"], "current_gw": current, "gw": gw, "question": question, "real_players": real}


def ask(url: str, user_id: str, question: str) -> dict[str, Any]:
    resp = requests.post(f"{url.rstrip('/')}/ask",
                         headers={"Content-Type": "application/json", "X-User-Id": user_id},
                         json={"question": question, "debug": True}, timeout=180)
    resp.raise_for_status()
    return resp.json()


def judge(body: dict[str, Any], cell: dict[str, Any]) -> tuple[bool, str]:
    dbg = body.get("debug") or {}
    rt = dbg.get("routing_trace") or {}
    seq = list(rt.get("tool_sequence") or [])
    text = str(body.get("final_text") or "")
    folded = _fold(text)
    named = [wn for wn in cell["real_players"] if _fold(wn) in folded]
    hits = transaction_hits(text)
    composed = "get_fixture_outlook" in seq and "get_team_snapshot" in seq
    args_seq = list(rt.get("tool_args_sequence") or [])
    axes = sorted({str((a or {}).get("axis")) for n, a in zip(seq, args_seq) if n == "get_fixture_outlook"})
    both_axes = {"attack", "defence"} <= set(axes)
    ok = (composed and both_axes and bool(named) and not hits
          and dbg.get("selected_tool") == "get_fixture_outlook")
    line = (f"seq={seq} calendar_axes={axes} selected_tool={dbg.get('selected_tool')!r} named_real={named} "
            f"(live top-{len(cell['real_players'])}: {cell['real_players']}) transaction_hits={hits} "
            f"composed_primary={rt.get('composed_primary_tool')!r}")
    return ok, line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--team", default="Arsenal")
    parser.add_argument("--lead", type=int, default=1)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--reps", type=int, default=3)
    args = parser.parse_args(argv)

    cell = live_cell(args.team, args.lead, args.top_n)
    print(f"[i93] live cell: {cell['team']} GW{cell['gw']} (current GW{cell['current_gw']}); "
          f"real top-{args.top_n} by points: {cell['real_players']}")
    print(f"[i93] question: {cell['question']!r}")
    all_ok = True
    for rep in range(args.reps):
        body = ask(args.url, args.user_id, cell["question"])
        ok, line = judge(body, cell)
        all_ok &= ok
        print(f"  rep {rep}: {'OK ' if ok else 'BAD'} {line}")
        print(f"         final_text: {(body.get('final_text') or '')[:220]!r}")
    print(f"[i93] {'OK' if all_ok else 'FAIL'}: {args.reps} reps must be composed, read BOTH calendar axes, "
          f"name a real player, stay clean, and keep get_fixture_outlook as selected_tool")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

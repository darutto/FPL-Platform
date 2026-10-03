"""i125(b): does a captain question with a linked team end without a captain?

Prod, 2026-10-02: «¿A quién capitaneo esta jornada? Dame un top 3 numerado.»
with team_id=68643 -- the evaluator rejected, the retry called
get_gameweek_context and the served answer was only «Jornada actual: GW5 ...»,
no captain at all.

R reps of that question by POST /ask (debug) against prod, one fresh
X-User-Id per rep (free cap, i99). Per turn, read off the response -- never
off what was requested:

* retry_attempted / synthesis_turn / evaluator_verdict (routing_trace);
* tool_sequence + tool_args_sequence: which tool the retry ran (the calls
  after the primary's, i.e. beyond the first rank_captain_candidates);
* names_captain: does final_text name at least one player that the primary
  rank_captain_candidates output ranked (debug.raw_output when that is the
  selected tool, else unknown -> checked against a name list fetched once
  from the same deploy, see below).

Cost cap (declared, i125(b) card): R <= 5 by construction (hard-coded max);
a luna captain turn with a retry is ~74K tokens (i124 audit), ~0.02 USD, so
the run is bounded at ~0.10 USD, under the 0.50 USD cap.

Usage: python measure_i125b_captain_retry.py OUT.jsonl [--reps N] [--no-team]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

import requests

URL = "https://fpl-backend-production-4151.up.railway.app"
QUESTION = "¿A quién capitaneo esta jornada? Dame un top 3 numerado."
TEAM_ID = 68643
MAX_REPS = 5


def _ranked_names(raw: dict) -> list[str]:
    names: list[str] = []
    for key in ("ranked_candidates", "global_candidates", "squad_candidates", "candidates", "rankings"):
        for c in raw.get(key) or []:
            if isinstance(c, dict):
                n = c.get("web_name") or c.get("name") or c.get("player_name")
                if n and n not in names:
                    names.append(n)
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--reps", type=int, default=MAX_REPS)
    ap.add_argument("--no-team", action="store_true")
    a = ap.parse_args()
    reps = min(a.reps, MAX_REPS)
    team_id = None if a.no_team else TEAM_ID
    run = f"i125b-{'noteam' if team_id is None else 'team'}-{uuid.uuid4().hex[:6]}"
    with open(a.out, "a", encoding="utf-8") as f:
        version = requests.get(f"{URL}/version", timeout=30).json()
        f.write(json.dumps({"kind": "pre", "run_id": run, "version": version, "team_id": team_id,
                            "reps": reps, "ts": time.time()}) + "\n")
        for i in range(1, reps + 1):
            user = f"{run}-u{i}"
            payload = {"question": QUESTION, "debug": True}
            if team_id is not None:
                payload["team_id"] = team_id
            t0 = time.time()
            r = requests.post(f"{URL}/ask", headers={"X-User-Id": user}, json=payload, timeout=240)
            body = r.json()
            dbg = body.get("debug") or {}
            rt = dbg.get("routing_trace") or {}
            seq = rt.get("tool_sequence") or []
            args_seq = rt.get("tool_args_sequence") or []
            raw = dbg.get("raw_output") or {}
            ranked = _ranked_names(raw) if dbg.get("selected_tool") == "rank_captain_candidates" else []
            # Ranked names from the card payload the UI renders, when present.
            for c in (body.get("captain_ranking") or []):
                n = isinstance(c, dict) and (c.get("web_name") or c.get("name"))
                if n and n not in ranked:
                    ranked.append(n)
            text = body.get("final_text") or ""
            named = [n for n in ranked if n.lower() in text.lower()]
            summary = {
                "status": r.status_code,
                "retry_attempted": rt.get("retry_attempted"),
                "synthesis_turn": rt.get("synthesis_turn"),
                "tool_sequence": seq,
                "tool_args_sequence": args_seq,
                "selected_tool": dbg.get("selected_tool"),
                "verdict": rt.get("evaluator_verdict"),
                "ranked_known": ranked[:10],
                "names_in_text": named,
                "names_captain": bool(named),
                "text_head": text[:160],
                "llm_used": body.get("llm_used"),
            }
            f.write(json.dumps({"kind": "turn", "run_id": run, "i": i, "user": user,
                                "latency_s": round(time.time() - t0, 1), "response": body,
                                "summary": summary, "ts": time.time()}, ensure_ascii=False) + "\n")
            print(json.dumps({"i": i, **{k: summary[k] for k in (
                "retry_attempted", "synthesis_turn", "tool_sequence", "selected_tool",
                "names_captain", "names_in_text")}, "text_head": text[:90]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

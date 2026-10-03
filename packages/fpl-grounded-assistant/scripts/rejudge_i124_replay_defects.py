"""i124 (C) gate: do the three real defects of the replay stay rejected?

The replay (field-notes/2026-10-03-i124-evaluator-replay.md) recorded each
primary's text and its tools' (name, status), not the outputs. To re-judge
the three primaries with a real defect -- #2 Haaland/Salah (compare_players
not_found), #8 Liverpool defence (self-contradiction about home games), #14
Free Hit 6/7/8 (claims about GW7/GW8 the tool did not evaluate) -- the tool is
re-executed now with the arguments the question implies, its status is
checked against the recorded one, and the served evaluator of this branch
judges the RECORDED primary text against that output, exactly as
``_apply_evaluator`` hands it over (the model view under MODEL_VIEW_KEY).

Caveat, reported with the result: the re-executed output is today's data,
not byte-for-byte what the primary saw.

Usage: python rejudge_i124_replay_defects.py REPLAY.jsonl OUT.jsonl [--judgments 3]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
for rel in [".", "../fpl-data-core", "../fpl-api-client", "../fpl-player-registry", "../fpl-query-tools",
            "../fpl-tool-contract", "../fpl-tool-runner", "../fpl-captain-engine", "../football-data-contract"]:
    p = str((PKG / rel).resolve())
    if p not in sys.path:
        sys.path.insert(0, p)

CASES = {
    2: ("compare_players", {"query_a": "Haaland", "query_b": "Salah"}),
    8: ("get_team_results", {"team": "Liverpool"}),
    14: ("get_chip_advice", {"chip": "free_hit"}),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("replay")
    ap.add_argument("out")
    ap.add_argument("--judgments", type=int, default=3)
    a = ap.parse_args()

    import fpl_server
    from fpl_grounded_assistant import evaluator as ev
    from fpl_grounded_assistant import orchestrator as orch
    from fpl_grounded_assistant.harness import _build_eval_client
    from fpl_grounded_assistant.tool_dispatch import run_tool

    bootstrap = fpl_server._fetch_bootstrap_with_retry()
    client = _build_eval_client("openai")
    rows = {r["n"]: r for r in (json.loads(l) for l in open(a.replay, encoding="utf-8")) if r.get("kind") == "turn"}
    with open(a.out, "a", encoding="utf-8") as f:
        for n, (tool, args) in CASES.items():
            rec = rows[n]
            recorded_status = dict(rec["tools"]).get(tool)
            output = run_tool(tool, args, bootstrap)
            call = {"name": tool, "args": args, "output": output,
                    ev.MODEL_VIEW_KEY: orch._truncate_tool_output(output, tool_name=tool)}
            verdicts = []
            for _ in range(a.judgments):
                v = ev.evaluate_response(question=rec["question"], primary_response=rec["primary_response"],
                                         tool_calls=[call], provider="openai", client=client)
                verdicts.append({"approved": v.approved, "grounded": v.grounded, "complete": v.complete,
                                 "safe": v.safe, "retry_feedback": v.retry_feedback,
                                 "fail_open_reason": v.fail_open_reason, "tokens_used": v.tokens_used})
            row = {"n": n, "question": rec["question"], "tool": tool, "args": args,
                   "recorded_status": recorded_status, "status_now": output.get("status"),
                   "verdicts": verdicts, "ts": time.time()}
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            print(f"#{n} status recorded={recorded_status} now={output.get('status')} "
                  f"approved={[v['approved'] for v in verdicts]} fail_open={[v['fail_open_reason'] for v in verdicts]}")
            for v in verdicts:
                if not v["approved"]:
                    print(f"    {v['retry_feedback']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

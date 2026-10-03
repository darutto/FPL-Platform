"""i132: post the bench boost question R times to a local server and record the verdict.

The only question whose tool output the i132 change touches is bench boost
(``signals.favoured_players``); R=3 inside the 16-question set is too thin to
read a SAFE-rule change off. This repeats that one question against a server
(one X-User-Id per turn, so quota never cuts a turn) and writes one JSON line
per turn, read off the response's ``routing_trace`` and the server's own
audit line (joined in request order and checked by question text, as in
``measure_i124_evaluator_rejections.py``).

Usage:
  python measure_i132_bench_boost_reps.py BASE_URL AUDIT_DIR OUT.jsonl REPS
"""
import glob
import json
import os
import sys
import time
import uuid

import requests

base, audit_dir, out, reps = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
Q = "¿Debería activar el bench boost esta jornada?"


def lines():
    rows = []
    for p in sorted(glob.glob(os.path.join(audit_dir, "*.ndjson"))):
        rows += [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    return rows


seen = len(lines())
run = uuid.uuid4().hex[:6]
with open(out, "a", encoding="utf-8") as f:
    for n in range(1, reps + 1):
        body = requests.post(f"{base}/ask", headers={"X-User-Id": f"i132bb-{run}-{n}"},
                             json={"question": Q, "debug": True}, timeout=300).json()
        rt = body["debug"]["routing_trace"]
        new = lines()[seen:]
        seen += len(new)
        line = new[-1] if new else {}
        assert line.get("question") == Q, line.get("question")
        rec = {"n": n, "question": Q, "evaluator_verdict": rt.get("evaluator_verdict"),
               "retry_attempted": rt.get("retry_attempted"), "tool_sequence": rt.get("tool_sequence"),
               "final_text": body.get("final_text"), "tokens": line.get("tokens"),
               "usd_cost_estimate": line.get("usd_cost_estimate"), "ts": time.time()}
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        v = rec["evaluator_verdict"] or {}
        print(n, v.get("approved"), v.get("safe"), rec["usd_cost_estimate"], flush=True)

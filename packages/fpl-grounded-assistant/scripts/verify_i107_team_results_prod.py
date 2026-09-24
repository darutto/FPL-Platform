"""i107 prod check: the two results questions are answered by get_team_results.

Sends the two prod shapes ("cómo le ha ido de local", "goles en los últimos N
partidos") by POST /ask with debug=True and asserts FROM THE JSON BODY:

* ``routing_trace.tool_sequence`` == ["get_team_results"] (one call);
* ``web_fetch`` appears nowhere in the sequence;
* ``final_text`` carries real numbers (at least one score-like "N-N" or a
  digit next to "gol"/"partido"/"PJ") and is not the honest-guard sentence.

Usage:
    python scripts/verify_i107_team_results_prod.py \
        --url https://fpl-backend-production-4151.up.railway.app \
        --user-id i107-verify-$(date +%Y%m%d%H%M) [--jsonl out.jsonl]

Exit 0 when every check holds; 1 otherwise. Costs 2 orchestrated turns on a
free-tier id.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

import requests

QUESTIONS = [
    ("tr-01", "¿Cómo le ha ido al Arsenal de local esta temporada?"),
    ("tr-02", "¿Cuántos goles ha marcado el Liverpool en los últimos 5 partidos?"),
]
_NUMBERS = re.compile(r"\b\d+\s*-\s*\d+\b|\b\d+\s+(?:gol|goles|partido|partidos|PJ)\b", re.IGNORECASE)


def _post(url: str, user_id: str, question: str) -> dict:
    resp = requests.post(f"{url.rstrip('/')}/ask",
                         headers={"Content-Type": "application/json", "X-User-Id": user_id},
                         json={"question": question, "debug": True}, timeout=180)
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--user-id", required=True)
    ap.add_argument("--jsonl", default=None, help="append the raw bodies here")
    a = ap.parse_args()
    version = requests.get(f"{a.url.rstrip('/')}/version", timeout=30).json()
    print(f"prod /version: {version}")
    ok = True
    for qid, question in QUESTIONS:
        body = _post(a.url, a.user_id, question)
        if a.jsonl:
            with open(a.jsonl, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"id": qid, "question": question, "body": body}, ensure_ascii=False) + "\n")
        trace = (body.get("debug") or {}).get("routing_trace") or {}
        seq = list(trace.get("tool_sequence") or [])
        text = body.get("final_text") or ""
        checks = {
            "sequence_is_single_get_team_results": seq == ["get_team_results"],
            "no_web_fetch": "web_fetch" not in seq,
            "numbers_in_text": bool(_NUMBERS.search(text)),
            "not_guarded": not text.startswith("No obtuve una respuesta útil"),
        }
        ok &= all(checks.values())
        print(f"{qid}: seq={seq} outcome={body.get('outcome')} checks={checks}\n  {text[:200]!r}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

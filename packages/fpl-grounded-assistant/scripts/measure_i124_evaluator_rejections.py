"""i124: how often does the evaluator reject, why, and what does the retry cost?

Prod 2026-09-23 / 2026-10-02: rejected turns were correct, tool-grounded
answers; the feedback asked to "cite more"; the retry re-called the SAME tool
and roughly doubled the turn's tokens (and once lost an argument). Before any
change to the evaluator, measure:

  (1) the share of orchestrated turns the evaluator rejects;
  (2) of those, how many reject an answer that was already tool-grounded
      (every primary call came back ok) with feedback that only asks to cite
      or show more -- versus a real error;
  (3) what the retry does (same tool? same args? another tool?) and what it
      costs (tokens of a rejected turn vs an approved one).

Corpus: the ten canonical questions of i37 plus the distinct questions of
the prod audit of 2026-10-02 (real traffic). R reps each, against a server
URL (a local branch server with the prod orchestrator config, or prod), with
debug on; one X-User-Id per (question, rep) so quota never cuts a turn.
Everything is read off the response's routing_trace -- the verdict, the
retry, the executed calls and their args -- never off what was requested.

Cost cap: --max-turns (default 48) is a hard stop. Tokens come from the
server's own audit lines (``--audit-dir``), joined in request order: the
local server is single-worker and called sequentially, and each join is
checked by question text.

Usage:
  python measure_i124_evaluator_rejections.py OUT.jsonl --base-url http://127.0.0.1:8765 \
      --reps 3 --audit-dir <server AUDIT_LOG_DIR>
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import uuid

import requests

I37_QUESTIONS = [
    "¿A quién capitaneo esta jornada?",
    "¿Quién es mejor capitán, Haaland o Salah?",
    "¿Qué tal pinta el calendario del Arsenal en las próximas 5 jornadas?",
    "Dame el resumen de Bruno Fernandes",
    "¿Qué jugadores pueden explotar la zona más débil de la defensa del Chelsea?",
    "¿Quiénes son los 5 máximos goleadores de la temporada?",
    "¿Qué defensas baratos tienen buen calendario?",
    "¿Cómo está el Liverpool defensivamente?",
    "¿Qué zonas débiles tiene el Tottenham?",
    "Compara a Palmer con Saka",
]
PROD_2026_10_02_QUESTIONS = [
    "¿Qué tan recomendable es usar la wildcard en la siguiente fecha?",
    "Recomiéndame jugadores de Fulham para mi transferencia en la fecha 6",
    "con los buenos encuentros que tendrá fulham en las proximas 3 jornadas, he considerado trabajar el "
    "free hit en esas fechas, cual seria la mejor jornada para utilizarlo?",
    "¿Usar free hit en la jornada 6, 7 u 8? ¿Cuándo es el mejor momento?",
    "¿Debería activar el bench boost esta jornada?",
    "Recomiendame jugadores de fulham para considerar con mi transferencia en la fecha 6",
]
CORPUS = I37_QUESTIONS + PROD_2026_10_02_QUESTIONS
#: i123: the chip/transfer family -- the answers where internal names leaked
#: (prod free hit 6/7/8, local wildcard and Fulham transfer).
CHIP_FAMILY = PROD_2026_10_02_QUESTIONS[:5]
SUBSETS = {"all": CORPUS, "chip": CHIP_FAMILY}


def _audit_lines(audit_dir: str) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(glob.glob(os.path.join(audit_dir, "*.ndjson"))):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--max-turns", type=int, default=48)
    ap.add_argument("--audit-dir", required=True)
    ap.add_argument("--subset", choices=sorted(SUBSETS), default="all")
    a = ap.parse_args()
    base = a.base_url.rstrip("/")
    run = f"i124-{uuid.uuid4().hex[:6]}"
    plan = [(q, r) for r in range(1, a.reps + 1) for q in SUBSETS[a.subset]][: a.max_turns]
    seen_audit = len(_audit_lines(a.audit_dir))
    with open(a.out, "a", encoding="utf-8") as f:
        version = requests.get(f"{base}/version", timeout=30).json()
        f.write(json.dumps({"kind": "pre", "run_id": run, "base_url": base, "version": version,
                            "reps": a.reps, "planned_turns": len(plan), "ts": time.time()}) + "\n")
        for n, (question, rep) in enumerate(plan, 1):
            user = f"{run}-{n}"
            t0 = time.time()
            r = requests.post(f"{base}/ask", headers={"X-User-Id": user},
                              json={"question": question, "debug": True}, timeout=300)
            body = r.json()
            rt = (body.get("debug") or {}).get("routing_trace") or {}
            audit = _audit_lines(a.audit_dir)
            new = audit[seen_audit:]
            seen_audit = len(audit)
            line = new[-1] if new else None
            if line is not None and line.get("question") != question:
                raise SystemExit(f"audit join broke at turn {n}: {line.get('question')!r} != {question!r}")
            rec = {
                "kind": "turn", "run_id": run, "n": n, "rep": rep, "question": question,
                "status": r.status_code, "latency_s": round(time.time() - t0, 1),
                "branch": rt.get("branch"),
                "retry_attempted": rt.get("retry_attempted"),
                "retry_delivery": rt.get("retry_delivery"),
                "evaluator_verdict": rt.get("evaluator_verdict"),
                "tool_sequence": rt.get("tool_sequence"),
                "tool_args_sequence": rt.get("tool_args_sequence"),
                "synthesis_turn": rt.get("synthesis_turn"),
                "final_text": body.get("final_text"),
                "audit_tool_calls": (line or {}).get("tool_calls"),
                "tokens": (line or {}).get("tokens"),
                "usd_cost_estimate": (line or {}).get("usd_cost_estimate"),
                "ts": time.time(),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            v = rec["evaluator_verdict"] or {}
            print(f"#{n:02d} r{rep} approved={v.get('approved')} retry={rec['retry_attempted']} "
                  f"delivery={rec['retry_delivery']} tok={(rec['tokens'] or {}).get('total')} "
                  f"{question[:50]!r}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

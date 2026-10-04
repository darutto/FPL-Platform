"""i119 gate grader: do the answers to a transfer question push (urgency / danger)?

Decided by Leo (option C, 2026-10-04): neutral transfer vocabulary is fine
when the user asks about transfers («transfer», «¿qué jugador venderías?»);
the rule blocks urgency or danger («vende ya», «hay que sacarlo», «peligro»).
So this gate counts ``opportunity_framing.urgency_hits`` on the served text,
not raw ``transaction_hits`` (reported alongside, informational only). The
E3 chip grader is unchanged.

Usage:
  python scripts/grade_i119_clarification_urgency.py ARM.jsonl [ARM2.jsonl ...] [--ids ad-05]
Exit 0 when every arm has 0 rows with urgency hits.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

# opportunity_framing is pure stdlib; load it by path so this script runs
# without the package's import chain (as verify_i93_composed_prod.py does).
_OF_PATH = Path(__file__).resolve().parents[1] / "fpl_grounded_assistant" / "opportunity_framing.py"
_spec = importlib.util.spec_from_file_location("opportunity_framing", _OF_PATH)
_of = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_of)
transaction_hits = _of.transaction_hits
urgency_hits = _of.urgency_hits


def grade_row(row: dict) -> dict:
    text = row.get("answer_text_full") or row.get("answer_text") or ""
    return {
        "question_id": row.get("question_id"),
        "rep": row.get("rep"),
        "outcome": row.get("outcome"),
        "tool_sequence": row.get("tool_sequence"),
        "urgency_hits": urgency_hits(text),
        "transaction_hits": transaction_hits(text),
    }


def summarize(rows: list[dict], ids: set[str]) -> dict:
    graded = [grade_row(r) for r in rows if r.get("question_id") in ids and not r.get("exception")]
    return {
        "rows": len(graded),
        "urgency_rows": sum(bool(g["urgency_hits"]) for g in graded),
        "transaction_rows_informational": sum(bool(g["transaction_hits"]) for g in graded),
        "gate": bool(graded) and not any(g["urgency_hits"] for g in graded),
        "graded": graded,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arms", nargs="+")
    parser.add_argument("--ids", default="ad-05")
    args = parser.parse_args(argv)
    ids = set(args.ids.split(","))
    ok = True
    for arm in args.arms:
        rows = [json.loads(l) for l in Path(arm).read_text(encoding="utf-8").splitlines() if l.strip()]
        s = summarize(rows, ids)
        ok = ok and s["gate"]
        print(f"== {arm}")
        print(json.dumps({k: v for k, v in s.items() if k != "graded"}, indent=1))
        for g in s["graded"]:
            print(f"| {g['question_id']} | {g['rep']} | {g['outcome']} | urgency={g['urgency_hits']} "
                  f"| tx(info)={len(g['transaction_hits'])} |")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

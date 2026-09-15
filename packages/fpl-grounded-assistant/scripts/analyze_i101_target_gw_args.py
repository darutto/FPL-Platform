"""Read-out for measure_i101_target_gw_args.py JSONL files.

Per phrase (all reps): did every executed get_fixture_outlook call carry
``target_gw`` equal to the gameweek the phrase names, and did the tool's
produced series describe exactly that gameweek? A phrase is a HIT only when
every rep satisfies BOTH -- the argument being right is what i101 adds, the
series being right is what the user actually gets.

Three per-rep verdicts, read off the recorded trace (never off the question):

  arg_ok     every get_fixture_outlook call has target_gw == expected
  series_ok  the LAST get_fixture_outlook call's series is exactly [expected]
  routed     at least one get_fixture_outlook call executed

The BEFORE file (main, no target_gw in the catalog) is expected to show
arg_ok = 0 everywhere (the argument does not exist) and series_ok only where
the model's horizon arithmetic happened to land on the named GW as a window
-- which cannot be a single-GW series for lead >= 2, so series_ok = 0 too.

Usage:
    python scripts/analyze_i101_target_gw_args.py <before.jsonl> [<after.jsonl> ...]
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def load(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def rep_verdict(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("i101") or {}
    expected = meta.get("expected_target_gw")
    calls = meta.get("calls") or []
    routed = bool(calls)
    arg_ok = routed and all(c.get("target_gw") == expected for c in calls)
    last = calls[-1] if calls else {}
    series_ok = routed and list(last.get("series_gws") or []) == [expected]
    return {
        "expected": expected,
        "routed": routed,
        "arg_ok": bool(arg_ok),
        "series_ok": bool(series_ok),
        "target_gws": [c.get("target_gw") for c in calls],
        "horizons": [c.get("horizon") for c in calls],
        "series": [c.get("series_gws") for c in calls],
        "exception": row.get("exception"),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_q: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_q[r["question_id"]].append(rep_verdict(r))
    per_phrase: dict[str, dict[str, Any]] = {}
    for qid, reps in by_q.items():
        per_phrase[qid] = {
            "expected": reps[0]["expected"],
            "reps": len(reps),
            "routed": sum(1 for v in reps if v["routed"]),
            "arg_ok": sum(1 for v in reps if v["arg_ok"]),
            "series_ok": sum(1 for v in reps if v["series_ok"]),
            "hit": all(v["arg_ok"] and v["series_ok"] for v in reps),
            "target_gws": [v["target_gws"] for v in reps],
            "horizons": [v["horizons"] for v in reps],
            "series": [v["series"] for v in reps],
        }
    n = len(per_phrase)
    hits = sum(1 for p in per_phrase.values() if p["hit"])
    exceptions = sum(1 for r in rows if r.get("exception"))
    cost = round(sum(r.get("cost_usd") or 0 for r in rows), 4)
    return {
        "rows": len(rows), "phrases": n, "hits": hits, "exceptions": exceptions,
        "cost_usd": cost,
        "arg_ok_reps": sum(p["arg_ok"] for p in per_phrase.values()),
        "series_ok_reps": sum(p["series_ok"] for p in per_phrase.values()),
        "per_phrase": per_phrase,
    }


def print_summary(label: str, s: dict[str, Any]) -> None:
    print(f"=== {label}: {s['phrases']} phrases, {s['rows']} rows, {s['exceptions']} exceptions, ${s['cost_usd']}")
    print(f"    HITS (every rep arg_ok AND series_ok): {s['hits']}/{s['phrases']}  "
          f"| arg_ok reps {s['arg_ok_reps']}/{s['rows']} | series_ok reps {s['series_ok_reps']}/{s['rows']}")
    for qid, p in s["per_phrase"].items():
        flag = "HIT " if p["hit"] else "miss"
        print(f"    {flag} {qid:<24} J{p['expected']}  arg_ok {p['arg_ok']}/{p['reps']}  "
              f"series_ok {p['series_ok']}/{p['reps']}  target_gw={p['target_gws']}  "
              f"horizon={p['horizons']}  series={p['series']}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for path in argv:
        print_summary(Path(path).name, summarize(load(path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

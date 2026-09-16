"""Read-out for measure_i93_composed_content.py JSONL files.

Per phrase (all reps), three counts read off the recorded rows:

  composed   both get_fixture_outlook and get_team_snapshot ran in the round
  named      answer_text mentions >= 1 web_name the snapshot RETURNED
  clean      transaction_hits(answer_text) is empty

A phrase is a HIT only when EVERY rep is both ``named`` and ``clean`` --
naming a real player is what i93 adds, staying clean is the boundary it
must not cross. The BEFORE file (main catalog) is expected at 0 named
(no players tool ran) and, trivially, clean.

Usage:
    python scripts/analyze_i93_composed_content.py <before.jsonl> [<after.jsonl> ...]
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def load(path: str) -> list[dict[str, Any]]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def rep_verdict(row: dict[str, Any]) -> dict[str, Any]:
    m = row.get("i93") or {}
    # Recompute from the raw fields the row carries (answer_text + the names
    # the tool returned) so the verdict follows the current matcher, not the
    # one the run happened to import; falls back to the stored projection.
    if row.get("answer_text") is not None and m.get("snapshot_web_names") is not None:
        from measure_i93_composed_content import named_real_players  # noqa: PLC0415
        named = named_real_players(str(row["answer_text"]), list(m["snapshot_web_names"]))
    else:
        named = list(m.get("named_real_players") or [])
    hits = list(m.get("transaction_hits") or [])
    return {
        "composed": bool(m.get("composed")),
        "named": bool(named),
        "clean": not hits,
        "players": named,
        "hits": hits,
        "sequence": m.get("tool_sequence") or [],
        "exception": row.get("exception"),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_q: dict[str, list[dict[str, Any]]] = defaultdict(list)
    synthetic: dict[str, bool] = {}
    for r in rows:
        by_q[r["question_id"]].append(rep_verdict(r))
        synthetic[r["question_id"]] = bool((r.get("i78a") or {}).get("dgw_synthetic"))
    per: dict[str, dict[str, Any]] = {}
    for qid, reps in by_q.items():
        per[qid] = {
            "dgw_synthetic": synthetic.get(qid, False),
            "majority": sum(1 for v in reps if v["named"] and v["clean"]) * 2 >= len(reps),
            "reps": len(reps),
            "composed": sum(v["composed"] for v in reps),
            "named": sum(v["named"] for v in reps),
            "clean": sum(v["clean"] for v in reps),
            "hit": all(v["named"] and v["clean"] for v in reps),
            "players": [v["players"] for v in reps],
            "hits": [v["hits"] for v in reps],
            "sequences": [v["sequence"] for v in reps],
        }
    real = {q: p for q, p in per.items() if not p["dgw_synthetic"]}
    synth = {q: p for q, p in per.items() if p["dgw_synthetic"]}
    return {
        "rows": len(rows), "phrases": len(per),
        "hits": sum(1 for p in per.values() if p["hit"]),
        "majority_hits": sum(1 for p in per.values() if p["majority"]),
        # The i78-A corpus carries synthetic DGW cells (a second fixture
        # appended to the phrase that the frozen bootstrap does not have).
        # They exist to test routing under "doble jornada" wording; for a
        # CONTENT read the data contradicts the question, so they are
        # reported apart, never silently dropped.
        "real_cells": len(real), "real_hits": sum(1 for p in real.values() if p["hit"]),
        "synthetic_dgw_cells": len(synth), "synthetic_dgw_hits": sum(1 for p in synth.values() if p["hit"]),
        "composed_reps": sum(p["composed"] for p in per.values()),
        "named_reps": sum(p["named"] for p in per.values()),
        "clean_reps": sum(p["clean"] for p in per.values()),
        "transaction_hit_reps": sum(p["reps"] - p["clean"] for p in per.values()),
        "exceptions": sum(1 for r in rows if r.get("exception")),
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 4),
        "per_phrase": per,
    }


def print_summary(label: str, s: dict[str, Any]) -> None:
    print(f"=== {label}: {s['phrases']} phrases, {s['rows']} rows, {s['exceptions']} exceptions, ${s['cost_usd']}")
    print(f"    real cells (data matches the phrase): {s['real_hits']}/{s['real_cells']} strict "
          f"| synthetic DGW cells (phrase claims a DGW the data lacks): {s['synthetic_dgw_hits']}/{s['synthetic_dgw_cells']} strict "
          f"| majority (>=2/3 reps) over all: {s['majority_hits']}/{s['phrases']}")
    print(f"    HITS (every rep names a returned player AND is clean): {s['hits']}/{s['phrases']}  "
          f"| composed reps {s['composed_reps']}/{s['rows']} | named reps {s['named_reps']}/{s['rows']} "
          f"| clean reps {s['clean_reps']}/{s['rows']} | reps with transaction words {s['transaction_hit_reps']}")
    for qid, p in s["per_phrase"].items():
        flag = "HIT " if p["hit"] else "miss"
        tag = " [synthetic DGW]" if p["dgw_synthetic"] else ""
        print(f"    {flag} {qid:<24}{tag} composed {p['composed']}/{p['reps']} named {p['named']}/{p['reps']} "
              f"clean {p['clean']}/{p['reps']}  players={p['players']}  hits={p['hits']}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for path in argv:
        print_summary(Path(path).name, summarize(load(path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

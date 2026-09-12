"""i82 before/after read-out for the ``season_history`` routing family.

Denominator, fixed in the PR before either run: every phrase runs R times
(3); a phrase "hits" when >= 2/R runs pick a tool in its acceptable set
(per-phrase majority, so one noisy run cannot decide). Reported:

  * per new tool: hits / targets (criterion >= 80 %)
  * controls: how many phrases' MAJORITY is a tool in their forbidden set
    (criterion: zero -- what NEWLY resolves, not only what still fails)
  * the raw R x N table, so the aggregate cannot hide a 2/3 that flips

Usage:
    python scripts/analyze_i82_season_routing.py before.jsonl [after.jsonl]
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

NEW_TOOLS = ("get_player_season_points", "get_historical_gameweek_top_scorer")


def _forbidden_by_id() -> dict[str, set[str]]:
    """``forbidden_tools`` lives only in the corpus (the measurement row does
    not carry it), so it is joined back by question id here."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from tool_routing_corpus import CORPUS  # noqa: PLC0415
    return {q["id"]: set(q.get("forbidden_tools") or []) for q in CORPUS}


def _load(path: str) -> list[dict]:
    rows = []
    forbidden = _forbidden_by_id()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            r["forbidden_tools"] = sorted(forbidden.get(r.get("question_id"), set()))
            rows.append(r)
    return [r for r in rows if r.get("family") == "season_history"]


def _first_tool(r: dict) -> str | None:
    seq = r.get("tool_sequence") or []
    return seq[0] if seq else r.get("tool_chosen")


def summarize(rows: list[dict]) -> dict:
    by_q: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_q[r["question_id"]].append(r)

    table = []
    per_tool_hits: Counter = Counter()
    per_tool_n: Counter = Counter()
    control_migrations = []
    for qid in sorted(by_q):
        obs = by_q[qid]
        picks = [_first_tool(o) for o in obs]
        acceptable = set(obs[0].get("acceptable_tools") or [])
        forbidden = set(obs[0].get("forbidden_tools") or [])
        majority_tool, majority_n = Counter(p for p in picks if p).most_common(1)[0] if any(picks) else (None, 0)
        hit = sum(1 for p in picks if p in acceptable) * 2 >= len(picks)  # >= R/2 of R (2 of 3)
        target = next((t for t in NEW_TOOLS if t in acceptable), None)
        if target:
            per_tool_n[target] += 1
            per_tool_hits[target] += int(hit)
        elif majority_tool in forbidden and majority_n * 2 >= len(picks):
            control_migrations.append((qid, majority_tool, picks))
        table.append((qid, obs[0]["question"], acceptable, picks, hit))

    return {
        "table": table,
        "per_tool": {t: (per_tool_hits[t], per_tool_n[t]) for t in NEW_TOOLS},
        "control_migrations": control_migrations,
        "exceptions": sum(1 for r in rows if r.get("exception")),
        "cost_usd": sum(r.get("cost_usd") or 0.0 for r in rows),
        "n_calls": len(rows),
    }


def print_summary(label: str, s: dict) -> None:
    print(f"=== {label}: {s['n_calls']} calls, {s['exceptions']} exceptions, ${s['cost_usd']:.4f} ===")
    for t, (h, n) in s["per_tool"].items():
        pct = (100.0 * h / n) if n else 0.0
        print(f"  {t}: {h}/{n} phrases hit by majority ({pct:.0f}%)")
    print(f"  control phrases whose MAJORITY is a forbidden tool: {len(s['control_migrations'])}")
    for qid, tool, picks in s["control_migrations"]:
        print(f"    {qid}: majority={tool} picks={picks}")
    print("  raw table (id | picks | hit):")
    for qid, q, acc, picks, hit in s["table"]:
        print(f"    {qid:7s} {'HIT ' if hit else 'miss'} {picks}  <- {sorted(acc)}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for path in argv:
        print_summary(Path(path).name, summarize(_load(path)))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

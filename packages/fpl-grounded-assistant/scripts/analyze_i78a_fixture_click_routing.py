"""i78-A before/after read-out for the ``fixture_click`` routing family.

Denominator, fixed before the first run:

  * every phrase runs R times (3), fixed order;
  * a canonical phrase HITS when ALL R runs pick ``get_fixture_outlook`` as
    the FIRST tool AND ``get_fixtures_for_gw`` appears nowhere in the tool
    sequence of any run (the plan's "3/3 to the expected tool, never the
    gameweek dump"). Stricter than i82's 2-of-3 majority, on purpose: the
    surface is a tap, and one dump in three taps is what the card reported;
  * a control MIGRATES when its majority first tool is one of the two tools
    whose descriptions i78-A rewrites (``get_fixture_outlook``,
    ``get_fixtures_for_gw``) and that tool is not in its acceptable set; the
    i82 ``forbidden_tools`` criterion is reported alongside so the two new
    season tools are still watched.

Everything is read from the JSONL rows the driver wrote, never from the
corpus that requested them: a phrase's picks, its sequence, and the cost are
what the run produced. The raw R x N table is printed so a 2/3 cannot hide
inside an aggregate.

Usage:
    python scripts/analyze_i78a_fixture_click_routing.py before.jsonl [after.jsonl ...]
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED = "get_fixture_outlook"
DUMP = "get_fixtures_for_gw"
TOUCHED = (EXPECTED, DUMP)
FAMILY = "fixture_click"


def _load(path: str) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _first_tool(r: dict) -> str | None:
    seq = r.get("tool_sequence") or []
    return seq[0] if seq else r.get("tool_chosen")


def _reached(r: dict, tool: str) -> bool:
    return tool in (r.get("tool_sequence") or [])


def summarize(rows: list[dict]) -> dict:
    by_q: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_q[r["question_id"]].append(r)

    canonical_table = []
    control_table = []
    hits_by_kind: Counter = Counter()
    n_by_kind: Counter = Counter()
    reached_by_kind: Counter = Counter()
    dump_rows = 0
    migrations_touched = []
    migrations_forbidden = []

    # Preserve the driver's order (canonical first, controls after) by first
    # appearance rather than sorting ids.
    order: list[str] = []
    for r in rows:
        if r["question_id"] not in order:
            order.append(r["question_id"])

    for qid in order:
        obs = by_q[qid]
        picks = [_first_tool(o) for o in obs]
        seqs = [o.get("tool_sequence") or [] for o in obs]
        acceptable = set(obs[0].get("acceptable_tools") or [])
        forbidden = set(obs[0].get("forbidden_tools") or [])
        dumps = sum(1 for o in obs if _reached(o, DUMP))
        dump_rows += dumps
        counted = Counter(p for p in picks if p)
        majority_tool, majority_n = counted.most_common(1)[0] if counted else (None, 0)

        if obs[0].get("family") == FAMILY:
            meta = obs[0].get("i78a") or {}
            kind = meta.get("kind", "?")
            if meta.get("cell_position") == "future":
                kind = f"{kind} (future cell)"
            hit = all(p == EXPECTED for p in picks) and dumps == 0
            reached = sum(1 for o in obs if _reached(o, EXPECTED))
            n_by_kind[kind] += 1
            hits_by_kind[kind] += int(hit)
            reached_by_kind[kind] += int(reached == len(obs))
            canonical_table.append((qid, kind, picks, seqs, dumps, hit, obs[0]["question"]))
        else:
            migrated_touched = (
                majority_tool in TOUCHED
                and majority_tool not in acceptable
                and majority_n * 2 >= len(picks)
            )
            migrated_forbidden = majority_tool in forbidden and majority_n * 2 >= len(picks)
            if migrated_touched:
                migrations_touched.append((qid, majority_tool, picks))
            if migrated_forbidden:
                migrations_forbidden.append((qid, majority_tool, picks))
            ok = sum(1 for p in picks if p in acceptable)
            control_table.append((qid, picks, ok, sorted(acceptable), obs[0]["question"]))

    return {
        "canonical_table": canonical_table,
        "control_table": control_table,
        "by_kind": {k: (hits_by_kind[k], n_by_kind[k], reached_by_kind[k]) for k in n_by_kind},
        "dump_rows": dump_rows,
        "migrations_touched": migrations_touched,
        "migrations_forbidden": migrations_forbidden,
        "exceptions": sum(1 for r in rows if r.get("exception")),
        "empty_provider": sum(1 for r in rows if r.get("empty_provider_response")),
        "cost_usd": sum(r.get("cost_usd") or 0.0 for r in rows),
        "n_calls": len(rows),
        "models": sorted({f"{r.get('provider')}/{r.get('model')}" for r in rows}),
        "corpus_sha": sorted({json.dumps(r.get("corpus_sha256"), sort_keys=True) for r in rows}),
    }


def print_summary(label: str, s: dict) -> None:
    print(f"=== {label}: {s['n_calls']} calls, {s['exceptions']} exceptions, "
          f"{s['empty_provider']} empty-provider rows, ${s['cost_usd']:.4f}, "
          f"model={s['models']} ===")
    for sha in s["corpus_sha"]:
        print(f"  corpus sha256: {sha}")
    total_hit = sum(h for h, _, _ in s["by_kind"].values())
    total_n = sum(n for _, n, _ in s["by_kind"].values())
    print(f"  canonical phrases 3/3 to {EXPECTED} with no {DUMP} anywhere: {total_hit}/{total_n}")
    for kind, (h, n, reached) in s["by_kind"].items():
        print(f"    {kind}: {h}/{n} hit; {reached}/{n} reached {EXPECTED} in all runs")
    print(f"  rows whose sequence contains {DUMP}: {s['dump_rows']}")
    print(f"  controls whose MAJORITY migrated into a touched tool: {len(s['migrations_touched'])}")
    for qid, tool, picks in s["migrations_touched"]:
        print(f"    {qid}: majority={tool} picks={picks}")
    print(f"  controls whose MAJORITY is an i82-forbidden tool: {len(s['migrations_forbidden'])}")
    for qid, tool, picks in s["migrations_forbidden"]:
        print(f"    {qid}: majority={tool} picks={picks}")
    print("  raw canonical table (id | kind | first picks | dumps | hit | sequences):")
    for qid, kind, picks, seqs, dumps, hit, _q in s["canonical_table"]:
        print(f"    {qid:26s} {kind:38s} {'HIT ' if hit else 'miss'} dumps={dumps} {picks}  seq={seqs}")
    print("  raw control table (id | picks | acceptable-of-R | acceptable):")
    for qid, picks, ok, acc, _q in s["control_table"]:
        print(f"    {qid:8s} {ok}/{len(picks)} {picks}  <- {acc}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for path in argv:
        print_summary(Path(path).name, summarize(_load(path)))
        print()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main(sys.argv[1:]))

"""i100 read-out: /ask vs /session/{id}/ask on the i78-A matrix.

Everything is read from the rows ``measure_i100_session_route_parity.py``
wrote -- what each route actually selected and executed -- never from the
corpus that requested it. Criteria, fixed before the run:

* a canonical phrase HITS on a route when ALL R reps pick
  ``get_fixture_outlook`` as the FIRST tool AND ``get_fixtures_for_gw``
  appears in no sequence (the i78-A criterion, unchanged);
* the two routes AGREE on a rep when ``selected_tool`` and the executed
  ``tool_sequence`` are identical; a phrase is PARITY when all R reps agree;
* a control migrates when its majority first tool on a route is outside its
  acceptable set (reported per route);
* ``rewritten_question`` is counted as ECHO when it equals the phrase sent
  (a fresh session has nothing to resolve) and REWRITE otherwise -- the only
  work the session path does before ``ask_v2`` that /ask does not.

The raw R x N table is printed per route so a 2/3 cannot hide in an aggregate.

Usage:
    python scripts/analyze_i100_session_route_parity.py <jsonl>
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED = "get_fixture_outlook"
DUMP = "get_fixtures_for_gw"
ROUTES = ("ask", "session")


def _load(path: str) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if "_header" not in r:
                rows.append(r)
    return rows


def _first(o: dict) -> str | None:
    seq = o.get("tool_sequence") or []
    return seq[0] if seq else o.get("selected_tool")


def summarize(rows: list[dict]) -> dict:
    by_q: dict[str, list[dict]] = defaultdict(list)
    order: list[str] = []
    for r in rows:
        if r["question_id"] not in order:
            order.append(r["question_id"])
        by_q[r["question_id"]].append(r)

    hits = {rt: Counter() for rt in ROUTES}
    n_kind: Counter = Counter()
    parity_by_kind: Counter = Counter()
    agree_reps = 0
    total_reps = 0
    dump_rows = {rt: 0 for rt in ROUTES}
    exceptions = {rt: 0 for rt in ROUTES}
    echo = rewrite = 0
    migrations = {rt: [] for rt in ROUTES}
    table: list[str] = []
    disagreements: list[str] = []

    for qid in order:
        obs = by_q[qid]
        kind = obs[0].get("kind") or ("control" if obs[0].get("control") else "?")
        acceptable = set(obs[0].get("acceptable_tools") or [])
        is_canonical = obs[0].get("family") == "fixture_click"
        picks = {rt: [_first(o[rt]) for o in obs] for rt in ROUTES}
        seqs = {rt: [o[rt].get("tool_sequence") or [] for o in obs] for rt in ROUTES}
        for rt in ROUTES:
            dump_rows[rt] += sum(DUMP in s for s in seqs[rt])
            exceptions[rt] += sum(o[rt].get("exception") is not None for o in obs)
        for o in obs:
            rq = o["session"].get("rewritten_question")
            if rq is None or rq == o["question"]:
                echo += 1
            else:
                rewrite += 1
        agrees = [
            o["ask"].get("selected_tool") == o["session"].get("selected_tool")
            and (o["ask"].get("tool_sequence") or []) == (o["session"].get("tool_sequence") or [])
            for o in obs
        ]
        agree_reps += sum(agrees)
        total_reps += len(agrees)
        if is_canonical:
            n_kind[kind] += 1
            for rt in ROUTES:
                if all(p == EXPECTED for p in picks[rt]) and not any(DUMP in s for s in seqs[rt]):
                    hits[rt][kind] += 1
            if all(agrees):
                parity_by_kind[kind] += 1
        else:
            for rt in ROUTES:
                maj = Counter(picks[rt]).most_common(1)[0][0]
                if maj is not None and maj not in acceptable:
                    migrations[rt].append((qid, maj))
        table.append(f"{qid:16} {kind:20} ask={picks['ask']}  session={picks['session']}  agree={agrees}")
        for i, ok in enumerate(agrees):
            if not ok:
                o = obs[i]
                disagreements.append(
                    f"{qid} r{o['rep']}: ask={o['ask'].get('selected_tool')} {o['ask'].get('tool_sequence')} | "
                    f"session={o['session'].get('selected_tool')} {o['session'].get('tool_sequence')}"
                )

    return {
        "n_by_kind": dict(n_kind), "hits": {rt: dict(hits[rt]) for rt in ROUTES},
        "parity_by_kind": dict(parity_by_kind), "agree_reps": agree_reps, "total_reps": total_reps,
        "dump_rows": dump_rows, "exceptions": exceptions, "rewritten_echo": echo, "rewritten_rewrite": rewrite,
        "migrations": migrations, "table": table, "disagreements": disagreements,
    }


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    rows = _load(argv[0])
    s = summarize(rows)
    print(f"rows: {len(rows)} (= reps x phrases); reps agreeing on selected_tool+sequence: {s['agree_reps']}/{s['total_reps']}")
    print(f"exceptions: {s['exceptions']}   dump rows (get_fixtures_for_gw anywhere): {s['dump_rows']}")
    print(f"session rewritten_question: echo={s['rewritten_echo']} rewrite={s['rewritten_rewrite']}")
    print("\ncanonical hits (all reps -> get_fixture_outlook first, never the dump) per route, and route parity:")
    for kind, n in s["n_by_kind"].items():
        print(f"  {kind:22} ask {s['hits']['ask'].get(kind, 0)}/{n}   session {s['hits']['session'].get(kind, 0)}/{n}   parity {s['parity_by_kind'].get(kind, 0)}/{n}")
    print(f"\ncontrols migrated: ask={s['migrations']['ask']}  session={s['migrations']['session']}")
    print("\nR x N table:")
    for line in s["table"]:
        print("  " + line)
    if s["disagreements"]:
        print("\ndisagreeing reps:")
        for d in s["disagreements"]:
            print("  " + d)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

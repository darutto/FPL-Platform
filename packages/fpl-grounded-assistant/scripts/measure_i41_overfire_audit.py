"""i41 over-fire audit: does the widened get_my_squad trigger reach anything it
should not?

OBSERVATION ONLY — deliberately NOT the pre-registered gate, which lives in
measure_i41_ownership_triggers.py and must stay untouched so the decision rule
cannot be edited after seeing results. This script exists because the gate uses
3 negative controls (15 calls) while the asset being protected is PR #171's
"0 over-fires in 30 negative calls", and because widening a trigger obliges an
audit of what fires now that did not before, not just a check that the target
finally fires.

Questions are chosen to stress the *specific* wording that was added:

*   ``tf-09`` and ``pv-09`` open with "Necesito saber…" — the new description
    names "necesito 4 medios" as a trigger, so an over-generalisation on the
    verb alone would show up here first.
*   ``pv-01`` asks about a player's **ownership**, a possession word that refers
    to the market rather than to the user.
*   ``pv-10`` asks about injury availability, which the description lists among
    the fields this tool returns.

The rest are ordinary market/fixture/captaincy questions with no personal
reference at all. Every one of them must stay at 0 get_my_squad calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import measure_tool_routing as base  # noqa: E402
import measure_squad_tool_routing as squad  # noqa: E402

TOOL = "get_my_squad"

AUDIT_IDS = [
    "tf-09",  # "Necesito saber qué equipos..." — verb-only over-generalisation
    "pv-09",  # "Necesito saber si Enzo Fernández..." — same
    "pv-01",  # "...cuál es su ownership actual?" — possession, but the market's
    "pv-10",  # "¿Está disponible Rodri o sigue lesionado?" — availability field
    "tf-02",  # plain fixture-difficulty question
    "pv-13",  # plain price/position question
    "cp-01",  # plain captaincy question
    "tf-12",  # plain defensive-fixture question
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bootstrap", default=str(base.DEFAULT_BOOTSTRAP))
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    base._configure_imports()
    base._load_env_file(base.PACKAGE_ROOT / ".env")

    import os
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set; aborting before any paid call.", file=sys.stderr)
        return 2

    from tool_routing_corpus import CORPUS
    by_id = {q["id"]: q for q in CORPUS}
    missing = [i for i in AUDIT_IDS if i not in by_id]
    if missing:
        raise SystemExit(f"ids not in corpus: {missing}")
    questions = [by_id[i] for i in AUDIT_IDS]

    bootstrap = dict(json.loads(Path(args.bootstrap).read_text(encoding="utf-8")))
    bootstrap["_my_team_id"] = squad.TEAM_ID  # worst case: a team IS connected

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = len(questions) * args.reps
    print(f"i41 over-fire audit: {len(questions)} questions x {args.reps} reps = {total} "
          f"calls, team_connected (id={squad.TEAM_ID})", file=sys.stderr)

    fires: dict[str, int] = defaultdict(int)
    excs = 0
    cost = 0.0
    with out_path.open("a", encoding="utf-8") as fh:
        for q in questions:
            for rep in range(args.reps):
                obs = base.run_one(q, rep, bootstrap, api_key)
                obs["condition"] = "team_connected"
                obs["label"] = "overfire_audit"
                fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
                fh.flush()
                cost += obs["cost_usd"]
                if obs["exception"] is not None:
                    excs += 1
                elif TOOL in (obs.get("tool_sequence") or []):
                    fires[q["id"]] += 1

    print(f"\ncost: ${cost:.4f}   exceptions: {excs}", file=sys.stderr)
    print(f"\n--- OVER-FIRE AUDIT ({total} negative calls, all must be 0) ---")
    for qid in AUDIT_IDS:
        flag = "  <-- OVER-FIRE" if fires[qid] else ""
        print(f"  {qid:<8} {TOOL} {fires[qid]}/{args.reps}{flag}")
    total_fires = sum(fires.values())
    print(f"\n  total over-fires: {total_fires}/{total}")
    return 1 if total_fires or excs else 0


if __name__ == "__main__":
    raise SystemExit(main())

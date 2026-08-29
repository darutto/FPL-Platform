"""i41: does ``get_my_squad`` fire on ownership expressed WITHOUT a possessive?

MEASUREMENT ONLY. Imports ``measure_tool_routing.run_one()`` and
``measure_squad_tool_routing``'s negative controls and TEAM_ID unchanged, so
the call path and the "team connected" injection are identical to the #171
measurement this is compared against.

Scope is the six cases the i41 brief pre-registered, ``team_connected`` only
(the defect is about a connected user whose phrasing lacks a possessive, so the
no-team condition measures nothing here):

  target  sb-02, sb-13     -- must reach >= 4/5 get_my_squad calls
  guard   neg-defensas, neg-comparar, neg-jornada -- must stay 0/5
  observe ad-05            -- reported, explicitly NOT a gate

The decision rule was written before any call was made and lives in the brief:
**the guard outranks the target.** A single over-fire on any negative control
rejects the change even at 5/5 on both targets, because a false fire injects
someone's squad into a general question -- it dirties the context, costs more,
and can bias the answer. Failing to call is cheaper than calling wrongly.

Usage (from packages/fpl-grounded-assistant):

    python scripts/measure_i41_ownership_triggers.py \
        --out ../../field-notes/artifacts/i41-pre.jsonl --reps 5 --label pre
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import measure_tool_routing as base  # noqa: E402
import measure_squad_tool_routing as squad  # noqa: E402

TOOL = "get_my_squad"

#: Pre-registered targets: ownership without a possessive.
TARGET_IDS = ["sb-02", "sb-13"]

#: Pre-registered observation, no gate. ad-05 is underdetermined between two
#: advice tools and was so before get_my_squad existed.
OBSERVE_IDS = ["ad-05"]

#: Pre-registered guard. Any fire here rejects the change.
GUARD_IDS = [q["id"] for q in squad.NEGATIVE_CONTROLS]


def _questions() -> list[dict[str, Any]]:
    from tool_routing_corpus import CORPUS

    by_id = {q["id"]: q for q in CORPUS}
    missing = [i for i in TARGET_IDS + OBSERVE_IDS if i not in by_id]
    if missing:
        raise SystemExit(f"ids not in corpus: {missing}")
    return (
        [by_id[i] for i in TARGET_IDS + OBSERVE_IDS]
        + list(squad.NEGATIVE_CONTROLS)
    )


def summarise(observations: list[dict[str, Any]], reps: int) -> int:
    """Print the pre-registered verdict. Returns a process exit code."""
    fires: dict[str, int] = defaultdict(int)
    no_tool: dict[str, int] = defaultdict(int)
    excs: dict[str, int] = defaultdict(int)
    for obs in observations:
        qid = obs["question_id"]
        if obs["exception"] is not None:
            excs[qid] += 1
            continue
        if TOOL in (obs.get("tool_sequence") or []):
            fires[qid] += 1
        if not (obs.get("tool_sequence") or []):
            no_tool[qid] += 1

    def row(qid: str) -> str:
        return (f"  {qid:<14} {TOOL} {fires[qid]}/{reps}"
                f"   no-tool {no_tool[qid]}/{reps}"
                f"{'   EXCEPTIONS ' + str(excs[qid]) if excs[qid] else ''}")

    print("\n--- TARGET (needs >= 4/5 each) ---")
    for qid in TARGET_IDS:
        print(row(qid))
    print("\n--- GUARD (needs 0/5 each; outranks target) ---")
    for qid in GUARD_IDS:
        print(row(qid))
    print("\n--- OBSERVATION ONLY (not a gate) ---")
    for qid in OBSERVE_IDS:
        print(row(qid))

    target_ok = all(fires[q] >= 4 for q in TARGET_IDS)
    guard_ok = all(fires[q] == 0 for q in GUARD_IDS)
    total_exc = sum(excs.values())

    print("\n=== VERDICT ===")
    print(f"  target met: {target_ok}   guard held: {guard_ok}   exceptions: {total_exc}")
    if total_exc:
        print("  INVALID -- exceptions present, do not trust these counts.")
        return 3
    if not guard_ok:
        print("  REJECT -- a negative control fired. Guard outranks target.")
        return 1
    if not target_ok:
        print("  REJECT -- guard held but the target was not reached.")
        return 1
    print("  ACCEPT -- guard held and both targets reached.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bootstrap", default=str(base.DEFAULT_BOOTSTRAP))
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", required=True, help="pre | post — recorded in each row")
    args = ap.parse_args(argv)

    base._configure_imports()
    base._load_env_file(base.PACKAGE_ROOT / ".env")

    import os
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set; aborting before any paid call.", file=sys.stderr)
        return 2

    questions = _questions()
    raw = json.loads(Path(args.bootstrap).read_text(encoding="utf-8"))
    bootstrap = dict(raw)
    bootstrap["_my_team_id"] = squad.TEAM_ID

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = len(questions) * args.reps
    print(f"i41 [{args.label}]: {len(questions)} questions x {args.reps} reps = {total} calls "
          f"against {base.PROVIDER}/{base.MODEL}, team_connected (id={squad.TEAM_ID})",
          file=sys.stderr)

    observations: list[dict[str, Any]] = []
    cost = 0.0
    with out_path.open("a", encoding="utf-8") as fh:
        for q in questions:
            for rep in range(args.reps):
                obs = base.run_one(q, rep, bootstrap, api_key)
                obs["condition"] = "team_connected"
                obs["team_id"] = squad.TEAM_ID
                obs["label"] = args.label
                fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
                fh.flush()
                observations.append(obs)
                cost += obs["cost_usd"]
        print(f"  {len(observations)}/{total} done, ${cost:.4f}", file=sys.stderr)

    print(f"\ncost: ${cost:.4f}", file=sys.stderr)
    return summarise(observations, args.reps)


if __name__ == "__main__":
    raise SystemExit(main())

"""i46: did the bounded extra round actually reduce the defect?

MEASUREMENT ONLY. Makes real, paid LLM calls. Not a gate, not wired to CI,
and it does not touch the i25 golden battery or its reference row.

Reuses ``measure_i46_synthesis_instrument`` (PR #198) unchanged for the
per-provider-call capture -- finish_reason, the usage breakdown and the
tool-payload bytes -- so a row here and a row there are directly comparable.

Why PAIRED, and what that rules out
-----------------------------------
The historical 5.2% cannot be the "before" number: it was measured on a
different corpus, on a different date, against a different bootstrap. Two
rates gathered that far apart differ for reasons that have nothing to do with
this change. So both arms run **inside one session, interleaved rep by rep on
the same questions**, and only that pairing is reported as the result.

How the "before" arm exists at all
----------------------------------
The fix is unconditional in the product -- no flag, no env var, by design. So
the BEFORE arm is produced by the *instrument*, not the product: it patches
``orchestrator._run_synthesis_extra_round`` to a stub returning "no text, no
tokens", which is exactly the pre-fix control flow. Nothing about the product
becomes configurable to make this measurable.

Note this isolates (b) from (c) for free. The stub suppresses only the extra
round; the (c) notice still prefixes the fallback render in both arms. Since
the measured signal is ``synthesis_turn``, which the notice never sets, the
rate difference between arms is attributable to (b) alone. (c) is a
presentation change and is reported separately, never as evidence that (b)
worked.

Pre-registered, written before any call was made
------------------------------------------------
    Success   rate_after <= (1/3) * rate_before, paired, same session
    Guard     0 extra calls on turns whose synthesis already returned text
    Report    turns rescued, turns that still reached (c), and the token and
              cost delta per affected turn

The guard outranks the success criterion. An extra call on a healthy turn is
money spent on every good answer to fix a minority defect; failing to rescue
is merely the status quo.

Usage (from packages/fpl-grounded-assistant):

    python scripts/measure_i46_fix_paired.py \
        --out ../../field-notes/artifacts/i46-fix-paired.jsonl --reps 10
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import measure_tool_routing as base  # noqa: E402
import measure_i46_synthesis_instrument as inst  # noqa: E402

PROVIDER = inst.PROVIDER
MODEL = inst.MODEL

#: Production settings. The server never passes max_tokens, so ask_v2() takes
#: ask_orchestrated's default of 1024 -- measuring at anything else would be
#: measuring a configuration nobody runs.
PROD_MAX_TOKENS = inst.PROD_MAX_TOKENS

EST_USD_PER_CALL = inst.EST_USD_PER_CALL

#: Pre-registered success ratio: the after-rate must be at most a third of the
#: before-rate. Compared by exact cross-multiplication, never by dividing two
#: float rates -- 2/10 vs 6/10 is exactly a third, and in binary floats that
#: comparison goes the wrong way.
SUCCESS_DIVISOR = 3

#: The confirmed repro (6/9 across three battery runs, 9/10 in PR #198's probe).
TARGET_ID = "gw-04"

#: The guard population: a ranking question whose synthesis has never failed
#: (0/52 across the i18/i19/i42 probes). Turns like this must make no extra
#: call at all -- that is where the cost of a wrong fix would land.
GUARD_ID = "sb-04"


def _stub_extra_round(**_kwargs: Any) -> tuple[None, int, int, int]:
    """The pre-fix control flow: no extra round, no text, no tokens."""
    return None, 0, 0, 0


def _run_arm(
    question: dict[str, Any],
    rep: int,
    bootstrap: dict[str, Any],
    api_key: str,
    arm: str,
) -> dict[str, Any]:
    """One observation. ``arm`` is "before" (fix stubbed out) or "after"."""
    from fpl_grounded_assistant import orchestrator as orch_mod

    real = orch_mod._run_synthesis_extra_round
    if arm == "before":
        orch_mod._run_synthesis_extra_round = _stub_extra_round
    try:
        obs = inst.run_one(question, rep, bootstrap, api_key, PROD_MAX_TOKENS)
    finally:
        orch_mod._run_synthesis_extra_round = real

    obs["arm"] = arm
    calls = obs.get("provider_calls") or []
    obs["provider_call_count"] = len(calls)
    # An extra round happened iff a third provider call was made.
    obs["extra_round_fired"] = len(calls) >= 3
    obs["rescued"] = bool(obs.get("synthesis_turn")) and obs["extra_round_fired"]
    # Real usage summed from the per-call capture, independent of the
    # orchestrator's own token accounting, so the cost delta is ground truth
    # either way. (The fix also corrects an accounting under-count on this
    # path; measuring from the trace means that correction cannot inflate the
    # reported delta.)
    obs["usage_in"] = sum((c.get("usage_input_tokens") or 0) for c in calls)
    obs["usage_out"] = sum((c.get("usage_output_tokens") or 0) for c in calls)
    obs["usage_cached"] = sum((c.get("usage_cached_tokens") or 0) for c in calls)
    obs["usage_cost_usd"] = base.cost_usd(
        obs["usage_in"], obs["usage_out"], obs["usage_cached"]
    )
    return obs


def _scored(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only turns that executed a tool: a turn with no tool cannot fail
    synthesis and would only dilute the denominator."""
    return [
        r for r in rows
        if r.get("exception") is None and (r.get("tool_sequence") or [])
    ]


def _rate(rows: list[dict[str, Any]]) -> tuple[int, int]:
    return sum(1 for r in rows if not r.get("synthesis_turn")), len(rows)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarise(observations: list[dict[str, Any]], reps: int) -> int:
    print("\n=== i46 FIX -- PAIRED MEASUREMENT ===")
    n_exc = sum(1 for o in observations if o.get("exception"))
    if n_exc:
        print(f"  WARNING: {n_exc} exception(s). An excepted observation is not "
              f"evidence either way; read the rows before trusting a cell.")

    target = _scored([o for o in observations if o["question_id"] == TARGET_ID])
    guard = _scored([o for o in observations if o["question_id"] == GUARD_ID])

    before = [o for o in target if o["arm"] == "before"]
    after = [o for o in target if o["arm"] == "after"]
    b_n, b_d = _rate(before)
    a_n, a_d = _rate(after)

    print(f"\n  --- THE TWO PAIRED FIGURES ({TARGET_ID}, same session) ---")
    print(f"  {'arm':>7} {'n':>4} {'synth=False':>12} {'rate':>7}")
    for label, (n, d) in (("before", (b_n, b_d)), ("after", (a_n, a_d))):
        print(f"  {label:>7} {d:>4} {n:>12} {(f'{n/d:.0%}' if d else 'n/a'):>7}")

    # --- Success criterion, exact integer comparison ---
    if b_d == 0 or a_d == 0:
        verdict = "UNDETERMINED"
        detail = "an arm has no scored turns"
    elif b_n == 0:
        verdict = "UNDETERMINED"
        detail = ("the before-arm did not reproduce the defect at all, so "
                  "there was nothing to reduce -- this run measures nothing")
    else:
        ok = a_n * b_d * SUCCESS_DIVISOR <= b_n * a_d
        verdict = "MET" if ok else "NOT MET"
        detail = f"{a_n}/{a_d} vs {b_n}/{b_d}, target <= 1/{SUCCESS_DIVISOR} of before"
    print(f"\n  SUCCESS: {verdict} -- {detail}")

    # --- Guard ---
    guard_extra = [o for o in guard if o["extra_round_fired"]]
    healthy_extra = [
        o for o in observations
        if o.get("synthesis_turn") and o.get("provider_call_count", 0) >= 3
        and not o.get("extra_round_fired")
    ]
    print(f"\n  --- GUARD (outranks success) ---")
    print(f"  {GUARD_ID}: {len(guard)} scored turns, "
          f"{len(guard_extra)} made an extra call")
    g_before = [o for o in guard if o["arm"] == "before"]
    g_after = [o for o in guard if o["arm"] == "after"]
    for label, rows in (("before", g_before), ("after", g_after)):
        counts = defaultdict(int)
        for o in rows:
            counts[o["provider_call_count"]] += 1
        print(f"    {label:>6}: provider calls per turn -> {dict(sorted(counts.items()))}")
    guard_held = len(guard_extra) == 0
    print(f"  GUARD: {'HELD' if guard_held else 'BROKEN'}")

    # --- (b): what the extra round actually did ---
    fired = [o for o in after if o["extra_round_fired"]]
    rescued = [o for o in fired if o["rescued"]]
    still_c = [o for o in after if not o.get("synthesis_turn")]
    print(f"\n  --- (b) THE EXTRA ROUND ---")
    print(f"  fired on          {len(fired)}/{len(after)} after-arm turns")
    print(f"  rescued (prose)   {len(rescued)}/{len(fired)} of those")
    print(f"  still reached (c) {len(still_c)}/{len(after)}")
    print("  NOTE: (c) is a presentation change. A turn that still lands on a "
          "marked render is NOT a success for (b); the two are reported apart.")

    # --- Cost of the change, on the turns that actually paid it ---
    print(f"\n  --- COST, per turn where the extra round fired ---")
    base_cost = _mean([o["usage_cost_usd"] for o in before])
    base_tok = _mean([float(o["usage_in"] + o["usage_out"]) for o in before])
    if fired:
        f_cost = _mean([o["usage_cost_usd"] for o in fired])
        f_tok = _mean([float(o["usage_in"] + o["usage_out"]) for o in fired])
        print(f"  before-arm mean: {base_tok:8.0f} tok  ${base_cost:.5f}")
        print(f"  fired    mean:   {f_tok:8.0f} tok  ${f_cost:.5f}")
        print(f"  delta:           {f_tok - base_tok:+8.0f} tok  "
              f"${f_cost - base_cost:+.5f} per affected turn")
    else:
        print("  the extra round never fired; no delta to report")
    unaffected = [o for o in after if not o["extra_round_fired"]]
    if unaffected:
        print(f"  unaffected after-arm turns: {len(unaffected)}, mean "
              f"{_mean([float(o['usage_in'] + o['usage_out']) for o in unaffected]):.0f} tok "
              f"(these must not move -- that is the guard, in tokens)")

    print("\n=== VERDICT ===")
    if n_exc:
        print("  INVALID -- exceptions present.")
        return 3
    if not guard_held:
        print("  REJECT -- an extra call fired on a turn that did not need one.")
        return 1
    if verdict == "MET":
        print("  ACCEPT -- guard held and the paired reduction met the criterion.")
        return 0
    print(f"  NOT ACCEPTED -- guard held, success {verdict}.")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bootstrap", default=str(base.DEFAULT_BOOTSTRAP))
    ap.add_argument("--reps", type=int, default=10,
                    help="10, not 3: cp-12 went 0/3, 0/3, 3/3 across battery runs.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--env-file", default=None)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args(argv)

    base._configure_imports()
    base._load_env_file(
        Path(args.env_file) if args.env_file else base.PACKAGE_ROOT / ".env"
    )
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set; aborting before any paid call.",
              file=sys.stderr)
        return 2

    from tool_routing_corpus import CORPUS
    by_id = {q["id"]: q for q in CORPUS}
    for qid in (TARGET_ID, GUARD_ID):
        if qid not in by_id:
            raise SystemExit(f"{qid} not in corpus")
    questions = [by_id[TARGET_ID], by_id[GUARD_ID]]

    bootstrap_path = Path(args.bootstrap)
    bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    boot_sha = inst._sha256(bootstrap_path)

    total_calls = len(questions) * args.reps * 2  # two arms
    est = total_calls * EST_USD_PER_CALL
    header = {
        "measurement": "i46-fix-paired",
        "provider": PROVIDER, "model": MODEL, "reps": args.reps,
        "max_tokens": PROD_MAX_TOKENS,
        "turns_planned": total_calls,
        "target_id": TARGET_ID, "guard_id": GUARD_ID,
        "success_divisor": SUCCESS_DIVISOR,
        "bootstrap_name": bootstrap_path.name, "bootstrap_sha256": boot_sha,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }
    print("=== i46 FIX PAIRED MEASUREMENT ===", file=sys.stderr)
    for k, v in header.items():
        print(f"  {k}: {v}", file=sys.stderr)
    print(f"  ESTIMATED COST: ${est:.4f} ({total_calls} turns; the after-arm "
          f"makes a 3rd call when the round fires, so real spend runs higher)",
          file=sys.stderr)

    if not args.yes:
        try:
            reply = input(f"Spend ~${est:.4f}? [y/N] ")
        except EOFError:
            print("No TTY; re-run with --yes.", file=sys.stderr)
            return 2
        if reply.strip().lower() not in ("y", "yes"):
            print("Aborted before any paid call.", file=sys.stderr)
            return 1

    capture = inst._ProviderEventCapture()
    logging.getLogger("fpl_grounded_assistant").addHandler(capture)
    logging.getLogger("fpl_grounded_assistant").setLevel(logging.INFO)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    observations: list[dict[str, Any]] = []
    spend = 0.0
    done = 0
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_header": header}, ensure_ascii=False) + "\n")
        fh.flush()
        # Interleaved: before/after alternate within each rep, so any provider
        # drift over the session lands on both arms equally instead of on
        # whichever one happened to run second.
        for question in questions:
            for rep in range(args.reps):
                for arm in ("before", "after"):
                    obs = _run_arm(question, rep, bootstrap, api_key, arm)
                    obs["_bootstrap_sha256"] = boot_sha
                    fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
                    fh.flush()
                    observations.append(obs)
                    spend += obs.get("usage_cost_usd") or 0.0
                    done += 1
                    if done % 10 == 0 or done == total_calls:
                        print(f"  {done}/{total_calls} turns, ${spend:.4f} so far",
                              file=sys.stderr)

    inst._verify_provider(capture.events, PROVIDER, MODEL)
    print(f"\nReal spend: ${spend:.4f}   provider events checked: "
          f"{len(capture.events)}", file=sys.stderr)
    return summarise(observations, args.reps)


if __name__ == "__main__":
    raise SystemExit(main())

"""i58: how many turns does the card gate lose to the i46 extra round?

MEASUREMENT ONLY. Imports the product; edits none of it. Makes real, paid
LLM calls. This is an INSTRUMENT, not a gate: never wire it into CI.

The question
------------
``harness.ask_v2`` used to card an orchestrator turn only when
``tool_call_count == 1``. The i46 extra round (``_run_synthesis_extra_round``)
calls a tool a second time when the synthesis call asks for one instead of
writing prose; on those turns ``tool_call_count`` reads 2. When the second
call is the SAME cardable tool, the turn ends in good prose over cardable data
and, under the old gate, loses its card. i58 changes the gate to "one distinct
tool with cardable output". The card asked for the number of affected turns
BEFORE promising anything. This script produces it.

Definition, pre-registered
--------------------------
A **rescued cardable turn** is an observation with

    tool_call_count == 2
    and maybe_atomic_tool_card(tool_chosen, tool_output, None) is not None
    and is_single_distinct_tool_turn(tool_chosen, 2, tool_sequence)

i.e. exactly the turn the old gate refused and the new gate cards. Every row
also carries the ingredients (``tool_sequence``, ``tool_call_count``,
``tool_chosen``, ``cardable``) so the count can be recomputed by hand, plus
``would_card_old`` / ``would_card_new`` for the two gates side by side. The
predicates are the product's own (``atomic_tool_cards``), not re-typed here.

Corpus
------
The i46 instrument's corpus (``measure_i46_synthesis_instrument``): its three
``rank_players_by_metric`` payload arms at the production budget
(``PROD_MAX_TOKENS``). Its fourth case, ``gw-04``, is EXCLUDED by
construction and by evidence: its tools (``get_gameweek_context``,
``web_fetch``) have no card composer, so no gw-04 turn can be a rescued
cardable turn whatever its count -- and the 50 gw-04 turns already on disk
(field-notes/artifacts/i46-instrument-probe-2026-08-30.jsonl,
i46-fix-paired-2026-08-31.jsonl) show 0 with a cardable tool. Paying for
more of them would buy nothing.

The doubled-budget arms (``HIGH_MAX_TOKENS``) are not run: i58 is about what
production does, and production runs at ``PROD_MAX_TOKENS``.

Order is fixed and rep-major (p03, p10, p50, p03, ...) so a run stopped by the
spend cap still covers every arm evenly.

Not covered
-----------
``_eval_client=None``, as in the i46 instrument: the evaluator retry path is
not exercised. The count is for the primary + synthesis (+ extra round) path.

Spend
-----
``--max-spend-usd`` (default 2.0) is enforced inside the loop, not only
declared: the loop stops before a call that could cross it. Real spend is
summed from the rows on disk. Every row is written and flushed before the
next call.

Usage (from packages/fpl-grounded-assistant):

    python scripts/measure_i58_rescued_cardable_turns.py \\
        --out ../../field-notes/artifacts/i58-rescued-turns-2026-09-13.jsonl \\
        --reps 25 --yes

    python scripts/measure_i58_rescued_cardable_turns.py \\
        --summarise-only ../../field-notes/artifacts/i58-rescued-turns-2026-09-13.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import measure_tool_routing as base  # noqa: E402
import measure_i46_synthesis_instrument as inst  # noqa: E402

# Pinned, never read from the environment (same rule as the i46 instrument).
PROVIDER = inst.PROVIDER      # "openai"
MODEL = inst.MODEL            # "gpt-5.6-luna"
MAX_TOKENS = inst.PROD_MAX_TOKENS

#: Pre-spend estimate per call (i41 mean on luna). The run reports real spend.
EST_USD_PER_CALL = inst.EST_USD_PER_CALL

DEFAULT_MAX_SPEND_USD = 2.0
DEFAULT_REPS = 25

#: The corpus: the i46 instrument's cardable arms. gw-04 is excluded (see
#: module docstring); this list is the instrument's, not a copy.
CORPUS: list[dict[str, Any]] = list(inst.PAYLOAD_ARMS)
EXCLUDED_CASES: dict[str, str] = {
    inst.PROBE_CASE_ID: (
        "tools get_gameweek_context/web_fetch have no card composer; 50 turns on "
        "disk (i46 probe + paired runs) show 0 with a cardable tool"
    ),
}

#: Provider-event verification; a module attribute so tests can neutralise it
#: without reaching into the instrument.
verify_provider = inst._verify_provider


# --------------------------------------------------------------------------
# One observation
# --------------------------------------------------------------------------

def _classify(result: Any) -> dict[str, Any]:
    """The i58 fields, computed with the PRODUCT's predicates on the real result."""
    from fpl_grounded_assistant.atomic_tool_cards import (
        is_single_distinct_tool_turn,
        maybe_atomic_tool_card,
    )
    tool_output = result.tool_output if isinstance(result.tool_output, dict) else {}
    tool_sequence = base.extract_tool_sequence(result)
    count = int(getattr(result, "tool_call_count", 0) or 0)
    cardable = maybe_atomic_tool_card(result.tool_chosen, tool_output, None) is not None
    single_distinct = is_single_distinct_tool_turn(result.tool_chosen, count, tool_sequence)
    return {
        "tool_sequence": tool_sequence,
        "distinct_tools": sorted({n for n in tool_sequence if n}),
        "tool_call_count": count,
        "cardable": cardable,
        "single_distinct_tool": single_distinct,
        "would_card_old": count == 1 and cardable,
        "would_card_new": single_distinct and cardable,
        # The number the card asked for.
        "rescued_cardable": count == 2 and cardable and single_distinct,
        # For transparency: count-2 turns with cardable output that the new
        # gate still refuses because a second, different tool ran.
        "count2_cardable_multi_tool": count == 2 and cardable and not single_distinct,
    }


def run_one(
    question: dict[str, Any],
    rep_index: int,
    bootstrap: dict[str, Any],
    api_key: str,
    max_tokens: int = MAX_TOKENS,
) -> dict[str, Any]:
    """One ask_orchestrated() call, instrumented like the i46 instrument.

    Never raises: exceptions land in the observation so the caller can write
    it to disk and keep going.
    """
    from fpl_grounded_assistant import orchestrator as orch_mod
    from fpl_grounded_assistant.orchestrator import ask_orchestrated

    recorder = inst._CallRecorder()
    real_fn = orch_mod.call_orch_provider

    t0 = time.monotonic()
    obs: dict[str, Any] = {
        "question_id": question["id"],
        "arm": question.get("arm", "control"),
        "family": question.get("family"),
        "acceptable_tools": question.get("acceptable_tools"),
        "rep": rep_index,
        "question": question["question"],
        "model": MODEL,
        "provider": PROVIDER,
        "requested_max_tokens": max_tokens,
        "intended_top_n": question.get("intended_top_n"),
        "captured_at": None,
        "latency_ms": None,
        "exception": None,
    }
    try:
        orch_mod.call_orch_provider = (
            lambda provider_name, **kw: recorder(real_fn, provider_name, **kw)
        )
        try:
            result = ask_orchestrated(
                question["question"],
                bootstrap,
                provider=PROVIDER,
                model=MODEL,
                api_key=api_key,
                max_tokens=max_tokens,
                temperature=None,
                top_p=None,
                _eval_client=None,
            )
        finally:
            orch_mod.call_orch_provider = real_fn

        tool_output = result.tool_output if isinstance(result.tool_output, dict) else {}
        tool_args = dict(result.tool_args or {})
        obs.update(
            outcome=result.outcome,
            tool_chosen=result.tool_chosen,
            tool_args=tool_args,
            actual_top_n=tool_args.get("top_n"),
            returned_rows=len(tool_output.get("ranked") or []),
            tool_output_status=tool_output.get("status"),
            tool_output_code=tool_output.get("code"),
            tool_output_metric=tool_output.get("metric"),
            synthesis_turn=bool(getattr(result, "synthesis_turn", False)),
            answer_text=(result.answer_text or "")[:400],
            rounds_used=getattr(result, "rounds_used", 0),
            error=result.error,
            primary_input_tokens=result.primary_input_tokens,
            primary_output_tokens=result.primary_output_tokens,
            primary_cache_read_tokens=result.primary_cache_read_tokens,
            total_tokens=result.total_tokens,
            cost_usd=base.cost_usd(
                result.primary_input_tokens,
                result.primary_output_tokens,
                result.primary_cache_read_tokens,
                model=MODEL,
                provider=PROVIDER,
            ),
        )
        obs.update(_classify(result))
    except Exception as exc:  # noqa: BLE001 -- must never lose an observation
        obs.update(
            outcome="harness_exception",
            tool_chosen=None, tool_args={}, actual_top_n=None, returned_rows=None,
            tool_output_status=None, tool_output_code=None, tool_output_metric=None,
            synthesis_turn=False, answer_text="", rounds_used=0, error=str(exc),
            primary_input_tokens=0, primary_output_tokens=0,
            primary_cache_read_tokens=0, total_tokens=0, cost_usd=0.0,
            exception=repr(exc),
            tool_sequence=[], distinct_tools=[], tool_call_count=0,
            cardable=False, single_distinct_tool=False,
            would_card_old=False, would_card_new=False,
            rescued_cardable=False, count2_cardable_multi_tool=False,
        )

    obs["provider_calls"] = recorder.calls
    obs["provider_call_count"] = len(recorder.calls)
    # Same definition as measure_i46_fix_paired: primary + synthesis + one more.
    obs["extra_round_fired"] = len(recorder.calls) >= 3
    obs["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
    obs["captured_at"] = datetime.now(timezone.utc).isoformat()
    return obs


# --------------------------------------------------------------------------
# Summary -- read back from the file, never from the in-memory list
# --------------------------------------------------------------------------

def read_jsonl(path: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    header: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "_header" in row:
                header = row["_header"]
            elif all(str(k).startswith("_") for k in row):
                continue  # bookkeeping rows (e.g. _stopped_by_cap), not observations
            else:
                rows.append(row)
    return header, rows


def summarise(path: Path) -> dict[str, Any]:
    """Count the rescued cardable turns from what is ON DISK at *path*.

    Returns the summary dict (also printed) so a test can assert on it.
    """
    header, rows = read_jsonl(path)
    n_exc = sum(1 for r in rows if r.get("exception"))
    scored = [r for r in rows if not r.get("exception")]
    spend = sum((r.get("cost_usd") or 0.0) for r in rows)

    total = {
        "observations": len(rows),
        "exceptions": n_exc,
        "scored": len(scored),
        "rescued_cardable": sum(1 for r in scored if r.get("rescued_cardable")),
        "count2_cardable_multi_tool": sum(
            1 for r in scored if r.get("count2_cardable_multi_tool")
        ),
        "would_card_old": sum(1 for r in scored if r.get("would_card_old")),
        "would_card_new": sum(1 for r in scored if r.get("would_card_new")),
        "extra_round_fired": sum(1 for r in scored if r.get("extra_round_fired")),
        "spend_usd": round(spend, 4),
    }
    by_q: dict[str, dict[str, Any]] = {}
    for qid in sorted({r["question_id"] for r in scored}):
        qs = [r for r in scored if r["question_id"] == qid]
        by_q[qid] = {
            "n": len(qs),
            "tool_call_count": dict(sorted(Counter(r.get("tool_call_count") for r in qs).items(),
                                           key=lambda kv: str(kv[0]))),
            "sequences": dict(sorted(
                Counter(" > ".join(r.get("tool_sequence") or []) or "(none)" for r in qs).items()
            )),
            "cardable": sum(1 for r in qs if r.get("cardable")),
            "rescued_cardable": sum(1 for r in qs if r.get("rescued_cardable")),
            "count2_cardable_multi_tool": sum(
                1 for r in qs if r.get("count2_cardable_multi_tool")
            ),
            "would_card_old": sum(1 for r in qs if r.get("would_card_old")),
            "would_card_new": sum(1 for r in qs if r.get("would_card_new")),
            "extra_round_fired": sum(1 for r in qs if r.get("extra_round_fired")),
            "synthesis_turn_false": sum(1 for r in qs if not r.get("synthesis_turn")),
        }

    print("\n=== i58 -- RESCUED CARDABLE TURNS (read from disk) ===")
    print(f"  file: {path}")
    if header:
        print(f"  provider/model: {header.get('provider')}/{header.get('model')}   "
              f"max_tokens: {header.get('max_tokens')}   reps planned: {header.get('reps')}")
    print(f"  observations {total['observations']}   exceptions {n_exc}   "
          f"scored {total['scored']}   real spend ${total['spend_usd']:.4f}")
    if n_exc:
        print("  WARNING: exceptions present; an excepted row is not evidence either way.")
    print(f"\n  {'case':>8} {'n':>4} {'cardable':>9} {'extra_rnd':>9} "
          f"{'card_old':>9} {'card_new':>9} {'RESCUED':>8} {'c2_multi':>9} {'synth=F':>8}  counts / sequences")
    for qid, q in by_q.items():
        print(f"  {qid:>8} {q['n']:>4} {q['cardable']:>9} {q['extra_round_fired']:>9} "
              f"{q['would_card_old']:>9} {q['would_card_new']:>9} {q['rescued_cardable']:>8} "
              f"{q['count2_cardable_multi_tool']:>9} {q['synthesis_turn_false']:>8}  "
              f"{q['tool_call_count']}  {q['sequences']}")
    print(f"\n  RESCUED CARDABLE TURNS (count==2, one distinct tool, cardable output): "
          f"{total['rescued_cardable']} / {total['scored']} scored")
    print(f"  cards under old gate {total['would_card_old']}   under new gate "
          f"{total['would_card_new']}   delta +{total['would_card_new'] - total['would_card_old']}")
    print(f"  count-2 cardable turns the new gate STILL refuses (two distinct tools): "
          f"{total['count2_cardable_multi_tool']}")
    return {"total": total, "by_question": by_q}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def _plan(reps: int) -> list[tuple[dict[str, Any], int]]:
    """Rep-major, fixed order: every arm once per rep."""
    return [(q, rep) for rep in range(reps) for q in CORPUS]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="JSONL to write (required unless --summarise-only).")
    ap.add_argument("--summarise-only", default=None,
                    help="Do not call anything; summarise this JSONL from disk.")
    ap.add_argument("--bootstrap", default=str(base.DEFAULT_BOOTSTRAP))
    ap.add_argument("--reps", type=int, default=DEFAULT_REPS)
    ap.add_argument("--max-spend-usd", type=float, default=DEFAULT_MAX_SPEND_USD,
                    help="Hard cap enforced inside the loop (default 2.0).")
    ap.add_argument("--env-file", default=None,
                    help="KEY=VALUE file holding OPENAI_API_KEY (default: package .env).")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the interactive spend confirmation.")
    args = ap.parse_args(argv)

    if args.summarise_only:
        summarise(Path(args.summarise_only))
        return 0
    if not args.out:
        ap.error("--out is required unless --summarise-only is given")

    base._configure_imports()
    base._load_env_file(
        Path(args.env_file) if args.env_file else base.PACKAGE_ROOT / ".env"
    )
    key_env = base.API_KEY_ENV_BY_PROVIDER[PROVIDER]
    api_key = os.environ.get(key_env)
    if not api_key:
        print(f"{key_env} not set (checked env + --env-file); aborting before any "
              f"paid call.", file=sys.stderr)
        return 2

    bootstrap_path = Path(args.bootstrap)
    bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    boot_sha = inst._sha256(bootstrap_path)

    plan = _plan(args.reps)
    total_calls = len(plan)
    est = total_calls * EST_USD_PER_CALL

    header = {
        "measurement": "i58-rescued-cardable-turns",
        "provider": PROVIDER, "model": MODEL, "max_tokens": MAX_TOKENS,
        "reps": args.reps, "calls_planned": total_calls,
        "corpus": [q["id"] for q in CORPUS],
        "excluded_cases": EXCLUDED_CASES,
        "order": "rep-major, fixed",
        "eval_client": None,
        "max_spend_usd": args.max_spend_usd,
        "est_usd_per_call": EST_USD_PER_CALL,
        "bootstrap_name": bootstrap_path.name, "bootstrap_sha256": boot_sha,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }
    print("=== i58 RESCUED CARDABLE TURNS ===", file=sys.stderr)
    for k, v in header.items():
        print(f"  {k}: {v}", file=sys.stderr)
    print(f"  ESTIMATED COST: ${est:.4f} ({total_calls} calls x ~${EST_USD_PER_CALL}/call); "
          f"hard cap ${args.max_spend_usd:.2f}", file=sys.stderr)
    if est > args.max_spend_usd:
        print("  Estimate exceeds the cap; lower --reps or raise --max-spend-usd.",
              file=sys.stderr)
        return 2

    if not args.yes:
        try:
            reply = input(f"Spend ~${est:.4f} on {total_calls} calls? [y/N] ")
        except EOFError:
            print("No TTY for confirmation; re-run with --yes.", file=sys.stderr)
            return 2
        if reply.strip().lower() not in ("y", "yes"):
            print("Aborted before any paid call.", file=sys.stderr)
            return 1

    capture = inst._ProviderEventCapture()
    logging.getLogger("fpl_grounded_assistant").addHandler(capture)
    logging.getLogger("fpl_grounded_assistant").setLevel(logging.INFO)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    spend = 0.0
    n_done = 0
    stopped_by_cap = False
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_header": header}, ensure_ascii=False) + "\n")
        fh.flush()
        for question, rep in plan:
            if spend + EST_USD_PER_CALL > args.max_spend_usd:
                stopped_by_cap = True
                break
            obs = run_one(question, rep, bootstrap, api_key)
            obs["_bootstrap_sha256"] = boot_sha
            # On disk before any aggregate: a crash cannot lose a paid call.
            fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
            fh.flush()
            spend += obs.get("cost_usd") or 0.0
            n_done += 1
            if n_done % 10 == 0 or n_done == total_calls:
                print(f"  {n_done}/{total_calls} done, ${spend:.4f} so far", file=sys.stderr)
        if stopped_by_cap:
            print(f"  STOPPED by spend cap after {n_done}/{total_calls} calls "
                  f"(${spend:.4f} + ~${EST_USD_PER_CALL} would cross ${args.max_spend_usd:.2f})",
                  file=sys.stderr)
            fh.write(json.dumps({"_stopped_by_cap": {"calls_done": n_done,
                                                     "spend_usd": round(spend, 4)}}) + "\n")

    verify_provider(capture.events, PROVIDER, MODEL)
    print(f"\nReal spend (in-memory sum): ${spend:.4f}   provider events checked: "
          f"{len(capture.events)}", file=sys.stderr)

    # The number reported is the one read back from the file, not the loop's.
    summarise(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

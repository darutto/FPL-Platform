"""Split the current LLM router's per-answer cost into provider ROUNDS.

measure_tool_routing.py records tokens/cost for the whole primary path of
one ask_orchestrated() call. This script reuses its run_one() unchanged and
additionally wraps fpl_grounded_assistant.orchestrator.call_orch_provider
(the single function every provider round goes through -- tool selection,
loop follow-ups, synthesis, evaluator retry) to record EACH round's usage
in order. No production code is edited; the wrapper lives only in this
process.

Round 1 is the tool-selection call: system prompt + full tool catalog +
question. It is the part a Jev router would replace. Later rounds carry
the tool output and produce the answer; they remain with the LLM either way.

Usage (from packages/fpl-grounded-assistant, OPENAI_API_KEY in env or .env):
    python scripts/measure_luna_rounds.py --out field-notes-artifacts-luna-rounds.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_tool_routing as mt  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bootstrap", default=str(mt.DEFAULT_BOOTSTRAP))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    mt._configure_imports()
    mt._load_env_file(mt.PACKAGE_ROOT / ".env")
    api_key = mt.require_api_key(mt.PROVIDER)

    import fpl_grounded_assistant.orchestrator as orch  # noqa: E402
    from tool_routing_corpus import CORPUS  # noqa: E402

    rounds: list[dict[str, Any]] = []
    real_call = orch.call_orch_provider

    def recording_call(*a: Any, **kw: Any) -> Any:
        t0 = time.monotonic()
        res = real_call(*a, **kw)
        msgs = kw.get("messages") or (a[4] if len(a) > 4 else [])
        rounds.append({
            "with_tools": bool(kw.get("tools")),
            "n_messages": len(msgs),
            "input_tokens": res.input_tokens or 0,
            "output_tokens": res.output_tokens or 0,
            "cache_read_tokens": res.cache_read_tokens or 0,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "error_code": res.error_code,
        })
        return res

    orch.call_orch_provider = recording_call

    bootstrap = json.loads(Path(args.bootstrap).read_text(encoding="utf-8"))
    questions = list(CORPUS)[: args.limit] if args.limit else list(CORPUS)
    print(f"{len(questions)} questions against {mt.PROVIDER}/{mt.MODEL}", file=sys.stderr)

    written: list[dict[str, Any]] = []
    with args.out.open("w", encoding="utf-8") as fh:
        for i, q in enumerate(questions, 1):
            rounds.clear()
            obs = mt.run_one(q, 0, bootstrap, api_key)
            obs["rounds"] = list(rounds)
            for k, r in enumerate(obs["rounds"], 1):
                r["cost_usd"] = mt.cost_usd(r["input_tokens"], r["output_tokens"], r["cache_read_tokens"], model=mt.MODEL, provider=mt.PROVIDER)
            fh.write(json.dumps(obs, ensure_ascii=False) + "\n"); fh.flush()
            written.append(obs)
            if i % 25 == 0 or i == len(questions):
                print(f"  {i}/{len(questions)}  {mt.format_spend(written)}", file=sys.stderr)

    # ---- report
    n = len(written)
    by_pos: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for o in written:
        for k, r in enumerate(o["rounds"], 1):
            by_pos[k].append(r)
    total_cost = sum(o["cost_usd"] or 0 for o in written)
    print(f"\n{n} answers, total ${total_cost:.4f}, ${total_cost/n:.6f}/answer")
    print(f"rounds per answer: " + ", ".join(f"{c}x{k}" for k, c in sorted(
        ((k, sum(1 for o in written if len(o['rounds']) == k)) for k in {len(o['rounds']) for o in written}))))
    print(f"\n{'round':>6s} {'n':>4s} {'with_tools':>10s} {'in tok/call':>12s} {'cache/call':>11s} {'out tok/call':>13s} {'$/call':>10s} {'p50 ms':>8s} {'share of $':>11s}")
    for k in sorted(by_pos):
        rs = by_pos[k]; m = len(rs)
        c = sum(r["cost_usd"] or 0 for r in rs)
        lat = sorted(r["latency_ms"] for r in rs)
        print(f"{k:>6d} {m:>4d} {sum(r['with_tools'] for r in rs):>10d} {sum(r['input_tokens'] for r in rs)/m:>12.0f} {sum(r['cache_read_tokens'] for r in rs)/m:>11.0f} {sum(r['output_tokens'] for r in rs)/m:>13.0f} {c/m:>10.6f} {lat[m//2]:>8.0f} {100*c/total_cost:>10.1f}%")
    r1 = by_pos.get(1, [])
    if r1:
        c1 = sum(r["cost_usd"] or 0 for r in r1)
        print(f"\nRound-1 (tool selection) share: ${c1:.4f} of ${total_cost:.4f} = {100*c1/total_cost:.1f}%  -> ${c1/n:.6f}/answer; Jev v2b routing was $0.000149/answer, fan-out $0.000209")


if __name__ == "__main__":
    main()

"""i124 offline replay: does the evaluator still reject once it can SEE the data?

Option C from field-notes/2026-10-03-i124-evaluator-rejections.md, measured
without touching prod or the served evaluator. Nothing here changes code
paths outside this script.

1. Primaries: each corpus question runs through the REAL ``ask_orchestrated``
   (prod orchestrator config: provider/model from the flags, live bootstrap,
   no team). ``orchestrator.evaluate_response`` is replaced -- in this process
   only -- by a capture that records exactly what the evaluator would receive
   (question, primary answer, tool_calls with their outputs) and approves, so
   no retry runs and the primary is what the user would have read.
2. Judgments: the REAL ``evaluator.evaluate_response`` with the production
   evaluator client, ``--judgments`` times per arm:
     * ``today``   -- the served user message: ``tool(args) -> status``;
     * ``payload`` -- the same message plus, per call, the payload the MODEL
       saw (``orchestrator._truncate_tool_output``: lists capped, hidden
       fields dropped). Same system prompt, same model; only the user
       message builder differs, swapped inside this script.
3. Cost guard: primary tokens priced by ``model_pricing.cost_usd``; evaluator
   tokens (reported combined in+out) priced at the model's INPUT rate --
   evaluator outputs are a short JSON verdict. The run aborts before the next
   call once the running estimate passes ``--max-usd``.

Usage:
  python replay_i124_evaluator_payload.py OUT.jsonl [--judgments 2] [--max-usd 0.09]
Requires the provider key in the environment (OPENAI_API_KEY for openai).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
for rel in [".", "../fpl-data-core", "../fpl-api-client", "../fpl-player-registry", "../fpl-query-tools",
            "../fpl-tool-contract", "../fpl-tool-runner", "../fpl-captain-engine", "../football-data-contract"]:
    p = str((PKG / rel).resolve())
    if p not in sys.path:
        sys.path.insert(0, p)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_i124_evaluator_rejections import CORPUS  # noqa: E402


class CostGuard(Exception):
    pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--judgments", type=int, default=2)
    ap.add_argument("--max-usd", type=float, default=0.09)
    a = ap.parse_args()

    os.environ.pop("FPL_EVAL_DISABLED", None)
    os.environ.pop("FPL_ORCH_EVAL_VERDICT_ONLY", None)
    os.environ.pop("FPL_ORCH_LOOP_ENABLED", None)
    os.environ.pop("FPL_JEV_MODE", None)

    import fpl_server
    from fpl_grounded_assistant import evaluator as ev
    from fpl_grounded_assistant import orchestrator as orch
    from fpl_grounded_assistant.evaluator import EvaluatorVerdict
    from fpl_grounded_assistant.harness import _build_eval_client
    from fpl_grounded_assistant.model_pricing import PRICING_PER_1M_BY_MODEL, cost_usd

    bootstrap = fpl_server._fetch_bootstrap_with_retry()
    if not bootstrap:
        raise SystemExit("could not fetch the live bootstrap")
    eval_client = _build_eval_client(a.provider)
    if eval_client is None:
        raise SystemExit("no evaluator client (key missing or evaluator disabled)")
    eval_model = os.environ.get(ev._EVAL_MODEL_ENV, "").strip() or ev._EVALUATOR_MODELS[a.provider]
    eval_rate = PRICING_PER_1M_BY_MODEL[eval_model]["input"] / 1e6

    spent = 0.0
    real_evaluate = ev.evaluate_response
    today_builder = ev._build_evaluator_user_message

    def payload_builder(question, primary_response, tool_calls):
        base = today_builder(question, primary_response, tool_calls)
        blocks = []
        for tc in tool_calls or []:
            out = tc.get("output") if isinstance(tc.get("output"), dict) else {}
            view = orch._truncate_tool_output(out, tool_name=tc.get("name"))
            blocks.append(f"{tc.get('name')} DATA: {json.dumps(view, ensure_ascii=False, default=str)}")
        data = "\n".join(blocks) if blocks else "(no tool data)"
        return base.replace("\nJudge. Output JSON only.", f"\nTOOL DATA (what the primary saw):\n{data}\n\nJudge. Output JSON only.")

    def judge(builder, captured):
        nonlocal spent
        if spent > a.max_usd:
            raise CostGuard(f"cost guard: {spent:.4f} > {a.max_usd}")
        ev._build_evaluator_user_message = builder
        try:
            v = real_evaluate(question=captured["question"], primary_response=captured["primary_response"],
                              tool_calls=captured["tool_calls"], provider=a.provider, client=eval_client)
        finally:
            ev._build_evaluator_user_message = today_builder
        msg_chars = len(builder(captured["question"], captured["primary_response"], captured["tool_calls"]))
        if v is None:
            return {"approved": None, "error": "no verdict", "msg_chars": msg_chars}
        spent += (v.tokens_used or 0) * eval_rate
        return {"approved": v.approved, "grounded": v.grounded, "complete": v.complete, "safe": v.safe,
                "retry_feedback": v.retry_feedback, "tokens_used": v.tokens_used, "msg_chars": msg_chars}

    with open(a.out, "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "pre", "provider": a.provider, "model": a.model, "eval_model": eval_model,
                            "judgments": a.judgments, "max_usd": a.max_usd, "ts": time.time()}) + "\n")
        try:
            for n, question in enumerate(CORPUS, 1):
                if spent > a.max_usd:
                    raise CostGuard(f"cost guard: {spent:.4f} > {a.max_usd}")
                captured: dict = {}

                def capture(**kwargs):
                    captured.update(question=kwargs["question"], primary_response=kwargs["primary_response"],
                                    tool_calls=list(kwargs.get("tool_calls") or []))
                    return EvaluatorVerdict(approved=True, grounded=True, complete=True, safe=True,
                                            retry_feedback=None, tokens_used=0)

                orch.evaluate_response = capture
                try:
                    r = orch.ask_orchestrated(question, bootstrap, provider=a.provider, model=a.model,
                                              _eval_client=object())
                finally:
                    orch.evaluate_response = real_evaluate
                spent += cost_usd(r.primary_input_tokens, r.primary_output_tokens,
                                  r.primary_cache_read_tokens, model=a.model, provider=a.provider) or 0.0
                if not captured:
                    row = {"kind": "turn", "n": n, "question": question, "evaluated": False,
                           "outcome": r.outcome, "answer_text": r.answer_text}
                else:
                    row = {
                        "kind": "turn", "n": n, "question": question, "evaluated": True, "outcome": r.outcome,
                        "primary_response": captured["primary_response"],
                        "tools": [(tc.get("name"), (tc.get("output") or {}).get("status")) for tc in captured["tool_calls"]],
                        "today": [judge(today_builder, captured) for _ in range(a.judgments)],
                        "payload": [judge(payload_builder, captured) for _ in range(a.judgments)],
                    }
                row["spent_usd"] = round(spent, 5)
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                f.flush()
                t = [j.get("approved") for j in row.get("today", [])]
                p = [j.get("approved") for j in row.get("payload", [])]
                print(f"#{n:02d} today={t} payload={p} spent={spent:.4f} {question[:50]!r}", flush=True)
        except CostGuard as exc:
            f.write(json.dumps({"kind": "abort", "reason": str(exc)}) + "\n")
            print(exc, flush=True)
    print(f"total estimated spend: {spent:.4f} USD")
    return 0


if __name__ == "__main__":
    sys.exit(main())

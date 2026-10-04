"""i143: where does the machine talk in chip answers come from, and is it gone?

Runs the E3 chip ids (tool_routing_corpus) R times through ``ask_orchestrated``
with the prod config (openai / gpt-5.6-luna, evaluator ON), no team linked,
on a bootstrap assembled as the server does. Per turn it keeps BOTH texts:

* ``primary_text`` -- what the model first wrote (the evaluator's input,
  recorded at the call boundary; the served text when no evaluator ran);
* ``final_text``   -- what was served (the retry, when the evaluator rejected).

and grades each with the i123 grader's i143 detectors (``tool_talk``,
``spanish_chip_names``) plus its i123 ``leaks``. That separates "the model
writes it" from "the retry writes it after a rejection".

Usage (paid): python scripts/measure_i143_chip_language.py OUT.jsonl REPS
              python scripts/measure_i143_chip_language.py --summary FILE [FILE ...]
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "scripts"))
from measure_tool_routing import (  # noqa: E402
    MODEL,
    PROVIDER,
    _configure_imports,
    _load_env_file,
    cost_usd,
    require_api_key,
)

_spec = importlib.util.spec_from_file_location("grade_i123", PACKAGE_ROOT / "scripts" / "grade_i123_internal_names.py")
grade = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grade)

E3_IDS = ["ad-03", "ad-04", "ad-05", "ad-07", "ad-10", "cvg-01", "cvg-02", "cvg-03", "cvg-04",
          "cvg-05", "cvg-09", "cvg-10", "cvg-11", "cvg-12"]


def detect(text: str) -> dict:
    leaks = grade.leaks(text or "")
    return {"tooltalk": grade.tool_talk(text or ""), "chipname_es": grade.spanish_chip_names(text or ""),
            "internal_names": any(leaks.values())}


def summary(paths: list[str]) -> int:
    for p in paths:
        rows = [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]
        # Recomputed from the stored texts with the CURRENT detectors, so the
        # summary and any re-read of the JSONL always come from one detector.
        for r in rows:
            r["primary"], r["final"] = detect(r["primary_text"]), detect(r["final_text"])
        n = len(rows)
        retried = [r for r in rows if r["retry_attempted"]]
        out = {
            "arm": Path(p).name, "turns": n,
            "rejected": sum(r["rejected"] for r in rows),
            "final_tooltalk": sum(bool(r["final"]["tooltalk"]) for r in rows),
            "final_chipname_es": sum(bool(r["final"]["chipname_es"]) for r in rows),
            "final_internal_names": sum(r["final"]["internal_names"] for r in rows),
            "primary_tooltalk": sum(bool(r["primary"]["tooltalk"]) for r in rows),
            # where the served tool talk came from
            "final_tooltalk_from_retry_only": sum(
                bool(r["final"]["tooltalk"]) and not r["primary"]["tooltalk"] for r in retried),
            "final_tooltalk_already_in_primary": sum(
                bool(r["final"]["tooltalk"]) and bool(r["primary"]["tooltalk"]) for r in rows),
            "usd_total": round(sum(r["usd_cost_estimate"] for r in rows), 4),
        }
        out["usd_per_turn"] = round(out["usd_total"] / n, 5) if n else None
        print(json.dumps(out))
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--summary":
        return summary(argv[1:])
    out_path, reps = Path(argv[0]), int(argv[1])
    _configure_imports()
    sys.path.insert(0, str((PACKAGE_ROOT / ".." / "fpl-pipeline").resolve()))
    _load_env_file(PACKAGE_ROOT / ".env")
    api_key = require_api_key(PROVIDER)

    from fpl_pipeline import assemble_captain_context
    from fpl_grounded_assistant import orchestrator as orch_mod
    from fpl_grounded_assistant.harness import _build_eval_client
    from tool_routing_corpus import CORPUS

    questions = [q for q in CORPUS if q["id"] in set(E3_IDS)]
    bootstrap = assemble_captain_context()["bootstrap"]
    eval_client = _build_eval_client(PROVIDER, api_key=api_key)
    if eval_client is None:
        print("evaluator client unavailable; refusing to measure without it", file=sys.stderr)
        return 1

    calls: list[dict] = []
    real_evaluate = orch_mod.evaluate_response

    def _recording(**kwargs):
        v = real_evaluate(**kwargs)
        calls.append({"primary_response": kwargs.get("primary_response"), "approved": v.approved,
                      "retry_feedback": v.retry_feedback})
        return v

    orch_mod.evaluate_response = _recording
    spent = 0.0
    with out_path.open("a", encoding="utf-8") as f:
        for rep in range(reps):
            for q in questions:
                calls.clear()
                t0 = time.monotonic()
                r = orch_mod.ask_orchestrated(q["question"], bootstrap, provider=PROVIDER, model=MODEL,
                                              api_key=api_key, max_tokens=1024, temperature=None,
                                              top_p=None, _eval_client=eval_client)
                primary = calls[0]["primary_response"] if calls else r.answer_text
                cost = ((cost_usd(r.primary_input_tokens, r.primary_output_tokens, r.primary_cache_read_tokens) or 0.0)
                        + (cost_usd(r.evaluator_input_tokens, 0, 0) or 0.0))
                spent += cost
                row = {
                    "question_id": q["id"], "rep": rep, "question": q["question"], "outcome": r.outcome,
                    "tool_sequence": [e.get("name") for e in r.tool_calls_trace or ()],
                    "retry_attempted": r.retry_attempted,
                    "rejected": any(not c["approved"] for c in calls),
                    "evaluator_feedback": [c["retry_feedback"] for c in calls if not c["approved"]],
                    "primary_text": primary, "final_text": r.answer_text,
                    "primary": detect(primary), "final": detect(r.answer_text),
                    "usd_cost_estimate": round(cost, 6), "latency_s": round(time.monotonic() - t0, 1),
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                print(f"{q['id']} r{rep}: rej={row['rejected']} talk={bool(row['final']['tooltalk'])} "
                      f"chip_es={bool(row['final']['chipname_es'])} spent~${spent:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

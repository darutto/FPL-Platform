"""i133: replay the evaluator alone on payloads that carry get_gameweek_context.

Reads the evaluator calls recorded by ``probe_i133_blank_claims.py`` (question,
primary response, each call with its ``model_view``), keeps the ones whose
TOOL DATA includes get_gameweek_context, and re-judges each REPS times with the
real evaluator (openai / gpt-5.6-luna, prod default). Writes one line per
judgment with the verdict and whether its feedback asserts a blank. The
payloads are the recorded ones -- nothing is re-fetched -- so a blank claim
here can only come from the evaluator's reading.

Usage (paid, evaluator calls only):
  python scripts/replay_i133_evaluator_blank.py PROBE.jsonl OUT.jsonl REPS
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "scripts"))
from measure_tool_routing import PROVIDER, _configure_imports, _load_env_file, require_api_key  # noqa: E402
from probe_i133_blank_claims import claims_blank  # noqa: E402


def main(argv: list[str]) -> int:
    probe_path, out_path, reps = Path(argv[0]), Path(argv[1]), int(argv[2])
    _configure_imports()
    _load_env_file(PACKAGE_ROOT / ".env")
    api_key = require_api_key(PROVIDER)

    from fpl_grounded_assistant.evaluator import MODEL_VIEW_KEY, evaluate_response
    from fpl_grounded_assistant.harness import _build_eval_client

    client = _build_eval_client(PROVIDER, api_key=api_key)
    if client is None:
        print("evaluator client unavailable", file=sys.stderr)
        return 1

    cases = []
    for line in probe_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for i, call in enumerate(row["evaluator_calls"]):
            if any(v["name"] == "get_gameweek_context" for v in call["tool_views"]):
                cases.append((row["question_id"], row["rep"], i, row["question"], call))

    tokens = 0
    with out_path.open("a", encoding="utf-8") as f:
        for qid, rep, idx, question, call in cases:
            tool_calls = [
                {"name": v["name"], "args": v["args"] or {}, "output": v["view"] or {}, MODEL_VIEW_KEY: v["view"]}
                for v in call["tool_views"]
            ]
            for k in range(reps):
                verdict = evaluate_response(question=question, primary_response=call["primary_response"],
                                            tool_calls=tool_calls, provider=PROVIDER, client=client)
                tokens += verdict.tokens_used
                rec = {"question_id": qid, "rep": rep, "eval_call": idx, "replay": k,
                       "approved": verdict.approved, "retry_feedback": verdict.retry_feedback,
                       "verdict_claims": claims_blank(verdict.retry_feedback),
                       "tokens_used": verdict.tokens_used,
                       "tools": [v["name"] for v in call["tool_views"]]}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(f"{qid} r{rep} call{idx} replay{k}: approved={verdict.approved} "
                      f"claims={bool(rec['verdict_claims'])}", flush=True)
    print(f"cases={len(cases)} judgments={len(cases) * reps} evaluator_tokens={tokens}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

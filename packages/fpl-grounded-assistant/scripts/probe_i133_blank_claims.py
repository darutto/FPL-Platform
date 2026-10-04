"""i133 probe: are the "blank gameweek" claims in the data or in the reading?

Seen 2026-10-03 (i124 payload gate n=43, i132 after r3 n=13): the evaluator
rejected chip answers asking to "reconcile that GW6 is blank for 20 teams",
and a retried answer repeated it. The live tools return no blanks today.

This drives the two real questions through ``ask_orchestrated`` with the prod
orchestrator config (openai / gpt-5.6-luna, evaluator ON) on a bootstrap
assembled exactly as the server does at startup (``assemble_captain_context``),
and records, per evaluator call, the TOOL DATA it was given (the same
``model_view`` the primary saw) next to its verdict and the served text.

Each row answers three questions off what was produced, never off what was
asked for:
  * ``payload_blanks``   -- does any payload the evaluator got carry a blank
                            (non-empty ``blank_gw_alerts`` / ``bgw_teams``, or a
                            ``gameweek_type`` other than normal/unknown)?
  * ``verdict_claims``   -- does a rejection's feedback assert a blank?
  * ``text_claims``      -- does the served text assert a blank?

Usage (paid: one luna turn + evaluator per row):
  python scripts/probe_i133_blank_claims.py OUT.jsonl REPS
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "scripts"))
from measure_tool_routing import (  # noqa: E402
    MODEL,
    PROVIDER,
    _configure_imports,
    cost_usd,
    _load_env_file,
    require_api_key,
)

QUESTIONS = {
    "i124-n43": "¿Qué tan recomendable es usar la wildcard en la siguiente fecha?",
    "i132-n13": ("con los buenos encuentros que tendrá fulham en las proximas 3 jornadas, he "
                 "considerado trabajar el free hit en esas fechas, cual seria la mejor jornada "
                 "para utilizarlo?"),
}

#: A positive blank claim. Negations ("no hay jornada en blanco", "sin blanks")
#: are excluded by requiring no negation in the 25 chars before the match.
_CLAIM_RE = re.compile(r"(?:en blanco|\bblanks?\b|sin partido|no jueg\w+)", re.I)
_NEG_RE = re.compile(r"\b(?:no hay|ni|sin|ningun\w*|no se detecta\w*|no existe\w*|tampoco)\b[^.]{0,25}$", re.I)


def claims_blank(text: str | None) -> list[str]:
    hits = []
    for m in _CLAIM_RE.finditer(text or ""):
        before = (text or "")[max(0, m.start() - 40):m.start()]
        if not _NEG_RE.search(before):
            hits.append((text or "")[max(0, m.start() - 60):m.end() + 40].replace("\n", " "))
    return hits


def payload_blanks(view: dict) -> list[str]:
    found = []
    for alert in view.get("blank_gw_alerts") or []:
        found.append(f"blank_gw_alerts GW{alert.get('gw')} count={alert.get('count')}")
    sig = view.get("signals") or {}
    if sig.get("bgw_teams"):
        found.append(f"signals.bgw_teams={sig['bgw_teams']}")
    if sig.get("gameweek_type") not in (None, "normal", "unknown"):
        found.append(f"signals.gameweek_type={sig['gameweek_type']}")
    return found


def main(argv: list[str]) -> int:
    out_path, reps = Path(argv[0]), int(argv[1])
    _configure_imports()
    sys.path.insert(0, str((PACKAGE_ROOT / ".." / "fpl-pipeline").resolve()))
    _load_env_file(PACKAGE_ROOT / ".env")
    api_key = require_api_key(PROVIDER)

    from fpl_pipeline import assemble_captain_context
    from fpl_grounded_assistant import orchestrator as orch_mod
    from fpl_grounded_assistant.evaluator import MODEL_VIEW_KEY
    from fpl_grounded_assistant.harness import _build_eval_client

    assembled = assemble_captain_context()
    bootstrap = assembled["bootstrap"]
    eval_client = _build_eval_client(PROVIDER, api_key=api_key)
    if eval_client is None:
        print("evaluator client unavailable; refusing to measure without it", file=sys.stderr)
        return 1

    calls: list[dict] = []
    real_evaluate = orch_mod.evaluate_response

    def _recording_evaluate(**kwargs):
        verdict = real_evaluate(**kwargs)
        views = [
            {"name": tc.get("name"), "args": tc.get("args"), "view": tc.get(MODEL_VIEW_KEY)}
            for tc in kwargs.get("tool_calls") or [] if isinstance(tc, dict)
        ]
        calls.append({
            "primary_response": kwargs.get("primary_response"),
            "tool_views": views,
            "payload_blanks": [b for v in views if isinstance(v["view"], dict) for b in payload_blanks(v["view"])],
            "approved": verdict.approved,
            "retry_feedback": verdict.retry_feedback,
            "verdict_claims": claims_blank(verdict.retry_feedback),
            "primary_claims": claims_blank(kwargs.get("primary_response")),
        })
        return verdict

    orch_mod.evaluate_response = _recording_evaluate
    spent = 0.0
    with out_path.open("a", encoding="utf-8") as f:
        for rep in range(reps):
            for qid, question in QUESTIONS.items():
                calls.clear()
                t0 = time.monotonic()
                r = orch_mod.ask_orchestrated(
                    question, bootstrap, provider=PROVIDER, model=MODEL, api_key=api_key,
                    max_tokens=1024, temperature=None, top_p=None, _eval_client=eval_client,
                )
                row = {
                    "question_id": qid, "rep": rep, "question": question,
                    "assembled_gameweek": assembled["gameweek"],
                    "outcome": r.outcome,
                    "tool_sequence": [e.get("name") for e in r.tool_calls_trace or ()],
                    "retry_attempted": r.retry_attempted,
                    "final_text": r.answer_text,
                    "text_claims": claims_blank(r.answer_text),
                    "evaluator_calls": list(calls),
                    "payload_blanks_any": any(c["payload_blanks"] for c in calls),
                    "verdict_claims_any": any(c["verdict_claims"] for c in calls),
                    "latency_s": round(time.monotonic() - t0, 1),
                    # primary at luna prices + evaluator tokens priced as input (upper-ish estimate)
                    "usd_cost_estimate": (cost_usd(r.primary_input_tokens, r.primary_output_tokens,
                                                   r.primary_cache_read_tokens) or 0.0)
                    + (cost_usd(r.evaluator_input_tokens, 0, 0) or 0.0),
                }
                spent += row["usd_cost_estimate"] or 0.0
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                f.flush()
                print(f"{qid} r{rep}: outcome={r.outcome} retry={r.retry_attempted} "
                      f"payload_blanks={row['payload_blanks_any']} verdict_claims={row['verdict_claims_any']} "
                      f"text_claims={bool(row['text_claims'])} spent~${spent:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

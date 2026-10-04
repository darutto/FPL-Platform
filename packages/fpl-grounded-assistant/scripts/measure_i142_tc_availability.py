"""i142 gate: does the TC answer still hedge on the candidate's availability?

Drives «¿Uso el Triple Captain esta jornada?» through ``ask_orchestrated`` with
the prod orchestrator config (openai / gpt-5.6-luna, evaluator ON) on a
bootstrap assembled as the server does (``assemble_captain_context``), and
writes one line per turn read off what was produced: the served text, the
evaluator's verdicts (recorded at the call boundary), whether a retry ran,
the cost, and ``hedge_hits`` -- phrases that say availability cannot be
certified / confirmed.

Usage (paid): python scripts/measure_i142_tc_availability.py OUT.jsonl REPS
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
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

QUESTION = "¿Uso el Triple Captain esta jornada?"

#: «no puedo certificar/confirmar su disponibilidad», «no tengo datos suficientes
#: para … disponibilidad», «no puedo garantizar que esté disponible». Folded text.
HEDGE = re.compile(
    r"certific\w*[^.]{0,60}disponib|"
    r"no (?:puedo|podemos|es posible|se puede) (?:confirmar|garantizar|asegurar|verificar)[^.]{0,60}disponib|"
    r"no (?:tengo|hay) (?:datos|informacion)[^.]{0,80}disponib|"
    r"disponib\w*[^.]{0,60}no (?:esta|puedo|se puede) (?:confirm|verific|certific|garantiz)|"
    # added after the first run (stricter, declared in the field note): the
    # before arm hedged as «no añado ninguna afirmación sobre su disponibilidad»
    r"afirmacion\w* sobre su disponib"
)

#: The evaluator rejecting because it could not see the candidate's minutes /
#: status (the reason i142 exists).
AVAIL_REJECT = re.compile(r"minutos[^.]{0,60}(?:temporada|jugados)[^.]{0,80}estado|"
                          r"estado[^.]{0,40}disponibilidad")


def regrade(paths: list[str]) -> int:
    for p in paths:
        rows = [json.loads(line) for line in Path(p).read_text(encoding="utf-8").splitlines() if line.strip()]
        n = len(rows)
        hedge = sum(bool(hedge_hits(r["final_text"])) for r in rows)
        rejected = sum(r["rejected"] for r in rows)
        avail_rej = sum(any(AVAIL_REJECT.search(fold(v.get("retry_feedback") or "")) for v in r["evaluator_verdicts"]
                            if not v["approved"]) for r in rows)
        cost = sum(r["usd_cost_estimate"] for r in rows)
        print(json.dumps({"arm": Path(p).name, "turns": n, "hedge_rows": hedge, "rejected_rows": rejected,
                          "rejected_for_minutes_status": avail_rej, "usd_total": round(cost, 4),
                          "usd_per_turn": round(cost / n, 5) if n else None}))
    return 0


def fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def hedge_hits(text: str) -> list[str]:
    return [m.group(0) for m in HEDGE.finditer(fold(text))]


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--regrade":
        return regrade(argv[1:])
    out_path, reps = Path(argv[0]), int(argv[1])
    _configure_imports()
    sys.path.insert(0, str((PACKAGE_ROOT / ".." / "fpl-pipeline").resolve()))
    _load_env_file(PACKAGE_ROOT / ".env")
    api_key = require_api_key(PROVIDER)

    from fpl_pipeline import assemble_captain_context
    from fpl_grounded_assistant import orchestrator as orch_mod
    from fpl_grounded_assistant.harness import _build_eval_client

    bootstrap = assemble_captain_context()["bootstrap"]
    eval_client = _build_eval_client(PROVIDER, api_key=api_key)
    if eval_client is None:
        print("evaluator client unavailable; refusing to measure without it", file=sys.stderr)
        return 1

    verdicts: list[dict] = []
    real_evaluate = orch_mod.evaluate_response

    def _recording(**kwargs):
        v = real_evaluate(**kwargs)
        verdicts.append({"approved": v.approved, "retry_feedback": v.retry_feedback,
                         "primary_hedge_hits": hedge_hits(kwargs.get("primary_response") or "")})
        return v

    orch_mod.evaluate_response = _recording
    spent = 0.0
    with out_path.open("a", encoding="utf-8") as f:
        for rep in range(reps):
            verdicts.clear()
            t0 = time.monotonic()
            r = orch_mod.ask_orchestrated(QUESTION, bootstrap, provider=PROVIDER, model=MODEL,
                                          api_key=api_key, max_tokens=1024, temperature=None,
                                          top_p=None, _eval_client=eval_client)
            chip_calls = [e for e in (r.tool_calls_trace or ()) if e.get("name") == "get_chip_advice"]
            sig = ((chip_calls[-1].get("output") or {}).get("signals") or {}) if chip_calls else {}
            cost = ((cost_usd(r.primary_input_tokens, r.primary_output_tokens, r.primary_cache_read_tokens) or 0.0)
                    + (cost_usd(r.evaluator_input_tokens, 0, 0) or 0.0))
            spent += cost
            row = {
                "rep": rep, "question": QUESTION, "outcome": r.outcome,
                "tool_sequence": [e.get("name") for e in r.tool_calls_trace or ()],
                "top_player": sig.get("top_player"),
                "top_minutes_played_season": sig.get("top_minutes_played_season"),
                "top_status": sig.get("top_status"),
                "retry_attempted": r.retry_attempted,
                "evaluator_verdicts": list(verdicts),
                "rejected": any(not v["approved"] for v in verdicts),
                "final_text": r.answer_text,
                "hedge_hits": hedge_hits(r.answer_text),
                "usd_cost_estimate": round(cost, 6),
                "latency_s": round(time.monotonic() - t0, 1),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"r{rep}: outcome={r.outcome} rejected={row['rejected']} hedge={bool(row['hedge_hits'])} "
                  f"top={row['top_player']} min={row['top_minutes_played_season']} spent~${spent:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

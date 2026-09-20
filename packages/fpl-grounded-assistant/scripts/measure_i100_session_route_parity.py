"""i100: does the session endpoint route the calendar phrases like /ask does?

MEASUREMENT ONLY -- real, paid LLM calls. The UI sends the first turn of a
conversation by ``POST /ask`` and every later one by ``POST /session/{id}/ask``,
so a /fixtures tap made with a session already open goes down the path i78-A
never measured. This runs the i78-A matrix through BOTH HTTP routes, in
process, on the same code, bootstrap and model, on the same day:

* corpus: ``tool_routing_corpus.i78a_fixture_click_corpus()`` (the 28 canonical
  phrases the UI generates, as loaded from field-notes/artifacts/
  i78a-canonical-phrases.json) plus the i78-A controls (``i78a_controls``);
* protocol: R reps (default 3), fixed order (phrase-major, rep-minor, /ask then
  /session for each rep), provider/model pinned by ``measure_tool_routing``
  (openai / gpt-5.6-luna), evaluator OFF (``FPL_EVAL_DISABLED=1``, the parity
  of i78-A's ``_eval_client=None``), bootstrap
  field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json, declared spend
  cap checked BEFORE the first call;
* each session turn is the FIRST turn of a freshly opened session (no prior
  history that could legitimately change the answer), with a fresh X-User-Id
  per call (the free tier caps at 5/day per id -- i99);
* the observation row carries, per route: ``selected_tool`` and
  ``routing_trace.tool_sequence`` / ``tool_args_sequence`` from the debug
  blob, ``intent``, ``outcome``, the session's ``rewritten_question`` (the one
  thing the session path does before ask_v2 that /ask does not), tokens and
  latency. Raw bodies are kept so nothing has to be re-derived.

Usage (from packages/fpl-grounded-assistant; .env is read for the API key):

    python scripts/measure_i100_session_route_parity.py \
        --out ../../field-notes/artifacts/i100-session-route-parity-<date>.jsonl --reps 3

Read-out: scripts/analyze_i100_session_route_parity.py <jsonl>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import measure_tool_routing as base  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _estimate_usd(n_calls: int) -> float:
    """Same pre-run ceiling i78-A used (i82 reference: 84 calls -> $0.11)."""
    return round(n_calls * (0.11 / 84) * 1.5, 3)


def _debug_bits(body: dict[str, Any]) -> dict[str, Any]:
    dbg = body.get("debug") or {}
    rt = dbg.get("routing_trace") or {}
    return {
        "selected_tool": dbg.get("selected_tool"),
        "tool_sequence": list(rt.get("tool_sequence") or []),
        "tool_args_sequence": list(rt.get("tool_args_sequence") or []),
        "composed_primary_tool": rt.get("composed_primary_tool"),
        "branch": rt.get("branch"),
        "orchestrator_outcome": rt.get("orchestrator_outcome"),
        "tokens": dbg.get("tokens") or rt.get("tokens"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=str(base.DEFAULT_BOOTSTRAP))
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--out", required=True)
    parser.add_argument("--no-controls", action="store_true")
    parser.add_argument("--only-kind", default=None)
    parser.add_argument("--cap-usd", type=float, default=3.0)
    args = parser.parse_args(argv)

    base._configure_imports()
    base._load_env_file(base.PACKAGE_ROOT / ".env")
    api_key = base.require_api_key(base.PROVIDER)
    # Pin what the server process will read, exactly as prod is configured
    # (measure_tool_routing pins the same pair for the in-process runs).
    os.environ["FPL_ORCH_ENABLED"] = "1"
    os.environ["FPL_ORCH_PROVIDER"] = base.PROVIDER
    os.environ["FPL_ORCH_MODEL"] = base.MODEL
    os.environ[base.API_KEY_ENV_BY_PROVIDER[base.PROVIDER]] = api_key
    os.environ["FPL_EVAL_DISABLED"] = "1"
    os.environ.pop("REDIS_URL", None)

    from tool_routing_corpus import (  # noqa: PLC0415
        I78A_CANONICAL_PHRASES_PATH,
        i78a_controls,
        i78a_fixture_click_corpus,
    )
    canonical = i78a_fixture_click_corpus()
    if args.only_kind:
        canonical = [q for q in canonical if q["i78a"]["kind"] == args.only_kind]
    controls = [] if args.no_controls else i78a_controls()
    questions = canonical + controls
    if not questions:
        print("nothing to run", file=sys.stderr)
        return 1

    corpus_sha = {
        "i78a_canonical_phrases_json": _sha256(I78A_CANONICAL_PHRASES_PATH),
        "tool_routing_corpus_py": _sha256(SCRIPTS_DIR / "tool_routing_corpus.py"),
    }
    total_calls = len(questions) * args.reps * 2
    estimate = _estimate_usd(total_calls)
    print(f"corpus: {len(canonical)} canonical + {len(controls)} controls = {len(questions)} phrases "
          f"x {args.reps} reps x 2 routes = {total_calls} calls against {base.PROVIDER}/{base.MODEL}",
          file=sys.stderr)
    print(f"corpus sha256: {json.dumps(corpus_sha)}", file=sys.stderr)
    print(f"estimated spend: ${estimate:.3f} (cap ${args.cap_usd:.2f})", file=sys.stderr)
    if estimate > args.cap_usd:
        print("estimate exceeds the declared cap; no call made.", file=sys.stderr)
        return 2

    import fpl_server  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from fpl_grounded_assistant.orch_config import get_orch_model, get_orch_provider  # noqa: PLC0415

    bootstrap = json.loads(Path(args.bootstrap).read_text(encoding="utf-8"))
    fpl_server._init_bootstrap(bootstrap)
    fpl_server._init_classifier_client(None)
    fpl_server.write_audit_entry = lambda entry: None  # type: ignore[assignment]
    client = TestClient(fpl_server.app)
    resolved = {"provider": get_orch_provider(), "model": get_orch_model(get_orch_provider())}
    print(f"server sees provider/model: {resolved}", file=sys.stderr)
    assert resolved == {"provider": base.PROVIDER, "model": base.MODEL}, resolved

    def call(path: str, question: str) -> tuple[dict[str, Any], float, str | None]:
        t0 = time.monotonic()
        try:
            resp = client.post(path, json={"question": question, "debug": True},
                               headers={"X-User-Id": f"i100-{uuid.uuid4().hex[:10]}"})
            body = resp.json()
            return body, (time.monotonic() - t0) * 1000, None if resp.status_code == 200 else f"http {resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            return {}, (time.monotonic() - t0) * 1000, f"{type(exc).__name__}: {exc}"

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_done = 0
    n_exc = 0
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"_header": {
            "measurement": "i100-session-route-parity", "provider": base.PROVIDER, "model": base.MODEL,
            "reps": args.reps, "calls_planned": total_calls, "cap_usd": args.cap_usd, "estimate_usd": estimate,
            "bootstrap": str(args.bootstrap), "bootstrap_sha256": _sha256(Path(args.bootstrap)),
            "corpus_sha256": corpus_sha, "eval_disabled": True, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }}) + "\n")
        for q in questions:
            for rep in range(args.reps):
                ask_body, ask_ms, ask_exc = call("/ask", q["question"])
                sid = client.post("/session").json()["session_id"]
                sess_body, sess_ms, sess_exc = call(f"/session/{sid}/ask", q["question"])
                row = {
                    "question_id": q["id"], "family": q["family"], "kind": (q.get("i78a") or {}).get("kind"),
                    "acceptable_tools": q["acceptable_tools"], "forbidden_tools": list(q.get("forbidden_tools") or []),
                    "control": q["control"], "rep": rep, "question": q["question"],
                    "model": base.MODEL, "provider": base.PROVIDER,
                    "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "ask": {**_debug_bits(ask_body), "intent": ask_body.get("intent"), "outcome": ask_body.get("outcome"),
                            "latency_ms": round(ask_ms), "exception": ask_exc},
                    "session": {**_debug_bits(sess_body), "intent": sess_body.get("intent"), "outcome": sess_body.get("outcome"),
                                "rewritten_question": sess_body.get("rewritten_question"),
                                "latency_ms": round(sess_ms), "exception": sess_exc, "session_id": sid},
                    "raw": {"ask": ask_body, "session": sess_body},
                    "corpus_sha256": corpus_sha,
                }
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                n_done += 2
                n_exc += int(ask_exc is not None) + int(sess_exc is not None)
                a, s = row["ask"], row["session"]
                print(f"  {q['id']:16} r{rep} ask={a['selected_tool']!s:24} seq={a['tool_sequence']} | "
                      f"sess={s['selected_tool']!s:24} seq={s['tool_sequence']} rewritten={s['rewritten_question'] is not None}",
                      file=sys.stderr)
                if n_done % 20 == 0 or n_done == total_calls:
                    print(f"  {n_done}/{total_calls} done, {n_exc} exceptions", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

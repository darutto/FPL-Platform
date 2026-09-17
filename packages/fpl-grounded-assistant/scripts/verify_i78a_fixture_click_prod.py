"""i78-A prod check: the same /fixtures cell phrase, sent N times unedited,
reaches the same tool every time and never the whole-gameweek dump.

Runs AFTER the PR is merged and deployed. Nothing here is asserted from the
phrase that was sent: every line is read off the /ask debug blob (debug=true,
same shape scripts/verify_prod_rollover.py reads) -- selected_tool, the
orchestrator's tool-call trace, the tool's own raw_output.

The phrase must be the one the UI inserts: tap the cell (or team row) on
/fixtures, copy the composer text verbatim and pass it as --question. When a
--question is not given, the phrase is read from the generated contract
file by id (--phrase-id, default fc-new-att-cell); note that file was built
against GW1 of the frozen measurement bootstrap, so in prod prefer the live
composer text for the current gameweek.

Usage:

    python scripts/verify_i78a_fixture_click_prod.py \
        --url https://fpl-backend-production-4151.up.railway.app \
        --user-id i78a-verify-$(date +%Y%m%d%H%M) \
        --question "Newcastle vs LEE (a domicilio), J4: ¿qué tal pinta ofensivamente y defensivamente para el Newcastle?" \
        --reps 3

Exit 0 when all reps selected get_fixture_outlook, no rep's trace contains
get_fixtures_for_gw, and every raw_output with a verdict carries
verdict_scope="match" for a one-GW horizon; exit 1 otherwise. The per-rep
lines are the evidence either way -- paste them into the PR/card.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

EXPECTED = "get_fixture_outlook"
DUMP = "get_fixtures_for_gw"
CONTRACT = Path(__file__).resolve().parents[3] / "field-notes" / "artifacts" / "i78a-canonical-phrases.json"


def _phrase_from_contract(phrase_id: str) -> str:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for p in data["phrases"]:
        if p["id"] == phrase_id:
            return p["question"]
    raise SystemExit(f"phrase id {phrase_id!r} not in {CONTRACT}")


def _ask(base_url: str, question: str, user_id: str) -> dict:
    resp = requests.post(
        f"{base_url.rstrip('/')}/ask",
        headers={"Content-Type": "application/json", "X-User-Id": user_id},
        json={"question": question, "debug": True},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--user-id", required=True, help="a FRESH id per run, so no session state leaks in")
    parser.add_argument("--question", default=None, help="the composer text, verbatim")
    parser.add_argument("--phrase-id", default="fc-new-att-cell")
    parser.add_argument("--reps", type=int, default=3)
    args = parser.parse_args()

    question = args.question or _phrase_from_contract(args.phrase_id)
    print(f"[i78a] question: {question!r}")
    print(f"[i78a] {args.reps} reps against {args.url} as user {args.user_id}")

    failures: list[str] = []
    for rep in range(args.reps):
        body = _ask(args.url, question, args.user_id)
        debug = body.get("debug") or {}
        trace = debug.get("routing_trace") or {}
        tool_calls = trace.get("orchestrator_tool_calls") or []
        selected = debug.get("selected_tool")
        raw = debug.get("raw_output") or {}
        n_fixtures = len(raw.get("fixtures") or []) if isinstance(raw, dict) else 0
        verdict_scope = raw.get("verdict_scope") if isinstance(raw, dict) else None
        verdict = raw.get("verdict") if isinstance(raw, dict) else None
        n_gws = len(raw.get("series") or []) if isinstance(raw, dict) else None
        print(
            f"  rep {rep}: selected_tool={selected!r} tool_calls={tool_calls!r} "
            f"tool_input={debug.get('tool_input')!r} series_len={n_gws} "
            f"verdict_scope={verdict_scope!r} raw_fixtures={n_fixtures} "
            f"final_text_chars={len(body.get('final_text') or '')}"
        )
        if verdict:
            print(f"         verdict: {verdict}")
        if selected != EXPECTED:
            failures.append(f"rep {rep}: selected_tool={selected!r}, expected {EXPECTED}")
        if DUMP in tool_calls:
            failures.append(f"rep {rep}: {DUMP} in tool_calls {tool_calls!r}")
        if verdict is not None and n_gws is not None and n_gws < 3:
            if verdict_scope != "match":
                failures.append(f"rep {rep}: {n_gws} GW(s) but verdict_scope={verdict_scope!r}")
            if "racha" in verdict.lower():
                failures.append(f"rep {rep}: short horizon still says 'racha': {verdict!r}")

    if failures:
        print("[i78a] FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"[i78a] OK: {args.reps}/{args.reps} reps -> {EXPECTED}, no {DUMP}, short-horizon verdicts describe the match")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())

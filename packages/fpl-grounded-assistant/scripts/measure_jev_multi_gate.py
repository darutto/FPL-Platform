"""Pilot: a single-vs-multi-tool GATE as one more Noul in the routing request.

Idea (user's): if the question needs several tools, send it straight to the
LLM orchestrator; otherwise route with Jev and take the latency/cost win.
Asked in the SAME request as `route` (parallel, no extra round trip).

Labels: "a complete answer needs outputs from >= 2 DIFFERENT tools", read
from the text. Multi = the cvg squad-eval + chip questions, build + chip,
two-position slices, transfer-vs-differential, wildcard-with-fixture-
justification, and every i93 fixture-cell phrase (attack + defence + team
snapshot by design). Everything else single. Second reference: luna's own
behaviour over 5 reps (>1 tool in >= 3 of 5 reps), which over-counts because
it includes redundant context calls.

Consequence asymmetry: a false "single" on a multi question routes one tool
and risks an incomplete answer (though the synthesis LLM still has the
catalog and can call a second tool -- one extra round, not a wrong answer);
a false "multi" only forfeits the saving. So the gate should favour recall
on multi; the sweep below shows the trade-off per threshold.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests

from measure_jev_tool_routing import PROVIDERS, _RETRYABLE_STATUSES, _retry_after_seconds, build_criteria_v2, load_api_key, PACKAGE_ROOT  # noqa: E402
from tool_routing_corpus import CORPUS, i93_fixture_cell_corpus  # noqa: E402

MULTI_IDS = {
    "cvg-01", "cvg-02", "cvg-03", "cvg-06", "cvg-07", "cvg-08", "cvg-11", "cvg-12",
    "sb-07", "sb-13", "sb-14", "ad-11",
}

GATE = {
    "needs_multiple_tools": {
        "type": "noul",
        "instructions": "Does a COMPLETE answer require combining the outputs of two or more DIFFERENT tools, rather than one tool's output?",
        "criteria": {
            "true": "The question asks for two things that live in different tools: evaluate the user's squad AND judge a chip; build a squad AND judge a chip; a club's fixture difficulty on attack AND on defence plus its players; players of two different positions under one budget; a named swap AND alternative differentials; a squad build justified by each player's fixtures.",
            "false": "One tool answers it fully: a single player's stats or form, one club's schedule or overview, one ranking, one gameweek fact, one chip verdict with no squad evaluation, one swap verdict, one squad build.",
        },
    },
}


def call(session: requests.Session, api_key: str, question: str, criteria: dict[str, object], max_attempts: int = 6) -> dict[str, Any]:
    p = PROVIDERS["native"]
    body = {"model": p["model"], "state": question, "questions": {
        "route": {"type": "choice", "instructions": "Which tool should answer this Fantasy Premier League question first?", "criteria": criteria},
        **GATE,
    }}
    for attempt in range(max_attempts):
        resp = session.post(p["url"], headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=body, timeout=20)
        if resp.status_code not in _RETRYABLE_STATUSES:
            resp.raise_for_status()
            return resp.json()
        if attempt == max_attempts - 1:
            resp.raise_for_status()
        time.sleep(_retry_after_seconds(resp.headers.get("retry-after")) or min(30.0, 2 ** attempt))
    raise RuntimeError("unreachable")


def luna_multi_rate() -> dict[str, float]:
    p = PACKAGE_ROOT / "field-notes-artifacts-llm-luna-5reps.jsonl"
    if not p.exists():
        return {}
    cnt: dict[str, list[bool]] = defaultdict(list)
    for line in p.open(encoding="utf-8"):
        r = json.loads(line)
        cnt[r["question_id"]].append(len(r["tool_sequence"]) > 1)
    return {k: sum(v) / len(v) for k, v in cnt.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PACKAGE_ROOT / "field-notes-artifacts-jev-multi-gate.jsonl")
    parser.add_argument("--delay", type=float, default=0.3)
    args = parser.parse_args()

    api_key = load_api_key(PROVIDERS["native"]["key_env"])
    criteria = build_criteria_v2()
    session = requests.Session()
    luna = luna_multi_rate()

    items = [(it, it["id"] in MULTI_IDS, "corpus") for it in CORPUS] + [(it, True, "i93") for it in i93_fixture_cell_corpus()]
    rows: list[dict[str, Any]] = []
    with args.out.open("w", encoding="utf-8") as fh:
        for it, label, src in items:
            try:
                a = call(session, api_key, it["question"], criteria)["answers"]
            except requests.RequestException as exc:
                print(f"  [{it['id']}] REQUEST FAILED: {exc}"); time.sleep(args.delay); continue
            row = {"id": it["id"], "set": src, "family": it["family"], "question": it["question"], "label_multi": label,
                   "p_multi": a["needs_multiple_tools"]["noul"], "route": a["route"]["choice"], "route_conf": a["route"]["confidence"],
                   "luna_multi_rate": luna.get(it["id"])}
            rows.append(row); fh.write(json.dumps(row, ensure_ascii=False) + "\n"); fh.flush()
            time.sleep(args.delay)

    pos = [r for r in rows if r["label_multi"]]; neg = [r for r in rows if not r["label_multi"]]
    print(f"{len(rows)} questions: {len(pos)} labelled multi, {len(neg)} single")
    print(f"P(multi) on labelled-multi : mean {sum(r['p_multi'] for r in pos)/len(pos):.2f}  min {min(r['p_multi'] for r in pos):.2f}")
    print(f"P(multi) on labelled-single: mean {sum(r['p_multi'] for r in neg)/len(neg):.2f}  max {max(r['p_multi'] for r in neg):.2f}")
    print(f"\n{'thr':>5s} {'recall multi':>13s} {'sent to LLM (of single)':>24s} {'kept for Jev':>13s}")
    for thr in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        tp = sum(r["p_multi"] >= thr for r in pos); fp = sum(r["p_multi"] >= thr for r in neg)
        kept = len(rows) - tp - fp
        print(f"{thr:5.1f} {tp:>6d}/{len(pos)} ({100*tp/len(pos):3.0f}%) {fp:>10d}/{len(neg)} ({100*fp/len(neg):3.0f}%) {kept:>7d}/{len(rows)} ({100*kept/len(rows):3.0f}%)")
    print("\nlabelled-multi with LOW P(multi) (< 0.4):")
    for r in sorted(pos, key=lambda r: r["p_multi"])[:12]:
        if r["p_multi"] < 0.4: print(f"  {r['id']:12s} p={r['p_multi']:.2f} luna_multi={r['luna_multi_rate']}  {r['question'][:80]}")
    print("labelled-single with HIGH P(multi) (>= 0.5):")
    for r in sorted(neg, key=lambda r: -r["p_multi"]):
        if r["p_multi"] >= 0.5: print(f"  {r['id']:12s} p={r['p_multi']:.2f} luna_multi={r['luna_multi_rate']}  {r['question'][:80]}")
    # agreement with luna's actual behaviour
    both = [r for r in rows if r["luna_multi_rate"] is not None]
    if both:
        lm = [r for r in both if r["luna_multi_rate"] >= 0.6]
        print(f"\nluna multi-tool in >=3/5 reps: {len(lm)}/{len(both)}; Jev P(multi)>=0.5 among those: {sum(r['p_multi']>=0.5 for r in lm)}/{len(lm)}")


if __name__ == "__main__":
    main()

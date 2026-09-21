"""Pilot: Jev speculative fan-out for multi-tool routing.

One request per question carrying FOUR questions over the same state:
  route                 choice  -- the v2 criteria (primary tool)
  need_team_snapshot    noul    -- companion: that club's real players/form
  need_my_squad         noul    -- companion: the user's own squad (i41 condition)
  need_gameweek_context noul    -- companion: GW number/deadline/DGW-BGW status

Questions run in parallel inside Jev and cannot see each other's answers;
code composes. This measures whether the companions fire where the product
already decided they should:
  * i93 fixture-cell phrases (24): primary get_fixture_outlook AND
    get_team_snapshot in the same round -- the i93 design decision
    (composed_primary_call), so need_team_snapshot is expected True.
  * tool_routing_corpus (118): need_my_squad expected True exactly on the
    routing_label_overlay rows (i41), False elsewhere; need_team_snapshot
    expected False except rows where get_team_snapshot is itself acceptable
    (excluded from that score); need_gameweek_context is NOT scored -- no
    decided policy labels it as a companion -- only its fire rate per family
    is reported, because luna's redundant get_gameweek_context-before-
    get_chip_advice call is the behaviour we want to know Jev avoids.

Native API only. Usage (from packages/fpl-grounded-assistant):
    python scripts/measure_jev_fanout.py --out field-notes-artifacts-jev-fanout.jsonl
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests

from measure_jev_tool_routing import (  # noqa: E402  (configures sys.path on import)
    PROVIDERS, _RETRYABLE_STATUSES, _retry_after_seconds, build_criteria_v2, load_api_key, PACKAGE_ROOT,
)
from jev_routing_criteria_v2 import NONE_OPTION  # noqa: E402
from routing_label_overlay import ADD_ACCEPTABLE, acceptable_tools  # noqa: E402
from tool_routing_corpus import CORPUS, i93_fixture_cell_corpus  # noqa: E402

THRESHOLD = 0.5

COMPANIONS: dict[str, dict[str, object]] = {
    "need_team_snapshot": {
        "type": "noul",
        "instructions": "Besides the main tool, does a good answer need this specific club's real players and their current form and stats (an overview of one team's squad)?",
        "criteria": {
            "true": "The question is about one club's match or outlook and the answer should name that club's players with real numbers.",
            "false": "No club's players are needed: a player question, a league-wide ranking, a gameweek fact, a chip or transfer verdict, a squad build.",
        },
    },
    "need_my_squad": {
        "type": "noul",
        "instructions": "Does answering correctly require knowing which players the user ALREADY OWNS in their own Fantasy squad?",
        "criteria": {
            "true": "The question presupposes an existing squad, with or without a possessive: 'mi equipo', 'mi plantilla', 'evalúa mi equipo', 'the rest of my team', 'the budget I have left', 'after these transfers', 'I need 4 midfielders'.",
            "false": "Nothing implies an existing squad: a market question, a comparison between players, a gameweek fact, building a team from scratch ('armar un equipo desde cero', 'arranco de cero').",
        },
    },
    "need_gameweek_context": {
        "type": "noul",
        "instructions": "Beyond what the main tool computes itself, does the answer need the current gameweek number, its deadline, or which upcoming rounds are double or blank, as extra context?",
        "criteria": {
            "true": "The question asks about the deadline, the current or next round number, or double/blank rounds, or cannot be answered without anchoring to the current round.",
            "false": "The main tool already handles the gameweek internally (chip advice, captaincy, fixture outlook, rankings), or the question is not time-anchored.",
        },
    },
}


def call(session: requests.Session, api_key: str, question: str, criteria: dict[str, object], max_attempts: int = 6) -> dict[str, Any]:
    p = PROVIDERS["native"]
    body = {
        "model": p["model"],
        "state": question,
        "questions": {
            "route": {
                "type": "choice",
                "instructions": "Which tool should answer this Fantasy Premier League question first?",
                "criteria": criteria,
            },
            **COMPANIONS,
        },
    }
    for attempt in range(max_attempts):
        resp = session.post(p["url"], headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=body, timeout=20)
        if resp.status_code not in _RETRYABLE_STATUSES:
            resp.raise_for_status()
            return resp.json()
        if attempt == max_attempts - 1:
            resp.raise_for_status()
        time.sleep(_retry_after_seconds(resp.headers.get("retry-after")) or min(30.0, 2 ** attempt))
    raise RuntimeError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PACKAGE_ROOT / "field-notes-artifacts-jev-fanout.jsonl")
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    api_key = load_api_key(PROVIDERS["native"]["key_env"])
    criteria = build_criteria_v2()
    session = requests.Session()

    items: list[dict[str, Any]] = []
    for it in i93_fixture_cell_corpus():
        items.append({**it, "set": "i93", "expect_snapshot": True, "expect_my_squad": False, "acceptable": list(it["acceptable_tools"])})
    for it in CORPUS:
        acc = acceptable_tools(it)
        items.append({
            **it, "set": "corpus", "acceptable": acc,
            "expect_snapshot": None if "get_team_snapshot" in acc else False,
            "expect_my_squad": it["id"] in ADD_ACCEPTABLE,
        })
    print(f"{len(items)} questions ({sum(i['set']=='i93' for i in items)} i93 + {sum(i['set']=='corpus' for i in items)} corpus), {len(criteria)} route options + {len(COMPANIONS)} nouls")

    rows: list[dict[str, Any]] = []
    with args.out.open("w", encoding="utf-8") as fh:
        for it in items:
            t0 = time.monotonic()
            try:
                res = call(session, api_key, it["question"], criteria)
            except requests.RequestException as exc:
                print(f"  [{it['id']}] REQUEST FAILED: {exc}")
                time.sleep(args.delay)
                continue
            lat = (time.monotonic() - t0) * 1000
            a = res["answers"]
            row = {
                "id": it["id"], "set": it["set"], "family": it["family"], "question": it["question"],
                "acceptable": it["acceptable"],
                "route": a["route"].get("choice"), "route_confidence": a["route"].get("confidence"),
                "p_snapshot": a["need_team_snapshot"]["noul"],
                "p_my_squad": a["need_my_squad"]["noul"],
                "p_gw_context": a["need_gameweek_context"]["noul"],
                "expect_snapshot": it["expect_snapshot"], "expect_my_squad": it["expect_my_squad"],
                "latency_ms": round(lat, 1), "usage": res.get("usage"),
            }
            row["route_ok"] = row["route"] in it["acceptable"]
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n"); fh.flush()
            print(f"  [{'OK' if row['route_ok'] else 'MISS'}] {it['id']:22s} route={row['route']!r:30s} snap={row['p_snapshot']:.2f} mine={row['p_my_squad']:.2f} gw={row['p_gw_context']:.2f}")
            time.sleep(args.delay)

    # ---- report
    def rate(xs: list[bool]) -> str:
        return f"{sum(xs)}/{len(xs)} ({100*sum(xs)/len(xs):.0f}%)" if xs else "-"

    print("\nPRIMARY route accuracy:")
    for s in ("i93", "corpus"):
        print(f"  {s:7s} {rate([r['route_ok'] for r in rows if r['set']==s])}")

    def noul_report(name: str, pkey: str, ekey: str) -> None:
        scored = [r for r in rows if r[ekey] is not None]
        tp = [r for r in scored if r[ekey] and r[pkey] >= THRESHOLD]
        fn = [r for r in scored if r[ekey] and r[pkey] < THRESHOLD]
        fp = [r for r in scored if not r[ekey] and r[pkey] >= THRESHOLD]
        tn = [r for r in scored if not r[ekey] and r[pkey] < THRESHOLD]
        pos = [r[pkey] for r in scored if r[ekey]]; neg = [r[pkey] for r in scored if not r[ekey]]
        print(f"\n{name} @ {THRESHOLD}: recall {len(tp)}/{len(tp)+len(fn)}  false-positives {len(fp)}/{len(fp)+len(tn)}")
        if pos: print(f"  P(true) on expected-True : mean {sum(pos)/len(pos):.2f}  min {min(pos):.2f}")
        if neg: print(f"  P(true) on expected-False: mean {sum(neg)/len(neg):.2f}  max {max(neg):.2f}")
        for r in fn: print(f"  FN {r['id']:22s} p={r[pkey]:.2f}  {r['question'][:80]}")
        for r in fp: print(f"  FP {r['id']:22s} p={r[pkey]:.2f}  {r['question'][:80]}")

    noul_report("need_team_snapshot", "p_snapshot", "expect_snapshot")
    noul_report("need_my_squad", "p_my_squad", "expect_my_squad")

    print(f"\nneed_gameweek_context fire rate (P>= {THRESHOLD}) by family (unscored, informational):")
    fam: dict[str, list[float]] = defaultdict(list)
    for r in rows: fam[r["family"]].append(r["p_gw_context"])
    for f, ps in sorted(fam.items()):
        print(f"  {f:22s} {sum(p>=THRESHOLD for p in ps)}/{len(ps)}  mean {sum(ps)/len(ps):.2f}")

    tin = sum(r["usage"]["input_tokens"] for r in rows); lat = sorted(r["latency_ms"] for r in rows)
    print(f"\ncost: {tin} input tokens, avg {tin/len(rows):.0f}/q, ${tin*0.042/1e6:.4f} total, ${tin*0.042/1e6/len(rows):.6f}/q; latency p50 {lat[len(lat)//2]:.0f}ms p95 {lat[int(len(lat)*.95)]:.0f}ms")


if __name__ == "__main__":
    main()

"""Pilot: stability of PLANS as route options over N reps.

Menu = CRITERIA_V2 (31 tools + none) + PLANS_V2 (3 compositions). One Choice
question. Expected route per question under Card E:
  * chip on existing/unspecified squad -> plan_chip_general_then_my_squad
    (STRICT); LENIENT also accepts get_chip_advice, because code can map a
    bare chip route onto the same plan -- the two counts bracket how much
    the policy depends on Jev vs on code.
  * build-from-scratch + chip           -> plan_build_squad_then_chip
  * i93 composed cell phrases           -> plan_fixture_cell_both_axes_with_players
  * everything else: overlay acceptable_tools (card_e="chip"), and any
    plan_* choice is a LEAK.
Reports per-rep and majority-over-reps counts, confidence bands, and the
questions whose route flips between reps.

Usage: python measure_jev_plans.py --reps 5 --out ../field-notes-artifacts-jev-plans-5reps.jsonl
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

from jev_routing_criteria_v2 import PLANS_V2  # noqa: E402
from measure_jev_tool_routing import PROVIDERS, build_criteria_v2, call_jev, load_api_key, PACKAGE_ROOT  # noqa: E402
from routing_label_overlay import acceptable_tools  # noqa: E402
from tool_routing_corpus import CORPUS, i93_fixture_cell_corpus  # noqa: E402

CHIP_PLAN = "plan_chip_general_then_my_squad"
BUILD_PLAN = "plan_build_squad_then_chip"
CELL_PLAN = "plan_fixture_cell_both_axes_with_players"
CHIP_IDS = {"cvg-01", "cvg-02", "cvg-03", "cvg-04", "cvg-05", "cvg-09", "cvg-10", "cvg-11", "cvg-12",
            "ad-03", "ad-04", "ad-07", "ad-10"}
BUILD_IDS = {"cvg-06", "cvg-07", "cvg-08", "sb-07"}
# ad-05 is transfer-or-chip: either the chip plan or transfer advice is fine.
AMBIG = {"ad-05": {CHIP_PLAN, "get_transfer_advice", "get_chip_advice"}}


def expected(item: dict, src: str) -> tuple[set[str], set[str], str]:
    """(strict set, lenient set, group)"""
    q = item["id"]
    if src == "i93":
        return {CELL_PLAN}, {CELL_PLAN}, "cell"
    if q in CHIP_IDS:
        return {CHIP_PLAN}, {CHIP_PLAN, "get_chip_advice"}, "chip"
    if q in BUILD_IDS:
        return {BUILD_PLAN}, {BUILD_PLAN}, "build"
    if q in AMBIG:
        return AMBIG[q], AMBIG[q], "ambig"
    acc = set(acceptable_tools(item, "chip"))
    return acc, acc, "single"


def fmt(xs: list[int]) -> str:
    return f"{sum(xs) / len(xs):5.1f} ({min(xs)}-{max(xs)})"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--delay", type=float, default=0.25)
    ap.add_argument("--out", type=Path, default=PACKAGE_ROOT / "field-notes-artifacts-jev-plans-5reps.jsonl")
    a = ap.parse_args()

    crit = {**build_criteria_v2(), **PLANS_V2}
    key = load_api_key(PROVIDERS["native"]["key_env"])
    p = PROVIDERS["native"]
    s = requests.Session()
    items = [(it, "corpus") for it in CORPUS] + [(it, "i93") for it in i93_fixture_cell_corpus()]
    print(f"{len(crit)} options, {len(items)} questions x {a.reps} reps")

    rows = []
    with a.out.open("w", encoding="utf-8") as fh:
        for rep in range(a.reps):
            t0 = time.time()
            tok = 0
            for it, src in items:
                try:
                    res = call_jev(s, key, p["url"], p["model"], it["question"], crit)
                except requests.RequestException as exc:
                    print(f"  [{it['id']}] rep{rep} FAILED: {exc}")
                    continue
                r = res["answers"]["route"]
                strict, lenient, grp = expected(it, src)
                row = {"rep": rep, "id": it["id"], "set": src, "group": grp, "question": it["question"],
                       "choice": r["choice"], "confidence": r["confidence"],
                       "strict_ok": r["choice"] in strict, "lenient_ok": r["choice"] in lenient,
                       "leak": grp == "single" and r["choice"].startswith("plan_"),
                       "usage": res.get("usage")}
                tok += (res.get("usage") or {}).get("input_tokens", 0)
                rows.append(row)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                time.sleep(a.delay)
            print(f"rep {rep}: {time.time() - t0:.0f}s, {tok / len(items):.0f} input tok/q")

    by_q: dict[str, list] = defaultdict(list)
    for r in rows:
        by_q[r["id"]].append(r)
    print(f"\n{'group':8s} {'n':>4s} {'strict/rep (min-max)':>24s} {'lenient/rep (min-max)':>24s} {'majority strict':>16s} {'flips':>6s}")
    for g in ("chip", "build", "cell", "ambig", "single"):
        qs = [q for q, rs in by_q.items() if rs[0]["group"] == g]
        if not qs:
            continue
        per_rep_s = [sum(r["strict_ok"] for r in rows if r["rep"] == k and r["group"] == g) for k in range(a.reps)]
        per_rep_l = [sum(r["lenient_ok"] for r in rows if r["rep"] == k and r["group"] == g) for k in range(a.reps)]
        maj = sum(sum(r["strict_ok"] for r in by_q[q]) > a.reps / 2 for q in qs)
        flips = sum(len({r["choice"] for r in by_q[q]}) > 1 for q in qs)
        print(f"{g:8s} {len(qs):>4d} {fmt(per_rep_s):>24s} {fmt(per_rep_l):>24s} {maj:>10d}/{len(qs):<5d} {flips:>6d}")

    leaks = [r for r in rows if r["leak"]]
    print(f"\nleaks (single-tool question -> plan): {len(leaks)} of {sum(r['group'] == 'single' for r in rows)} single rows")
    for q, n in Counter(r["id"] for r in leaks).most_common():
        print(f"  {q:8s} {n}/{a.reps}  {by_q[q][0]['question'][:70]}")

    print("\nconfidence on plan routes, by group (p50 / min):")
    for g in ("chip", "build", "cell"):
        cs = sorted(r["confidence"] for r in rows if r["group"] == g and r["choice"].startswith("plan_"))
        if cs:
            print(f"  {g:6s} p50 {cs[len(cs) // 2]:.2f}  min {cs[0]:.2f}  n={len(cs)}")

    print("\nquestions whose route FLIPS across reps (chip/build/cell/ambig):")
    for q, rs in by_q.items():
        if rs[0]["group"] != "single" and len({r["choice"] for r in rs}) > 1:
            print(f"  {q:8s} {dict(Counter(r['choice'] for r in rs))}  conf {[round(r['confidence'], 2) for r in rs]}")

    print("\nstrict misses by majority (chip/build/cell):")
    for q, rs in by_q.items():
        if rs[0]["group"] in ("chip", "build", "cell") and sum(r["strict_ok"] for r in rs) <= a.reps / 2:
            print(f"  {q:8s} {dict(Counter(r['choice'] for r in rs))} | {rs[0]['question'][:70]}")


if __name__ == "__main__":
    main()

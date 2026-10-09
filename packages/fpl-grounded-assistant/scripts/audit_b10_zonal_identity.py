"""Bloque 10: audit of the store-player <-> FPL-element identity adapter.

Offline and read-only: runs ``select_store_profile`` for every FPL element
with minutes against a shots store and reports, with denominators:

  * elements -> store: how many resolve, by method, and how many are
    rejected, by reason (the denominator is every element with minutes);
  * store -> elements: of the store profiles (>= MIN_PLAYER_SHOTS), how many
    are claimed by exactly one element, by none, or by several (a conflict
    the adapter must never produce).

Usage (from packages/fpl-grounded-assistant):
    python scripts/audit_b10_zonal_identity.py \
        --store ../fpl-tactical/data/tactical/seasons/2025-2026/understat_shots.parquet \
        --bootstrap ../../field-notes/artifacts/b10-bootstrap-2026-10-08.json \
        --out ../../field-notes/artifacts/b10-identity-audit.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
PKGS = PKG.parent
for p in [PKG, *(PKGS / n for n in (
        "fpl-api-client", "fpl-data-core", "fpl-player-registry", "fpl-query-tools",
        "fpl-tool-contract", "fpl-tool-runner", "fpl-captain-engine", "fpl-pipeline",
        "fpl-tactical", "fpl-historical", "football-data-contract", "sportmonks-client",
        "football-identity-registry", "football-intelligence"))]:
    sys.path.insert(0, str(p))

import pandas as pd  # noqa: E402

from fpl_grounded_assistant import player_snapshot_zonal as pz  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--bootstrap", required=True)
    ap.add_argument("--reference-bootstrap", default=None,
                    help="bootstrap holding the store season's FPL totals; pairs are "
                         "linked by player code and xG is compared as an independent control")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    boot = json.loads(Path(a.bootstrap).read_text(encoding="utf-8"))
    bundle = pz.load_store_bundle(pd.read_parquet(a.store))
    shares = bundle["shares"]
    elements = [e for e in boot["elements"] if (e.get("minutes") or 0) > 0]

    by_reason: Counter = Counter()
    by_method: Counter = Counter()
    claimed: dict[str, list[int]] = defaultdict(list)
    rejected_samples: dict[str, list[str]] = defaultdict(list)
    for el in elements:
        name, method, reason = pz.select_store_profile(el, boot, bundle)
        if name is not None:
            by_method[method] += 1
            claimed[name].append(el["id"])
        else:
            by_reason[reason] += 1
            if len(rejected_samples[reason]) < 6:
                rejected_samples[reason].append(f'{el.get("first_name")} {el.get("second_name")}')

    control = None
    if a.reference_bootstrap:
        ref = json.loads(Path(a.reference_bootstrap).read_text(encoding="utf-8"))
        ref_by_code = {e.get("code"): e for e in ref["elements"]}
        cur_by_id = {e["id"]: e for e in boot["elements"]}
        pairs, outliers = [], []
        for name, ids in claimed.items():
            r = ref_by_code.get(cur_by_id[ids[0]].get("code"))
            if not r or (r.get("minutes") or 0) < 450 or float(r.get("expected_goals") or 0) < 1.0:
                continue
            ratio = shares[name]["total_xg"] / float(r["expected_goals"])
            pairs.append(ratio)
            if not 0.4 <= ratio <= 2.5:
                outliers.append({"store": name, "fpl": f'{r["first_name"]} {r["second_name"]}',
                                 "store_np_xg": round(shares[name]["total_xg"], 2),
                                 "fpl_xg": float(r["expected_goals"])})
        pairs.sort()
        control = {
            "reference": a.reference_bootstrap,
            "pairs_compared": len(pairs),
            "median_ratio_store_np_xg_over_fpl_xg": round(pairs[len(pairs) // 2], 3) if pairs else None,
            "within_0.4_2.5": sum(1 for r in pairs if 0.4 <= r <= 2.5),
            "outliers": outliers,
        }

    store_claims = Counter(
        "one_element" if len(claimed.get(n, [])) == 1
        else "no_element" if not claimed.get(n) else "several_elements"
        for n in shares
    )
    report = {
        "store": a.store, "bootstrap": a.bootstrap,
        "elements_with_minutes": len(elements),
        "elements_resolved": sum(by_method.values()),
        "by_method": dict(by_method),
        "elements_rejected": dict(by_reason),
        "rejected_samples": rejected_samples,
        "store_profiles": len(shares),
        "store_profiles_by_claim": dict(store_claims),
        "independent_xg_control": control,
        "conflicts": {n: ids for n, ids in claimed.items() if len(ids) > 1},
    }
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rejected_samples"},
                     ensure_ascii=False, indent=2))
    return 0 if not report["conflicts"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

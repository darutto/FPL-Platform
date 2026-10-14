"""Rolling-origin evaluation of M1, M2 and M3: predict gameweek k from history strictly before each kickoff.

usage: python scripts/rolling_origin.py RUN_DIR OUT_DIR [--gws 2 3 4 5 6]
RUN_DIR is a finished ``trial-output/runs/TAG`` (store/, capture.json). Makes no request: the feature build already
cuts history strictly before each fixture's kickoff, so one build serves every gameweek. Writes
``OUT_DIR/rolling_origin.json`` (aggregates, one entry per gameweek plus ``all``), ``rolling_origin.md`` (the table)
and ``detail.json`` (names, local only, never committed). Run it with the PYTHONPATH of ``run_trial_checks.py``.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from football_intelligence.ingestion import live_trial_checks as chk
from football_intelligence.ingestion.live_trial import RESULT_KNOWN_AFTER_HOURS, build_team_registry


def pct(x: dict | None) -> str:
    return "—" if not x or not x.get("n") else f"{x['agree']}/{x['n']} = {100 * x['agree'] / x['n']:.1f} %"


def m2_row(detail: list[dict]) -> dict[str, Any]:
    starters = [d for d in detail if d["started"]]
    ok = [d for d in starters if d["status"] == "ok"]
    mapped = [d for d in ok if d["actual_role"] is not None]
    b = chk.baseline_comparison(starters, mapped)
    l = b["like_for_like_subset"]
    return {"starters": len(starters), "answers": len(ok), "abstains": len(starters) - len(ok),
            "abstain_reasons": dict(Counter(r for d in starters if d["status"] != "ok" for r in d["reason_codes"])),
            "like_for_like_n": l["n"], "role_module": l["role_module"], "role_baseline": l["role_baseline"],
            "flank_module": l["flank_module"], "flank_baseline": l["flank_baseline"],
            "differ": b["where_module_and_baseline_differ"], "both_right": l["both_right"], "both_wrong": l["both_wrong"],
            "role_changes": b["role_changes_since_last_start"], "baseline_answers": b["answers"],
            "baseline_role_all": b["role_agreement_all_it_answers"]}


def m1_row(detail: list[dict]) -> dict[str, Any]:
    scored = [d for d in detail if d["status"] == "ok" and d["start_probability"] is not None]
    pairs = [(d["start_probability"], d["started"]) for d in scored]
    rate = sum(y for _, y in pairs) / len(pairs) if pairs else None
    shares = [(d["share"], d["started"]) for d in scored if d["share"] is not None]
    played = [d for d in scored if d["minutes"] > 0 and d["expected_minutes"] is not None]
    return {"evaluated": len(detail), "answers": len(scored), "coverage": len(scored) / len(detail) if detail else None,
            "brier_module": chk.brier(pairs), "brier_constant": chk.brier((rate, y) for _, y in pairs) if rate is not None else None,
            "brier_raw_share": chk.brier(shares),
            "mae_minutes": sum(abs(d["expected_minutes"] - d["minutes"]) for d in played) / len(played) if played else None,
            "played_evaluated": len(played),
            "predicted_start_not_started": sum(1 for d in scored if d["start_probability"] >= chk.LARGE_MISS_HIGH and not d["started"]),
            "predicted_no_start_but_started": sum(1 for d in scored if d["start_probability"] <= chk.LARGE_MISS_LOW and d["started"])}


def m3_row(detail: list[dict]) -> dict[str, Any]:
    have = [d for d in detail if d["feature_trailing"] is not None]
    close = lambda a, b: (a is None and b is None) or (a is not None and b is not None and abs(a - b) < 1e-6)
    return {"team_fixtures": len(detail), "feature_rows": len(have),
            "trailing": chk.agreement((round(d["feature_trailing"], 6), round(d["expected"]["trailing"], 6)) for d in have),
            "leading": chk.agreement((round(d["feature_leading"], 6), round(d["expected"]["leading"], 6)) for d in have),
            "previous_rest": {"n": len(have), "agree": sum(1 for d in have if close(d["feature_previous_rest"], d["expected"]["previous_rest_days"]))},
            "next_rest": {"n": len(have), "agree": sum(1 for d in have if close(d["feature_next_rest"], d["expected"]["next_rest_days"]))},
            "module_ok": sum(1 for d in detail if d["status"] == "ok")}


def render(rows: dict[str, dict]) -> str:
    keys = list(rows)
    f = lambda v: "—" if v is None else f"{v:.3f}"
    out = ["## M2 — role and flank against \"same position as his last start\"", "",
           "| GW | Starters | Answers (abstains) | Like-for-like n | Role module | Role base | Flank module | Flank base | Differ: base / module / neither | Role changes: n / detected / new role predicted |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for k in keys:
        m = rows[k]["m2"]; d = m["differ"]; c = m["role_changes"]
        out.append(f"| {k} | {m['starters']} | {m['answers']} ({m['abstains']}) | {m['like_for_like_n']} | {pct(m['role_module'])} | {pct(m['role_baseline'])} | "
                   f"{pct(m['flank_module'])} | {pct(m['flank_baseline'])} | {d['baseline_right']} / {d['module_right']} / {d['neither']} | "
                   f"{c['n']} / {c['module_detected_a_change_beforehand']} / {c['module_predicted_the_new_role']} |")
    out += ["", "## M1 — start probability and expected minutes", "",
            "| GW | Evaluated | Answers (coverage) | Brier module | Brier constant | Brier raw share | MAE minutes (n) | Predicted start, did not / predicted no start, did |",
            "|---|---|---|---|---|---|---|---|"]
    for k in keys:
        m = rows[k]["m1"]
        out.append(f"| {k} | {m['evaluated']} | {m['answers']} ({100 * (m['coverage'] or 0):.0f} %) | {f(m['brier_module'])} | {f(m['brier_constant'])} | "
                   f"{f(m['brier_raw_share'])} | {'—' if m['mae_minutes'] is None else round(m['mae_minutes'], 1)} ({m['played_evaluated']}) | "
                   f"{m['predicted_start_not_started']} / {m['predicted_no_start_but_started']} |")
    out += ["", "## M3 — agreement with the calendar", "",
            "| GW | Team-fixtures | Trailing | Leading | Previous rest | Next rest | Module ok |", "|---|---|---|---|---|---|---|"]
    for k in keys:
        m = rows[k]["m3"]
        out.append(f"| {k} | {m['team_fixtures']} | {pct(m['trailing'])} | {pct(m['leading'])} | "
                   f"{m['previous_rest']['agree']}/{m['previous_rest']['n']} | {m['next_rest']['agree']}/{m['next_rest']['n']} | {m['module_ok']} |")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--gws", type=int, nargs="+", default=[2, 3, 4, 5, 6])
    args = parser.parse_args(argv)
    started = time.time()
    capture = json.loads((args.run_dir / "capture.json").read_text(encoding="utf-8"))
    store = args.run_dir / "store"
    frames = chk.load_frames(store / "features/builds-v2/live-trial")
    base = chk.load_base(store / "v1" / "premier-league")
    _, index = build_team_registry(capture)
    from football_data_contract import canonical_player_id
    absent = {canonical_player_id(f"{e['first_name']} {e['second_name']}".strip(), (e.get("birth_date") or "")[:10] or None)
              for e in capture["fpl"]["elements"] if e.get("status") in ("i", "s", "u")}
    m3_agg, m3_all = chk.run_m3(frames, base, capture, index, known_after_hours=RESULT_KNOWN_AFTER_HOURS, until_gameweek=max(args.gws))
    rows: dict[str, dict] = {}
    pooled: dict[str, list] = {"m1": [], "m2": [], "m3": []}
    names: dict[str, str] = {}
    for gw in args.gws:
        _, d2 = chk.run_m2(frames, base, gw)
        _, d1 = chk.run_m1(frames, base, gw, absent=absent)
        d3 = [d for d in m3_all if d["gameweek"] == gw]
        rows[str(gw)] = {"m1": m1_row(d1), "m2": m2_row(d2), "m3": m3_row(d3)}
        pooled["m1"] += d1; pooled["m2"] += d2; pooled["m3"] += d3
        names.update({d["player_id"]: d["name"] for d in d2})
        print(f"[{round(time.time() - started)}s] GW{gw}: m2 starters {rows[str(gw)]['m2']['starters']}", flush=True)
    rows["all"] = {"m1": m1_row(pooled["m1"]), "m2": m2_row(pooled["m2"]), "m3": m3_row(pooled["m3"])}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "rolling_origin.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    (args.out_dir / "rolling_origin.md").write_text(render(rows), encoding="utf-8")
    (args.out_dir / "detail.json").write_text(json.dumps({"names": names}), encoding="utf-8")
    print(render(rows))
    print(f"total {round(time.time() - started)} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

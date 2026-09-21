"""Pilot: can Jev fill the CATEGORICAL tool arguments, and does it beat regex?

Inventory of luna's tool_args over the 118-question corpus splits arguments
into four classes: names copied from the question (resolvers already do
this deterministically), literals (gw, budget, top_n -- regex), defaults
(horizon=5 -- code), and a small set of CATEGORICAL args mapped from
Spanish phrasing: axis, chip, season kind, position. Only the last class
is Choice-shaped. For each, this compares three things against labels
read from the question text:
  * a keyword/regex baseline (what code alone would do),
  * Jev Choice questions asked in ONE request together with the route
    question (speculative fan-out: every arg question is asked, code
    consumes only the ones relevant to the routed tool).
If regex ties Jev on an arg, Jev is not needed for that arg.

Labels are literal readings of the text. Two are judgement calls and are
flagged in LABELS: tf-13 axis=defence (user wants to sign a defender),
ad-05 chip=none ("el chip", unnamed).

Usage (from packages/fpl-grounded-assistant/scripts):
    python measure_jev_args.py --out ../field-notes-artifacts-jev-args.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests

from measure_jev_tool_routing import PROVIDERS, _RETRYABLE_STATUSES, _retry_after_seconds, build_criteria_v2, load_api_key, PACKAGE_ROOT  # noqa: E402
from tool_routing_corpus import CORPUS  # noqa: E402

ARG_QUESTIONS: dict[str, dict[str, object]] = {
    "axis": {
        "type": "choice",
        "instructions": "If the question is about fixture difficulty, which side of the game does it care about?",
        "criteria": {
            "attack": "How easy it is to SCORE: attackers, captaincy, 'en ataque', 'para atacar', 'ofensivo'.",
            "defence": "How easy it is to keep a CLEAN SHEET: defenders, goalkeepers, 'para la defensa', 'portería a cero', wanting to sign a defender.",
            "both": "Both sides explicitly asked.",
            "unspecified": "No side named: a plain schedule, a general 'how hard is the run', a team overview, or not about fixtures at all.",
        },
    },
    "chip": {
        "type": "choice",
        "instructions": "Which FPL chip, if any, does the question ask about?",
        "criteria": {
            "bench_boost": "Bench boost.",
            "triple_captain": "Triple captain.",
            "wildcard": "Wildcard.",
            "free_hit": "Free hit.",
            "none": "No specific chip named (including a generic 'the chip' with no name, or a question not about chips).",
        },
    },
    "season": {
        "type": "choice",
        "instructions": "Which season does the question refer to?",
        "criteria": {
            "previous": "The immediately previous season, named relatively: 'la temporada pasada', 'anterior', 'el año pasado', 'la última temporada completa'.",
            "explicit": "A season named by its years: '2024-25', '22/23', '2023-2024', '2025-26'.",
            "current_or_unspecified": "This season ('esta temporada', 'hasta ahora', 'lleva'), or no season mentioned at all.",
        },
    },
    "position": {
        "type": "choice",
        "instructions": "Which player position does the question restrict itself to?",
        "criteria": {
            "GKP": "Goalkeepers: 'arquero', 'portero', 'keeper'.",
            "DEF": "Defenders: 'defensa', 'defensor', 'defensas'.",
            "MID": "Midfielders: 'medio', 'mediocampista', 'medios'.",
            "FWD": "Forwards: 'delantero', 'atacante', 'forward'.",
            "multiple": "Two or more positions named together.",
            "none": "No position restriction.",
        },
    },
}

#: id -> {arg: label}. Only the args relevant to that question's family are
#: labelled; an arg absent here is not scored for that question.
LABELS: dict[str, dict[str, str]] = {
    # axis (team_fixtures)
    "tf-01": {"axis": "unspecified"}, "tf-02": {"axis": "unspecified"}, "tf-03": {"axis": "unspecified"},
    "tf-04": {"axis": "attack"}, "tf-05": {"axis": "unspecified"}, "tf-06": {"axis": "unspecified"},
    "tf-07": {"axis": "defence"}, "tf-08": {"axis": "defence"}, "tf-09": {"axis": "attack"},
    "tf-10": {"axis": "unspecified"}, "tf-11": {"axis": "unspecified"}, "tf-12": {"axis": "defence"},
    "tf-13": {"axis": "defence", "position": "DEF"},  # judgement: signing a defender
    "tf-14": {"axis": "unspecified"},
    # chip (chip_vs_gameweek + advice + sb-07)
    **{f"cvg-{i:02d}": {"chip": "bench_boost"} for i in (1, 2, 3, 4, 5, 6, 10, 11, 12)},
    "cvg-07": {"chip": "free_hit"}, "cvg-08": {"chip": "wildcard"}, "cvg-09": {"chip": "triple_captain"},
    "ad-01": {"chip": "none"}, "ad-02": {"chip": "none"}, "ad-03": {"chip": "wildcard"}, "ad-04": {"chip": "triple_captain"},
    "ad-05": {"chip": "none"},  # judgement: 'el chip', unnamed
    "ad-06": {"chip": "none"}, "ad-07": {"chip": "free_hit"}, "ad-08": {"chip": "none"}, "ad-09": {"chip": "none"},
    "ad-10": {"chip": "bench_boost"}, "ad-11": {"chip": "none"}, "ad-12": {"chip": "none"},
    "sb-07": {"chip": "bench_boost", "position": "none"},
    # season (season_history)
    **{i: {"season": "previous"} for i in ("sp-01", "sp-03", "sp-05", "sp-06", "sp-08", "sp-09", "sp-10", "ts-04", "ts-10")},
    **{i: {"season": "explicit"} for i in ("sp-02", "sp-04", "sp-07", "ts-05", "ts-07")},
    **{i: {"season": "current_or_unspecified"} for i in ("ts-01", "ts-02", "ts-03", "ts-06", "ts-08", "ts-09",
                                                         "sh-c01", "sh-c02", "sh-c03", "sh-c04", "sh-c05", "sh-c06", "sh-c07", "sh-c08")},
    # position (squad_building)
    "sb-01": {"position": "none"}, "sb-02": {"position": "MID"}, "sb-03": {"position": "FWD"}, "sb-04": {"position": "none"},
    "sb-05": {"position": "FWD"}, "sb-06": {"position": "DEF"}, "sb-08": {"position": "MID"}, "sb-09": {"position": "none"},
    "sb-10": {"position": "DEF"}, "sb-11": {"position": "none"}, "sb-12": {"position": "none"}, "sb-13": {"position": "multiple"},
    "sb-14": {"position": "none"},
}


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def keyword_baseline(question: str) -> dict[str, str]:
    q = _fold(question)
    att = bool(re.search(r"\b(ataque|atacar|ofensiv\w*|capitan\w*)\b", q))
    dfn = bool(re.search(r"\b(defensa|defensiv\w*|defensor\w*|porteria)\b", q))
    axis = "both" if att and dfn else "attack" if att else "defence" if dfn else "unspecified"
    chip = ("bench_boost" if "bench boost" in q else "triple_captain" if "triple captain" in q
            else "wildcard" if "wildcard" in q else "free_hit" if "free hit" in q else "none")
    if re.search(r"\b(20)?\d{2}\s*[-/]\s*(20)?\d{2}\b", q):
        season = "explicit"
    elif re.search(r"(temporada|ano) (pasad|anterior)|ultima temporada|ano pasado", q):
        season = "previous"
    else:
        season = "current_or_unspecified"
    pos = []
    if re.search(r"\b(arquer\w*|porter\w*|keeper)\b", q): pos.append("GKP")
    if re.search(r"\b(defens\w*)\b", q): pos.append("DEF")
    if re.search(r"\b(medio\w*|mediocamp\w*)\b", q): pos.append("MID")
    if re.search(r"\b(delanter\w*|atacante\w*|forward\w*)\b", q): pos.append("FWD")
    position = "multiple" if len(pos) > 1 else pos[0] if pos else "none"
    return {"axis": axis, "chip": chip, "season": season, "position": position}


def call(session: requests.Session, api_key: str, question: str, criteria: dict[str, object], max_attempts: int = 6) -> dict[str, Any]:
    p = PROVIDERS["native"]
    body = {"model": p["model"], "state": question, "questions": {
        "route": {"type": "choice", "instructions": "Which tool should answer this Fantasy Premier League question first?", "criteria": criteria},
        **ARG_QUESTIONS,
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PACKAGE_ROOT / "field-notes-artifacts-jev-args.jsonl")
    parser.add_argument("--delay", type=float, default=0.3)
    args = parser.parse_args()

    api_key = load_api_key(PROVIDERS["native"]["key_env"])
    criteria = build_criteria_v2()
    session = requests.Session()
    items = [it for it in CORPUS if it["id"] in LABELS]
    print(f"{len(items)} labelled questions, {len(ARG_QUESTIONS)} arg questions + route per request")

    rows: list[dict[str, Any]] = []
    with args.out.open("w", encoding="utf-8") as fh:
        for it in items:
            try:
                res = call(session, api_key, it["question"], criteria)
            except requests.RequestException as exc:
                print(f"  [{it['id']}] REQUEST FAILED: {exc}"); time.sleep(args.delay); continue
            a = res["answers"]
            row = {"id": it["id"], "question": it["question"], "labels": LABELS[it["id"]],
                   "baseline": keyword_baseline(it["question"]),
                   "jev": {k: a[k]["choice"] for k in ARG_QUESTIONS},
                   "jev_conf": {k: a[k]["confidence"] for k in ARG_QUESTIONS},
                   "route": a["route"]["choice"], "usage": res.get("usage")}
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n"); fh.flush()
            time.sleep(args.delay)

    print(f"\n{'arg':10s} {'n':>3s} {'keyword baseline':>18s} {'jev':>10s}   disagreements (id: label | baseline | jev conf)")
    for arg in ARG_QUESTIONS:
        scored = [r for r in rows if arg in r["labels"]]
        if not scored: continue
        b = sum(r["baseline"][arg] == r["labels"][arg] for r in scored)
        j = sum(r["jev"][arg] == r["labels"][arg] for r in scored)
        print(f"{arg:10s} {len(scored):>3d} {b:>7d}/{len(scored)} ({100*b/len(scored):3.0f}%) {j:>4d}/{len(scored)} ({100*j/len(scored):3.0f}%)")
        for r in scored:
            if r["baseline"][arg] != r["labels"][arg] or r["jev"][arg] != r["labels"][arg]:
                print(f"      {r['id']:7s} {r['labels'][arg]:22s} | {r['baseline'][arg]:22s} | {r['jev'][arg]:22s} {r['jev_conf'][arg]:.2f}")
    tin = sum(r["usage"]["input_tokens"] for r in rows)
    print(f"\ntokens: avg {tin/len(rows):.0f} input/q (route-only v2b was 3538; fan-out with 3 nouls was 4977)")


if __name__ == "__main__":
    main()

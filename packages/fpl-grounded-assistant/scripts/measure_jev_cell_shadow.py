"""Pilot phase 2, family 1: the Jev path for the /fixtures cell tap (i93 / i93-b).

Arm B2 of the comparison; arm A is ``measure_i93_composed_content.py`` on
main (the full orchestrator). Both arms are read by the SAME, unmodified
``analyze_i93_composed_content.py`` -- the shipped i93-b gate: the answer
names a player the snapshot RETURNED, has no transaction words, and the
calendar tool read BOTH axes (plus target_gw_ok, reported).

The path, per phrase (ONE provider call):
  1. One Jev request, three questions in parallel:
     * ``route``: v2 criteria WITHOUT get_chip_advice + PLANS_V2 + none (the
       same menu as the chip shadow -- one menu for every family);
     * ``chip``: unused here, kept so the request is the one prod would send;
     * ``club``: a Choice over the clubs CODE found in the text ("select
       instead of generate": code proposes candidates, Jev picks which one
       the question is about). Skipped when code finds exactly one.
  2. Code: route must be plan_fixture_cell_both_axes_with_players, a club
     must be chosen, and a gameweek literal must be in the text (J5 / fecha
     5 / jornada 5 / GW5). Anything else escalates to the full orchestrator
     (``--fallback``), which is what prod does for every question today.
  3. Code runs the plan: get_fixture_outlook(axis=attack) and (axis=defence)
     with team_query + target_gw, and get_team_snapshot(team_name,
     top_n_players=5) -- the exact calls i93-b asks the orchestrator to make.
  4. One provider call, no tools, writes the answer from those three outputs
     under the orchestrator's own MATCH_COMPOSITION rule (read out of
     ``orchestrator._SYSTEM_PROMPT``, not paraphrased).

Rows carry ``i93`` = ``measure_i93_composed_content.project(...)`` over a
trace of the calls this path executed, so the grader reads them exactly as it
reads the orchestrator's.

Usage (from packages/fpl-grounded-assistant/scripts; OPENAI_API_KEY in env,
TYPESAFE_API_KEY in .env.jev-pilot):
    python measure_jev_cell_shadow.py --reps 3 --fallback \
        --out ../field-notes-artifacts-phase2-cell-B2-jev.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import requests

from jev_routing_criteria_v2 import PLANS_V2  # noqa: E402
from measure_jev_chip_shadow import CHIP_ARG, ROUTE_Q  # noqa: E402
from measure_jev_tool_routing import PROVIDERS, build_criteria_v2, load_api_key  # noqa: E402
import measure_tool_routing as mt  # noqa: E402
from measure_i93_composed_content import _ResultCapture, project  # noqa: E402
from tool_routing_corpus import i93_fixture_cell_corpus  # noqa: E402

from fpl_grounded_assistant import orchestrator as orch_mod  # noqa: E402
from fpl_grounded_assistant.orchestrator import _extract_text_from_response  # noqa: E402
from fpl_grounded_assistant.provider_client import call_orch_provider  # noqa: E402
from fpl_grounded_assistant.team_fixture_calendar import _TEAM_RESOLVE_ALIASES  # noqa: E402
from fpl_grounded_assistant.tool_dispatch import run_tool  # noqa: E402

CELL_PLAN = "plan_fixture_cell_both_axes_with_players"
GW_RE = re.compile(r"\b(?:J|fecha|jornada|gameweek|GW)\s*(\d{1,2})\b", re.I)
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ']+")


def match_composition_rule() -> str:
    """The orchestrator's own MATCH_COMPOSITION line, verbatim."""
    for line in orch_mod._SYSTEM_PROMPT.splitlines():
        if "MATCH_COMPOSITION" in line:
            return line.strip()
    raise SystemExit("MATCH_COMPOSITION not found in orchestrator._SYSTEM_PROMPT")


BODY_SYSTEM = (
    "Eres el asistente de Fantasy Premier League de Bendito Fantasy. Respondes en "
    "espanol, breve y concreto, con los datos de los tools como unica fuente.\n"
    "Regla:\n{rule}\n\nSalidas de los tools para esta pregunta:\n{payload}\n"
)


def candidate_clubs(question: str, bootstrap: dict[str, Any]) -> dict[int, str]:
    """Clubs named in 1-3 word spans of the text, by EXACT name / short_name /
    alias key only.

    Not by the shared resolver's full rules: its last tier is a substring
    match on the club name (fine for a team_query the model wrote), which on
    arbitrary words of a sentence resolves "tal" (in "¿qué tal pinta...")
    to Crystal Palace -- measured on all 24 cell phrases. Candidate
    extraction scans every span, so only exact keys may count.
    """
    exact: dict[str, dict[str, Any]] = {}
    for t in bootstrap.get("teams", []) or []:
        for k in (t.get("name"), t.get("short_name")):
            if k:
                exact[str(k).lower()] = t
    for alias, target in _TEAM_RESOLVE_ALIASES.items():
        hit = next((t for t in bootstrap.get("teams", []) or []
                    if str(target).lower() in (str(t.get("short_name", "")).lower(), str(t.get("name", "")).lower())), None)
        if hit is not None:
            exact.setdefault(str(alias).lower(), hit)
    words = WORD_RE.findall(question)
    found: dict[int, str] = {}
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            t = exact.get(" ".join(words[i:i + n]).lower())
            if t is not None:
                found.setdefault(int(t["id"]), str(t.get("name") or t.get("short_name")))
    return found


def call_jev(session: requests.Session, key: str, criteria: dict[str, Any], question: str,
             clubs: dict[int, str]) -> dict[str, Any]:
    p = PROVIDERS["native"]
    questions: dict[str, Any] = {"route": {**ROUTE_Q, "criteria": criteria}, "chip": CHIP_ARG}
    if len(clubs) > 1:
        questions["club"] = {
            "type": "choice",
            "instructions": "Which club is this question about -- whose match outlook and players does it ask for?",
            "criteria": {name: f"The question asks about {name}." for name in clubs.values()},
        }
    body = {"model": p["model"], "state": question, "questions": questions}
    for attempt in range(6):
        r = session.post(p["url"], headers={"Authorization": f"Bearer {key}",
                                            "Content-Type": "application/json"}, json=body, timeout=20)
        if r.status_code not in {429, 503}:
            r.raise_for_status()
            return r.json()
        time.sleep(min(30.0, 2 ** attempt))
    r.raise_for_status()
    raise RuntimeError("unreachable")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--bootstrap", default=str(mt.DEFAULT_BOOTSTRAP))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fallback", action="store_true")
    ap.add_argument("--delay", type=float, default=0.25)
    a = ap.parse_args()

    bootstrap = json.loads(Path(a.bootstrap).read_text(encoding="utf-8"))
    bs = bootstrap.get("bootstrap", bootstrap)
    criteria = {k: v for k, v in build_criteria_v2().items() if k != "get_chip_advice"}
    criteria.update(PLANS_V2)
    rule = match_composition_rule()
    jev_key = load_api_key(PROVIDERS["native"]["key_env"])
    llm_key = mt.require_api_key(mt.PROVIDER)
    session = requests.Session()
    items = i93_fixture_cell_corpus()
    print(f"{len(items)} cell phrases x {a.reps} reps, fallback={a.fallback}, {mt.PROVIDER}/{mt.MODEL}")

    capture = _ResultCapture()
    original = orch_mod.ask_orchestrated
    orch_mod.ask_orchestrated = capture.wrap(original)
    try:
        run(a, items, bootstrap, bs, criteria, rule, jev_key, llm_key, session, capture)
    finally:
        orch_mod.ask_orchestrated = original
    print(f"\nGrade with:\n  python analyze_i93_composed_content.py {a.out}")


def run(a, items, bootstrap, bs, criteria, rule, jev_key, llm_key, session, capture) -> None:
    with a.out.open("w", encoding="utf-8") as fh:
        for rep in range(a.reps):
            for it in items:
                q = it["question"]
                t0 = time.time()
                clubs = candidate_clubs(q, bs)
                jev = call_jev(session, jev_key, criteria, q, clubs)
                ans = jev["answers"]
                route = ans["route"]["choice"]
                if len(clubs) == 1:
                    club = next(iter(clubs.values()))
                elif "club" in ans:
                    club = ans["club"]["choice"]
                else:
                    club = None
                gm = GW_RE.search(q)
                gw = int(gm.group(1)) if gm else None
                runnable = route == CELL_PLAN and club is not None and gw is not None

                row: dict[str, Any] = {
                    "question_id": it["id"], "family": it["family"], "rep": rep, "question": q,
                    "arm": "jev_cell", "i78a": it.get("i78a"),
                    "jev_route": route, "jev_route_conf": ans["route"]["confidence"],
                    "club_candidates": list(clubs.values()), "club": club,
                    "club_conf": ans["club"]["confidence"] if "club" in ans else None,
                    "gameweek_arg": gw, "exception": None,
                    "jev_input_tokens": (jev.get("usage") or {}).get("input_tokens"),
                }
                if not runnable:
                    if not a.fallback:
                        row.update(escalated=False, outcome="not_runnable", answer_text="", i93=None,
                                   cost_usd=0.0, latency_ms=round((time.time() - t0) * 1000, 1))
                    else:
                        # Same capture measure_i93 uses, so an escalated row is
                        # graded from the orchestrator's own trace, like arm A.
                        capture.last = None
                        obs = mt.run_one(it, rep, bootstrap, llm_key)
                        text = getattr(capture.last, "answer_text", "") if capture.last is not None else ""
                        row.update(escalated=True, outcome=f"escalated:{obs.get('outcome')}",
                                   answer_text=text,
                                   i93=project(capture.last, text, expected_gw=(it.get("i78a") or {}).get("gameweek"))
                                   if capture.last is not None else None,
                                   tool_sequence=obs.get("tool_sequence"), cost_usd=obs.get("cost_usd"),
                                   latency_ms=round((time.time() - t0) * 1000, 1))
                else:
                    boot = mt.bootstrap_for_call(bootstrap, None)
                    calls = [
                        ("get_fixture_outlook", {"axis": "attack", "team_query": club, "target_gw": gw}),
                        ("get_fixture_outlook", {"axis": "defence", "team_query": club, "target_gw": gw}),
                        ("get_team_snapshot", {"team_name": club, "top_n_players": 5}),
                    ]
                    trace = [{"name": n, "args": args, "output": run_tool(n, args, boot)} for n, args in calls]
                    payload = json.dumps([{"tool": e["name"], "args": e["args"], "output": e["output"]}
                                          for e in trace], ensure_ascii=False, default=str)
                    call = call_orch_provider(
                        mt.PROVIDER, model=mt.MODEL, system=BODY_SYSTEM.format(rule=rule, payload=payload),
                        tools=[], messages=[{"role": "user", "content": q}],
                        max_tokens=1024, temperature=None, top_p=None, api_key=llm_key,
                    )
                    text = (_extract_text_from_response(call.response, mt.PROVIDER) or "") if call.response else ""
                    fake = type("R", (), {"tool_calls_trace": trace})()
                    u = (call.input_tokens or 0, call.output_tokens or 0, call.cache_read_tokens or 0)
                    row.update(escalated=False, outcome="ok" if text else "empty_body", answer_text=text,
                               i93=project(fake, text, expected_gw=(it.get("i78a") or {}).get("gameweek")),
                               tool_sequence=[e["name"] for e in trace],
                               primary_input_tokens=u[0], primary_output_tokens=u[1],
                               primary_cache_read_tokens=u[2], cost_usd=mt.cost_usd(*u),
                               latency_ms=round((time.time() - t0) * 1000, 1))
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                print(f"  rep{rep} {it['id']:16s} {route:42s} club={club!s:16s} gw={gw} "
                      f"{'ESC' if row.get('escalated') else row['outcome']:10s} {row['latency_ms']:6.0f}ms")
                time.sleep(a.delay)
    print(f"\nGrade with:\n  python analyze_i93_composed_content.py {a.out}")


if __name__ == "__main__":
    main()

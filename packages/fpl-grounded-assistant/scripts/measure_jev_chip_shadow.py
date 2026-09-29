"""Pilot eval 4: the Jev shadow path for chip questions, graded by the i108 E3 gate.

Arm B of the comparison. Arm A is ``measure_tool_routing.py --team-id`` on
merged main (the full orchestrator). Both arms are graded by the SAME
deterministic grader (``scripts/grade_i108_chip_two_parts.py``), so this
measures the path, not the wording.

The path, per question (ONE provider call, not 2-3 rounds):
  1. Jev, one request: `route` (Choice over the v2 tool criteria WITHOUT
     get_chip_advice, plus the three plans, plus none_of_these) and `chip`
     (Choice over the four chips + none). Menu without get_chip_advice is the
     pilot's E4 finding: with the tool AND the plan in the menu the chip family
     splits and confidence falls to p50 0.70; without it, the plan takes the
     family at 0.94-0.98.
  2. Code decides: chip route = the plan, OR get_my_squad with a chip word in
     the text (closed vocabulary -- the rule that took the measured 11/13 to
     13/13). The gameweek is a literal, read by regex, never by a model.
  3. Code runs get_chip_advice deterministically (same run_tool, same
     bootstrap-with-_my_team_id as prod), so squad_fit is computed by E2.
  4. One provider call writes ONLY the body: the system prompt is the E3
     CHIP_COMPOSITION rule plus this tool's output with the E3 hidden fields
     dropped -- no tool catalog, no tool-use round.
  5. compose_chip_answer() prepends the header and appends the particular
     sentence, exactly as the orchestrator does after E3.

Escalation (``--fallback``, the designed behaviour). When the path cannot run
-- Jev does not route to the chip plan, or the chip argument comes back
``none`` because the question names no chip ("guardo el chip") and the tool's
enum needs one -- the question goes to the FULL orchestrator unchanged, which
is what production does for every question today. So the shadow path is
"cheap and fast when it is sure, exactly today's behaviour when it is not".
Without ``--fallback`` those rows are written with ``chip_trace: null`` and an
empty answer, which is what the first eval-4 run measured and is a gap in the
prototype, not in the design.

Note what the escalation gate is NOT: a confidence threshold. On the rows that
escalated, Jev is CONFIDENT (0.92-0.94) that no chip is named -- the blocker is
the value, not the uncertainty. A threshold would only add escalations that the
gate already passes (measured: thr 0.5 escalates 5/42 instead of 3/42, all five
passing rows).

Usage (from packages/fpl-grounded-assistant/scripts, OPENAI_API_KEY in env,
TYPESAFE_API_KEY in .env.jev-pilot):

    python measure_jev_chip_shadow.py --reps 3 --team-id 68643 \
        --out ../field-notes-artifacts-jev-chip-shadow-team.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

import requests

from jev_routing_criteria_v2 import PLANS_V2  # noqa: E402
from measure_jev_plans import CHIP_PLAN  # noqa: E402
from measure_jev_tool_routing import PROVIDERS, build_criteria_v2, load_api_key  # noqa: E402
import measure_tool_routing as mt  # noqa: E402
from tool_routing_corpus import CORPUS  # noqa: E402

from fpl_grounded_assistant.chip_two_part import chip_composition_rule, compose_chip_answer  # noqa: E402
from fpl_grounded_assistant.orchestrator import _MODEL_HIDDEN_FIELDS, _extract_text_from_response  # noqa: E402
from fpl_grounded_assistant.provider_client import call_orch_provider  # noqa: E402
from fpl_grounded_assistant.tool_dispatch import run_tool  # noqa: E402

#: The i108 E3 gate's 14 chip ids, in the field note's order.
CHIP_IDS: tuple[str, ...] = (
    "cvg-01", "cvg-02", "cvg-03", "cvg-04", "cvg-05", "cvg-09", "cvg-10",
    "cvg-11", "cvg-12", "ad-03", "ad-04", "ad-05", "ad-07", "ad-10",
)

#: Closed vocabulary for the code rule in step 2. A chip question names its
#: chip or the word "chip"; nothing else promotes a squad route to the plan.
CHIP_WORDS = re.compile(r"bench\s*boost|triple\s*captain|wildcard|free\s*hit|\bchips?\b", re.I)

#: Jev's own arg question for which chip. Same wording as measure_jev_args,
#: where it matched the regex baseline 100% on this corpus.
CHIP_ARG = {
    "type": "choice",
    "instructions": "Which FPL chip, if any, does the question ask about?",
    "criteria": {
        "bench_boost": "Bench boost.",
        "triple_captain": "Triple captain.",
        "wildcard": "Wildcard.",
        "free_hit": "Free hit.",
        "none": "No specific chip named (including a generic 'the chip' with no name, or a question not about chips).",
    },
}

ROUTE_Q = {
    "type": "choice",
    "instructions": "Which tool should answer this Fantasy Premier League question first?",
}

#: "fecha 2", "jornada 3", "GW4", "gw 5" -> the number. Nothing else is a
#: gameweek: "esta ronda"/"este finde" mean the current one, which the tool
#: resolves itself when the argument is absent.
GW_RE = re.compile(r"\b(?:fecha|jornada|gameweek|gw)\s*(\d{1,2})\b", re.I)

BODY_SYSTEM = (
    "Eres el asistente de Fantasy Premier League de Bendito Fantasy. Respondes en "
    "espanol rioplatense neutro, breve y concreto.\n"
    "Escribes UNICAMENTE el cuerpo de una respuesta sobre un chip. Reglas:\n"
    + chip_composition_rule()
    + "\nSalida del tool get_chip_advice para esta pregunta (usala como unica fuente "
      "de datos; no inventes numeros ni jugadores):\n{payload}\n"
)


def fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def call_jev(session: requests.Session, api_key: str, criteria: dict[str, Any], question: str,
             max_attempts: int = 6) -> dict[str, Any]:
    """One Jev request carrying route + chip, with the pilot's retry policy."""
    p = PROVIDERS["native"]
    body = {"model": p["model"], "state": question,
            "questions": {"route": {**ROUTE_Q, "criteria": criteria}, "chip": CHIP_ARG}}
    for attempt in range(max_attempts):
        resp = session.post(p["url"], headers={"Authorization": f"Bearer {api_key}",
                                               "Content-Type": "application/json"},
                            json=body, timeout=20)
        if resp.status_code not in {429, 503}:
            resp.raise_for_status()
            return resp.json()
        if attempt == max_attempts - 1:
            resp.raise_for_status()
        time.sleep(min(30.0, 2 ** attempt))
    raise RuntimeError("unreachable")


def is_chip_route(route: str, question: str) -> tuple[bool, str]:
    """(take the chip path, why). The code rule, closed vocabulary."""
    if route == CHIP_PLAN:
        return True, "plan"
    if route == "get_my_squad" and CHIP_WORDS.search(question):
        return True, "squad+chip_word"
    return False, route


def model_payload(output: dict[str, Any]) -> str:
    """The tool output as the model sees it: E3's hidden fields dropped."""
    hidden = _MODEL_HIDDEN_FIELDS.get("get_chip_advice", frozenset())
    return json.dumps({k: v for k, v in output.items() if k not in hidden},
                      ensure_ascii=False, default=str)


def write_body(question: str, output: dict[str, Any], api_key: str) -> tuple[str, Any]:
    """One provider call, no tools, body only. Returns (text, call result)."""
    call = call_orch_provider(
        mt.PROVIDER,
        model=mt.MODEL,
        system=BODY_SYSTEM.format(payload=model_payload(output)),
        tools=[],
        messages=[{"role": "user", "content": question}],
        max_tokens=1024,
        temperature=None,
        top_p=None,
        api_key=api_key,
    )
    if call.response is None:
        return "", call
    return (_extract_text_from_response(call.response, mt.PROVIDER) or ""), call


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--team-id", type=int, default=None, help="omit for the no-team arm")
    ap.add_argument("--bootstrap", default=str(mt.DEFAULT_BOOTSTRAP))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--delay", type=float, default=0.25)
    ap.add_argument("--fallback", action="store_true",
                    help="escalate a row the path cannot run to the full orchestrator (prod's behaviour today)")
    a = ap.parse_args()

    bootstrap = json.loads(Path(a.bootstrap).read_text(encoding="utf-8"))
    bs = bootstrap.get("bootstrap", bootstrap)
    team_names = {t.get("id"): t.get("name") for t in bs.get("teams", []) or []
                  if isinstance(t, dict) and t.get("id") is not None and t.get("name")}

    criteria = {k: v for k, v in build_criteria_v2().items() if k != "get_chip_advice"}
    criteria.update(PLANS_V2)
    jev_key = load_api_key(PROVIDERS["native"]["key_env"])
    llm_key = mt.require_api_key(mt.PROVIDER)
    session = requests.Session()
    items = [it for it in CORPUS if it["id"] in CHIP_IDS]
    print(f"{len(items)} chip questions x {a.reps} reps, menu {len(criteria)} options, "
          f"team_id={a.team_id}, {mt.PROVIDER}/{mt.MODEL}")

    rows: list[dict[str, Any]] = []
    with a.out.open("w", encoding="utf-8") as fh:
        for rep in range(a.reps):
            for it in items:
                q = it["question"]
                t0 = time.time()
                jev = call_jev(session, jev_key, criteria, q)
                route = jev["answers"]["route"]["choice"]
                take, why = is_chip_route(route, q)
                chip = jev["answers"]["chip"]["choice"]
                gw_match = GW_RE.search(q)
                gw = int(gw_match.group(1)) if gw_match else None

                output: dict[str, Any] | None = None
                body, call = "", None
                if not (take and chip != "none") and a.fallback:
                    # Exactly arm A's call path, on the same bootstrap copy.
                    obs = mt.run_one(it, rep, bootstrap, llm_key, team_id=a.team_id)

                    row = {
                        "question_id": it["id"], "family": it["family"], "rep": rep,
                        "question": q, "team_id_present": a.team_id is not None,
                        "arm": "jev_shadow", "escalated": True,
                        "jev_route": route, "jev_route_conf": jev["answers"]["route"]["confidence"],
                        "route_reason": why, "jev_chip": chip,
                        "jev_chip_conf": jev["answers"]["chip"]["confidence"],
                        "gameweek_arg": gw,
                        "tool_sequence": obs.get("tool_sequence") or [],
                        "chip_trace": obs.get("chip_trace"),
                        "answer_text_full": obs.get("answer_text_full") or "",
                        "answer_text": (obs.get("answer_text_full") or "")[:400],
                        "rounds_used": obs.get("rounds_used") or 0,
                        "latency_ms": round((time.time() - t0) * 1000, 1),
                        "jev_input_tokens": (jev.get("usage") or {}).get("input_tokens"),
                        "primary_input_tokens": obs.get("primary_input_tokens") or 0,
                        "primary_output_tokens": obs.get("primary_output_tokens") or 0,
                        "primary_cache_read_tokens": obs.get("primary_cache_read_tokens") or 0,
                        "cost_usd": obs.get("cost_usd"),
                        "pricing_known": obs.get("pricing_known"),
                        "outcome": f"escalated:{obs.get('outcome')}",
                    }
                    rows.append(row)
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fh.flush()
                    print(f"  rep{rep} {it['id']:7s} {route:38s} chip={chip:15s} ESC  "
                          f"{row['latency_ms']:7.0f}ms  {row['tool_sequence']}")
                    time.sleep(a.delay)
                    continue
                if take and chip != "none":
                    args: dict[str, Any] = {"chip": chip}
                    if gw is not None:
                        args["gameweek"] = gw
                    output = run_tool("get_chip_advice", args,
                                      mt.bootstrap_for_call(bootstrap, a.team_id))
                    body, call = write_body(q, output, llm_key)

                answer = compose_chip_answer(body, output, team_names) if output else body
                usage = (getattr(call, "input_tokens", None) or 0,
                         getattr(call, "output_tokens", None) or 0,
                         getattr(call, "cache_read_tokens", None) or 0) if call else (0, 0, 0)
                row = {
                    "question_id": it["id"], "family": it["family"], "rep": rep,
                    "question": q, "team_id_present": a.team_id is not None,
                    "arm": "jev_shadow", "escalated": False,
                    "jev_route": route, "jev_route_conf": jev["answers"]["route"]["confidence"],
                    "route_reason": why, "jev_chip": chip,
                    "jev_chip_conf": jev["answers"]["chip"]["confidence"],
                    "gameweek_arg": gw,
                    "tool_sequence": ["get_chip_advice"] if output else [],
                    "chip_trace": mt.extract_chip_trace(type("R", (), {
                        "tool_calls_trace": [{"name": "get_chip_advice", "output": output}]})())
                    if output else None,
                    "answer_text_full": answer,
                    "answer_text": answer[:400],
                    "rounds_used": 1 if output else 0,
                    "latency_ms": round((time.time() - t0) * 1000, 1),
                    "jev_input_tokens": (jev.get("usage") or {}).get("input_tokens"),
                    "primary_input_tokens": usage[0], "primary_output_tokens": usage[1],
                    "primary_cache_read_tokens": usage[2],
                    "cost_usd": mt.cost_usd(usage[0], usage[1], usage[2]),
                    "pricing_known": mt.MODEL in mt.PRICING_PER_1M_BY_MODEL,
                    "outcome": "ok" if output else "no_chip_call",
                }
                rows.append(row)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                print(f"  rep{rep} {it['id']:7s} {route:38s} chip={chip:15s} "
                      f"{'CALL' if output else 'skip':4s} {row['latency_ms']:7.0f}ms")
                time.sleep(a.delay)

    called = [r for r in rows if r["chip_trace"]]
    print(f"\n{len(rows)} rows, chip call on {len(called)} ({100*len(called)/len(rows):.0f}%)")
    print(mt.format_spend(rows))
    lat = sorted(r["latency_ms"] for r in rows)
    print(f"latency p50 {lat[len(lat)//2]/1000:.1f}s (Jev + tool + one body call)")
    jev_tok = [r["jev_input_tokens"] for r in rows if r["jev_input_tokens"]]
    if jev_tok:
        print(f"Jev input tokens/q avg {sum(jev_tok)/len(jev_tok):.0f} "
              f"(${0.042 * sum(jev_tok) / 1e6 / len(rows):.6f}/answer, output free)")
    print(f"\nGrade with:\n  python grade_i108_chip_two_parts.py {a.out}")


if __name__ == "__main__":
    main()

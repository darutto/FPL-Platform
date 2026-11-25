"""Before/after A/B for table-card prose (TOP_N_ASKS + evaluator CARD TURNS), 2026-11-14.

MEASUREMENT ONLY, and PAID: every run calls the provider. Do not run without the owner's cost approval.

Arms
----
before  main's prompts, rebuilt IN MEMORY from this branch's prompts by removing exactly the clauses this change
        added, then SHA-256-checked against main's pins (the ``MAIN_*_SHA256`` constants below, the values pinned
        in tests/test_locale_s0_plumbing.py on main before this change). A mismatch aborts before any call.
after   this branch's prompts, unchanged.

Both arms use ``measure_tool_routing.run_one`` (the path every routing measurement and the golden battery use),
the same pinned bootstrap, provider and model. ``ask_orchestrated`` is wrapped to capture the result, so each row
also records what ``run_one`` does not: whether the evaluator rejected the first answer (and why), whether a retry
ran, the list-shaped lines and words of the final answer, and the evaluator + retry tokens (priced at the primary
model's tariff: an estimate, labelled as such).

Usage (from packages/fpl-grounded-assistant):

    python scripts/measure_table_prose_ab.py ab --reps 3 --out ../../field-notes/artifacts/table-prose-ab.jsonl
    python scripts/measure_table_prose_ab.py golden --arm before --reps 3 --out <before.jsonl> --report <before.md> --allow-stale --yes
    python scripts/measure_table_prose_ab.py golden --arm after  --reps 3 --out <after.jsonl>  --report <after.md>  --allow-stale --yes
    python scripts/measure_table_prose_ab.py ab --out x --dry-run     # prints plan + SHA checks, makes NO call

``--dry-run`` needs no API key. Everything else needs OPENAI_API_KEY (packages/fpl-grounded-assistant/.env).
Answer text goes to the JSONL only; keep it out of any public text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import measure_tool_routing as base  # noqa: E402

base._configure_imports()

from fpl_grounded_assistant import evaluator as evaluator_mod  # noqa: E402
from fpl_grounded_assistant import orchestrator as orch_mod  # noqa: E402

#: Pins on main before this change (tests/test_locale_s0_plumbing.py at commit af5ad576, #645).
MAIN_ORCH_SHA256 = "b4b09715d1acd6691787b50f0fc237a97029a4c9c62def3c7b4c6f5c4ea9b956"
MAIN_LOOP_SHA256 = "25641eca803d135604d79f15f7e10859881951ca1b1ee1dbe7f4bbbd49e014b3"
MAIN_EVALUATOR_SHA256 = "82efcffa20f74632ce9e023ab49115f3e208dff00dbac668f2fbd30617726707"

#: The exact text this change added; removing it yields main's prompt (verified by the SHA check, not assumed).
_ORCH_ADDED_1 = (
    " get_player_involvement, get_gw_report: their figures and rows, so say what they mean instead of listing them."
)
_ORCH_ADDED_2_PREFIX = "TOP_N_ASKS:"
_EVAL_ADDED_PREFIX = "- CARD TURNS:"

#: 6 ES + 2 EN ranking-style questions (question wording only; no store values).
QUESTIONS: list[dict[str, str]] = [
    {"id": "tn-01", "lang": "es", "question": "dame el top 10 de jugadores por xg"},
    {"id": "tn-02", "lang": "es", "question": "dame el ranking de contribuciones defensivas, top 10"},
    {"id": "tn-03", "lang": "es", "question": "quien lidera en porterías a cero"},
    {"id": "tn-04", "lang": "es", "question": "top 5 por forma"},
    {"id": "tn-05", "lang": "es", "question": "ranking de diferenciales"},
    {"id": "tn-06", "lang": "es", "question": "top 10 de precio más bajo"},
    {"id": "tn-07", "lang": "en", "question": "give me the top 10 players by xG"},
    {"id": "tn-08", "lang": "en", "question": "ranking of the best differentials right now"},
]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_orch(prompt: str) -> str:
    out = prompt.replace(_ORCH_ADDED_1, "", 1)
    return "\n".join(ln for ln in out.split("\n") if not ln.lstrip().startswith(_ORCH_ADDED_2_PREFIX))


def _strip_eval(prompt: str) -> str:
    return "\n".join(ln for ln in prompt.split("\n") if not ln.lstrip().startswith(_EVAL_ADDED_PREFIX))


def build_arms() -> dict[str, dict[str, str]]:
    after = {
        "orch": orch_mod._SYSTEM_PROMPT,
        "loop": orch_mod._LOOP_SYSTEM_PROMPT,
        "evaluator": evaluator_mod._EVALUATOR_SYSTEM_PROMPT,
    }
    before = {
        "orch": _strip_orch(after["orch"]),
        "loop": _strip_orch(after["loop"]),
        "evaluator": _strip_eval(after["evaluator"]),
    }
    for key, pin in (("orch", MAIN_ORCH_SHA256), ("loop", MAIN_LOOP_SHA256), ("evaluator", MAIN_EVALUATOR_SHA256)):
        if _sha(before[key]) != pin:
            raise SystemExit(f"ABORT: rebuilt 'before' {key} prompt does not match main's pin")
    return {"before": before, "after": after}


def apply_arm(arm: dict[str, str]) -> None:
    orch_mod._SYSTEM_PROMPT = arm["orch"]
    orch_mod._LOOP_SYSTEM_PROMPT = arm["loop"]
    evaluator_mod._EVALUATOR_SYSTEM_PROMPT = arm["evaluator"]


_LIST_LINE = re.compile(r"^\s*(?:[-*•]\s+|\d{1,2}[.)]\s+)")


class _Capture:
    """Wraps ask_orchestrated so the last OrchestratorResult is readable after run_one returns."""

    def __init__(self) -> None:
        self.orig = orch_mod.ask_orchestrated
        self.last: Any = None

    def __call__(self, *a: Any, **kw: Any) -> Any:
        self.last = self.orig(*a, **kw)
        return self.last


def observe(question: dict[str, str], rep: int, bootstrap: dict[str, Any], api_key: str, arm: str,
            cap: _Capture) -> dict[str, Any]:
    q = {"id": question["id"], "family": "table_prose", "acceptable_tools": [], "control": False,
         "question": question["question"]}
    cap.last = None
    obs = base.run_one(q, rep, bootstrap, api_key)
    text = obs.get("answer_text_full") or ""
    res = cap.last
    verdict = getattr(res, "evaluator_verdict", None)
    extra_in = (getattr(res, "evaluator_input_tokens", 0) or 0) + (getattr(res, "retry_input_tokens", 0) or 0)
    extra_out = (getattr(res, "evaluator_output_tokens", 0) or 0) + (getattr(res, "retry_output_tokens", 0) or 0)
    obs.update(
        arm=arm,
        lang=question["lang"],
        list_lines=sum(1 for ln in text.splitlines() if _LIST_LINE.match(ln)),
        words=len(text.split()),
        retry_attempted=bool(getattr(res, "retry_attempted", False)),
        evaluator_approved=getattr(verdict, "approved", None),
        evaluator_complete=getattr(verdict, "complete", None),
        evaluator_feedback=getattr(verdict, "retry_feedback", None),
        evaluator_retry_tokens_in=extra_in,
        evaluator_retry_tokens_out=extra_out,
        evaluator_retry_cost_usd_estimate=base.cost_usd(extra_in, extra_out, 0),
    )
    return obs


def cmd_ab(args: argparse.Namespace) -> int:
    arms = build_arms()
    runs = len(QUESTIONS) * args.reps * 2
    print(f"SHA check OK: 'before' rebuilt == main's pins ({MAIN_ORCH_SHA256[:12]}, {MAIN_LOOP_SHA256[:12]}, "
          f"{MAIN_EVALUATOR_SHA256[:12]}); 'after' = branch prompts.")
    print(f"Plan: {len(QUESTIONS)} questions x {args.reps} reps x 2 arms = {runs} orchestrated runs "
          f"(each ~2 primary calls + 1 evaluator call, +2 on a retry: ~{runs * 3}-{runs * 5} provider calls).")
    print(f"Estimate: about ${runs * 0.003:.2f} (the #645 card A/B averaged ~$0.003 per run); "
          f"the owner approves the cost first.")
    if args.dry_run:
        return 0
    base._load_env_file(base.PACKAGE_ROOT / ".env")
    api_key = base.require_api_key(base.PROVIDER)
    bootstrap = json.loads(Path(args.bootstrap).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cap = _Capture()
    orch_mod.ask_orchestrated = cap
    total = 0.0
    with out.open("w", encoding="utf-8") as fh:
        for name in ("before", "after"):
            apply_arm(arms[name])
            for q in QUESTIONS:
                for rep in range(args.reps):
                    o = observe(q, rep, bootstrap, api_key, name, cap)
                    total += (o.get("cost_usd") or 0.0) + (o.get("evaluator_retry_cost_usd_estimate") or 0.0)
                    fh.write(json.dumps(o, ensure_ascii=False, default=str) + "\n")
                    fh.flush()
    print(f"Done. {runs} runs written to {out}. Spend estimate (primary + evaluator/retry): ${total:.4f}.")
    return 0


def cmd_golden(args: argparse.Namespace, rest: list[str]) -> int:
    arms = build_arms()
    apply_arm(arms[args.arm])
    print(f"golden battery (controls) with the '{args.arm}' prompts.")
    import golden_battery

    return golden_battery.main(["--tier", "controls"] + rest)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ab = sub.add_parser("ab")
    ab.add_argument("--reps", type=int, default=3)
    ab.add_argument("--out", required=True)
    ab.add_argument("--bootstrap", default=str(base.DEFAULT_BOOTSTRAP))
    ab.add_argument("--dry-run", action="store_true")
    g = sub.add_parser("golden")
    g.add_argument("--arm", choices=("before", "after"), required=True)
    args, rest = ap.parse_known_args(argv)
    return cmd_ab(args) if args.cmd == "ab" else cmd_golden(args, rest)


if __name__ == "__main__":
    raise SystemExit(main())

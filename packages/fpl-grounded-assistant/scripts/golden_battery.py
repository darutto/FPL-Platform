"""i25 golden battery — model acceptance runner.

Answers one question: **can this model be the production model?**

    python scripts/golden_battery.py --tier controls --out ../../field-notes/artifacts/golden-luna.jsonl
    python scripts/golden_battery.py --tier full --model gpt-5.6-luna --report golden-luna.md

Deliberately NOT wired to CI: it needs credentials and costs money, and the two
required checks must keep running without either. The mutation tests in
tests/test_golden_battery.py are the part CI runs, and they need no key.

What this file owns
-------------------
Running and reporting only. Every case, assertion and threshold lives in
``golden_axes.py``, so adding an axis (i32, language) never touches this file.
The call path is ``measure_tool_routing.run_one`` unchanged — the same one the
routing, squad and i41 measurements used, so a golden row and a one-off
measurement are directly comparable.

Guarantees the runner enforces, each from a specific failure already paid for
------------------------------------------------------------------------------
*   **Provider/model are asserted, not assumed.** Every call's
    ``fpl_provider_event`` is captured and compared against what was requested;
    a mismatch aborts. A silent fallback to another provider once produced a
    run that passed and proved nothing.
*   **Bootstrap is pinned by sha256** in the report header, with model,
    max_tokens, temperature and reps. Two people must not be able to run "the
    same" battery against a different answer space.
*   **Cost is estimated and confirmed before spending**, and the exact planned
    call count is printed.
*   **Exceptions invalidate the run.** An excepted observation is not evidence
    either way; the report refuses a verdict rather than averaging over it.
*   **Cases are deduplicated across axes.** sb-02 and the eight audit questions
    belong to two axes each; they are called once and scored twice.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import measure_tool_routing as base  # noqa: E402
import measure_squad_tool_routing as squad  # noqa: E402
import golden_axes as axes_mod  # noqa: E402

#: Mean cost per call over the i41 run (84 calls, $0.367) on gpt-5.6-luna.
#: Only used for the pre-spend estimate; the report prints real spend.
EST_USD_PER_CALL = 0.0044


class _ProviderEventCapture(logging.Handler):
    """Collects fpl_provider_event payloads so provider/model can be asserted."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.events: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        event = getattr(record, "fpl_event", None)
        if isinstance(event, dict) and "provider" in event:
            self.events.append(event)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plan(tier: str) -> "OrderedDict[str, axes_mod.Case]":
    """Every distinct case across all axes, in stable order, deduped by id."""
    plan: OrderedDict[str, axes_mod.Case] = OrderedDict()
    for axis in axes_mod.build_axes(tier):
        for case in axis.cases:
            plan.setdefault(case.id, case)
    return plan


def _verify_provider(events: list[dict[str, Any]], provider: str, model: str) -> None:
    """Abort on any event that did not come from what was requested."""
    if not events:
        raise SystemExit(
            "ABORT: no fpl_provider_event was captured. The run cannot prove "
            "which provider answered, so its result would mean nothing."
        )
    bad = [
        e for e in events
        if e.get("provider") != provider
        or (e.get("model") and model not in str(e.get("model")))
    ]
    if bad:
        seen = {(e.get("provider"), e.get("model")) for e in bad}
        raise SystemExit(
            f"ABORT: {len(bad)} provider event(s) did not match the requested "
            f"{provider}/{model}. Saw: {sorted(seen)}. A silent fallback "
            f"produces a run that can pass and prove nothing."
        )


def _markdown_report(
    header: dict[str, Any],
    results: list[axes_mod.AxisResult],
    accepted: bool,
    verdict: str,
    spend: float,
    exceptions: int,
) -> str:
    lines = [
        f"# Golden battery — {header['model']}",
        "",
        "Diffable: two models compare by reading two of these tables, with no re-run.",
        "",
        "| field | value |",
        "|---|---|",
        f"| model | `{header['model']}` |",
        f"| provider | `{header['provider']}` |",
        f"| tier | `{header['tier']}` |",
        f"| reps | {header['reps']} |",
        f"| max_tokens | {header['max_tokens']} |",
        f"| temperature | {header['temperature']} |",
        f"| bootstrap | `{header['bootstrap_name']}` |",
        f"| bootstrap sha256 | `{header['bootstrap_sha256']}` |",
        f"| distinct cases | {header['cases']} |",
        f"| calls | {header['calls']} |",
        f"| spend USD | {spend:.4f} |",
        f"| run at | {header['run_at']} |",
        "",
        "| axis | kind | result | threshold | verdict | reference |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        mark = "PASS" if r.passed else "**FAIL**"
        thr = (f"<= {r.threshold:.0%}" if r.kind == axes_mod.GUARD
               else f">= {r.threshold:.0%}")
        lines.append(
            f"| {r.axis_id} | {r.kind} | {r.numerator}/{r.denominator} "
            f"{r.label} ({r.rate:.0%}) | {thr} | {mark} | {r.reference} |"
        )
    lines += ["", f"**{verdict}**", ""]
    if exceptions:
        lines.append(
            f"> **INVALID RUN — {exceptions} harness exception(s).** An excepted "
            "observation is not evidence either way; do not read the rates above."
        )
    lines.append(
        "> Guards outrank targets: a breached guard fails the model even when "
        "every target passes."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", choices=("controls", "full"), default="controls",
                    help="controls = the 47 pinned routing cases (fast check); "
                         "full = all 90 (the decision run)")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", required=True, help="JSONL observations path")
    ap.add_argument("--report", default=None, help="markdown report path")
    ap.add_argument("--bootstrap", default=str(base.DEFAULT_BOOTSTRAP))
    ap.add_argument("--provider", default=base.PROVIDER)
    ap.add_argument("--model", default=base.MODEL)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    args = ap.parse_args(argv)

    base._configure_imports()
    base._load_env_file(base.PACKAGE_ROOT / ".env")

    # run_one reads these at call time; set them so --model/--provider are real
    # and not silently ignored.
    base.PROVIDER, base.MODEL = args.provider, args.model

    import os
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set; aborting before any paid call.", file=sys.stderr)
        return 2

    plan = _plan(args.tier)
    calls = len(plan) * args.reps
    bootstrap_path = Path(args.bootstrap)
    header = {
        "model": args.model, "provider": args.provider, "tier": args.tier,
        "reps": args.reps, "max_tokens": args.max_tokens, "temperature": "None (unset)",
        "bootstrap_name": bootstrap_path.name,
        "bootstrap_sha256": _sha256(bootstrap_path),
        "cases": len(plan), "calls": calls,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    print(f"\ngolden battery — tier={args.tier}  model={args.model}  provider={args.provider}")
    print(f"  {len(plan)} distinct cases x {args.reps} reps = {calls} calls")
    print(f"  bootstrap {bootstrap_path.name} sha256={header['bootstrap_sha256'][:16]}...")
    print(f"  estimated spend ~${calls * EST_USD_PER_CALL:.2f} "
          f"(at ${EST_USD_PER_CALL}/call, measured on i41)")
    if not args.yes:
        if input("  proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            print("  aborted before spending.")
            return 0

    capture = _ProviderEventCapture()
    logging.getLogger("fpl_grounded_assistant").addHandler(capture)
    logging.getLogger("fpl_grounded_assistant").setLevel(logging.INFO)

    bootstrap = dict(json.loads(bootstrap_path.read_text(encoding="utf-8")))
    bootstrap["_my_team_id"] = squad.TEAM_ID   # the ownership axis needs a team

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    observations: list[dict[str, Any]] = []
    spend = 0.0
    with out_path.open("w", encoding="utf-8") as fh:
        for idx, case in enumerate(plan.values(), start=1):
            for rep in range(args.reps):
                obs = base.run_one(case.as_question(), rep, bootstrap, api_key)
                obs["tier"] = args.tier
                observations.append(obs)
                fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
                fh.flush()
                spend += obs["cost_usd"]
            if idx % 10 == 0 or idx == len(plan):
                print(f"  {idx}/{len(plan)} cases, ${spend:.4f}", file=sys.stderr)

    _verify_provider(capture.events, args.provider, args.model)

    exceptions = sum(1 for o in observations if o.get("exception") is not None)
    results = [axes_mod.score_axis(a, observations) for a in axes_mod.build_axes(args.tier)]
    accepted, verdict = axes_mod.overall_verdict(results)
    if exceptions:
        accepted, verdict = False, (
            f"INVALID — {exceptions} harness exception(s); no verdict is claimed."
        )

    report = _markdown_report(header, results, accepted, verdict, spend, exceptions)
    print("\n" + report)
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
        print(f"report written to {args.report}", file=sys.stderr)
    print(f"observations written to {out_path}", file=sys.stderr)

    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())

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
    call count is printed. The per-call estimate was measured on one model, so
    it is offered only for that model; for any other the pre-spend line says the
    estimate is unknown and the report's cost is reported as unknown rather than
    computed from a tariff that does not apply.
*   **The API key follows the provider.** ``--provider gemini`` requires
    GOOGLE_API_KEY, not OPENAI_API_KEY -- the same mapping production uses in
    ``harness.py::_build_eval_client``. A flag that is accepted and then
    ignored, or that demands a key it will not use, is the i56 pattern.
*   **The corpus is preflighted offline before a cent is spent.** Every pinned
    player and team is resolved against the bootstrap; expired ones abort the
    run by name. Stale cases do not merely lose data, they manufacture
    findings: the first reference row reported pv-11 failing synthesis 3/3 and
    called it a reproduction of i46, when in fact Gordon had left and there was
    nothing to synthesise. ``--allow-stale`` proceeds while EXCLUDING them from
    scoring with the reason recorded and both denominators reported.
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
import golden_preflight as preflight  # noqa: E402

#: Mean cost per call over the i41 run (84 calls, $0.367) on gpt-5.6-luna.
#: Only used for the pre-spend estimate; the report prints real spend. It is a
#: measurement of ONE model, so it is offered only when that model is the one
#: being run -- a per-call figure from another tariff is not an estimate, it is
#: a wrong number wearing a dollar sign.
EST_USD_PER_CALL = 0.0044
EST_REFERENCE_MODEL = "gpt-5.6-luna"


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
    stale: "list[preflight.StaleCase] | None" = None,
    spend_line: str | None = None,
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
        f"| stale cases excluded | {header.get('stale_excluded', 0)} |",
        f"| spend USD | {spend_line or f'{spend:.4f}'} |",
        f"| pricing basis | {header.get('pricing_basis', 'unrecorded')} |",
        f"| run at | {header['run_at']} |",
        "",
        "| axis | kind | result | threshold | verdict | excluded | reference |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        mark = "PASS" if r.passed else "**FAIL**"
        if r.blocked_by and not r.passed:
            mark = f"**FAIL ({r.blocked_by})**"
        thr = (f"<= {r.threshold:.0%}" if r.kind == axes_mod.GUARD
               else f">= {r.threshold:.0%}")
        cell = (f"{r.numerator}/{r.denominator} {r.label} ({r.rate:.0%})")
        if r.companion_numerator is not None:
            cell += (f"<br>{r.companion_label}: {r.companion_numerator}/"
                     f"{r.denominator} ({(r.companion_rate or 0):.0%})")
        lines.append(
            f"| {r.axis_id} | {r.kind} | {cell} | {thr} | {mark} | "
            f"{r.excluded or ''} | {r.reference} |"
        )
    lines += ["", f"**{verdict}**", ""]
    for r in results:
        if not r.breakdown:
            continue
        lines += [f"### {r.axis_id} — behaviour breakdown (reported, not gated)", ""]
        if r.breakdown_note:
            lines += [r.breakdown_note, ""]
        lines += ["| behaviour | n |", "|---|---|"]
        for label, count in sorted(r.breakdown.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {label} | {count} |")
        lines.append("")
    if stale:
        lines += [
            "## Excluded by preflight",
            "",
            "Pinned entities that no longer resolve. Excluded from scoring, not "
            "counted as passes or failures — a question about a departed player "
            "measures nothing. The questions are deliberately NOT rewritten here: "
            "#171, i38 and i41 were scored against this exact text.",
            "",
            "| case | reason |",
            "|---|---|",
        ]
        for item in sorted(stale, key=lambda s: s.case_id):
            lines.append(f"| `{item.case_id}` | {item.reason} |")
        lines.append("")
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
    ap.add_argument("--provider", default=base.PROVIDER,
                    choices=sorted(base.API_KEY_ENV_BY_PROVIDER),
                    help="LLM provider (default: %(default)s); also selects "
                         "which API key env var is required")
    ap.add_argument("--model", default=base.MODEL,
                    help="model id (default: %(default)s); one with no entry in "
                         "measure_tool_routing.PRICING_PER_1M_BY_MODEL runs "
                         "with its cost reported as unknown")
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    ap.add_argument("--allow-stale", action="store_true",
                    help="run despite expired pinned entities, excluding those "
                         "cases from scoring with the reason recorded")
    args = ap.parse_args(argv)

    base._configure_imports()
    base._load_env_file(base.PACKAGE_ROOT / ".env")

    # run_one reads these at call time; set them so --model/--provider are real
    # and not silently ignored.
    base.PROVIDER, base.MODEL = args.provider, args.model

    # Provider-aware: gemini needs GOOGLE_API_KEY, not OPENAI_API_KEY. Same
    # mapping production uses (harness.py::_build_eval_client).
    api_key = base.require_api_key(args.provider)

    plan = _plan(args.tier)
    bootstrap_path = Path(args.bootstrap)

    # ---- preflight, before a cent is spent -----------------------------
    bootstrap_raw = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    stale = preflight.check({c.id: c.question for c in plan.values()}, bootstrap_raw)
    stale_ids = {item.case_id for item in stale}
    stale_reasons = {item.case_id: item.reason for item in stale}
    if stale:
        print("\n" + preflight.format_report(stale))
        if not args.allow_stale:
            print(
                "\nABORT: the corpus has expired against this bootstrap. A stale "
                "case does not merely lose data, it manufactures findings -- a "
                "question about a departed player fails every axis for reasons "
                "that have nothing to do with the model.\n"
                "Re-run with --allow-stale to proceed while excluding these "
                "cases (both denominators are reported), or replace the "
                "questions first.",
                file=sys.stderr,
            )
            return 4
        print(f"  --allow-stale: excluding {len(stale_ids)} case(s) from scoring.\n")

    calls = len(plan) * args.reps
    header = {
        "model": args.model, "provider": args.provider, "tier": args.tier,
        "reps": args.reps, "max_tokens": args.max_tokens, "temperature": "None (unset)",
        "bootstrap_name": bootstrap_path.name,
        "bootstrap_sha256": _sha256(bootstrap_path),
        "cases": len(plan), "calls": calls,
        "pricing_basis": (
            f"`{args.model}` per-1M rates"
            if args.model in base.PRICING_PER_1M_BY_MODEL
            else f"**none — `{args.model}` is not priced; cost is reported as "
                 f"unknown, never estimated at another model's rates**"
        ),
        "stale_excluded": len(stale_ids),
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    print(f"\ngolden battery — tier={args.tier}  model={args.model}  provider={args.provider}")
    print(f"  {len(plan)} distinct cases x {args.reps} reps = {calls} calls")
    print(f"  bootstrap {bootstrap_path.name} sha256={header['bootstrap_sha256'][:16]}...")
    if args.model == EST_REFERENCE_MODEL:
        print(f"  estimated spend ~${calls * EST_USD_PER_CALL:.2f} "
              f"(at ${EST_USD_PER_CALL}/call, measured on i41)")
    else:
        print(f"  estimated spend UNKNOWN for {args.model}: the "
              f"${EST_USD_PER_CALL}/call figure was measured on "
              f"{EST_REFERENCE_MODEL} and does not transfer. "
              f"{calls} paid calls are planned.")
    if not args.yes:
        if input("  proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            print("  aborted before spending.")
            return 0

    capture = _ProviderEventCapture()
    logging.getLogger("fpl_grounded_assistant").addHandler(capture)
    logging.getLogger("fpl_grounded_assistant").setLevel(logging.INFO)

    bootstrap = dict(bootstrap_raw)
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
                if case.id in stale_ids:
                    obs["excluded_from_scoring"] = stale_reasons[case.id]
                observations.append(obs)
                fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
                fh.flush()
                spend += obs["cost_usd"] or 0.0
            if idx % 10 == 0 or idx == len(plan):
                print(f"  {idx}/{len(plan)} cases, "
                      f"{base.format_spend(observations)}", file=sys.stderr)

    _verify_provider(capture.events, args.provider, args.model)

    exceptions = sum(1 for o in observations if o.get("exception") is not None)
    results = [axes_mod.score_axis(a, observations, stale_ids)
               for a in axes_mod.build_axes(args.tier)]
    accepted, verdict = axes_mod.overall_verdict(results)
    if exceptions:
        accepted, verdict = False, (
            f"INVALID — {exceptions} harness exception(s); no verdict is claimed."
        )

    report = _markdown_report(header, results, accepted, verdict, spend,
                              exceptions, stale,
                              spend_line=base.format_spend(observations))
    print("\n" + report)
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
        print(f"report written to {args.report}", file=sys.stderr)
    print(f"observations written to {out_path}", file=sys.stderr)

    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())

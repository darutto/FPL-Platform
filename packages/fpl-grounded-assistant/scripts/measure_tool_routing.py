"""Drive ask_orchestrated() directly against the frozen bootstrap to measure
which tool the model picks for each question in tool_routing_corpus.CORPUS,
and where it confuses tool-family boundaries.

This is a MEASUREMENT script: it makes real, paid LLM calls (no mocking, no
test-injection). It changes no product behaviour -- orchestrator.py and
friends are only imported, never edited.

Usage (from packages/fpl-grounded-assistant, with PYTHONPATH set up so this
scripts/ directory and every packages/* directory are importable -- see
run_full_measurement.sh / the field-notes report for the exact invocation
used):

    python scripts/measure_tool_routing.py --out field-notes/artifacts/tool-routing-observations-2026-08-23.jsonl --reps 5

Every observation is appended to --out as one JSON line IMMEDIATELY after the
call returns, and the file handle is flushed after every write. A crash mid
run, or a bug in the (separate) analysis script, cannot lose already-paid-for
observations -- they are on disk before any aggregate is computed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOOTSTRAP = REPO_ROOT / "field-notes" / "artifacts" / "agentic-loop-bootstrap-2026-08-18.json"

# Production config per the measurement task: pinned explicitly rather than
# read from FPL_ORCH_PROVIDER/FPL_ORCH_MODEL so a stray env var can't silently
# change what was measured.
PROVIDER = "openai"
MODEL = "gpt-5.6-luna"

#: gpt-5.6-luna per-1M-token pricing (see run_agentic_loop_experiment.py,
#: OpenAI rates https://developers.openai.com/api/docs/models/, 2026-08-20).
PRICING_PER_1M: dict[str, float] = {"input": 0.20, "output": 1.20, "cache_read": 0.02}


def _configure_imports() -> None:
    """Put every packages/* dir and this scripts/ dir on sys.path."""
    packages_dir = REPO_ROOT / "packages"
    for pkg in sorted(packages_dir.iterdir()):
        if pkg.is_dir():
            sys.path.insert(0, str(pkg))
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def _load_env_file(env_path: Path) -> None:
    """Minimal KEY=VALUE .env loader; does not overwrite already-set env vars."""
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def cost_usd(input_tokens: int, output_tokens: int, cache_read_tokens: int) -> float:
    return (
        input_tokens / 1_000_000 * PRICING_PER_1M["input"]
        + output_tokens / 1_000_000 * PRICING_PER_1M["output"]
        + cache_read_tokens / 1_000_000 * PRICING_PER_1M["cache_read"]
    )


def extract_tool_sequence(result: Any) -> list[str]:
    """Full ordered tool-name sequence actually executed for one call.

    Reads ``result.tool_calls_trace`` (populated for both the legacy
    single-round path and the bounded-loop path -- see orchestrator.py's
    ``_attaches_tool_calls_trace`` decorator). Falls back to the single
    ``tool_chosen`` field only if the trace is empty, which should not
    happen on a result that executed a tool; the fallback exists so a
    harness bug never masquerades as "no tool called".
    """
    trace = getattr(result, "tool_calls_trace", None) or ()
    names = [entry.get("name") for entry in trace if entry.get("name")]
    if names:
        return names
    if getattr(result, "tool_chosen", None):
        return [result.tool_chosen]
    return []


def run_one(question: dict[str, Any], rep_index: int, bootstrap: dict[str, Any], api_key: str) -> dict[str, Any]:
    """Make one ask_orchestrated() call and return a flat observation dict.

    Never raises: any exception is captured into the observation itself so
    the caller can write it to disk and keep going. An excepted observation
    has outcome="harness_exception" and a non-null "exception" field --
    callers MUST check for these before trusting any aggregate (two identical
    tracebacks diff clean and would otherwise look like a normal result).
    """
    from fpl_grounded_assistant.orchestrator import ask_orchestrated

    t0 = time.monotonic()
    base = {
        "question_id": question["id"],
        "family": question["family"],
        "acceptable_tools": question["acceptable_tools"],
        "control": question["control"],
        "pinned": bool(question.get("pinned", False)),
        "rep": rep_index,
        "question": question["question"],
        "model": MODEL,
        "provider": PROVIDER,
        "captured_at": None,
        "latency_ms": None,
        "exception": None,
    }
    try:
        result = ask_orchestrated(
            question["question"],
            bootstrap,
            provider=PROVIDER,
            model=MODEL,
            api_key=api_key,
            max_tokens=1024,
            temperature=None,
            top_p=None,
            _eval_client=None,
        )
        tool_output = result.tool_output if isinstance(result.tool_output, dict) else {}
        base.update(
            outcome=result.outcome,
            tool_chosen=result.tool_chosen,
            tool_sequence=extract_tool_sequence(result),
            tool_call_count=result.tool_call_count,
            # --- i25 golden battery: assertion surface -------------------
            # Added so the battery asserts on the same observation the other
            # measurements produce, instead of forking a second call path.
            # Three of this week's four measurements were wrong because the
            # instrument was improvised; one shared path is the fix.
            tool_args=dict(result.tool_args or {}),
            tool_output_status=tool_output.get("status"),
            tool_output_code=tool_output.get("code"),
            tool_output_metric=tool_output.get("metric"),
            tool_output_order=tool_output.get("order"),
            # i52: whether the ranking used the model's own candidate list or
            # the deterministic pool. Read from the structured field rather
            # than inferred from prose, which is what blocked this count.
            # Additive: no existing decision rule reads these.
            tool_output_pool_source=tool_output.get("pool_source"),
            tool_output_pool_size=tool_output.get("pool_size"),
            synthesis_turn=bool(getattr(result, "synthesis_turn", False)),
            answer_text=(result.answer_text or "")[:400],
            rounds_used=getattr(result, "rounds_used", 0),
            error=result.error,
            primary_input_tokens=result.primary_input_tokens,
            primary_output_tokens=result.primary_output_tokens,
            primary_cache_read_tokens=result.primary_cache_read_tokens,
            total_tokens=result.total_tokens,
            cost_usd=cost_usd(
                result.primary_input_tokens,
                result.primary_output_tokens,
                result.primary_cache_read_tokens,
            ),
        )
    except Exception as exc:  # noqa: BLE001 -- must never lose an observation
        base.update(
            outcome="harness_exception",
            tool_chosen=None,
            tool_sequence=[],
            tool_call_count=0,
            tool_args={},
            tool_output_status=None,
            tool_output_code=None,
            tool_output_metric=None,
            tool_output_order=None,
            synthesis_turn=False,
            answer_text="",
            rounds_used=0,
            error=str(exc),
            primary_input_tokens=0,
            primary_output_tokens=0,
            primary_cache_read_tokens=0,
            total_tokens=0,
            cost_usd=0.0,
            exception=repr(exc),
        )
    base["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
    base["captured_at"] = datetime.now(timezone.utc).isoformat()
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=str(DEFAULT_BOOTSTRAP))
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=0, help="0 = all questions in the corpus")
    parser.add_argument("--only-family", default=None)
    parser.add_argument("--only-id", default=None, help="comma-separated question ids")
    args = parser.parse_args(argv)

    _configure_imports()
    _load_env_file(PACKAGE_ROOT / ".env")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set (checked env + .env); aborting before any paid call.", file=sys.stderr)
        return 2

    from tool_routing_corpus import CORPUS

    questions = list(CORPUS)
    if args.only_family:
        questions = [q for q in questions if q["family"] == args.only_family]
    if args.only_id:
        wanted = set(args.only_id.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    if args.limit:
        questions = questions[: args.limit]
    if not questions:
        print("No questions matched the given filters; nothing to do.", file=sys.stderr)
        return 1

    bootstrap = json.loads(Path(args.bootstrap).read_text(encoding="utf-8"))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_calls = len(questions) * args.reps
    print(
        f"Running {len(questions)} questions x {args.reps} reps = {total_calls} calls "
        f"against {PROVIDER}/{MODEL}. Appending to {out_path}",
        file=sys.stderr,
    )

    n_done = 0
    n_exceptions = 0
    total_cost = 0.0
    with out_path.open("a", encoding="utf-8") as fh:
        for q in questions:
            for rep in range(args.reps):
                obs = run_one(q, rep, bootstrap, api_key)
                fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
                fh.flush()
                n_done += 1
                if obs["exception"] is not None:
                    n_exceptions += 1
                total_cost += obs["cost_usd"]
                if n_done % 25 == 0 or n_done == total_calls:
                    print(
                        f"  {n_done}/{total_calls} done, {n_exceptions} exceptions so far, "
                        f"${total_cost:.4f} so far",
                        file=sys.stderr,
                    )

    print(
        f"DONE. {n_done} observations written, {n_exceptions} exceptions, total cost ${total_cost:.4f}",
        file=sys.stderr,
    )
    return 0 if n_exceptions == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())

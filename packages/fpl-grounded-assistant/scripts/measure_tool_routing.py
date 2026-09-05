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

Provider and model are pinned below and overridable only by an explicit flag on
the scripts that expose one; the API key follows the provider, and cost is
priced per model or reported as unknown. Each row also carries
``empty_provider_response`` so an empty-synthesis event belongs to a row rather
than only to the console.
"""
from __future__ import annotations

import argparse
import json
import logging
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

#: Provider -> the env var holding that provider's API key. This is the SAME
#: mapping production uses in ``fpl_grounded_assistant/harness.py``
#: (``_build_eval_client``: openai -> OPENAI_API_KEY, gemini -> GOOGLE_API_KEY,
#: anthropic -> ANTHROPIC_API_KEY) and that
#: ``run_agentic_loop_experiment.PROVIDERS[*]["key_env"]`` already encodes; it
#: is not a second opinion about which key a provider needs.
#: tests/test_probe_provider_flags.py fails if this drifts from either, or if
#: anyone pins the lookup back to OPENAI_API_KEY for every provider.
API_KEY_ENV_BY_PROVIDER: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
}

#: Per-1M-token pricing BY MODEL. A model absent from this table has no price
#: here, and the absence is reported as such: tokens are still recorded, cost is
#: recorded as unknown. It is never estimated at another model's rates -- a cost
#: computed from the wrong tariff is a number that looks true and is wrong,
#: which is worse than no number at all.
#: Rows mirror ``run_agentic_loop_experiment.DEFAULT_MODEL_PRICING_PER_1M``
#: (OpenAI rates https://developers.openai.com/api/docs/models/, 2026-08-20).
PRICING_PER_1M_BY_MODEL: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0, "cache_read": 0.10},
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00, "cache_read": 0.15},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075},
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20, "cache_read": 0.02},
    "gpt-5.6-terra": {"input": 2.00, "output": 12.00, "cache_read": 0.20},
    "gpt-5.6-sol": {"input": 5.00, "output": 30.00, "cache_read": 0.50},
}


def api_key_env_for(provider: str) -> str:
    """Name of the env var holding *provider*'s key.

    Unknown providers get no OPENAI_API_KEY consolation prize: handing one
    provider's key to another produces an auth error at best and a call billed
    to the wrong account at worst.
    """
    try:
        return API_KEY_ENV_BY_PROVIDER[provider]
    except KeyError:
        raise SystemExit(
            f"Unknown provider {provider!r}. Known: "
            f"{', '.join(sorted(API_KEY_ENV_BY_PROVIDER))}."
        ) from None


def resolve_api_key(provider: str) -> tuple[str | None, str]:
    """Return ``(key_or_None, env_var_name)`` for *provider* from os.environ."""
    env_name = api_key_env_for(provider)
    return os.environ.get(env_name), env_name


def require_api_key(provider: str) -> str:
    """Return *provider*'s key or exit 2 naming the var that was missing."""
    key, env_name = resolve_api_key(provider)
    if not key:
        print(
            f"{env_name} not set (checked env + .env) for provider {provider!r}; "
            "aborting before any paid call.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return key


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


def cost_usd(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    model: str | None = None,
) -> float | None:
    """Cost for one call, or ``None`` when *model* has no price in the table.

    ``None`` means "unknown", not "free". Callers must render it as unknown --
    see ``format_spend`` -- rather than folding it into a total at 0.0 or at
    some other model's rates.
    """
    prices = PRICING_PER_1M_BY_MODEL.get(model if model is not None else MODEL)
    if not prices:
        return None
    return (
        input_tokens / 1_000_000 * prices["input"]
        + output_tokens / 1_000_000 * prices["output"]
        + cache_read_tokens / 1_000_000 * prices["cache_read"]
    )


def format_spend(observations: list[dict[str, Any]]) -> str:
    """One line of spend for a set of observations, honest about what is unknown.

    Rows whose model has no known price contribute their tokens to the count of
    unpriced calls instead of silently adding 0.0 to the dollar total.
    """
    known = [o for o in observations if o.get("cost_usd") is not None]
    unknown = [o for o in observations if o.get("cost_usd") is None]
    total = sum(float(o["cost_usd"]) for o in known)
    line = f"${total:.4f} over {len(known)} priced call(s)"
    if unknown:
        models = sorted({str(o.get("model")) for o in unknown})
        tokens = sum(int(o.get("total_tokens") or 0) for o in unknown)
        line += (
            f"; COST UNKNOWN for {len(unknown)} call(s) on {', '.join(models)} "
            f"({tokens} tokens, no price in PRICING_PER_1M_BY_MODEL -- not "
            f"estimated at another model's rates)"
        )
    return line


#: Logger the orchestrator emits fpl_provider_event records on.
_ORCH_LOGGER = "fpl_grounded_assistant"

#: The event a successful-but-useless provider call emits: no tool call, no
#: text, no usage (orchestrator.py::_log_orch_provider_event).
_EMPTY_EVENT = "provider_call_success_empty"


class _EmptyResponseCapture(logging.Handler):
    """Counts ``provider_call_success_empty`` events during ONE call.

    Without this the event only ever reached stderr, so an observation could
    not be told apart from one where the model actually wrote the answer: the
    empty-synthesis events in a run were real, countable in the console, and
    attributable to no row in the JSONL. That makes the i46 synthesis
    measurement unauditable after the fact, which is the whole point of paying
    for the observations.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.empty_events = 0

    def emit(self, record: logging.LogRecord) -> None:
        event = getattr(record, "fpl_event", None)
        if isinstance(event, dict) and event.get("event") == _EMPTY_EVENT:
            self.empty_events += 1


class _capture_empty_responses:
    """Attach an ``_EmptyResponseCapture`` for the duration of one call.

    Added and removed per call so the count belongs to exactly one row, and
    INFO is forced on only while it is attached -- the events are logged at
    INFO and are invisible at the default level.
    """

    def __init__(self, handler: _EmptyResponseCapture) -> None:
        self.handler = handler

    def __enter__(self) -> _EmptyResponseCapture:
        self._logger = logging.getLogger(_ORCH_LOGGER)
        self._prev_level = self._logger.level
        if self._prev_level > logging.INFO or self._prev_level == logging.NOTSET:
            self._logger.setLevel(logging.INFO)
        self._logger.addHandler(self.handler)
        return self.handler

    def __exit__(self, *exc_info: Any) -> None:
        self._logger.removeHandler(self.handler)
        self._logger.setLevel(self._prev_level)


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
    base: dict[str, Any] = {
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
    # Built before the try so an exception raised after the call still reports
    # the events that were already observed, instead of a flat False.
    empty_capture = _EmptyResponseCapture()
    try:
        with _capture_empty_responses(empty_capture):
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
            # A provider call that succeeded and returned nothing usable. Paired
            # with synthesis_turn=False this is the auditable signature of the
            # deterministic render() fallback standing in for empty synthesis --
            # previously visible only as a line on stderr, belonging to no row.
            empty_provider_response=empty_capture.empty_events > 0,
            empty_provider_response_count=empty_capture.empty_events,
            answer_text=(result.answer_text or "")[:400],
            rounds_used=getattr(result, "rounds_used", 0),
            error=result.error,
            primary_input_tokens=result.primary_input_tokens,
            primary_output_tokens=result.primary_output_tokens,
            primary_cache_read_tokens=result.primary_cache_read_tokens,
            total_tokens=result.total_tokens,
            # Priced with the model this row records, so the tariff and the
            # model can never disagree. None = unknown price, never 0.0.
            cost_usd=cost_usd(
                result.primary_input_tokens,
                result.primary_output_tokens,
                result.primary_cache_read_tokens,
                model=base["model"],
            ),
            pricing_known=base["model"] in PRICING_PER_1M_BY_MODEL,
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
            empty_provider_response=empty_capture.empty_events > 0,
            empty_provider_response_count=empty_capture.empty_events,
            answer_text="",
            rounds_used=0,
            error=str(exc),
            primary_input_tokens=0,
            primary_output_tokens=0,
            primary_cache_read_tokens=0,
            total_tokens=0,
            # A call that raised carried no tokens, so 0.0 is exact under any
            # tariff -- this is not a priced-at-unknown-rates estimate.
            cost_usd=0.0,
            pricing_known=base["model"] in PRICING_PER_1M_BY_MODEL,
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

    api_key = require_api_key(PROVIDER)

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
    written: list[dict[str, Any]] = []
    with out_path.open("a", encoding="utf-8") as fh:
        for q in questions:
            for rep in range(args.reps):
                obs = run_one(q, rep, bootstrap, api_key)
                fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
                fh.flush()
                written.append(obs)
                n_done += 1
                if obs["exception"] is not None:
                    n_exceptions += 1
                if n_done % 25 == 0 or n_done == total_calls:
                    print(
                        f"  {n_done}/{total_calls} done, {n_exceptions} exceptions so far, "
                        f"{format_spend(written)} so far",
                        file=sys.stderr,
                    )

    print(
        f"DONE. {n_done} observations written, {n_exceptions} exceptions, "
        f"spend {format_spend(written)}",
        file=sys.stderr,
    )
    return 0 if n_exceptions == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())

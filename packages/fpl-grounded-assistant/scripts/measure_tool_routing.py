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

i109: ``--team-id N`` (or env ``FPL_MEASURE_TEAM_ID``) connects a real FPL
team to every call, the way ``harness.ask_v2(team_id=...)`` does in prod: a
SHALLOW COPY of the frozen bootstrap gets ``_my_team_id`` and is handed to
``ask_orchestrated``; the shared bootstrap dict is never mutated (it is the
one object every one of the 118xR calls reuses). Without the flag nothing
about the call changes. Every row records ``team_id_present`` and
``my_squad_result`` -- the latter read off ``tool_calls_trace`` (did
``get_my_squad`` run, and what did it return), never off the answer text or
the question. ``get_my_squad`` fetches the team's picks live from the FPL API,
so a ``--team-id`` run is a network run beyond the provider call.
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

# i105: the price table, the cache-share convention and the per-call cost
# formula live in ONE place, ``fpl_grounded_assistant.model_pricing`` -- the
# module the production audit line prices from. This script used to carry its
# own copy (and ``audit.py`` a third, per-provider and stale). Importing the
# package needs the sibling packages on sys.path; ``main()`` does that late, so
# for a direct ``python scripts/measure_tool_routing.py`` run the import falls
# back to configuring the path here first. Under pytest the package is already
# importable (pytest.ini pythonpath) and the first import succeeds.


def _configure_imports() -> None:
    """Put every packages/* dir and this scripts/ dir on sys.path."""
    packages_dir = REPO_ROOT / "packages"
    for pkg in sorted(packages_dir.iterdir()):
        if pkg.is_dir():
            sys.path.insert(0, str(pkg))
    sys.path.insert(0, str(Path(__file__).resolve().parent))


try:
    from fpl_grounded_assistant.model_pricing import (  # noqa: E402
        CACHE_READ_INCLUDED_IN_INPUT,
        PRICING_PER_1M_BY_MODEL,
        billable_input_tokens,
        cost_usd as _shared_cost_usd,
    )
except ImportError:
    _configure_imports()
    from fpl_grounded_assistant.model_pricing import (  # noqa: E402
        CACHE_READ_INCLUDED_IN_INPUT,
        PRICING_PER_1M_BY_MODEL,
        billable_input_tokens,
        cost_usd as _shared_cost_usd,
    )


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
    provider: str | None = None,
) -> float | None:
    """Cost for one call at this script's pinned MODEL/PROVIDER unless given.

    Thin wrapper over ``model_pricing.cost_usd`` (the audit's formula) that
    supplies the script's pins as defaults. ``None`` means "unknown", not
    "free" -- see ``format_spend``.
    """
    return _shared_cost_usd(
        input_tokens, output_tokens, cache_read_tokens,
        model=model if model is not None else MODEL,
        provider=provider if provider is not None else PROVIDER,
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


#: i109: env alternative to ``--team-id``. The flag wins when both are set.
TEAM_ID_ENV: str = "FPL_MEASURE_TEAM_ID"

#: i109: the key ``get_my_squad`` reads the connected team from
#: (fpl_grounded_assistant/get_my_squad.py) and ``harness.ask_v2`` injects on
#: its bootstrap copy (harness.py, ``team_id`` parameter). Same key, same
#: shallow-copy rule.
MY_TEAM_ID_KEY: str = "_my_team_id"

#: The tool whose result ``my_squad_result`` classifies.
MY_SQUAD_TOOL: str = "get_my_squad"

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


def classify_my_squad_result(result: Any) -> str:
    """i109: what ``get_my_squad`` returned on this call, read off the trace.

    * ``"not_called"`` -- no executed call named ``get_my_squad``.
    * ``"squad"``      -- at least one such call came back ``status="ok"``
      with a non-empty ``players`` list (a real squad, not an empty shell).
    * ``"no_team"``    -- called, and every call said ``no_team_connected``
      (the handler saw no ``_my_team_id``).
    * ``"error"``      -- called, and the best it got was some other status
      (``not_found`` / ``error`` / an ``ok`` with no players). Kept apart
      from ``no_team`` so a bad id or a network failure is never read as
      "the flag did not reach the tool".

    Read from ``tool_calls_trace`` (every executed call, primary rounds and
    evaluator retry alike) -- never from the answer text, which can mention a
    squad it never fetched, and never from the question, which asks for one.
    """
    trace = getattr(result, "tool_calls_trace", None) or ()
    statuses: list[str] = []
    for entry in trace:
        if not isinstance(entry, dict) or entry.get("name") != MY_SQUAD_TOOL:
            continue
        output = entry.get("output")
        output = output if isinstance(output, dict) else {}
        status = str(output.get("status") or "")
        if status == "ok" and output.get("players"):
            return "squad"
        statuses.append(status)
    if not statuses:
        return "not_called"
    if all(status == "no_team_connected" for status in statuses):
        return "no_team"
    return "error"


def bootstrap_for_call(bootstrap: dict[str, Any], team_id: int | None) -> dict[str, Any]:
    """i109: the bootstrap ``ask_orchestrated`` gets for one call.

    With a team id: a SHALLOW COPY carrying ``_my_team_id`` -- the same rule
    as ``harness.ask_v2`` (harness.py, ``team_id`` parameter) and
    ``orchestrator.ask_orchestrated`` (its ``_question`` key): the caller's
    dict is shared by every call of the run and must never be mutated.
    Without one: the caller's dict itself, untouched, so a run with no flag
    hands the orchestrator exactly what it got before this flag existed.
    """
    if team_id is None:
        return bootstrap
    copy = dict(bootstrap)
    copy[MY_TEAM_ID_KEY] = team_id
    return copy


def run_one(
    question: dict[str, Any],
    rep_index: int,
    bootstrap: dict[str, Any],
    api_key: str,
    *,
    team_id: int | None = None,
) -> dict[str, Any]:
    """Make one ask_orchestrated() call and return a flat observation dict.

    Never raises: any exception is captured into the observation itself so
    the caller can write it to disk and keep going. An excepted observation
    has outcome="harness_exception" and a non-null "exception" field --
    callers MUST check for these before trusting any aggregate (two identical
    tracebacks diff clean and would otherwise look like a normal result).

    ``team_id`` (i109): connect this FPL team for the call, via
    ``bootstrap_for_call``. ``None`` (the default, and what every caller that
    predates the flag passes) changes nothing.
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
        # i109: whether a team was connected for THIS call. Set from the
        # argument, not from the bootstrap the caller passed (which never
        # carries the key -- the copy does).
        "team_id_present": team_id is not None,
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
                bootstrap_for_call(bootstrap, team_id),
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
            # i109: read off the trace, never off the question or the text.
            my_squad_result=classify_my_squad_result(result),
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
                provider=base["provider"],
            ),
            pricing_known=base["model"] in PRICING_PER_1M_BY_MODEL,
        )
    except Exception as exc:  # noqa: BLE001 -- must never lose an observation
        base.update(
            outcome="harness_exception",
            tool_chosen=None,
            tool_sequence=[],
            tool_call_count=0,
            # i109: no result to read a trace from.
            my_squad_result="not_called",
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


def resolve_team_id(flag_value: int | None) -> int | None:
    """i109: ``--team-id`` if given, else ``FPL_MEASURE_TEAM_ID`` if set and
    numeric, else ``None``. A non-numeric env value aborts rather than being
    silently ignored (a run that thinks it connected a team and did not is
    the i56 pattern)."""
    if flag_value is not None:
        return flag_value
    raw = os.environ.get(TEAM_ID_ENV, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"{TEAM_ID_ENV}={raw!r} is not an integer team id.") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=str(DEFAULT_BOOTSTRAP))
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=0, help="0 = all questions in the corpus")
    parser.add_argument("--only-family", default=None)
    parser.add_argument("--only-id", default=None, help="comma-separated question ids")
    parser.add_argument(
        "--team-id", type=int, default=None,
        help=(
            "i109: FPL team id to connect for every call (shallow-copied onto the "
            f"bootstrap as {MY_TEAM_ID_KEY}); env {TEAM_ID_ENV} is the alternative, "
            "the flag wins. Omitted: no team, calls unchanged."
        ),
    )
    args = parser.parse_args(argv)

    _configure_imports()
    _load_env_file(PACKAGE_ROOT / ".env")

    api_key = require_api_key(PROVIDER)
    team_id = resolve_team_id(args.team_id)

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
        f"against {PROVIDER}/{MODEL}"
        + (f", team_id={team_id} connected" if team_id is not None else ", no team connected")
        + f". Appending to {out_path}",
        file=sys.stderr,
    )

    n_done = 0
    n_exceptions = 0
    written: list[dict[str, Any]] = []
    with out_path.open("a", encoding="utf-8") as fh:
        for q in questions:
            for rep in range(args.reps):
                obs = run_one(q, rep, bootstrap, api_key, team_id=team_id)
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

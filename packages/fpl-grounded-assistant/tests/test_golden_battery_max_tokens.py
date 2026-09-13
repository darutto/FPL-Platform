"""i56 -- ``golden_battery.py --max-tokens`` reaches every provider call.

Before this, the flag was accepted, printed in the pinned report header, and
passed to nothing: ``measure_tool_routing.run_one`` pins ``max_tokens=1024``
inline. The header therefore described the default, not the run -- the
"accepted and then ignored" pattern the runner's own docstring names.

These tests drive the real ``main()`` -> ``base.run_one`` ->
``ask_orchestrated`` chain offline and assert on what the provider boundary
(``orchestrator.call_orch_provider``) RECEIVED -- never on ``args.max_tokens``
or on the header, which are the variables that asked for the value.

No network, ever (lesson of PR #212, where a test made ~40 real calls through
module globals mutated by an earlier test): the autouse fixture below pins
every module global the runner reads back to its current value and replaces
the call boundary with a raiser in BOTH namespaces that hold it. A test that
wants to observe the boundary installs its own recorder on top, and that
recorder never returns a usable response.
"""
from __future__ import annotations

import json
import logging
import sys
from collections import OrderedDict
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parent.parent
_SCRIPTS = _PKG / "scripts"
for _p in (str(_PKG), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import golden_battery as gb  # noqa: E402
import measure_tool_routing as base  # noqa: E402
import golden_preflight as preflight  # noqa: E402
from fpl_grounded_assistant import orchestrator as orch_mod  # noqa: E402
from fpl_grounded_assistant import provider_client  # noqa: E402
from fpl_grounded_assistant.provider_client import OrchCallResult  # noqa: E402


class _NetworkForbidden(RuntimeError):
    """Raised by the default boundary: no test in this module may reach a provider."""


def _forbidden(*_args, **_kwargs):
    raise _NetworkForbidden("call_orch_provider reached without a test recorder")


@pytest.fixture(autouse=True)
def _no_network_and_pinned_globals(monkeypatch):
    """Pin the runner's module globals to their current values and block the
    provider boundary. Every setattr here is undone by monkeypatch after each
    test, so no test can leak a mutated global into the next one."""
    # The call boundary, in both namespaces that hold it. ``ask_orchestrated``
    # resolves the orchestrator module's name at call time; the provider_client
    # one is the origin. A raiser in both means a test that forgets its
    # recorder fails loudly instead of dialling out.
    monkeypatch.setattr(orch_mod, "call_orch_provider", _forbidden)
    monkeypatch.setattr(provider_client, "call_orch_provider", _forbidden)
    # Globals ``run_one`` reads at call time; main() assigns them from args.
    monkeypatch.setattr(base, "PROVIDER", base.PROVIDER)
    monkeypatch.setattr(base, "MODEL", base.MODEL)
    # Nothing here may read the developer's .env or require a real key.
    monkeypatch.setattr(base, "_load_env_file", lambda *_a, **_k: None)
    monkeypatch.setattr(base, "require_api_key", lambda _provider: "test-key")
    # Runner globals the tests below may swap; pinned so the swap is undone.
    monkeypatch.setattr(gb, "_plan", gb._plan)
    monkeypatch.setattr(gb, "_ProviderBudget", gb._ProviderBudget)
    monkeypatch.setattr(gb, "_verify_provider", gb._verify_provider)
    monkeypatch.setattr(gb, "_verify_budget", gb._verify_budget)
    monkeypatch.setattr(preflight, "check", preflight.check)
    # The capture handler main() attaches is never removed; keep the logger
    # state from accumulating across tests.
    logger = logging.getLogger("fpl_grounded_assistant")
    handlers_before = list(logger.handlers)
    level_before = logger.level
    yield
    logger.handlers[:] = handlers_before
    logger.setLevel(level_before)


class _BoundaryRecorder:
    """Stands in for ``call_orch_provider``: records what it was asked for and
    answers with a failed call, so the orchestrator logs a real
    ``provider_call_failure`` event (with provider/model) and the run
    proceeds to its report without any client ever being built."""

    def __init__(self) -> None:
        self.max_tokens_seen: list = []

    def __call__(self, provider_name, **kwargs):
        self.max_tokens_seen.append(kwargs.get("max_tokens"))
        return OrchCallResult(
            response=None,
            error_code="test_boundary",
            error_msg="no provider call is made in tests",
            attempts=0,
            latency_ms=0.0,
        )


_REAL_PLAN = gb._plan  # captured before any test patches gb._plan


def _two_cases():
    plan = _REAL_PLAN("controls")
    return OrderedDict(list(plan.items())[:2])


def _run_main(tmp_path, bootstrap, monkeypatch, recorder, max_tokens):
    monkeypatch.setattr(orch_mod, "call_orch_provider", recorder)
    monkeypatch.setattr(gb, "_plan", lambda _tier: _two_cases())
    monkeypatch.setattr(preflight, "check", lambda _q, _b: [])
    bootstrap_path = tmp_path / "bootstrap.json"
    bootstrap_path.write_text(json.dumps(bootstrap), encoding="utf-8")
    out = tmp_path / "obs.jsonl"
    report = tmp_path / "report.md"
    argv = [
        "--tier", "controls", "--reps", "1", "--yes",
        "--provider", "openai", "--model", "gpt-5.6-luna",
        "--bootstrap", str(bootstrap_path),
        "--out", str(out), "--report", str(report),
    ]
    if max_tokens is not None:
        argv += ["--max-tokens", str(max_tokens)]
    rc = gb.main(argv)
    return rc, out, report


# ---------------------------------------------------------------------------
# The claim: the value on the flag is the value every provider call carried.
# ---------------------------------------------------------------------------

def test_max_tokens_flag_reaches_every_provider_call(tmp_path, bootstrap, monkeypatch):
    recorder = _BoundaryRecorder()

    rc, out, report = _run_main(tmp_path, bootstrap, monkeypatch, recorder, max_tokens=777)

    # Read off the boundary: two cases x one rep, every call carried 777 --
    # not the 1024 that base.run_one pins inline.
    assert recorder.max_tokens_seen == [777, 777]
    # The row records how many of its provider calls crossed the boundary,
    # read back from the file the run produced.
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["budgeted_provider_calls"] for r in rows] == [1, 1]
    # The header line is unchanged in shape and now describes the run.
    assert "| max_tokens | 777 |" in report.read_text(encoding="utf-8")
    assert rc in (0, 1)  # a verdict was reached; no abort


def test_default_budget_is_still_1024(tmp_path, bootstrap, monkeypatch):
    """Without the flag the reference row's effective budget is preserved."""
    recorder = _BoundaryRecorder()

    _run_main(tmp_path, bootstrap, monkeypatch, recorder, max_tokens=None)

    assert recorder.max_tokens_seen == [1024, 1024]


# ---------------------------------------------------------------------------
# The wrapper on its own: it overrides, it counts, it restores.
# ---------------------------------------------------------------------------

def test_budget_wrapper_overrides_whatever_the_caller_passed():
    seen = []

    def real_fn(provider_name, **kw):
        seen.append((provider_name, kw["max_tokens"]))
        return "result"

    budget = gb._ProviderBudget(333)
    assert budget(real_fn, "openai", max_tokens=1024, model="m") == "result"
    assert seen == [("openai", 333)]
    assert budget.calls == 1


def test_budget_run_one_restores_the_boundary_even_when_run_one_raises(monkeypatch):
    sentinel = _forbidden
    monkeypatch.setattr(orch_mod, "call_orch_provider", sentinel)

    def exploding_run_one(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(base, "run_one", exploding_run_one)
    budget = gb._ProviderBudget(5)
    with pytest.raises(RuntimeError, match="boom"):
        budget.run_one({"id": "x"}, 0, {}, "k")
    assert orch_mod.call_orch_provider is sentinel


# ---------------------------------------------------------------------------
# The guard: provider events without boundary crossings abort the run.
# ---------------------------------------------------------------------------

def test_events_without_budgeted_calls_abort():
    events = [{"provider": "openai", "model": "gpt-5.6-luna"}]
    with pytest.raises(SystemExit, match="crossed the --max-tokens boundary"):
        gb._verify_budget(events, 0, 777)


def test_events_with_budgeted_calls_pass():
    events = [{"provider": "openai", "model": "gpt-5.6-luna"}] * 3
    gb._verify_budget(events, 3, 777)  # no raise


def test_no_events_and_no_calls_is_not_this_guards_business():
    # _verify_provider already aborts an eventless run; this guard only speaks
    # when calls demonstrably happened.
    gb._verify_budget([], 0, 777)  # no raise


def test_bypassing_the_budget_in_main_is_caught_by_the_guard(tmp_path, bootstrap, monkeypatch):
    """If main() ever calls base.run_one directly again, the guard fires:
    the orchestrator logs provider events, but nothing crossed the boundary."""
    recorder = _BoundaryRecorder()

    class _Bypass(gb._ProviderBudget):
        def run_one(self, *args, **kwargs):
            return base.run_one(*args, **kwargs)  # the i56 regression, in miniature

    monkeypatch.setattr(gb, "_ProviderBudget", _Bypass)
    with pytest.raises(SystemExit, match="crossed the --max-tokens boundary"):
        _run_main(tmp_path, bootstrap, monkeypatch, recorder, max_tokens=777)
    # ...and what the boundary saw in that bypass is exactly the inline pin.
    assert recorder.max_tokens_seen == [1024, 1024]

"""Measurement probes: --provider/--model must be real, and cost must be honest.

Three defects in one family -- flags that are accepted and then do not do what
they say (the i56 pattern):

*   ``golden_battery.py`` honoured ``--provider`` but demanded OPENAI_API_KEY
    regardless, so ``--provider gemini`` either aborted for a key it did not
    need or handed Google an OpenAI key.
*   ``measure_captain_pool_variance.py`` had no such flags at all.
*   ``measure_tool_routing.PRICING_PER_1M`` was pinned to gpt-5.6-luna rates, so
    a run on any other model reported a cost computed from someone else's
    tariff: a number that looks true and is wrong.

No credentials and no network: every test here drives argument parsing, key
selection and pricing only.
"""
from __future__ import annotations

import logging
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parent.parent
_SCRIPTS = _PKG / "scripts"
for _p in (str(_PKG), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import measure_tool_routing as base  # noqa: E402
import measure_captain_pool_variance as variance  # noqa: E402
import golden_battery as battery  # noqa: E402
import run_agentic_loop_experiment as experiment  # noqa: E402

#: run_one before the autouse fixture replaces it with a raiser -- the tests in
#: section 4 exercise the real function against a stubbed orchestrator.
_REAL_RUN_ONE = base.run_one

_ALL_KEY_VARS = ("OPENAI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY")


@pytest.fixture(autouse=True)
def no_paid_calls(monkeypatch):
    """Two safety rails every test in this module runs under.

    1.  ``base.run_one`` is replaced by a raiser, so a test that gets further
        than it meant to fails instead of calling a provider. An early draft of
        this file did reach the network: ``main()`` mutates the module globals
        ``base.PROVIDER``/``base.MODEL`` and, with those left pointing at gemini
        by an earlier test, a later one sailed past key selection into real
        calls. They failed on the dummy key, but nothing in the test made that
        certain.
    2.  Those same globals are snapshotted and restored, so no test can leave
        the pinned production pair moved for the next one.
    """
    def _forbidden(*args, **kwargs):
        raise AssertionError(
            "run_one reached: no test in this module may make a provider call"
        )

    monkeypatch.setattr(base, "PROVIDER", base.PROVIDER)
    monkeypatch.setattr(base, "MODEL", base.MODEL)
    monkeypatch.setattr(base, "run_one", _forbidden)


@pytest.fixture
def clean_env(monkeypatch):
    """No provider key set, and no .env file is read."""
    for var in _ALL_KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(base, "_load_env_file", lambda path: None)
    return monkeypatch


# --------------------------------------------------------------------------
# 1. The key follows the provider
# --------------------------------------------------------------------------

def test_key_env_matches_production_mapping():
    """The probes must not hold a second opinion about which key a provider needs.

    This is the test that fails if anyone pins the lookup back to
    OPENAI_API_KEY: the mapping is compared against the one the experiment
    runner already encodes, which mirrors harness.py::_build_eval_client.
    """
    assert base.API_KEY_ENV_BY_PROVIDER == {
        provider: config["key_env"]
        for provider, config in experiment.PROVIDERS.items()
    }
    assert base.API_KEY_ENV_BY_PROVIDER["gemini"] == "GOOGLE_API_KEY"
    assert base.API_KEY_ENV_BY_PROVIDER["openai"] == "OPENAI_API_KEY"
    assert base.API_KEY_ENV_BY_PROVIDER["anthropic"] == "ANTHROPIC_API_KEY"


def test_harness_still_reads_the_same_two_vars():
    """Drift guard against production moving without the probes noticing."""
    source = (_PKG / "fpl_grounded_assistant" / "harness.py").read_text(encoding="utf-8")
    assert 'os.environ.get("OPENAI_API_KEY", "")' in source
    assert 'os.environ.get("GOOGLE_API_KEY", "")' in source


@pytest.mark.parametrize("provider,expected", sorted(base.API_KEY_ENV_BY_PROVIDER.items()))
def test_resolve_api_key_reads_only_that_providers_var(provider, expected, clean_env):
    clean_env.setenv(expected, f"key-for-{provider}")
    key, env_name = base.resolve_api_key(provider)
    assert (key, env_name) == (f"key-for-{provider}", expected)


def test_gemini_never_falls_back_to_the_openai_key(clean_env):
    """An OpenAI key present must not satisfy a gemini run.

    Falling back would not fail loudly: it would send Google a key it cannot
    use, or bill a call to the wrong account.
    """
    clean_env.setenv("OPENAI_API_KEY", "sk-openai")
    key, env_name = base.resolve_api_key("gemini")
    assert key is None
    assert env_name == "GOOGLE_API_KEY"
    with pytest.raises(SystemExit) as excinfo:
        base.require_api_key("gemini")
    assert excinfo.value.code == 2


def test_unknown_provider_is_refused_not_defaulted():
    with pytest.raises(SystemExit):
        base.api_key_env_for("wat")


# --------------------------------------------------------------------------
# 2. The flags reach the call, and the defaults do not move
# --------------------------------------------------------------------------

def test_defaults_are_the_pinned_production_pair():
    assert (base.PROVIDER, base.MODEL) == ("openai", "gpt-5.6-luna")


def test_pinned_config_is_not_read_from_env():
    """measure_tool_routing.py:36-40 pins provider/model deliberately.

    Command-line flags are explicit and so do not violate it; reading
    FPL_ORCH_PROVIDER/FPL_ORCH_MODEL would, because a stray env var could then
    silently change what was measured.
    """
    reads = re.compile(r"""(environ\.get|getenv|environ\[)\s*\(?["']FPL_ORCH""")
    for script in ("measure_tool_routing.py", "measure_captain_pool_variance.py",
                   "golden_battery.py"):
        source = (_SCRIPTS / script).read_text(encoding="utf-8")
        assert not reads.search(source), (
            f"{script} reads FPL_ORCH_*; the pinned defaults must not be "
            "movable by a stray env var (measure_tool_routing.py:36-40)"
        )


@pytest.fixture
def out_dir():
    """A writable output directory (tmp_path's root is not always writable here)."""
    path = Path(tempfile.mkdtemp())
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _argv(script, out_dir, *extra):
    argv = ["--out", str(out_dir / "o.jsonl"), *extra]
    if script is battery:
        argv += ["--yes"]
    return argv


@pytest.mark.parametrize("script", (variance, battery))
def test_flags_are_effective_not_decorative(script, clean_env, out_dir, monkeypatch):
    """--provider gemini --model X must set what run_one reads, select
    GOOGLE_API_KEY, and reach the call."""
    monkeypatch.setattr(base, "PROVIDER", "openai")
    monkeypatch.setattr(base, "MODEL", "gpt-5.6-luna")
    monkeypatch.setattr(battery.preflight, "check", lambda cases, bootstrap: [])
    clean_env.setenv("GOOGLE_API_KEY", "gk-live")

    seen: dict[str, str] = {}

    def _stop(*args, **kwargs):
        seen["provider"], seen["model"] = base.PROVIDER, base.MODEL
        raise RuntimeError("stop before any paid call")

    monkeypatch.setattr(base, "run_one", _stop)
    with pytest.raises(RuntimeError, match="stop before any paid call"):
        script.main(_argv(script, out_dir, "--provider", "gemini",
                          "--model", "gemini-3.8-flash"))
    assert seen == {"provider": "gemini", "model": "gemini-3.8-flash"}


@pytest.mark.parametrize("script", (variance, battery))
def test_gemini_run_does_not_abort_for_the_openai_key(
    script, clean_env, out_dir, monkeypatch, capsys
):
    """The acceptance criterion, as a test: with only GOOGLE_API_KEY set, a
    gemini run gets past key selection instead of aborting for a key it does
    not need."""
    clean_env.setenv("GOOGLE_API_KEY", "gk-live")
    monkeypatch.setattr(battery.preflight, "check", lambda cases, bootstrap: [])

    def _stop(*args, **kwargs):
        raise RuntimeError("reached the call")

    monkeypatch.setattr(base, "run_one", _stop)
    with pytest.raises(RuntimeError, match="reached the call"):
        script.main(_argv(script, out_dir, "--provider", "gemini",
                          "--model", "gemini-3.8-flash"))
    assert "OPENAI_API_KEY" not in capsys.readouterr().err


@pytest.mark.parametrize("script", (variance, battery))
def test_without_flags_the_openai_key_is_still_required(
    script, clean_env, out_dir, monkeypatch
):
    """No flags = today's behaviour, unchanged: openai/gpt-5.6-luna.

    The wrong provider's key is set, and no_paid_calls makes run_one a raiser,
    so reaching the call at all is a failure -- exit 2 must come first.
    """
    clean_env.setenv("GOOGLE_API_KEY", "gk-live")  # wrong key for the default
    monkeypatch.setattr(battery.preflight, "check", lambda cases, bootstrap: [])
    with pytest.raises(SystemExit) as excinfo:
        script.main(_argv(script, out_dir))
    assert excinfo.value.code == 2
    assert (base.PROVIDER, base.MODEL) == ("openai", "gpt-5.6-luna")


# --------------------------------------------------------------------------
# 3. An unknown model reports tokens and says the cost is unknown
# --------------------------------------------------------------------------

def test_known_model_prices_exactly_as_before():
    assert base.cost_usd(1_000_000, 1_000_000, 1_000_000, model="gpt-5.6-luna") == (
        pytest.approx(0.20 + 1.20 + 0.02)
    )


def test_pricing_table_matches_the_experiment_runners():
    shared = set(base.PRICING_PER_1M_BY_MODEL) & set(experiment.DEFAULT_MODEL_PRICING_PER_1M)
    assert shared
    for model in shared:
        assert base.PRICING_PER_1M_BY_MODEL[model] == experiment.DEFAULT_MODEL_PRICING_PER_1M[model]


def test_unknown_model_costs_none_not_another_models_rate():
    assert "gemini-3.8-flash" not in base.PRICING_PER_1M_BY_MODEL
    assert base.cost_usd(1_000_000, 1_000_000, 1_000_000, model="gemini-3.8-flash") is None


def test_format_spend_reports_tokens_and_declares_the_cost_unknown():
    line = base.format_spend([
        {"model": "gpt-5.6-luna", "cost_usd": 0.5, "total_tokens": 10},
        {"model": "gemini-3.8-flash", "cost_usd": None, "total_tokens": 4321},
    ])
    assert "$0.5000" in line
    assert "COST UNKNOWN" in line
    assert "gemini-3.8-flash" in line
    assert "4321 tokens" in line


def test_report_header_says_when_no_price_applies():
    header = {
        "model": "gemini-3.8-flash", "provider": "gemini", "tier": "controls",
        "reps": 1, "max_tokens": 1024, "temperature": "None (unset)",
        "bootstrap_name": "b.json", "bootstrap_sha256": "abc",
        "cases": 1, "calls": 1, "stale_excluded": 0, "run_at": "now",
        "pricing_basis": "**none - not priced**",
    }
    report = battery._markdown_report(
        header, [], False, "NOT ACCEPTED", 0.0, 0, None,
        spend_line="COST UNKNOWN for 1 call(s) on gemini-3.8-flash",
    )
    assert "pricing basis" in report
    assert "not priced" in report
    assert "COST UNKNOWN" in report


# --------------------------------------------------------------------------
# 4. The empty-synthesis fallback belongs to a row, not only to stderr
# --------------------------------------------------------------------------

class _FakeResult:
    """The subset of OrchestratorResult that run_one reads."""
    outcome = "ok"
    tool_chosen = "rank_captain_candidates"
    tool_calls_trace = ({"name": "rank_captain_candidates"},)
    tool_call_count = 1
    tool_args: dict = {}
    tool_output: dict = {"status": "ok"}
    synthesis_turn = False
    answer_text = "[ok]"
    rounds_used = 1
    error = None
    primary_input_tokens = 10
    primary_output_tokens = 20
    primary_cache_read_tokens = 0
    total_tokens = 30


_QUESTION = {
    "id": "q1", "family": "captain_pool", "acceptable_tools": ["x"],
    "control": False, "question": "¿A quién debería dar el brazalete?",
}


def _emit_empty_event(times: int) -> None:
    """Emit the event orchestrator.py:324 logs when a successful provider call
    returned no tool call, no text and no usage."""
    logger = logging.getLogger("fpl_grounded_assistant.orchestrator")
    for _ in range(times):
        event = {"event": "provider_call_success_empty", "provider": "openai",
                 "model": "gpt-5.6-luna", "latency_ms": 1.0, "attempts": 1}
        logger.info("fpl_provider_event %s", event, extra={"fpl_event": event})


def _run_one_with_events(monkeypatch, empty_events: int, raise_after: bool = False):
    """Drive the real run_one with a stubbed orchestrator that logs the event."""
    def _ask_orchestrated(*args, **kwargs):
        _emit_empty_event(empty_events)
        if raise_after:
            raise RuntimeError("boom after the provider spoke")
        return _FakeResult()

    module = types.ModuleType("fpl_grounded_assistant.orchestrator")
    module.ask_orchestrated = _ask_orchestrated
    monkeypatch.setitem(sys.modules, "fpl_grounded_assistant.orchestrator", module)
    monkeypatch.setattr(base, "run_one", _REAL_RUN_ONE)
    return _REAL_RUN_ONE(_QUESTION, 0, {}, "key")


def test_row_records_the_empty_synthesis_fallback(monkeypatch):
    """The measurement this unblocks: N such events in a run must be
    attributable to specific rows, not merely counted on the console."""
    obs = _run_one_with_events(monkeypatch, empty_events=1)
    assert obs["empty_provider_response"] is True
    assert obs["empty_provider_response_count"] == 1
    # Paired with synthesis_turn=False, this is the render() fallback.
    assert obs["synthesis_turn"] is False


def test_row_says_false_when_the_model_actually_answered(monkeypatch):
    obs = _run_one_with_events(monkeypatch, empty_events=0)
    assert obs["empty_provider_response"] is False
    assert obs["empty_provider_response_count"] == 0


def test_counts_do_not_leak_between_rows(monkeypatch):
    """The handler is attached per call, so row N+1 does not inherit row N."""
    first = _run_one_with_events(monkeypatch, empty_events=2)
    second = _run_one_with_events(monkeypatch, empty_events=0)
    assert first["empty_provider_response_count"] == 2
    assert second["empty_provider_response_count"] == 0
    assert not [h for h in logging.getLogger("fpl_grounded_assistant").handlers
                if isinstance(h, base._EmptyResponseCapture)]


def test_an_exception_after_the_event_still_reports_it(monkeypatch):
    obs = _run_one_with_events(monkeypatch, empty_events=1, raise_after=True)
    assert obs["outcome"] == "harness_exception"
    assert obs["empty_provider_response"] is True
    assert obs["empty_provider_response_count"] == 1


def test_the_event_name_still_exists_in_the_orchestrator():
    """If production renames the event, this probe would silently record False
    for every row -- a field that is always false looks like good news."""
    source = (_PKG / "fpl_grounded_assistant" / "orchestrator.py").read_text(encoding="utf-8")
    assert f'"{base._EMPTY_EVENT}"' in source

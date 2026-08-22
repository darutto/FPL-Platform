"""Regressions for adding a third provider to the agentic-loop experiment.

The driver used to enumerate ``("anthropic", "gemini")`` in three places (CLI
choices, the execution loop, the artifact renderer) and hardcoded the
credential lookup as "Google if gemini, else Anthropic". A third provider added
under that shape would have silently run every OpenAI observation against the
Anthropic key -- ``outcome=no_client`` with zero tokens, which reads as a
measured negative result rather than a run that never reached a provider.

These tests are hermetic: no provider call is made.
"""
from __future__ import annotations

import argparse
import importlib.util as _ilu
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PACKAGE_ROOT = _HERE.parent
_PACKAGES = _PACKAGE_ROOT.parent
_REPO_ROOT = _PACKAGES.parent

for _pkg in sorted(_PACKAGES.iterdir()):
    if _pkg.is_dir() and str(_pkg) not in sys.path:
        sys.path.insert(0, str(_pkg))

_MOD_PATH = _PACKAGE_ROOT / "scripts" / "run_agentic_loop_experiment.py"
_spec = _ilu.spec_from_file_location("run_agentic_loop_experiment", _MOD_PATH)
exp = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(exp)

_KEY_ENVS = ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY")


# ---------------------------------------------------------------------------
# 1. Pricing table
# ---------------------------------------------------------------------------

# Verbatim from https://developers.openai.com/api/docs/models/ (2026-08-20).
# A wrong number here does not fail loudly -- it silently corrupts every USD
# column in the artifact, so it is pinned rather than derived.
_DOCUMENTED_OPENAI_PRICES = {
    "gpt-5.6-luna":  {"input": 0.20, "output": 1.20,  "cache_read": 0.02},
    "gpt-5.6-terra": {"input": 2.00, "output": 12.00, "cache_read": 0.20},
    "gpt-5.6-sol":   {"input": 5.00, "output": 30.00, "cache_read": 0.50},
}


@pytest.mark.parametrize("model", sorted(_DOCUMENTED_OPENAI_PRICES))
def test_openai_pricing_matches_published_rates(model: str) -> None:
    assert exp.DEFAULT_MODEL_PRICING_PER_1M[model] == _DOCUMENTED_OPENAI_PRICES[model]


def test_default_openai_model_is_priced() -> None:
    """get_orch_model("openai") must resolve to a model the table can cost."""
    from fpl_grounded_assistant.orch_config import _PROVIDER_DEFAULT_MODELS

    assert _PROVIDER_DEFAULT_MODELS["openai"] in exp.DEFAULT_MODEL_PRICING_PER_1M


def test_estimate_cost_uses_luna_rates() -> None:
    observation = {
        "model": "gpt-5.6-luna",
        "evaluator_model": "gpt-5.6-luna",
        "primary_input_tokens": 1_000_000,
        "primary_output_tokens": 1_000_000,
        "primary_cache_read_tokens": 1_000_000,
        "evaluator_tokens": 0,
    }
    usd = exp._estimate_cost(observation, exp.DEFAULT_MODEL_PRICING_PER_1M)
    assert usd == pytest.approx(0.20 + 1.20 + 0.02)


# ---------------------------------------------------------------------------
# 2. Per-provider key + model resolution in the worker
# ---------------------------------------------------------------------------

class _FakeResult:
    outcome = "answered"
    answer_text = "ok"
    tool_chosen = "rank_players_by_metric"
    tool_args: dict = {}
    tool_output: dict = {}
    tool_calls_trace: tuple = ()
    rounds_used = 1
    rounds_exhausted = False
    primary_input_tokens = 11
    primary_output_tokens = 22
    primary_cache_read_tokens = 0
    evaluator_input_tokens = 3
    evaluator_output_tokens = 4
    total_tokens = 40
    evaluator_verdict = None


@pytest.fixture
def stub_worker(monkeypatch, tmp_path):
    """Run _worker without reaching a provider; yield the captured kwargs."""
    import fpl_grounded_assistant.harness as harness
    import fpl_grounded_assistant.orchestrator as orchestrator

    captured: dict = {}

    def _fake_ask(question, bootstrap, **kwargs):
        captured["question"] = question
        captured.update(kwargs)
        return _FakeResult()

    def _fake_eval_client(provider, api_key=None):
        captured["eval_provider"] = provider
        captured["eval_api_key"] = api_key
        return None

    monkeypatch.setattr(orchestrator, "ask_orchestrated", _fake_ask)
    monkeypatch.setattr(harness, "_build_eval_client", _fake_eval_client)

    for env in _KEY_ENVS:
        monkeypatch.setenv(env, "sentinel-" + env.lower())
    monkeypatch.delenv("FPL_ORCH_MODEL", raising=False)

    bootstrap = tmp_path / "bootstrap.json"
    bootstrap.write_text("{}", encoding="utf-8")

    def _run(provider: str, model: str | None):
        captured.clear()
        args = argparse.Namespace(
            repo_root=str(_REPO_ROOT),
            bootstrap=str(bootstrap),
            provider=provider,
            model=model,
            scenario="Q10",
        )
        assert exp._worker(args) == 0
        return captured

    return _run


def test_worker_openai_uses_openai_key_and_pinned_model(stub_worker) -> None:
    captured = stub_worker("openai", "gpt-5.6-luna")
    assert captured["api_key"] == "sentinel-openai_api_key"
    assert captured["model"] == "gpt-5.6-luna"
    assert captured["eval_api_key"] == "sentinel-openai_api_key"
    assert captured["eval_provider"] == "openai"


def test_worker_openai_falls_back_to_provider_default_model(stub_worker) -> None:
    from fpl_grounded_assistant.orch_config import get_orch_model

    captured = stub_worker("openai", None)
    assert captured["model"] == get_orch_model("openai")
    assert captured["api_key"] == "sentinel-openai_api_key"


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("anthropic", "sentinel-anthropic_api_key"),
        ("gemini", "sentinel-google_api_key"),
        ("openai", "sentinel-openai_api_key"),
    ],
)
def test_worker_key_lookup_per_provider(stub_worker, provider, expected) -> None:
    assert stub_worker(provider, None)["api_key"] == expected


def test_worker_sampling_controls_unchanged_for_existing_providers(stub_worker) -> None:
    """Arm semantics the earlier providers ran under must not shift."""
    anthropic = stub_worker("anthropic", None)
    assert anthropic["temperature"] == 0.0 and anthropic["top_p"] is None
    gemini = stub_worker("gemini", None)
    assert gemini["temperature"] == 0.0 and gemini["top_p"] == 1.0


def test_worker_omits_sampling_controls_gpt56_rejects(stub_worker) -> None:
    """GPT-5.6 answers a pinned temperature or top_p with HTTP 400.

    Sending either turns every OpenAI observation into outcome=llm_error with
    zero tokens -- and the SDK message ("...is not supported with this model")
    reads as a retired model, so the run looks like a bad model id.
    """
    captured = stub_worker("openai", "gpt-5.6-luna")
    assert captured["temperature"] is None
    assert captured["top_p"] is None


def test_sampling_label_reports_what_each_provider_pins() -> None:
    assert exp._sampling_label("anthropic") == "`0.0` / omitted"
    assert exp._sampling_label("gemini") == "`0.0` / `1.0`"
    assert exp._sampling_label("openai") == "omitted / omitted"


# ---------------------------------------------------------------------------
# 3. Provider-unit parsing + credential guard
# ---------------------------------------------------------------------------

def test_parse_provider_units_defaults_to_previously_measured_pair() -> None:
    assert exp.parse_provider_units(None) == [("anthropic", None), ("gemini", None)]


def test_parse_provider_units_supports_per_unit_models() -> None:
    units = exp.parse_provider_units("openai:gpt-5.6-luna,openai:gpt-5.6-terra")
    assert units == [("openai", "gpt-5.6-luna"), ("openai", "gpt-5.6-terra")]


def test_parse_provider_units_rejects_unknown_provider() -> None:
    with pytest.raises(SystemExit) as excinfo:
        exp.parse_provider_units("mistral")
    assert "mistral" in str(excinfo.value)


def test_required_keys_cover_only_selected_providers() -> None:
    assert exp.required_key_envs(exp.parse_provider_units("openai")) == ["OPENAI_API_KEY"]
    assert exp.required_key_envs(
        exp.parse_provider_units("openai:gpt-5.6-luna,openai:gpt-5.6-sol")
    ) == ["OPENAI_API_KEY"]
    assert exp.required_key_envs(exp.parse_provider_units(None)) == [
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
    ]


def _driver_args(tmp_path, providers: str) -> argparse.Namespace:
    bootstrap = tmp_path / "bootstrap.json"
    bootstrap.write_text("{}", encoding="utf-8")
    return argparse.Namespace(
        bootstrap=str(bootstrap),
        providers=providers,
        agentic_root=str(_REPO_ROOT),
        baseline_root=str(_REPO_ROOT),
        capture_only=False,
        capture_bootstrap=False,
        scenarios=None,
        arms=None,
        repetitions=1,
        semantic_scores=None,
        pricing_json=None,
        output=str(tmp_path / "out.md"),
    )


def test_openai_only_run_does_not_demand_google_key(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sentinel")
    monkeypatch.delenv("FPL_RUN_AGENTIC_EXPERIMENT", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        exp._driver(_driver_args(tmp_path, "openai:gpt-5.6-luna"))

    # It must get PAST the credential guard and stop at the paid-run interlock.
    message = str(excinfo.value)
    assert "FPL_RUN_AGENTIC_EXPERIMENT" in message
    assert "GOOGLE_API_KEY" not in message


def test_openai_only_run_still_demands_the_openai_key(monkeypatch, tmp_path) -> None:
    for env in _KEY_ENVS:
        monkeypatch.delenv(env, raising=False)

    with pytest.raises(SystemExit) as excinfo:
        exp._driver(_driver_args(tmp_path, "openai"))

    message = str(excinfo.value)
    assert "OPENAI_API_KEY" in message
    assert "ANTHROPIC_API_KEY" not in message


# ---------------------------------------------------------------------------
# 4. Rendering a three-provider observation set
# ---------------------------------------------------------------------------

def _observation(provider: str, model: str, arm: str, scenario: str) -> dict:
    return {
        "provider": provider,
        "model": model,
        "evaluator_model": model,
        "arm": arm,
        "scenario": scenario,
        "repetition": 1,
        "outcome": "answered",
        "answer_text": "Palmer | 6.5m",
        "tool_chosen": "rank_players_by_metric",
        "tool_args": {},
        "tool_output": {},
        "tool_calls_trace": [{"name": "rank_players_by_metric"}],
        "rounds_used": 1,
        "rounds_exhausted": False,
        "primary_input_tokens": 1000,
        "primary_output_tokens": 500,
        "primary_cache_read_tokens": 0,
        "evaluator_tokens": 100,
        "total_tokens": 1600,
        "evaluator_verdict": None,
        "axis1": {"catastrophic_failure": 0, "classification": "class-0"},
        "axis2": {"source": "model_json", "status": "valid", "errors": []},
        "axis3": {"score": 4},
        "composition": {"status": "valid"},
        "usd": 0.001,
    }


_UNITS = [
    ("anthropic", "claude-haiku-4-5-20251001"),
    ("gemini", "gemini-3.5-flash"),
    ("openai", "gpt-5.6-luna"),
    ("openai", "gpt-5.6-terra"),
]


def _render(tmp_path, observations, repetitions: int = 1) -> str:
    return exp._render_artifact(
        observations,
        bootstrap_path=tmp_path / "bootstrap.json",
        bootstrap_hash="deadbeef",
        captured_at="2026-08-20T00:00:00+00:00",
        fixture_counts=None,
        pricing=exp.DEFAULT_MODEL_PRICING_PER_1M,
        repetitions=repetitions,
    )


def _fabricated_artifact(tmp_path) -> str:
    observations = [
        _observation(provider, model, arm, scenario)
        for provider, model in _UNITS
        for arm in ("A", "B")
        for scenario in ("Q10", "Q11")
    ]
    return _render(tmp_path, observations)


def test_render_covers_every_unit_without_empty_rows(tmp_path) -> None:
    artifact = _fabricated_artifact(tmp_path)

    for provider, model in _UNITS:
        assert "| " + provider + " / " + model + " | A baseline | Q10 |" in artifact
        assert "## Answers: " + provider + " / " + model in artifact

    summary = artifact.split("## Summary", 1)[1].split("## Answers", 1)[0]
    data_rows = [
        line for line in summary.splitlines()
        if line.startswith("|") and not line.startswith("|---")
        and "Catastrophic" not in line
    ]
    # 4 units x 2 arms x 2 scenarios, and no row for an unmeasured combination.
    assert len(data_rows) == 16
    assert "| C loop |" not in summary
    assert "n/a" not in summary


def test_render_lists_the_models_actually_run(tmp_path) -> None:
    artifact = _fabricated_artifact(tmp_path)
    assert "- Providers: `anthropic` @ `claude-haiku-4-5-20251001`" in artifact
    assert "`openai` @ `gpt-5.6-terra`" in artifact
    assert "gpt-5.6-luna" in artifact.split("### Model pricing used", 1)[1]


def test_render_declares_the_openai_sampling_caveat(tmp_path) -> None:
    """A reader comparing tiers has to see that OpenAI is not pinned."""
    artifact = _fabricated_artifact(tmp_path)
    assert "openai omitted / omitted" in artifact
    assert "rejects temperature and top_p" in artifact


def test_render_single_provider_set_mentions_no_other_provider(tmp_path) -> None:
    artifact = _render(tmp_path, [_observation("openai", "gpt-5.6-luna", "B", "Q10")])
    assert "## Answers: gemini" not in artifact
    assert "## Answers: anthropic" not in artifact
    assert "## Answers: openai / gpt-5.6-luna" in artifact


def test_render_survives_a_worker_error_row(tmp_path) -> None:
    """A unit whose every observation failed must still render, at zero cost."""
    broken = _observation("openai", "gpt-5.6-luna", "B", "Q10")
    broken.update({
        "outcome": "worker_error",
        "rounds_used": 0,
        "total_tokens": 0,
        "usd": None,
        "axis3": {"score": "pending_human_review"},
        "composition": {"status": "unknown"},
    })
    artifact = _render(tmp_path, [broken])
    assert "| openai / gpt-5.6-luna | B tools | Q10 |" in artifact
    assert "n/a |" in artifact


# ---------------------------------------------------------------------------
# 5. Error classification: a rejected parameter is not a retired model
# ---------------------------------------------------------------------------

def test_unsupported_parameter_is_not_reported_as_model_not_found() -> None:
    from fpl_grounded_assistant.provider_client import (
        PERR_MODEL,
        PERR_PROVIDER,
        _classify_error,
    )

    class _BadRequestError(Exception):
        status_code = 400

    unsupported = _BadRequestError(
        "Error code: 400 - {'error': {'message': \"Unsupported parameter: "
        "'temperature' is not supported with this model.\", 'type': "
        "'invalid_request_error', 'param': 'temperature'}}"
    )
    assert _classify_error(unsupported) == PERR_PROVIDER

    retired = _BadRequestError("The model `gemini-2.0-flash` does not exist")
    assert _classify_error(retired) == PERR_MODEL

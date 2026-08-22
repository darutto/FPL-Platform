"""Regression tests for the GET /health/llm canary's output-token budget.

The canary asked for ``max_tokens=1`` — the cheapest possible call, and valid
on Gemini and Anthropic, which is what it was written against. OpenAI's
reasoning models (``gpt-5.6-*``) reject any ``max_output_tokens`` below 16 with
a bare HTTP 400. The probe reported that as ``error_code="provider"``, so
``GET /health/llm`` declared the production model dead while ``POST /ask`` was
serving correct answers on the very same model.

A monitor that reports red over a green service is worse than no monitor: the
next real outage is the one nobody believes. These tests pin the budget.
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant import provider_client
from fpl_grounded_assistant.provider_client import (
    _CANARY_MAX_TOKENS,
    OrchCallResult,
    probe_orch_model,
)

#: Documented minimum for OpenAI reasoning models. Verified live 2026-08-22
#: against gpt-5.6-luna, gemini-3.5-flash and claude-haiku-4-5: 16 is accepted
#: by all three, 1 is rejected by OpenAI alone.
OPENAI_REASONING_MIN_OUTPUT_TOKENS = 16


@pytest.fixture
def captured_kwargs(monkeypatch):
    """Intercept the canary's provider call and record its kwargs."""
    seen: dict = {}

    def _fake_call(**kwargs):
        seen.update(kwargs)
        return OrchCallResult(
            response=None, error_code=None, error_msg=None,
            attempts=1, latency_ms=1.0,
        )

    monkeypatch.setattr(provider_client, "call_orch_provider", _fake_call)
    return seen


def test_canary_budget_is_not_below_the_openai_reasoning_minimum():
    """The constant itself — guards against someone economising it back to 1."""
    assert _CANARY_MAX_TOKENS >= OPENAI_REASONING_MIN_OUTPUT_TOKENS


@pytest.mark.parametrize("provider", ["openai", "gemini", "anthropic", None])
def test_probe_requests_a_budget_every_provider_accepts(provider, captured_kwargs):
    """The wiring — the constant must actually reach the provider call."""
    probe_orch_model(provider, "any-model")
    assert captured_kwargs["max_tokens"] >= OPENAI_REASONING_MIN_OUTPUT_TOKENS


def test_probe_still_sends_no_tools_and_one_user_message(captured_kwargs):
    """The budget change must not have altered what makes the probe cheap."""
    probe_orch_model("openai", "gpt-5.6-luna")
    assert captured_kwargs["tools"] == []
    assert len(captured_kwargs["messages"]) == 1
    assert captured_kwargs["max_retries"] == 0


def test_probe_reports_ok_when_the_provider_call_succeeds(captured_kwargs):
    result = probe_orch_model("openai", "gpt-5.6-luna")
    assert result["ok"] is True
    assert result["error_code"] is None
    assert result["provider"] == "openai"
    assert result["model"] == "gpt-5.6-luna"


def test_probe_surfaces_a_provider_rejection_rather_than_raising(monkeypatch):
    """A 400 must come back as a verdict, not an exception — this is a probe."""
    def _fake_call(**_kwargs):
        return OrchCallResult(
            response=None, error_code="provider",
            error_msg="BadRequestError (HTTP 400)", attempts=1, latency_ms=1.0,
        )

    monkeypatch.setattr(provider_client, "call_orch_provider", _fake_call)
    result = probe_orch_model("openai", "gpt-5.6-luna")
    assert result["ok"] is False
    assert result["error_code"] == "provider"

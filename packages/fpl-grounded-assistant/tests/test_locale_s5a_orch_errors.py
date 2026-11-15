"""i18n S5a -- the orchestrator's generic failure texts follow the locale.

en is the wording these always had; es is new (they were English-only, so a
Spanish user saw English). The keys are paired in the catalogue; this drives the
real ``ask_orchestrated`` through each failure with a fake client.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from conftest import BOOTSTRAP
from fpl_grounded_assistant import orchestrator as orch
from fpl_grounded_assistant.catalogue import t
from fpl_grounded_assistant.orchestrator import ask_orchestrated


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for var in ("FPL_EVAL_DISABLED", "FPL_ORCH_LOOP_ENABLED", "FPL_JEV_MODE"):
        monkeypatch.delenv(var, raising=False)


def _usage():
    return NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0)


class _ToolClient:
    def __init__(self, name):
        self.messages = self
        self._name = name

    def create(self, **kwargs):
        block = NS(type="tool_use", id="c1", name=self._name, input={})
        return NS(content=[block], stop_reason="tool_use", usage=_usage())


class _RaisingClient:
    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        raise RuntimeError("provider down")


class _OpenGate:
    def is_open(self):
        return True

    def record_failure(self, *_):
        pass

    def reset_on_success(self):
        pass


@pytest.mark.parametrize("locale", ["es", "en"])
def test_unknown_tool(locale):
    r = ask_orchestrated("q", BOOTSTRAP, client=_ToolClient("not_a_real_tool"), locale=locale)
    assert r.outcome == orch.OUTCOME_UNKNOWN_TOOL
    assert r.answer_text == t("orch_err.unknown_tool", locale, tool=repr("not_a_real_tool"))


@pytest.mark.parametrize("locale", ["es", "en"])
def test_tool_raised(monkeypatch, locale):
    def _boom(name, args, bootstrap):
        raise RuntimeError("x")

    monkeypatch.setattr(orch, "run_tool", _boom)
    r = ask_orchestrated("q", BOOTSTRAP, client=_ToolClient("get_current_gameweek"), locale=locale)
    assert r.answer_text == t("orch_err.tool_raised", locale, tool=repr("get_current_gameweek"))


@pytest.mark.parametrize("locale", ["es", "en"])
def test_cooldown(locale):
    r = ask_orchestrated("q", BOOTSTRAP, client=_ToolClient("get_current_gameweek"), _gate=_OpenGate(), locale=locale)
    assert r.outcome == orch.OUTCOME_COOLDOWN
    assert r.answer_text == t("orch_err.cooldown", locale)


@pytest.mark.parametrize("locale", ["es", "en"])
def test_no_client(monkeypatch, locale):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    r = ask_orchestrated("q", BOOTSTRAP, provider="openai", locale=locale)
    assert r.outcome == orch.OUTCOME_NO_CLIENT
    assert r.answer_text == t("orch_err.no_client", locale)


@pytest.mark.parametrize("locale", ["es", "en"])
def test_llm_call_failed(monkeypatch, locale):
    monkeypatch.setenv("FPL_ORCH_MAX_RETRIES", "0")
    r = ask_orchestrated("q", BOOTSTRAP, client=_RaisingClient(), locale=locale)
    assert r.outcome == orch.OUTCOME_LLM_ERROR
    assert r.answer_text == t("orch_err.llm_failed", locale)


def test_es_and_en_differ_and_en_is_the_old_wording():
    for key, params, old in (
        ("orch_err.llm_failed", {}, "LLM call failed during orchestration."),
        ("orch_err.no_client", {}, "No LLM client available for orchestration."),
        ("orch_err.auth_failed", {}, "LLM authentication failed during orchestration."),
        ("orch_err.cooldown", {}, "LLM provider temporarily unavailable (cooldown active)."),
        ("orch_err.unknown_tool", {"tool": "'x'"}, "Model selected an unknown tool: 'x'."),
        ("orch_err.tool_raised", {"tool": "'x'"}, "Tool execution raised an error for 'x'."),
    ):
        assert t(key, "en", **params) == old
        assert t(key, "es", **params) != old

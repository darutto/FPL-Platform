"""Token accounting and zero-yield-log regression tests.

Covers two orchestrator.py fixes:

* Part A — OUTCOME_NO_TOOL, OUTCOME_UNKNOWN_TOOL, and OUTCOME_TOOL_ERROR now
  carry the primary call's token counts (previously dropped to the
  dataclass's 0-default even though the call had already succeeded and
  ``orch_call`` already had usage). OUTCOME_NO_CLIENT and OUTCOME_LLM_ERROR
  (the "call was attempted but failed" variant) are pinned at 0 — the first
  because no provider call is ever made, the second because
  ``OrchCallResult``'s own contract guarantees ``input_tokens`` /
  ``output_tokens`` / ``cache_read_tokens`` are ``None`` on any failure path
  across all three providers (nothing to report).

* Part B — a successful call (``error_code is None``) that yields no tool
  call, no text, and no usage now logs ``provider_call_success_empty``
  instead of an indistinguishable ``provider_call_success``.

All cases use Anthropic-shaped fake clients, following the pattern already
established in ``tests/test_multi_provider_follow_up.py``.
"""
from __future__ import annotations

import logging
import os
import sys
from types import SimpleNamespace as NS

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PKGS = os.path.dirname(_PKG)
for _path in [
    _PKG,
    os.path.join(_PKGS, "fpl-api-client"),
    os.path.join(_PKGS, "fpl-data-core"),
    os.path.join(_PKGS, "fpl-player-registry"),
    os.path.join(_PKGS, "fpl-query-tools"),
    os.path.join(_PKGS, "fpl-tool-contract"),
    os.path.join(_PKGS, "fpl-tool-runner"),
    os.path.join(_PKGS, "fpl-captain-engine"),
    os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

from fpl_grounded_assistant import orchestrator  # noqa: E402
from fpl_grounded_assistant.orchestrator import (  # noqa: E402
    OUTCOME_LLM_ERROR,
    OUTCOME_NO_CLIENT,
    OUTCOME_NO_TOOL,
    OUTCOME_TOOL_ERROR,
    OUTCOME_UNKNOWN_TOOL,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    ask_orchestrated,
)

_LOGGER_NAME = "fpl_grounded_assistant.orchestrator"


class _TextOnlyClient:
    """Anthropic-shaped: no tool_use block, plain text + usage."""

    def __init__(self, *, with_usage: bool = True) -> None:
        self.messages = self
        self.calls: list[dict] = []
        self._with_usage = with_usage

    def create(self, **kwargs):
        self.calls.append(kwargs)
        kw = {"content": [NS(type="text", text="Here is your answer.")], "stop_reason": "end_turn"}
        if self._with_usage:
            kw["usage"] = NS(input_tokens=42, output_tokens=17, cache_read_input_tokens=5)
        return NS(**kw)


class _UnknownToolClient:
    """Anthropic-shaped: tool_use block naming a tool outside the registry."""

    def __init__(self) -> None:
        self.messages = self
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        block = NS(type="tool_use", id="ant-1", name="not_a_real_tool", input={})
        usage = NS(input_tokens=30, output_tokens=8, cache_read_input_tokens=0)
        return NS(content=[block], stop_reason="tool_use", usage=usage)


class _ValidToolClient:
    """Anthropic-shaped: tool_use block naming a real, registered tool."""

    def __init__(self, tool_name: str) -> None:
        self.messages = self
        self.calls: list[dict] = []
        self._tool_name = tool_name

    def create(self, **kwargs):
        self.calls.append(kwargs)
        block = NS(type="tool_use", id="ant-1", name=self._tool_name, input={})
        usage = NS(input_tokens=55, output_tokens=3, cache_read_input_tokens=None)
        return NS(content=[block], stop_reason="tool_use", usage=usage)


class _EmptyClient:
    """Anthropic-shaped: no tool_use block, no text, no usage attribute at all."""

    def __init__(self) -> None:
        self.messages = self
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return NS(content=[], stop_reason="end_turn")


def _provider_events(records):
    return [
        r.fpl_event
        for r in records
        if hasattr(r, "fpl_event") and r.fpl_event.get("event", "").startswith("provider_call_success")
    ]


# ---------------------------------------------------------------------------
# Part A — token fields on OUTCOME_NO_TOOL / OUTCOME_UNKNOWN_TOOL / OUTCOME_TOOL_ERROR
# ---------------------------------------------------------------------------

def test_no_tool_outcome_reports_primary_tokens(bootstrap):
    result = ask_orchestrated(
        "off topic question the model answers directly",
        bootstrap,
        provider=PROVIDER_ANTHROPIC,
        client=_TextOnlyClient(),
        api_key="test-key",
        _eval_client=None,
    )
    assert result.outcome == OUTCOME_NO_TOOL
    assert result.primary_input_tokens == 42
    assert result.primary_output_tokens == 17
    assert result.primary_cache_read_tokens == 5
    assert result.total_tokens == 64


def test_unknown_tool_outcome_reports_primary_tokens(bootstrap):
    result = ask_orchestrated(
        "question",
        bootstrap,
        provider=PROVIDER_ANTHROPIC,
        client=_UnknownToolClient(),
        api_key="test-key",
        _eval_client=None,
    )
    assert result.outcome == OUTCOME_UNKNOWN_TOOL
    assert result.primary_input_tokens == 30
    assert result.primary_output_tokens == 8
    assert result.primary_cache_read_tokens == 0
    assert result.total_tokens == 38


def test_tool_error_outcome_reports_primary_tokens(monkeypatch, bootstrap):
    def _raise(*_args, **_kwargs):
        raise RuntimeError("tool blew up")

    monkeypatch.setattr(orchestrator, "run_tool", _raise)

    result = ask_orchestrated(
        "question",
        bootstrap,
        provider=PROVIDER_ANTHROPIC,
        client=_ValidToolClient("get_current_gameweek"),
        api_key="test-key",
        _eval_client=None,
    )
    assert result.outcome == OUTCOME_TOOL_ERROR
    assert result.primary_input_tokens == 55
    assert result.primary_output_tokens == 3
    assert result.primary_cache_read_tokens == 0
    assert result.total_tokens == 58


# ---------------------------------------------------------------------------
# Part A — sites that legitimately made no call still report zero
# ---------------------------------------------------------------------------

def test_no_client_outcome_reports_zero_tokens(monkeypatch, bootstrap):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = ask_orchestrated(
        "question",
        bootstrap,
        provider=PROVIDER_OPENAI,
        client=None,
        api_key=None,
        _eval_client=None,
    )
    assert result.outcome == OUTCOME_NO_CLIENT
    assert not result.llm_used
    assert result.primary_input_tokens == 0
    assert result.primary_output_tokens == 0
    assert result.primary_cache_read_tokens == 0
    assert result.total_tokens == 0


def test_llm_error_after_attempted_call_reports_zero_tokens(monkeypatch, bootstrap):
    monkeypatch.setenv("FPL_ORCH_TEST_INJECTION", "1")

    def _failing_request():
        raise RuntimeError("simulated provider failure")

    result = ask_orchestrated(
        "question",
        bootstrap,
        provider=PROVIDER_ANTHROPIC,
        _orch_request_fn=_failing_request,
        api_key="test-key",
        _eval_client=None,
    )
    assert result.outcome == OUTCOME_LLM_ERROR
    assert not result.llm_used
    assert result.primary_input_tokens == 0
    assert result.primary_output_tokens == 0
    assert result.primary_cache_read_tokens == 0
    assert result.total_tokens == 0


# ---------------------------------------------------------------------------
# Part B — zero-yield call is distinguishable from a genuine success in the log
# ---------------------------------------------------------------------------

def test_zero_yield_call_logs_distinguishable_event(bootstrap, caplog):
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        result = ask_orchestrated(
            "question",
            bootstrap,
            provider=PROVIDER_ANTHROPIC,
            client=_EmptyClient(),
            api_key="test-key",
            _eval_client=None,
        )

    assert result.outcome == OUTCOME_NO_TOOL
    assert result.primary_input_tokens == 0
    assert result.primary_output_tokens == 0
    assert result.primary_cache_read_tokens == 0

    events = _provider_events(caplog.records)
    assert len(events) == 1
    assert events[0]["event"] == "provider_call_success_empty"


def test_genuine_no_tool_success_still_logs_plain_success_event(bootstrap, caplog):
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        result = ask_orchestrated(
            "question",
            bootstrap,
            provider=PROVIDER_ANTHROPIC,
            client=_TextOnlyClient(),
            api_key="test-key",
            _eval_client=None,
        )

    assert result.outcome == OUTCOME_NO_TOOL
    events = _provider_events(caplog.records)
    assert len(events) == 1
    assert events[0]["event"] == "provider_call_success"

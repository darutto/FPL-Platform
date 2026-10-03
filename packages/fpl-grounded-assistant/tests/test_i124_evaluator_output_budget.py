"""i124 (1) -- the evaluator gets room to answer, and a fail-open says so.

Measured before (field-notes/2026-10-03-i124-evaluator-replay.md): the
evaluator called gpt-5.6-luna with max_output_tokens=256; the model reasons
first, the JSON came back cut mid-string, and ``evaluate_response`` returned
the reason-less fail-open -- approved=True, grounded=None. 5/10 prod verdicts
on 2026-10-02 were that, indistinguishable from a real approval.

Two changes pinned here:
* the output budget is per model (reasoning gpt-5.6-* get 1024, others keep
  256), overridable by FPL_EVAL_MAX_OUTPUT_TOKENS;
* every fail-open carries ``fail_open_reason`` and it reaches routing_trace
  and the audit line.

Fake clients only; no network.
"""
from __future__ import annotations

import json
import socket
from types import SimpleNamespace as NS

import pytest

from fpl_grounded_assistant import evaluator as ev
from fpl_grounded_assistant.evaluator import (
    FAIL_OPEN_EMPTY_OUTPUT,
    FAIL_OPEN_NO_CLIENT,
    FAIL_OPEN_PROVIDER_ERROR,
    FAIL_OPEN_REASONS,
    FAIL_OPEN_TRUNCATED_JSON,
    FAIL_OPEN_UNPARSEABLE,
    evaluate_response,
)

#: Real luna replies at max_output_tokens=256 (replay, 2026-10-03).
TRUNCATED_REAL = (
    '{"grounded":false,"complete":true,"safe":true,"retry_feedback":"Limita la justificación a los '
    'datos de la herramienta y elimina o'
)
GOOD = '{"grounded": true, "complete": true, "safe": true, "retry_feedback": null}'
BAD = '{"grounded": false, "complete": true, "safe": true, "retry_feedback": "Cita el dato."}'


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i124 tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_EVAL_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("FPL_EVAL_MODEL", raising=False)


class _OpenAIFake:
    """``client.responses.create`` recording its kwargs."""

    def __init__(self, text: str | None, *, output_tokens: int = 40, raise_exc: bool = False):
        self.responses = self
        self.calls: list[dict] = []
        self._text, self._out, self._raise = text, output_tokens, raise_exc

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise:
            raise RuntimeError("boom")
        return NS(output_text=self._text, output=[],
                  usage=NS(input_tokens=500, output_tokens=self._out))


class _AnthropicFake:
    def __init__(self, text: str):
        self.messages = self
        self.calls: list[dict] = []
        self._text = text

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return NS(content=[NS(type="text", text=self._text)], usage=NS(input_tokens=500, output_tokens=40))


def _judge(client, provider="openai"):
    return evaluate_response(question="q", primary_response="a", tool_calls=[], provider=provider, client=client)


# ---------------------------------------------------------------------------
# the budget
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model, budget", [
    ("gpt-5.6-luna", 1024), ("gpt-5.6-terra", 1024), ("gpt-5.6-sol", 1024),
    ("claude-haiku-4-5-20251001", 256), ("some-new-model", 256),
])
def test_budget_is_per_model(model, budget):
    assert ev._evaluator_max_output_tokens(model) == budget


def test_env_knob_overrides_and_ignores_garbage(monkeypatch):
    monkeypatch.setenv("FPL_EVAL_MAX_OUTPUT_TOKENS", "2048")
    assert ev._evaluator_max_output_tokens("claude-haiku-4-5-20251001") == 2048
    monkeypatch.setenv("FPL_EVAL_MAX_OUTPUT_TOKENS", "lots")
    assert ev._evaluator_max_output_tokens("gpt-5.6-luna") == 1024


def test_openai_call_carries_the_luna_budget():
    client = _OpenAIFake(GOOD)
    _judge(client)
    assert client.calls[0]["model"] == "gpt-5.6-luna"
    assert client.calls[0]["max_output_tokens"] == 1024


def test_anthropic_call_keeps_256():
    client = _AnthropicFake(GOOD)
    _judge(client, provider="anthropic")
    assert client.calls[0]["max_tokens"] == 256


# ---------------------------------------------------------------------------
# fail-open reasons
# ---------------------------------------------------------------------------

def test_real_verdicts_carry_no_reason():
    assert _judge(_OpenAIFake(GOOD)).fail_open_reason is None
    bad = _judge(_OpenAIFake(BAD))
    assert bad.approved is False and bad.fail_open_reason is None


def test_truncated_json_is_named_and_keeps_its_tokens():
    v = _judge(_OpenAIFake(TRUNCATED_REAL, output_tokens=256))
    assert v.approved is True and v.grounded is None
    assert v.fail_open_reason == FAIL_OPEN_TRUNCATED_JSON
    assert v.tokens_used == 756          # billed, so counted


def test_empty_output_with_tokens_spent():
    v = _judge(_OpenAIFake(None, output_tokens=256))
    assert v.fail_open_reason == FAIL_OPEN_EMPTY_OUTPUT


def test_provider_error():
    v = _judge(_OpenAIFake(GOOD, raise_exc=True))
    assert v.fail_open_reason == FAIL_OPEN_PROVIDER_ERROR and v.tokens_used == 0


def test_unparseable_complete_text():
    assert _judge(_OpenAIFake("Todo correcto.")).fail_open_reason == FAIL_OPEN_UNPARSEABLE
    assert _judge(_OpenAIFake('{"grounded": "maybe"}')).fail_open_reason == FAIL_OPEN_UNPARSEABLE


def test_no_client():
    assert _judge(None).fail_open_reason == FAIL_OPEN_NO_CLIENT


def test_reason_set_is_closed():
    assert FAIL_OPEN_REASONS == {"no_client", "provider_error", "empty_output", "truncated_json", "unparseable"}


# ---------------------------------------------------------------------------
# the reason reaches routing_trace and the audit line
# ---------------------------------------------------------------------------

def test_routing_trace_projects_the_reason():
    from fpl_grounded_assistant.harness import _project_orchestrator_run

    trace: dict = {}
    _project_orchestrator_run(trace, NS(evaluator_verdict=ev._fail_open(FAIL_OPEN_TRUNCATED_JSON, 300),
                                        retry_attempted=False, tool_calls_trace=()))
    assert trace["evaluator_verdict"]["fail_open_reason"] == FAIL_OPEN_TRUNCATED_JSON
    assert trace["evaluator_verdict"]["approved"] is True


def test_post_ask_audit_line_says_the_approval_was_a_fail_open(monkeypatch):
    from fastapi.testclient import TestClient

    import fpl_server
    from fpl_grounded_assistant import harness as harness_mod
    from fpl_grounded_assistant import orchestrator as orch_mod
    from fpl_grounded_assistant.quota import reset_quota

    from conftest import BOOTSTRAP

    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.setattr(harness_mod, "_build_eval_client", lambda *a, **k: object())
    # The evaluator client is an Anthropic-shaped fake whose reply is cut off.
    monkeypatch.setattr(orch_mod, "evaluate_response",
                        lambda **kw: evaluate_response(**{**kw, "client": _AnthropicFake(TRUNCATED_REAL)}))
    queue = [NS(content=[NS(type="tool_use", id="c1", name="get_current_gameweek", input={})]),
             NS(content=[NS(type="text", text="Estamos en la jornada 28.")])]

    class _Client:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **_k):
            return queue.pop(0) if queue else NS(content=[])

    monkeypatch.setattr(orch_mod, "_get_anthropic_client", lambda **_k: _Client())
    fpl_server._init_bootstrap(json.loads(json.dumps(BOOTSTRAP)))
    reset_quota()
    written: list = []
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda e: written.append(e))
    body = TestClient(fpl_server.app).post("/ask", json={"question": "¿en qué jornada estamos?", "debug": True},
                                           headers={"X-User-Id": "u-i124-fo"}).json()
    reset_quota()
    verdict = body["debug"]["routing_trace"]["evaluator_verdict"]
    assert verdict["approved"] is True and verdict["fail_open_reason"] == FAIL_OPEN_TRUNCATED_JSON
    assert written[-1].evaluator_verdict["fail_open_reason"] == FAIL_OPEN_TRUNCATED_JSON

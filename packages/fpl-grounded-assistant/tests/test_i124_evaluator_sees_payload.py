"""i124 (C) -- the evaluator judges against the data the primary saw.

Before: the evaluator's user message carried ``tool(args) → status`` per call
and nothing else, while its system prompt demands every factual claim cite a
tool result. It could verify nothing; it rejected grounded answers asking to
"cite", and the retry re-ran the same tool. Replay before deciding
(field-notes/2026-10-03-i124-evaluator-replay.md): with the payload, 54% ->
32% of parsed verdicts rejected; the real defects stay rejected.

Pinned here: the payload is the MODEL's view (``_truncate_tool_output``: lists
capped, ``_MODEL_HIDDEN_FIELDS`` dropped) -- reused, not a new path -- it
reaches the served evaluator message, and the trace is not mutated.
Fake clients only; no network.
"""
from __future__ import annotations

import json
import socket
from types import SimpleNamespace as NS

import pytest

from fpl_grounded_assistant import evaluator as ev
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.evaluator import MODEL_VIEW_KEY, EvaluatorVerdict, _build_evaluator_user_message
from fpl_grounded_assistant.orchestrator import ask_orchestrated

from conftest import BOOTSTRAP


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i124 tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.delenv("FPL_ORCH_EVAL_VERDICT_ONLY", raising=False)


# ---------------------------------------------------------------------------
# the message builder
# ---------------------------------------------------------------------------

def test_message_carries_tool_data_when_a_model_view_is_given():
    msg = _build_evaluator_user_message("q", "Estamos en la GW28.", [
        {"name": "get_current_gameweek", "args": {}, "output": {"status": "ok", "gameweek": 28},
         MODEL_VIEW_KEY: {"status": "ok", "gameweek": 28}},
    ])
    assert "get_current_gameweek({}) → ok" in msg
    assert 'TOOL DATA (what the primary saw):\nget_current_gameweek DATA: {"status": "ok", "gameweek": 28}' in msg
    assert msg.endswith("Judge. Output JSON only.")


def test_message_without_model_view_is_unchanged():
    calls = [{"name": "t", "args": {}, "output": {"status": "ok", "x": 1}}]
    msg = _build_evaluator_user_message("q", "a", calls)
    assert "TOOL DATA" not in msg
    assert msg == "USER ASKED: q\n\nPRIMARY ANSWERED: a\n\nTOOL CALLS MADE:\nt({}) → ok\n\nJudge. Output JSON only."


# ---------------------------------------------------------------------------
# the orchestrator hands the evaluator the model's view
# ---------------------------------------------------------------------------

def _run_capturing(monkeypatch, tool: str, output: dict, answer: str = "Respuesta."):
    seen: dict = {}

    def capture(**kwargs):
        seen["tool_calls"] = kwargs["tool_calls"]
        seen["message"] = ev._build_evaluator_user_message(kwargs["question"], kwargs["primary_response"],
                                                           kwargs["tool_calls"])
        return EvaluatorVerdict(approved=True, grounded=True, complete=True, safe=True, tokens_used=1)

    monkeypatch.setattr(orch_mod, "evaluate_response", capture)
    monkeypatch.setattr(orch_mod, "run_tool", lambda n, a, b: json.loads(json.dumps(output)))
    queue = [NS(content=[NS(type="tool_use", id="c1", name=tool, input={})]),
             NS(content=[NS(type="text", text=answer)])]

    class _Client:
        def __init__(self):
            self.messages = self

        def create(self, **_k):
            return queue.pop(0) if queue else NS(content=[])

    result = ask_orchestrated("q", BOOTSTRAP, client=_Client(), _eval_client=object())
    return result, seen


def test_evaluator_gets_the_capped_list_the_model_saw(monkeypatch):
    output = {"status": "ok", "injured": [{"web_name": f"P{i}"} for i in range(25)],
              "doubtful": [], "other": []}
    result, seen = _run_capturing(monkeypatch, "get_injury_list", output)
    view = seen["tool_calls"][0][MODEL_VIEW_KEY]
    assert view == orch_mod._truncate_tool_output(output, tool_name="get_injury_list")
    assert len(view["injured"]) == 10 and "_truncation_note" in view
    assert '"web_name": "P9"' in seen["message"] and '"web_name": "P10"' not in seen["message"]
    # the trace keeps the full output; nothing was mutated
    assert len(result.tool_calls_trace[0]["output"]["injured"]) == 25
    assert MODEL_VIEW_KEY not in result.tool_calls_trace[0]


def test_hidden_fields_stay_hidden_from_the_evaluator(monkeypatch):
    output = {"status": "ok", "chip": "bench_boost", "recommendation": "conditions_favorable",
              "squad_fit": {"verdict": "needs_transfers", "missing_count": 2},
              "squad_source": "linked_team", "linked_squad_error": None,
              "signals": {"favoured_teams": []}}
    _result, seen = _run_capturing(monkeypatch, "get_chip_advice", output)
    view = seen["tool_calls"][0][MODEL_VIEW_KEY]
    for hidden in orch_mod._MODEL_HIDDEN_FIELDS["get_chip_advice"]:
        assert hidden not in view
        assert hidden not in seen["message"].split("TOOL DATA", 1)[1]
    assert '"recommendation": "conditions_favorable"' in seen["message"]


def test_the_data_reaches_the_served_evaluator_call(monkeypatch):
    """End to end through the real evaluate_response with a fake provider:
    the text the provider receives contains the tool's numbers."""
    sent: list[str] = []

    class _EvalClient:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            sent.append(kwargs["messages"][0]["content"])
            return NS(content=[NS(type="text", text='{"grounded": true, "complete": true, "safe": true, '
                                                    '"retry_feedback": null}')],
                      usage=NS(input_tokens=10, output_tokens=5))

    monkeypatch.setattr(orch_mod, "run_tool", lambda n, a, b: {"status": "ok", "gameweek": 28})
    queue = [NS(content=[NS(type="tool_use", id="c1", name="get_current_gameweek", input={})]),
             NS(content=[NS(type="text", text="Estamos en la GW28.")])]

    class _Client:
        def __init__(self):
            self.messages = self

        def create(self, **_k):
            return queue.pop(0) if queue else NS(content=[])

    r = ask_orchestrated("¿Qué jornada?", BOOTSTRAP, client=_Client(), _eval_client=_EvalClient())
    assert r.evaluator_verdict.approved is True and r.evaluator_verdict.fail_open_reason is None
    assert 'get_current_gameweek DATA: {"status": "ok", "gameweek": 28}' in sent[0]

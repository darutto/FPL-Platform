"""i131 rule 3 -- a turn opened by get_my_squad belongs to the tool that answers.

Rule 2 (#359/#362) only fires when a gameweek anchor opens the turn. The
model more often opens chip turns with get_my_squad: in the field-notes
artifacts [get_my_squad, get_chip_advice] is the most frequent multi-tool
chip shape, and the orchestrator's slot (executed[0]) left the squad in it --
no chip card, intent my_squad. Without a linked team get_my_squad returns
no_team_connected and still opened the turn (cvg-02, i132 E3 baseline).

Rule 3: when the FIRST call is a SQUAD_CONTEXT_TOOLS tool, whatever its
status, the first tool outside both context sets owns the slot; with none,
the squad keeps it. Rules 1 (i93) and 2 are evaluated first, unchanged.

Both turns are real (tests/fixtures/i131c_squad_first_chip_turns.json):
cvg-02 without a team, cvg-01 with team 68643. Fake client, tools served
from the fixture, evaluator forced to approve -- no network, no paid call.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from fpl_grounded_assistant import harness, harness_adapter
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.evaluator import EvaluatorVerdict
from fpl_grounded_assistant.final_response import composed_primary_call
from fpl_grounded_assistant.orchestrator import ask_orchestrated

from conftest import BOOTSTRAP

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "i131c_squad_first_chip_turns.json").read_text(encoding="utf-8")
)
ANSWER = "Bench boost: condiciones favorables esta fecha."
_OUTPUTS: dict = {}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i131 rule-3 tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr(orch_mod, "run_tool", lambda name, args, bootstrap: json.loads(json.dumps(_OUTPUTS[name])))
    approved = EvaluatorVerdict(approved=True, grounded=True, complete=True, safe=True,
                                retry_feedback=None, tokens_used=17)
    monkeypatch.setattr(orch_mod, "evaluate_response", lambda **kwargs: approved)


def _usage() -> NS:
    return NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)


class _Client:
    def __init__(self, *responses: NS) -> None:
        self.messages = self
        self.queue = list(responses)

    def create(self, **_kwargs):
        return self.queue.pop(0) if self.queue else NS(content=[], stop_reason="end_turn", usage=_usage())


def _orch(case: dict, sequence=None):
    sequence = sequence or case["tool_sequence"]
    _OUTPUTS.clear()
    _OUTPUTS.update({"get_my_squad": case["my_squad_output"], "get_chip_advice": case["chip_output"],
                     "get_gameweek_context": {"status": "ok"}})
    args = {"get_my_squad": case["my_squad_args"], "get_chip_advice": {"chip": "bench_boost"},
            "get_gameweek_context": {}}
    calls = NS(content=[NS(type="tool_use", id=f"c{i}", name=n, input=args[n]) for i, n in enumerate(sequence)],
               stop_reason="tool_use", usage=_usage())
    text = NS(content=[NS(type="text", text=ANSWER)], stop_reason="end_turn", usage=_usage())
    return ask_orchestrated(case["question"], BOOTSTRAP, client=_Client(calls, text), _eval_client=object())


def _served(monkeypatch, case, orch_result):
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: orch_result)
    out = harness.ask_v2(case["question"], BOOTSTRAP, orch_client=object())
    from fpl_server import AskRequest
    return out, harness_adapter.to_ask_response(out, AskRequest(question=case["question"]))


# ---------------------------------------------------------------------------
# the two real turns
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("which", ["no_team", "team"])
def test_fixture_reproduces_the_recorded_shape(which):
    case = FIXTURE[which]
    r = _orch(case)
    assert [e["name"] for e in r.tool_calls_trace] == case["tool_sequence"] == ["get_my_squad", "get_chip_advice"]
    assert r.tool_chosen == case["recorded_tool_chosen"] == "get_my_squad"
    assert r.tool_calls_trace[0]["output"]["status"] == case["my_squad_output"]["status"]


@pytest.mark.parametrize("which", ["no_team", "team"])
def test_real_turn_serves_the_chip_card(monkeypatch, which):
    case = FIXTURE[which]
    out, resp = _served(monkeypatch, case, _orch(case))
    assert out["selected_tool"] == "get_chip_advice"
    assert out["routing_trace"]["composed_primary_tool"] == "get_chip_advice"
    assert resp.intent == "chip_advice"
    assert resp.chip is not None and resp.chip["chip"] == "bench_boost"
    assert ANSWER in resp.final_text          # model body; i108 E3 may add its header around it


def test_no_team_turn_is_the_no_team_connected_one():
    assert FIXTURE["no_team"]["my_squad_output"]["status"] == "no_team_connected"
    assert FIXTURE["team"]["my_squad_output"]["status"] == "ok"


def test_squad_with_only_context_after_it_keeps_the_squad(monkeypatch):
    case = FIXTURE["team"]
    out, _resp = _served(monkeypatch, case, _orch(case, sequence=["get_my_squad", "get_gameweek_context"]))
    assert out["selected_tool"] == "get_my_squad"
    assert "composed_primary_tool" not in out["routing_trace"]


# ---------------------------------------------------------------------------
# composed_primary_call, rule 3
# ---------------------------------------------------------------------------

def _t(name: str, status: str = "ok") -> dict:
    # ``success`` as the orchestrator stamps it: only error / invalid_argument /
    # missing_argument fail -- ambiguous, not_found and no_team_connected are
    # "success" in the trace.
    return {"round": 1, "tool_call_id": name, "name": name, "args": {}, "output": {"status": status},
            "success": status not in ("error", "invalid_argument", "missing_argument")}


@pytest.mark.parametrize("trace,owner", [
    # the change
    ([_t("get_my_squad"), _t("get_chip_advice")], "get_chip_advice"),
    ([_t("get_my_squad", "no_team_connected"), _t("get_chip_advice")], "get_chip_advice"),
    ([_t("get_my_squad"), _t("get_gameweek_context"), _t("get_chip_advice")], "get_chip_advice"),
    ([_t("get_my_squad"), _t("get_chip_advice"), _t("get_gameweek_context")], "get_chip_advice"),
    ([_t("get_my_squad"), _t("get_transfer_suggestion")], "get_transfer_suggestion"),
    ([_t("get_my_squad"), _t("get_transfer_suggestion"), _t("get_my_squad"), _t("get_transfer_suggestion")],
     "get_transfer_suggestion"),
    # first answering tool in model order
    ([_t("get_my_squad"), _t("get_chip_advice"), _t("get_transfer_suggestion")], "get_chip_advice"),
    # only context after the squad -> orchestrator slot (the squad)
    ([_t("get_my_squad"), _t("get_gameweek_context")], None),
    ([_t("get_my_squad"), _t("get_my_squad")], None),
    # rule 3 needs the squad FIRST
    ([_t("get_chip_advice"), _t("get_my_squad")], None),
    ([_t("get_transfer_suggestion"), _t("get_my_squad")], None),
    # rules 1 and 2 first, unchanged
    ([_t("get_my_squad"), _t("get_team_snapshot"), _t("get_fixture_outlook")], "get_fixture_outlook"),
    ([_t("get_gameweek_context"), _t("get_my_squad"), _t("get_chip_advice")], "get_chip_advice"),
    ([_t("get_gameweek_context"), _t("get_my_squad")], "get_my_squad"),
])
def test_owner_per_trace(trace, owner):
    hit = composed_primary_call(trace)
    assert (hit["name"] if hit else None) == owner


# ---------------------------------------------------------------------------
# harness: which non-ok turns the owner may rescue
# ---------------------------------------------------------------------------

def _result(outcome: str, trace: list) -> object:
    from fpl_grounded_assistant.orchestrator import OrchestratorResult
    return OrchestratorResult(
        question="q", tool_chosen=trace[0]["name"], tool_args={}, tool_output=trace[0]["output"],
        answer_text="texto del modelo", llm_used=True, model="m", outcome=outcome,
        tool_call_count=len(trace), tool_calls_trace=tuple(trace), synthesis_turn=True,
    )


def _ask(monkeypatch, orch_result):
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: orch_result)
    return harness.ask_v2("q", BOOTSTRAP, orch_client=object())


def test_no_team_squad_then_ok_chip_is_grounded(monkeypatch):
    out = _ask(monkeypatch, _result("tool_result_error",
                                    [_t("get_my_squad", "no_team_connected"), _t("get_chip_advice")]))
    assert out["routing_trace"]["branch"] == "orchestrator"
    assert out["selected_tool"] == "get_chip_advice"


def test_owner_that_is_not_ok_is_not_rescued(monkeypatch):
    """i60 stays: an ambiguous owner keeps the unsupported branch (and its chips)."""
    out = _ask(monkeypatch, _result("tool_result_error",
                                    [_t("get_my_squad", "no_team_connected"), _t("get_player_snapshot", "ambiguous")]))
    assert out["routing_trace"]["branch"] == "unsupported"
    assert out["selected_tool"] is None


def test_only_tool_result_error_is_rescued(monkeypatch):
    out = _ask(monkeypatch, _result("tool_error",
                                    [_t("get_my_squad", "no_team_connected"), _t("get_chip_advice")]))
    assert out["routing_trace"]["branch"] == "unsupported"


def test_a_non_ok_turn_without_an_owner_is_unchanged(monkeypatch):
    out = _ask(monkeypatch, _result("tool_result_error",
                                    [_t("get_my_squad", "no_team_connected"), _t("get_gameweek_context")]))
    assert out["routing_trace"]["branch"] == "unsupported"

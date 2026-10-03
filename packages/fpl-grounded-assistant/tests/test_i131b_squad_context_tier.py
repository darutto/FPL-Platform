"""i131 follow-up -- get_my_squad owns an anchored turn only when nothing else answered.

#359 (i131) handed the slot of an anchor-first turn to the first tool after
the gameweek anchor. In [get_gameweek_context, get_my_squad, get_chip_advice]
that was get_my_squad -- the user's squad, context for the chip question, not
its answer -- so the chip card still did not render. Seen 4x in the
field-notes artifacts (i108 E3 gate, cvg-11 with team; i109 cvg-04).

Rule: under rule 2, SQUAD_CONTEXT_TOOLS are skipped while another tool
answered; alone after the anchor they still own the slot. Rule 1 (i93) and
rule 2's anchor-first condition are unchanged.

The turn is the real one (tests/fixtures/i131b_cvg11_three_tools_2026-09-24.json):
question, sequence and the recorded get_chip_advice output. Fake client,
tools served from the fixture, evaluator forced to approve -- no network, no
paid call.
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
from fpl_grounded_assistant.final_response import (
    SQUAD_CONTEXT_TOOLS,
    composed_primary_call,
)
from fpl_grounded_assistant.orchestrator import ask_orchestrated

from conftest import BOOTSTRAP

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "i131b_cvg11_three_tools_2026-09-24.json").read_text(encoding="utf-8")
)
QUESTION = FIXTURE["question"]
SEQUENCE = FIXTURE["tool_sequence"]
ANSWER = "Bench boost en la fecha 2: condiciones favorables, pero te faltan dos piezas."
OUTPUTS = {
    "get_gameweek_context": FIXTURE["gameweek_context_output"],
    "get_my_squad": FIXTURE["my_squad_output"],
    "get_chip_advice": FIXTURE["chip_output"],
}
ARGS = {"get_gameweek_context": {}, "get_my_squad": {}, "get_chip_advice": {"chip": "bench_boost"}}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i131 follow-up tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr(orch_mod, "run_tool", lambda name, args, bootstrap: json.loads(json.dumps(OUTPUTS[name])))
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


def _orch(sequence=SEQUENCE):
    calls = NS(content=[NS(type="tool_use", id=f"c{i}", name=n, input=ARGS[n]) for i, n in enumerate(sequence)],
               stop_reason="tool_use", usage=_usage())
    text = NS(content=[NS(type="text", text=ANSWER)], stop_reason="end_turn", usage=_usage())
    return ask_orchestrated(QUESTION, BOOTSTRAP, client=_Client(calls, text), _eval_client=object())


def _served(monkeypatch, orch_result):
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: orch_result)
    out = harness.ask_v2(QUESTION, BOOTSTRAP, orch_client=object())
    from fpl_server import AskRequest
    return out, harness_adapter.to_ask_response(out, AskRequest(question=QUESTION))


# ---------------------------------------------------------------------------
# the real three-tool turn
# ---------------------------------------------------------------------------

def test_fixture_reproduces_the_recorded_shape():
    r = _orch()
    assert [e["name"] for e in r.tool_calls_trace] == SEQUENCE == [
        "get_gameweek_context", "get_my_squad", "get_chip_advice"]
    assert r.tool_chosen == "get_gameweek_context"          # as recorded (tool_chosen)


def test_real_turn_serves_the_chip_card(monkeypatch):
    out, resp = _served(monkeypatch, _orch())
    assert out["selected_tool"] == "get_chip_advice"
    assert out["routing_trace"]["composed_primary_tool"] == "get_chip_advice"
    assert resp.intent == "chip_advice"
    assert resp.chip is not None and resp.chip["chip"] == "bench_boost"


def test_squad_alone_after_the_anchor_still_owns_the_turn(monkeypatch):
    out, resp = _served(monkeypatch, _orch(sequence=["get_gameweek_context", "get_my_squad"]))
    assert out["selected_tool"] == "get_my_squad"
    assert resp.intent != "chip_advice"


# ---------------------------------------------------------------------------
# composed_primary_call, the tier
# ---------------------------------------------------------------------------

def _t(name: str) -> dict:
    return {"round": 1, "tool_call_id": name, "name": name, "args": {}, "output": {"status": "ok"}, "success": True}


def _owner(*names: str) -> "str | None":
    hit = composed_primary_call([_t(n) for n in names])
    return hit["name"] if hit else None


def test_squad_context_set_is_exactly_get_my_squad():
    assert SQUAD_CONTEXT_TOOLS == frozenset({"get_my_squad"})


@pytest.mark.parametrize("names,owner", [
    # the change
    (("get_gameweek_context", "get_my_squad", "get_chip_advice"), "get_chip_advice"),
    (("get_gameweek_context", "get_my_squad", "get_transfer_suggestion"), "get_transfer_suggestion"),
    # squad is all that answered -> still the owner
    (("get_gameweek_context", "get_my_squad"), "get_my_squad"),
    (("get_gameweek_context", "get_my_squad", "get_gameweek_context"), "get_my_squad"),
    # unchanged from #359
    (("get_gameweek_context", "get_chip_advice"), "get_chip_advice"),
    (("get_gameweek_context", "get_chip_advice", "get_my_squad"), "get_chip_advice"),
    (("get_gameweek_context", "build_squad", "get_chip_advice"), "build_squad"),
    (("get_current_gameweek", "rank_captain_candidates"), "rank_captain_candidates"),
    # squad-first turns are rule 3's (i131 rule 3), not rule 2's
    (("get_my_squad", "get_chip_advice"), "get_chip_advice"),
    (("get_my_squad", "get_gameweek_context", "get_chip_advice"), "get_chip_advice"),
    # rule 1 (i93) still wins
    (("get_gameweek_context", "get_my_squad", "get_fixture_outlook"), "get_fixture_outlook"),
])
def test_owner_per_sequence(names, owner):
    assert _owner(*names) == owner

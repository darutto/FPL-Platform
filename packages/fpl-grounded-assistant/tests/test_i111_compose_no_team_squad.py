"""i111 -- a chip turn opened by get_my_squad with no team linked is still composed.

The orchestrator reads the turn's outcome off its FIRST call. A chip question
where the model asks for the squad first, with no team linked, runs
[get_my_squad -> no_team_connected, get_chip_advice -> ok] and ends
``tool_result_error``. #364 already serves that turn grounded with the chip
card; but ``_compose_chip_answer`` required ``ok`` and left the text without
the i108 header and sentence, so it opened «No pude analizar tu plantilla…»
(E3 without a team: 29/32 on main, every miss this shape).

Pinned here: that ONE non-ok shape is composed; every other non-ok call keeps
the turn uncomposed; the guard still wins; the outcome itself is not changed.
The real turn is cvg-02 without a team (tests/fixtures/i131c_squad_first_chip_turns.json).
Fake client and tools from the fixture -- no network, no paid call.
"""
from __future__ import annotations

import json
import socket
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from fpl_grounded_assistant import harness, harness_adapter
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.chip_two_part import (
    FORBIDDEN_OPENINGS,
    PARTICULAR_PHRASE,
    fold,
    opening,
)
from fpl_grounded_assistant.evaluator import EvaluatorVerdict
from fpl_grounded_assistant.orchestrator import (
    OUTCOME_OK,
    OUTCOME_TOOL_ERROR,
    OUTCOME_TOOL_RESULT_ERROR,
    _compose_chip_answer,
    ask_orchestrated,
)

from conftest import BOOTSTRAP

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "i131c_squad_first_chip_turns.json").read_text(encoding="utf-8")
)
CASE = FIXTURE["no_team"]
#: The body the model wrote on this turn (i132 E3 baseline, cvg-02 r1).
BODY = ("No pude analizar tu plantilla porque no hay ningún equipo conectado. "
        "Conecta tu equipo desde la pestaña **Plantilla**.\n\nPara la **GW3**, las condiciones "
        "generales del bench boost son favorables.")
HEADER = "**Bench Boost — jornada favorable.**"
_OUTPUTS: dict = {}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i111 tests must not touch the network: {address!r}")
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


def _orch(squad_output: dict | None = None):
    _OUTPUTS.clear()
    _OUTPUTS.update({"get_my_squad": squad_output or CASE["my_squad_output"],
                     "get_chip_advice": CASE["chip_output"]})
    calls = NS(content=[NS(type="tool_use", id="c0", name="get_my_squad", input=CASE["my_squad_args"]),
                        NS(type="tool_use", id="c1", name="get_chip_advice", input={"chip": "bench_boost"})],
               stop_reason="tool_use", usage=_usage())
    text = NS(content=[NS(type="text", text=BODY)], stop_reason="end_turn", usage=_usage())
    return ask_orchestrated(CASE["question"], BOOTSTRAP, client=_Client(calls, text), _eval_client=object())


def _served(monkeypatch, orch_result):
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: orch_result)
    out = harness.ask_v2(CASE["question"], BOOTSTRAP, orch_client=object())
    from fpl_server import AskRequest
    return out, harness_adapter.to_ask_response(out, AskRequest(question=CASE["question"]))


# ---------------------------------------------------------------------------
# the real turn, read off what is served
# ---------------------------------------------------------------------------

def test_real_turn_is_composed_and_keeps_its_outcome():
    r = _orch()
    assert [e["name"] for e in r.tool_calls_trace] == ["get_my_squad", "get_chip_advice"]
    assert r.outcome == OUTCOME_TOOL_RESULT_ERROR           # not changed here
    assert r.answer_text.startswith(HEADER)
    assert BODY in r.answer_text
    assert fold(r.answer_text).rstrip(".").endswith(fold(PARTICULAR_PHRASE["invite"]))


def test_served_by_ask_opens_with_the_verdict_and_carries_the_card(monkeypatch):
    out, resp = _served(monkeypatch, _orch())
    assert resp.final_text.startswith(HEADER)
    opening_f = fold(opening(resp.final_text))
    assert not any(fold(p) in opening_f for p in FORBIDDEN_OPENINGS)
    assert not opening_f.startswith(fold("No pude analizar"))
    assert fold(PARTICULAR_PHRASE["invite"]) in fold(resp.final_text)
    # #364 owns the surface; asserted so a regression there shows up here too.
    assert resp.intent == "chip_advice" and resp.chip is not None
    assert out["routing_trace"]["grounded"] is True and out["outcome"] == "ok"
    assert not out.get("suggestions")


# ---------------------------------------------------------------------------
# every guard, one at a time
# ---------------------------------------------------------------------------

def _result(trace, outcome=OUTCOME_TOOL_RESULT_ERROR, **over):
    base = orch_mod.OrchestratorResult(
        question="q", tool_chosen=trace[0]["name"], tool_args={}, tool_output=trace[0].get("output") or {},
        answer_text=BODY, llm_used=True, model="m", outcome=outcome, tool_calls_trace=tuple(trace))
    return replace(base, **over) if over else base


SQUAD_NO_TEAM = {"name": "get_my_squad", "output": {"status": "no_team_connected"}}
CHIP_OK = {"name": "get_chip_advice", "output": CASE["chip_output"]}


def test_the_bounded_shape_is_composed():
    out = _compose_chip_answer(_result([SQUAD_NO_TEAM, CHIP_OK]), BOOTSTRAP)
    assert out.answer_text.startswith(HEADER)


@pytest.mark.parametrize("trace", [
    # another tool failed too
    [SQUAD_NO_TEAM, {"name": "get_gameweek_context", "output": {"status": "error"}}, CHIP_OK],
    # get_my_squad failed for another reason
    [{"name": "get_my_squad", "output": {"status": "error", "code": "squad_fetch_failed"}}, CHIP_OK],
    # another tool returned no_team_connected
    [{"name": "rank_captain_candidates", "output": {"status": "no_team_connected"}}, CHIP_OK],
    # a call with no output
    [SQUAD_NO_TEAM, {"name": "get_fixtures_for_gw"}, CHIP_OK],
    # the chip call itself failed
    [SQUAD_NO_TEAM, {"name": "get_chip_advice", "output": {"status": "error"}}],
])
def test_any_other_failure_stays_uncomposed(trace):
    r = _result(trace)
    assert _compose_chip_answer(r, BOOTSTRAP) is r


def test_another_outcome_stays_uncomposed():
    r = _result([SQUAD_NO_TEAM, CHIP_OK], outcome=OUTCOME_TOOL_ERROR)
    assert _compose_chip_answer(r, BOOTSTRAP) is r


def test_the_final_text_guard_still_wins():
    r = _result([SQUAD_NO_TEAM, CHIP_OK], final_text_guard_reason="html",
                answer_text="No se obtuvo respuesta útil.")
    assert _compose_chip_answer(r, BOOTSTRAP) is r


def test_ok_turns_are_composed_as_before():
    r = _result([CHIP_OK], outcome=OUTCOME_OK)
    assert _compose_chip_answer(r, BOOTSTRAP).answer_text.startswith(HEADER)

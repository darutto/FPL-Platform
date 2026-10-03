"""i131 -- a gameweek-anchor call never owns a turn another tool answered.

Prod, 2026-10-03 (i125 measurement, no team, rep 3): «¿A quién capitaneo
esta jornada? Dame un top 3 numerado.» The model called get_current_gameweek
and rank_captain_candidates in one response. The orchestrator's singular slot
is ``executed[0]``, so selected_tool was get_current_gameweek, the intent was
current_gameweek and the card served was «JORNADA ACTUAL · GW6» -- the
captain ranking the text described had no card.

Rule (final_response.composed_primary_call, rule 2): when the FIRST call of a
multi-tool turn is a GAMEWEEK_CONTEXT_TOOLS tool, the first tool outside that
set owns the slot. Read off what is served (ask_v2 -> to_ask_response), not
off the orchestrator's slot.

The turn is the real one: the question, the tool sequence and args from
field-notes/artifacts/i125a-captain-list-measurements-2026-10-03.jsonl
(run i125b-noteam-f07634, i=3) and the rank_captain_candidates output of the
i125(b) prod fixture. Fake client, tools served from fixtures, evaluator
forced to approve (as it did in prod) -- no network, no paid call.
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
    GAMEWEEK_CONTEXT_TOOLS,
    composed_primary_call,
)
from fpl_grounded_assistant.orchestrator import ask_orchestrated

from conftest import BOOTSTRAP

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "i125b_captain_turn_2026-10-02.json").read_text(encoding="utf-8")
)
QUESTION = "¿A quién capitaneo esta jornada? Dame un top 3 numerado."
CAPTAIN_ARGS = {"gameweek": 6, "horizon": 1}          # the real turn's args
CAPTAIN_OUTPUT = _FIXTURE["tool_output"]
GW_OUTPUT = {"status": "ok", "gameweek": 6}
ANSWER = "**Top 3 capitanes — GW6**\n\n1. **Pascal Groß (Brighton)**\n2. **Harvey Barnes (Newcastle)**\n3. **Kevin Schade (Brentford)**"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i131 tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)   # prod: loop off
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")

    outputs = {"rank_captain_candidates": CAPTAIN_OUTPUT, "get_current_gameweek": GW_OUTPUT}
    monkeypatch.setattr(orch_mod, "run_tool", lambda name, args, bootstrap: json.loads(json.dumps(outputs[name])))
    approved = EvaluatorVerdict(approved=True, grounded=True, complete=True, safe=True,
                                retry_feedback=None, tokens_used=17)
    monkeypatch.setattr(orch_mod, "evaluate_response", lambda **kwargs: approved)


def _usage() -> NS:
    return NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)


def _both_tools(order: tuple[str, str]) -> NS:
    blocks = {
        "get_current_gameweek": NS(type="tool_use", id="c-gw", name="get_current_gameweek", input={}),
        "rank_captain_candidates": NS(type="tool_use", id="c-rank", name="rank_captain_candidates",
                                      input=CAPTAIN_ARGS),
    }
    return NS(content=[blocks[n] for n in order], stop_reason="tool_use", usage=_usage())


def _text(text: str) -> NS:
    return NS(content=[NS(type="text", text=text)], stop_reason="end_turn", usage=_usage())


class _Client:
    def __init__(self, *responses: NS) -> None:
        self.messages = self
        self.queue = list(responses)

    def create(self, **_kwargs):
        return self.queue.pop(0) if self.queue else _text("")


def _orch(order=("get_current_gameweek", "rank_captain_candidates")):
    return ask_orchestrated(QUESTION, BOOTSTRAP, client=_Client(_both_tools(order), _text(ANSWER)),
                            _eval_client=object())


def _served(monkeypatch, orch_result):
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: orch_result)
    out = harness.ask_v2(QUESTION, BOOTSTRAP, orch_client=object())
    from fpl_server import AskRequest
    return out, harness_adapter.to_ask_response(out, AskRequest(question=QUESTION))


# ---------------------------------------------------------------------------
# the prod turn
# ---------------------------------------------------------------------------

def test_fixture_reproduces_the_prod_shape():
    """Premise: the orchestrator's own slot IS the anchor call."""
    r = _orch()
    assert [e["name"] for e in r.tool_calls_trace] == ["get_current_gameweek", "rank_captain_candidates"]
    assert r.tool_chosen == "get_current_gameweek"
    assert r.answer_text == ANSWER


def test_prod_turn_serves_the_captain_card(monkeypatch):
    out, resp = _served(monkeypatch, _orch())
    assert out["selected_tool"] == "rank_captain_candidates"
    assert out["tool_input"] == CAPTAIN_ARGS
    assert out["routing_trace"]["tool_sequence"] == ["get_current_gameweek", "rank_captain_candidates"]
    assert out["routing_trace"]["composed_primary_tool"] == "rank_captain_candidates"
    # What the UI renders, off the HTTP response.
    assert resp.intent == "rank_candidates"
    assert resp.captain_ranking, "no captain card served"
    served = [c["web_name"] for c in resp.captain_ranking]
    ranked = [c["web_name"] for c in CAPTAIN_OUTPUT["ranked_candidates"]]
    assert served == ranked[: len(served)]
    assert not (resp.generic_card and resp.generic_card.get("title") == "JORNADA ACTUAL")
    assert resp.final_text == ANSWER


def test_rank_first_order_is_unchanged(monkeypatch):
    out, resp = _served(monkeypatch, _orch(order=("rank_captain_candidates", "get_current_gameweek")))
    assert out["selected_tool"] == "rank_captain_candidates"
    assert "composed_primary_tool" not in out["routing_trace"]
    assert resp.intent == "rank_candidates" and resp.captain_ranking


# ---------------------------------------------------------------------------
# composed_primary_call, rule 2
# ---------------------------------------------------------------------------

def _t(name: str, success: bool = True, tag: str = "") -> dict:
    return {"round": 1, "tool_call_id": tag or name, "name": name, "args": {},
            "output": {"status": "ok" if success else "error", "tag": tag}, "success": success}


@pytest.mark.parametrize("anchor", sorted(GAMEWEEK_CONTEXT_TOOLS))
def test_anchor_first_yields_to_the_answering_tool(anchor):
    assert composed_primary_call([_t(anchor), _t("rank_captain_candidates")])["name"] == "rank_captain_candidates"


def test_anchor_set_is_exactly_the_two_gameweek_tools():
    assert GAMEWEEK_CONTEXT_TOOLS == frozenset({"get_current_gameweek", "get_gameweek_context"})


def test_first_answering_tool_in_model_order_wins():
    trace = [_t("get_current_gameweek"), _t("rank_captain_candidates"), _t("get_player_snapshot")]
    assert composed_primary_call(trace)["name"] == "rank_captain_candidates"


def test_owner_is_the_last_successful_call_of_the_answering_tool():
    trace = [_t("get_current_gameweek"), _t("rank_captain_candidates", tag="first"),
             _t("rank_captain_candidates", tag="good"), _t("rank_captain_candidates", success=False, tag="bad")]
    assert composed_primary_call(trace)["output"]["tag"] == "good"
    only_bad = [_t("get_current_gameweek"), _t("rank_captain_candidates", success=False, tag="bad")]
    assert composed_primary_call(only_bad)["output"]["tag"] == "bad"


@pytest.mark.parametrize("trace", [
    [_t("rank_captain_candidates"), _t("get_current_gameweek")],            # anchor not first
    [_t("get_current_gameweek"), _t("get_gameweek_context")],               # only anchors
    [_t("get_current_gameweek"), _t("get_current_gameweek", tag="2")],      # single tool
    [_t("get_team_snapshot"), _t("get_player_snapshot")],                   # no anchor
])
def test_every_other_turn_keeps_the_orchestrator_slot(trace):
    assert composed_primary_call(trace) is None


def test_calendar_composition_still_wins_over_the_anchor_rule():
    trace = [_t("get_current_gameweek"), _t("get_team_snapshot"), _t("get_fixture_outlook")]
    assert composed_primary_call(trace)["name"] == "get_fixture_outlook"

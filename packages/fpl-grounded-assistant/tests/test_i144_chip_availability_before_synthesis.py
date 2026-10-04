"""i144 -- the model writes knowing the chip is spent; no squad sentence for a spent chip.

Prod 2026-10-04 (Wildcard played in GW5, question in GW6): i137's lead was
right, but the body under «Para planificar…» had been written without knowing
the chip was gone («quedan 14 jornadas…, conservarlo te permite reaccionar») and
closed with the squad sentence «Te falta 1 jugador del grupo favorecido…».

(a) ``get_chip_advice`` now carries ``chip_availability`` -- the SAME decision
    the response layer applies (``chip_availability.decide_chip_availability``)
    -- and says it once in ``advice_text``; the prompt's CHIP_AVAILABILITY rule
    tells the model what to do with it. Unknown (no team) is said explicitly.
(b) ``compose_chip_answer`` drops the particular squad sentence when the chip
    is ``used``; the general header stays.

No network; the model is faked (the live behaviour is measured separately).
"""
from __future__ import annotations

import copy
import json
import socket
from types import SimpleNamespace as NS
from typing import Any

import pytest

from fpl_grounded_assistant import harness, harness_adapter
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.chip_advisor import get_chip_advice
from fpl_grounded_assistant.chip_two_part import compose_chip_answer
from fpl_grounded_assistant.evaluator import EvaluatorVerdict
from fpl_grounded_assistant.orchestrator import ask_orchestrated

#: bench boost windows chosen so a GW25 use returns in GW29 (current GW is 28).
WINDOWS_WITH_RETURN = [{"name": "bboost", "start_event": 1, "stop_event": 28},
                       {"name": "bboost", "start_event": 29, "stop_event": 38}]
#: FPL 2026-27 shape: the second window is the last one.
WINDOWS_LIVE = [{"name": "bboost", "start_event": 1, "stop_event": 19},
                {"name": "bboost", "start_event": 20, "stop_event": 38}]
SQUAD_SENTENCE_STEMS = ("te falta", "te faltan", "ya tienes el grupo favorecido", "enlaza tu equipo")
BODY = "Quedan varias jornadas en esta ventana; el calendario de la GW28 es favorable."


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i144 tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")


def _squad_rows() -> list[dict[str, Any]]:
    # 11 starters unknown to the bootstrap + a bench of the conftest players,
    # so squad_fit has something to say about the favoured group.
    rows = []
    for pos, element in enumerate(list(range(901, 912)) + [1, 2, 3, 4], start=1):
        rows.append({"id": element, "web_name": f"P{element}", "pick_position": pos, "is_starter": pos <= 11})
    return rows


def _bs(bootstrap, windows, used=None, remaining=None, players=True) -> dict[str, Any]:
    bs = copy.deepcopy(bootstrap)
    bs["fixture_difficulty_map"] = {13: 2, 14: 2, 1: 4, 8: 2, 11: 2}
    bs["chips"] = windows
    ctx: dict[str, Any] = {}
    if players:
        ctx["players"] = _squad_rows()
    if used is not None:
        ctx["chips_used"] = used
    if remaining is not None:
        ctx["chips_remaining"] = remaining
    if ctx:
        bs["_squad_context"] = ctx
    return bs


# ---------------------------------------------------------------------------
# (a) the tool output carries the decision
# ---------------------------------------------------------------------------

def test_used_with_a_return(bootstrap):
    out = get_chip_advice("bench_boost", _bs(bootstrap, WINDOWS_WITH_RETURN, used=[{"chip": "bench_boost", "event": 25}]))
    assert out["chip_availability"] == {"status": "used", "used_gw": 25, "returns_gw": 29}
    assert "already played this chip in GW25" in out["advice_text"]
    assert "comes back in GW29" in out["advice_text"]
    assert "do not advise keeping, saving or playing it now" in out["advice_text"]


def test_used_in_the_last_window(bootstrap):
    out = get_chip_advice("bench_boost", _bs(bootstrap, WINDOWS_LIVE, used=[{"chip": "bench_boost", "event": 22}]))
    assert out["chip_availability"] == {"status": "used", "used_gw": 22, "returns_gw": None}
    assert "does not come back this season" in out["advice_text"]


def test_used_in_the_other_window_is_available(bootstrap):
    out = get_chip_advice("bench_boost", _bs(bootstrap, WINDOWS_LIVE, used=[{"chip": "bench_boost", "event": 2}]))
    assert out["chip_availability"]["status"] == "available"
    assert "The user still has this chip" in out["advice_text"]


def test_no_team_is_unknown_and_said_explicitly(bootstrap):
    out = get_chip_advice("bench_boost", _bs(bootstrap, WINDOWS_LIVE, players=False))
    assert out["chip_availability"] == {"status": "unknown", "used_gw": None, "returns_gw": None}
    assert "unknown (no team linked): do not say it is available" in out["advice_text"]
    assert "this system" not in out["advice_text"].split("conditions")[0]


def test_without_windows_it_falls_back_to_chips_remaining(bootstrap):
    out = get_chip_advice("bench_boost", _bs(bootstrap, None, used=[{"chip": "bench_boost", "event": 25}], remaining=[]))
    assert out["chip_availability"]["status"] == "used"


# ---------------------------------------------------------------------------
# (b) no squad sentence for a spent chip
# ---------------------------------------------------------------------------

def _names(bs):
    return {t["id"]: t["name"] for t in bs["teams"]}


def test_compose_drops_the_squad_sentence_when_used_and_keeps_the_header(bootstrap):
    bs = _bs(bootstrap, WINDOWS_WITH_RETURN, used=[{"chip": "bench_boost", "event": 25}])
    out = get_chip_advice("bench_boost", bs)
    assert out["squad_fit"] is not None                    # there would have been a sentence
    text = compose_chip_answer(BODY, out, _names(bs))
    assert text.startswith("**Bench Boost")
    assert not any(stem in text.lower() for stem in SQUAD_SENTENCE_STEMS)


def test_compose_keeps_the_squad_sentence_when_available(bootstrap):
    bs = _bs(bootstrap, WINDOWS_LIVE, used=[])
    out = get_chip_advice("bench_boost", bs)
    text = compose_chip_answer(BODY, out, _names(bs))
    assert text.startswith("**Bench Boost")
    assert any(stem in text.lower() for stem in SQUAD_SENTENCE_STEMS)


# ---------------------------------------------------------------------------
# what /ask serves
# ---------------------------------------------------------------------------

def _served(monkeypatch, bs):
    out = get_chip_advice("bench_boost", bs)
    monkeypatch.setattr(orch_mod, "run_tool", lambda n, a, b: json.loads(json.dumps(out)))
    approved = EvaluatorVerdict(approved=True, grounded=True, complete=True, safe=True, tokens_used=1)
    monkeypatch.setattr(orch_mod, "evaluate_response", lambda **kwargs: approved)
    queue = [NS(content=[NS(type="tool_use", id="c1", name="get_chip_advice", input={"chip": "bench_boost"})],
                stop_reason="tool_use", usage=NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0)),
             NS(content=[NS(type="text", text=BODY)], stop_reason="end_turn",
                usage=NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0))]

    class _Client:
        def __init__(self):
            self.messages = self

        def create(self, **_k):
            return queue.pop(0) if queue else NS(content=[], stop_reason="end_turn",
                                                 usage=NS(input_tokens=0, output_tokens=0, cache_read_input_tokens=0))

    result = ask_orchestrated("¿Uso el Bench Boost esta jornada?", bs, client=_Client(), _eval_client=object())
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: result)
    v2 = harness.ask_v2("¿Uso el Bench Boost esta jornada?", bs, orch_client=object())
    from fpl_server import AskRequest
    req = AskRequest(question="¿Uso el Bench Boost esta jornada?", squad_context=bs["_squad_context"])
    return out, harness_adapter.to_ask_response(v2, req, bs)


def test_served_used_chip_has_no_squad_sentence(monkeypatch, bootstrap):
    out, resp = _served(monkeypatch, _bs(bootstrap, WINDOWS_WITH_RETURN, used=[{"chip": "bench_boost", "event": 25}],
                                         remaining=[]))
    text = resp.final_text
    assert text.startswith("Ya usaste el Bench Boost en la GW25. Vuelves a tenerlo desde la GW29.")
    assert "**Bench Boost" in text                         # header kept
    assert not any(stem in text.lower() for stem in SQUAD_SENTENCE_STEMS)
    assert resp.chip.get("chip_unavailable") is True


def test_served_available_chip_is_unchanged(monkeypatch, bootstrap):
    _, resp = _served(monkeypatch, _bs(bootstrap, WINDOWS_LIVE, used=[], remaining=["bench_boost"]))
    text = resp.final_text
    assert not text.startswith("Ya usaste")
    assert any(stem in text.lower() for stem in SQUAD_SENTENCE_STEMS)
    assert resp.chip.get("chip_unavailable") is False


@pytest.mark.parametrize("windows,used,remaining", [
    (WINDOWS_WITH_RETURN, [{"chip": "bench_boost", "event": 25}], []),
    (WINDOWS_LIVE, [{"chip": "bench_boost", "event": 2}], []),
    (WINDOWS_LIVE, [{"chip": "bench_boost", "event": 22}], ["bench_boost"]),
    (None, [{"chip": "bench_boost", "event": 25}], []),
    (None, None, ["bench_boost"]),
])
def test_the_tool_and_the_served_block_agree(monkeypatch, bootstrap, windows, used, remaining):
    out, resp = _served(monkeypatch, _bs(bootstrap, windows, used=used, remaining=remaining))
    assert (out["chip_availability"]["status"] == "used") is resp.chip.get("chip_unavailable")

"""i142 -- the triple captain candidate carries its season minutes and status.

i132 put ``minutes_played_season`` and ``status`` on bench boost's
favoured_players only. In prod (2026-10-04) the model said of Groß, the TC
top option, «no tengo datos suficientes para certificar su disponibilidad»
although the card shows his minutes. The TC signals now carry
``top_minutes_played_season`` / ``top_status`` (and ``evaluated_*`` for a
named candidate), read off the same bootstrap element with i132's mapping,
and both survive into what the model and the evaluator see. No network.
"""
from __future__ import annotations

import copy
import json
import socket
from types import SimpleNamespace as NS
from typing import Any

import pytest

from fpl_grounded_assistant import evaluator as ev
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.chip_advisor import CHIP_ADVICE_SPEC, get_chip_advice
from fpl_grounded_assistant.evaluator import EvaluatorVerdict
from fpl_grounded_assistant.find_players import _build_match_dict
from fpl_grounded_assistant.orchestrator import ask_orchestrated

#: element id -> (bootstrap minutes, bootstrap status code)
_AVAILABILITY = {1: (1890, "a"), 2: (2010, "d"), 3: (1500, "a"), 4: (300, "i"), 6: (450, "d"), 7: (0, "a")}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i142 tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)


@pytest.fixture
def tc_bootstrap(bootstrap) -> dict[str, Any]:
    bs = copy.deepcopy(bootstrap)
    for el in bs["elements"]:
        el["minutes"], el["status"] = _AVAILABILITY[el["id"]]
    return bs


def _ref(bs, element_id):
    el = next(e for e in bs["elements"] if e["id"] == element_id)
    return _build_match_dict(el, bs["teams"], bs.get("element_types", []), 0)


def test_top_candidate_carries_minutes_and_status(tc_bootstrap):
    sig = get_chip_advice("triple_captain", tc_bootstrap)["signals"]
    ref = _ref(tc_bootstrap, sig["top_element"])
    assert sig["top_minutes_played_season"] == ref["minutes_played_season"]
    assert sig["top_status"] == ref["status"]
    assert isinstance(sig["top_minutes_played_season"], int) and sig["top_minutes_played_season"] > 0


def test_named_candidate_carries_its_own(tc_bootstrap):
    sig = get_chip_advice("triple_captain", tc_bootstrap, player="Salah")["signals"]
    assert sig["evaluated_player"] == "Salah"
    assert sig["evaluated_minutes_played_season"] == 2010
    assert sig["evaluated_status"] == "Doubtful"
    # the top option keeps its own numbers next to them
    ref = _ref(tc_bootstrap, sig["top_element"])
    assert sig["top_minutes_played_season"] == ref["minutes_played_season"]


def test_unresolved_candidate_still_carries_the_top_options(tc_bootstrap):
    out = get_chip_advice("triple_captain", tc_bootstrap, player="Nadie Inexistente")
    assert out["recommendation"] == "missing_context"
    sig = out["signals"]
    assert sig["top_minutes_played_season"] is not None and sig["top_status"] is not None


def test_missing_minutes_is_zero_and_unknown_status_is_unknown(tc_bootstrap):
    bs = copy.deepcopy(tc_bootstrap)
    for el in bs["elements"]:
        if el["id"] == 3:   # Saka, named, so the ranking cannot hide the case
            del el["minutes"]
            el["status"] = "?"
    sig = get_chip_advice("triple_captain", bs, player="Saka")["signals"]
    assert sig["evaluated_player"] == "Saka"
    assert sig["evaluated_minutes_played_season"] == 0
    assert sig["evaluated_status"] == "Unknown"


def test_the_schema_declares_them():
    props = CHIP_ADVICE_SPEC.output_schema["properties"]["signals"]["properties"]
    for key in ("top_minutes_played_season", "top_status",
                "evaluated_minutes_played_season", "evaluated_status"):
        assert key in props


def test_they_survive_the_model_view(tc_bootstrap):
    out = get_chip_advice("triple_captain", tc_bootstrap)
    view = orch_mod._truncate_tool_output(copy.deepcopy(out), tool_name="get_chip_advice")
    assert view["signals"]["top_minutes_played_season"] == out["signals"]["top_minutes_played_season"]
    assert view["signals"]["top_status"] == out["signals"]["top_status"]


def test_the_evaluator_message_carries_them(monkeypatch, tc_bootstrap):
    out = get_chip_advice("triple_captain", tc_bootstrap)
    seen: dict = {}

    def capture(**kwargs):
        seen["message"] = ev._build_evaluator_user_message(
            kwargs["question"], kwargs["primary_response"], kwargs["tool_calls"])
        return EvaluatorVerdict(approved=True, grounded=True, complete=True, safe=True, tokens_used=1)

    monkeypatch.setattr(orch_mod, "evaluate_response", capture)
    monkeypatch.setattr(orch_mod, "run_tool", lambda n, a, b: json.loads(json.dumps(out)))
    queue = [NS(content=[NS(type="tool_use", id="c1", name="get_chip_advice",
                            input={"chip": "triple_captain"})]),
             NS(content=[NS(type="text", text="Respuesta.")])]

    class _Client:
        def __init__(self):
            self.messages = self

        def create(self, **_k):
            return queue.pop(0) if queue else NS(content=[])

    ask_orchestrated("¿Uso el Triple Captain esta jornada?", tc_bootstrap, client=_Client(), _eval_client=object())
    data = seen["message"].split("TOOL DATA", 1)[1]
    assert f'"top_minutes_played_season": {out["signals"]["top_minutes_played_season"]}' in data
    assert f'"top_status": "{out["signals"]["top_status"]}"' in data

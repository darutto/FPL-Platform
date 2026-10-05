"""i147 -- a chip already played shows no favoured group (Leo, option A).

After i146, a Wildcard played in GW5 and asked about in GW6 still opened its
read with «Grupo favorecido: Fulham» and the body planned the GW20 return
around Fulham's next five gameweeks (GW6-10). The favoured group is this
gameweek's run; with the chip spent it is the wrong planning input.

When ``chip_availability`` is ``used`` the tool output drops
``favoured_teams`` / ``favoured_players``, so the model, the evaluator and the
i108 header all go without it -- the header keeps «Wildcard — jornada X.».
Available and unknown chips are unchanged. ChipCard never drew the group.
No network.
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
from fpl_grounded_assistant.chip_two_part import general_header
from fpl_grounded_assistant.evaluator import EvaluatorVerdict
from fpl_grounded_assistant.orchestrator import ask_orchestrated

WINDOWS = [{"name": "bboost", "start_event": 1, "stop_event": 28},
           {"name": "bboost", "start_event": 29, "stop_event": 38}]
BODY = "Lectura de la jornada."


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i147 tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")


def _bs(bootstrap, used: list | None) -> dict[str, Any]:
    bs = copy.deepcopy(bootstrap)
    bs["fixture_difficulty_map"] = {13: 2, 14: 2, 1: 4, 8: 2, 11: 2}
    bs["chips"] = WINDOWS
    if used is not None:
        bs["_squad_context"] = {"chips_used": used, "chips_remaining": []}
    return bs


USED = [{"chip": "bench_boost", "event": 25}]
NOT_USED = [{"chip": "bench_boost", "event": 30}]   # the other window


def _names(bs):
    return {t["id"]: t["name"] for t in bs["teams"]}


def _group_names(out, bs) -> set[str]:
    names = _names(bs)
    teams = {names.get(t["team"]) or t["team_short"] for t in out["signals"].get("favoured_teams") or []}
    players = {p["web_name"] for p in out["signals"].get("favoured_players") or []}
    return {n for n in teams | players if n}


def test_used_chip_carries_no_favoured_group(bootstrap):
    out = get_chip_advice("bench_boost", _bs(bootstrap, USED))
    assert out["chip_availability"]["status"] == "used"
    assert "favoured_teams" not in out["signals"] and "favoured_players" not in out["signals"]
    assert out["signals"].get("average_fdr_top10") is not None        # the facts stay


def test_used_header_keeps_its_verdict_without_the_group(bootstrap):
    bs = _bs(bootstrap, USED)
    header = general_header(get_chip_advice("bench_boost", bs), _names(bs))
    assert header is not None and header.startswith("**Bench Boost — ")
    assert header.endswith(".**") and "Grupo favorecido" not in header


@pytest.mark.parametrize("used", [NOT_USED, None])
def test_available_and_unknown_keep_the_group(bootstrap, used):
    bs = _bs(bootstrap, used)
    out = get_chip_advice("bench_boost", bs)
    assert out["chip_availability"]["status"] in ("available", "unknown")
    assert out["signals"]["favoured_teams"]
    assert "Grupo favorecido" in general_header(out, _names(bs))


def test_only_the_group_differs_between_used_and_available(bootstrap):
    used = get_chip_advice("bench_boost", _bs(bootstrap, USED))
    available = get_chip_advice("bench_boost", _bs(bootstrap, NOT_USED))
    assert set(available["signals"]) - set(used["signals"]) == {"favoured_teams", "favoured_players"}


def _served(monkeypatch, bs):
    out = get_chip_advice("bench_boost", bs)
    monkeypatch.setattr(orch_mod, "run_tool", lambda n, a, b: json.loads(json.dumps(out)))
    approved = EvaluatorVerdict(approved=True, grounded=True, complete=True, safe=True, tokens_used=1)
    monkeypatch.setattr(orch_mod, "evaluate_response", lambda **kwargs: approved)
    usage = NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0)
    queue = [NS(content=[NS(type="tool_use", id="c1", name="get_chip_advice", input={"chip": "bench_boost"})],
                stop_reason="tool_use", usage=usage),
             NS(content=[NS(type="text", text=BODY)], stop_reason="end_turn", usage=usage)]

    class _Client:
        def __init__(self):
            self.messages = self

        def create(self, **_k):
            return queue.pop(0) if queue else NS(content=[], stop_reason="end_turn", usage=usage)

    result = ask_orchestrated("¿Uso el Bench Boost?", bs, client=_Client(), _eval_client=object())
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: result)
    v2 = harness.ask_v2("¿Uso el Bench Boost?", bs, orch_client=object())
    from fpl_server import AskRequest
    req = AskRequest(question="¿Uso el Bench Boost?", squad_context=bs.get("_squad_context"))
    return harness_adapter.to_ask_response(v2, req, bs)


def test_served_used_text_names_no_group(monkeypatch, bootstrap):
    group = _group_names(get_chip_advice("bench_boost", _bs(bootstrap, NOT_USED)), _bs(bootstrap, NOT_USED))
    assert group                                                         # there is a group to leak
    resp = _served(monkeypatch, _bs(bootstrap, USED))
    assert resp.final_text.startswith("Ya usaste el Bench Boost en la GW25.")
    assert "Grupo favorecido" not in resp.final_text
    assert not any(name in resp.final_text for name in group)


def test_served_available_text_is_unchanged(monkeypatch, bootstrap):
    resp = _served(monkeypatch, _bs(bootstrap, NOT_USED))
    assert "Grupo favorecido" in resp.final_text

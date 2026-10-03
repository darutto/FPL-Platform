"""i132 (b) -- bench boost's favoured players carry season minutes and status.

Before: ``signals.favoured_players`` named players (web_name, team, fdr) but
not their minutes or availability. The evaluator's SAFE rule ("no player
recommendations missing minutes_played_season + status check") then rejected
Bench Boost answers that named them, and the retry could not fix it: the tool
had no such data to cite (i124 gate: 4 of the remaining rejections). Leo's
decision 2026-10-03: the tool adds both.

What this file pins
-------------------
A. Every favoured player carries ``minutes_played_season`` and ``status``
   read off ITS bootstrap element (by id; the two Johnsons stay distinct),
   with the same mapping find_players / get_my_squad use.
B. The model sees them: they survive ``_truncate_tool_output`` (the model's
   view), and that view is what reaches the served evaluator message.
C. The deterministic i108 parts do not move: the general header and the
   composed answer are identical with and without the new keys.
D. Declared in ``CHIP_ADVICE_SPEC.output_schema``.
Fake clients only; no network.
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
from fpl_grounded_assistant.chip_two_part import compose_chip_answer, general_header
from fpl_grounded_assistant.evaluator import EvaluatorVerdict
from fpl_grounded_assistant.find_players import _build_match_dict
from fpl_grounded_assistant.orchestrator import ask_orchestrated

NEW_KEYS = ("minutes_played_season", "status")

#: element id -> (bootstrap minutes, bootstrap status code)
_AVAILABILITY = {1: (1890, "a"), 2: (2010, "a"), 3: (1500, "d"), 4: (300, "i"), 6: (450, "d"), 7: (0, "a")}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i132 tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.delenv("FPL_ORCH_EVAL_VERDICT_ONLY", raising=False)


@pytest.fixture
def bb_bootstrap(bootstrap) -> dict[str, Any]:
    """Same FDR map as the i108 E1 tests (favoured = 1, 2, 6, 7) plus minutes."""
    bs = copy.deepcopy(bootstrap)
    bs["fixture_difficulty_map"] = {13: 2, 14: 2, 1: 4, 8: 2, 11: 2}
    for el in bs["elements"]:
        minutes, status = _AVAILABILITY[el["id"]]
        el["minutes"] = minutes
        el["status"] = status
    return bs


def _strip_new_keys(out: dict[str, Any]) -> dict[str, Any]:
    stripped = copy.deepcopy(out)
    for p in stripped["signals"]["favoured_players"]:
        for k in NEW_KEYS:
            p.pop(k, None)
    return stripped


# ---------------------------------------------------------------------------
# A. read off each player's own element
# ---------------------------------------------------------------------------

def test_favoured_players_carry_minutes_and_status_by_element_id(bb_bootstrap):
    out = get_chip_advice("bench_boost", bb_bootstrap)
    players = out["signals"]["favoured_players"]
    assert {p["element"] for p in players} == {1, 2, 6, 7}
    by_id = {p["element"]: p for p in players}
    assert by_id[1]["minutes_played_season"] == 1890 and by_id[1]["status"] == "Available"
    assert by_id[2]["minutes_played_season"] == 2010 and by_id[2]["status"] == "Available"
    # The two Johnsons share a web_name; each keeps its own numbers.
    assert by_id[6]["minutes_played_season"] == 450 and by_id[6]["status"] == "Doubtful"
    assert by_id[7]["minutes_played_season"] == 0 and by_id[7]["status"] == "Available"


def test_same_values_as_find_players_for_the_same_element(bb_bootstrap):
    out = get_chip_advice("bench_boost", bb_bootstrap)
    elements = {e["id"]: e for e in bb_bootstrap["elements"]}
    for p in out["signals"]["favoured_players"]:
        ref = _build_match_dict(elements[p["element"]], bb_bootstrap["teams"],
                                bb_bootstrap.get("element_types", []), 0)
        assert p["minutes_played_season"] == ref["minutes_played_season"]
        assert p["status"] == ref["status"]


def test_missing_minutes_is_zero_and_unknown_status_is_unknown(bb_bootstrap):
    bs = copy.deepcopy(bb_bootstrap)
    for el in bs["elements"]:
        if el["id"] == 2:
            del el["minutes"]
            el["status"] = "?"
    out = get_chip_advice("bench_boost", bs)
    salah = next(p for p in out["signals"]["favoured_players"] if p["element"] == 2)
    assert salah["minutes_played_season"] == 0
    assert salah["status"] == "Unknown"


# ---------------------------------------------------------------------------
# B. the model and the evaluator see them
# ---------------------------------------------------------------------------

def test_new_fields_survive_the_model_view(bb_bootstrap):
    out = get_chip_advice("bench_boost", bb_bootstrap)
    view = orch_mod._truncate_tool_output(copy.deepcopy(out), tool_name="get_chip_advice")
    for p in view["signals"]["favoured_players"]:
        for k in NEW_KEYS:
            assert k in p


def test_served_evaluator_message_carries_the_minutes(monkeypatch, bb_bootstrap):
    out = get_chip_advice("bench_boost", bb_bootstrap)
    seen: dict = {}

    def capture(**kwargs):
        seen["message"] = ev._build_evaluator_user_message(
            kwargs["question"], kwargs["primary_response"], kwargs["tool_calls"])
        return EvaluatorVerdict(approved=True, grounded=True, complete=True, safe=True, tokens_used=1)

    monkeypatch.setattr(orch_mod, "evaluate_response", capture)
    monkeypatch.setattr(orch_mod, "run_tool", lambda n, a, b: json.loads(json.dumps(out)))
    queue = [NS(content=[NS(type="tool_use", id="c1", name="get_chip_advice",
                            input={"chip": "bench_boost"})]),
             NS(content=[NS(type="text", text="Respuesta.")])]

    class _Client:
        def __init__(self):
            self.messages = self

        def create(self, **_k):
            return queue.pop(0) if queue else NS(content=[])

    ask_orchestrated("¿bench boost?", bb_bootstrap, client=_Client(), _eval_client=object())
    data = seen["message"].split("TOOL DATA", 1)[1]
    assert '"minutes_played_season": 1890' in data
    assert '"status": "Doubtful"' in data


# ---------------------------------------------------------------------------
# C. the i108 deterministic parts do not move
# ---------------------------------------------------------------------------

def test_header_is_identical_with_and_without_the_new_keys(bb_bootstrap):
    out = get_chip_advice("bench_boost", bb_bootstrap)
    names = {t["id"]: t["name"] for t in bb_bootstrap["teams"]}
    header = general_header(out, names)
    assert header is not None and "Johnson" in header
    assert header == general_header(_strip_new_keys(out), names)
    assert "Available" not in header and "1890" not in header


def test_composed_answer_is_identical_with_and_without_the_new_keys(bb_bootstrap):
    out = get_chip_advice("bench_boost", bb_bootstrap)
    out["squad_source"] = "linked_team"
    out["squad_fit"] = {"held": [], "missing_count": 2, "verdict": "needs_transfers"}
    names = {t["id"]: t["name"] for t in bb_bootstrap["teams"]}
    body = "Cuerpo del modelo."
    assert compose_chip_answer(body, out, names) == compose_chip_answer(body, _strip_new_keys(out), names)


# ---------------------------------------------------------------------------
# D. declared
# ---------------------------------------------------------------------------

def test_output_schema_declares_the_new_fields():
    item = (CHIP_ADVICE_SPEC.output_schema["properties"]["signals"]["properties"]
            ["favoured_players"]["items"]["properties"])
    assert item["minutes_played_season"] == {"type": "integer"}
    assert item["status"] == {"type": "string"}

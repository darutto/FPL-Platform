"""Free transfers stated in the user's own words reach plan_to_sign deterministically.

Mocked and synthetic: the squad is the one ``test_plan_to_sign`` uses, the model is a
stand-in that calls the tool WITHOUT ``free_transfers`` (the observed failure), no network.
"""
from __future__ import annotations

import importlib

import pytest

from fpl_grounded_assistant.free_transfers_text import extract_free_transfers
from fpl_grounded_assistant.harness import ask_v2
from fpl_grounded_assistant.orchestrator import OrchestratorResult
from fpl_grounded_assistant.plan_followup import followup_args, sanitize_plan_state
from fpl_grounded_assistant.renderer import render
from test_plan_to_sign import _bootstrap, _squad_payload

pts = importlib.import_module("fpl_grounded_assistant.plan_to_sign")


@pytest.mark.parametrize("text,expected", [
    # Spanish
    ("sugiéreme una ruta para comprar a nico jackson, tengo 3 cambios disponibles", 3),
    ("tengo 3 cambios gratis", 3),
    ("3 cambios gratis", 3),
    ("tengo 2 transferencias libres", 2),
    ("me quedan 2 cambios", 2),
    ("me queda 1 cambio", 1),
    ("tengo tres cambios disponibles", 3),
    ("tengo 0 cambios gratis", 0),
    ("tengo cinco traspasos disponibles", 5),
    # English
    ("I have 2 free transfers", 2),
    ("2 FTs", 2),
    ("1 FT left", 1),
    ("I have 3 free transfers available", 3),
    ("3 transfers available", 3),
    ("how do I get Haaland, I have two free transfers", 2),
    # the same number said twice is still unambiguous
    ("tengo 3 cambios gratis, o sea 3 cambios gratis", 3),
])
def test_stated_free_transfers_are_read(text, expected):
    assert extract_free_transfers(text) == expected


@pytest.mark.parametrize("text", [
    "",
    "cómo ficho a nico jackson",
    "3 cambios de posición",                       # a different kind of change
    "tengo 3 cambios",                              # no word saying they are free: ambiguous
    "quiero hacer 3 cambios",
    "tengo 3 millones en el banco",
    "tengo 3.0m para gastar",
    "£8.5m",
    "necesito 1.2 millones",
    "compra a 3 jugadores",
    "2 transfers in the squad",
    "I have 2 transfers",                           # not clearly free
    "tengo 2 cambios gratis y 3 cambios gratis",    # two different numbers: ambiguous
    "tengo 9 cambios gratis",                       # out of FPL's range
    "tengo 6 cambios disponibles",
    "FTs",
    "a" * 700,
])
def test_everything_else_is_ignored(text):
    assert extract_free_transfers(text) is None


# ---------------------------------------------------------------------------
# end to end through ask_v2: the model forgets to pass free_transfers
# ---------------------------------------------------------------------------

LEO = "sugiéreme una ruta para comprar a nico jackson, tengo 3 cambios disponibles"


@pytest.fixture
def turn(monkeypatch):
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr(pts, "get_my_squad", lambda bs, gw=None: _squad_payload(0))

    def go(question, model_free_transfers=None):
        def fake_model(q, bootstrap, *args, **kwargs):
            from fpl_tool_runner import run_tool

            call = {"target": "nico jackson", "moves": "hits", "exclude_out_ids": [13, 14]}
            if model_free_transfers is not None:
                call["free_transfers"] = model_free_transfers
            out = run_tool("plan_to_sign", call, bootstrap)
            return OrchestratorResult(
                question=q, tool_chosen="plan_to_sign", tool_args=call, tool_output=out,
                answer_text=render("plan_to_sign", out, locale="es"), llm_used=True, model="fake", outcome="ok",
            )

        monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", fake_model)
        return ask_v2(question, _bootstrap(), orch_client=object())

    return go


def _three_move(result):
    options = [o for o in result["raw_output"]["options"] if o["moves"] == 3]
    assert options, result["raw_output"]["options"]
    return options


def test_leos_sentence_prices_a_three_move_route_with_the_three_free_transfers(turn):
    result = turn(LEO)
    raw = result["raw_output"]
    assert raw["free_transfers"] == 3 and raw["free_transfers_basis"] == "given"
    assert raw["free_transfers_source"] == "text"
    assert all(o["hit_cost"] == 0 and o["hit_basis"] == "given" for o in _three_move(result))
    assert "suponiendo" not in result["answer_text"]


def test_without_the_sentence_the_same_route_is_priced_on_the_assumption(turn):
    result = turn("sugiéreme una ruta para comprar a nico jackson")
    raw = result["raw_output"]
    assert raw["free_transfers"] is None and raw["free_transfers_source"] is None
    assert all(o["hit_cost"] == 8 and o["hit_basis"] == "assumed_one_free" for o in _three_move(result))


def test_a_number_the_model_passed_is_kept_when_the_text_says_nothing(turn):
    raw = turn("sugiéreme una ruta para comprar a nico jackson", model_free_transfers=2)["raw_output"]
    assert raw["free_transfers"] == 2 and raw["free_transfers_source"] == "model"


def test_the_text_wins_over_a_contradicting_model_and_the_card_says_so(turn):
    result = turn(LEO, model_free_transfers=1)
    raw = result["raw_output"]
    assert raw["free_transfers"] == 3 and raw["free_transfers_source"] == "text_over_model"
    assert all(o["hit_cost"] == 0 for o in _three_move(result))
    assert "3 traspasos gratis" in result["answer_text"]
    assert "3 free transfers" in render("plan_to_sign", raw, locale="en")


def test_the_number_survives_into_the_plan_state_and_the_follow_up(turn):
    state = turn(LEO)["plan_state"]
    assert state["free_transfers"] == 3
    args = followup_args(sanitize_plan_state(state))
    assert args["free_transfers"] == 3


def test_an_agreeing_model_is_not_reported_as_overridden(turn):
    raw = turn(LEO, model_free_transfers=3)["raw_output"]
    assert raw["free_transfers"] == 3 and raw["free_transfers_source"] == "model"
    assert "traspasos gratis que me dijiste" not in render("plan_to_sign", raw, locale="es")

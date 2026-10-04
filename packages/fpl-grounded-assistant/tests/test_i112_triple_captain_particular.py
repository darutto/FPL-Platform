"""i112 -- triple captain gets a particular part: is the best option in your squad?

Decision (Leo, 2026-10-03): yes. Same pattern as i108 E3 -- the code writes
the verdict header and the particular sentence, the model writes the body.

What this file pins
-------------------
A. The tool names its best option by id (``signals.top_element``), and that
   option is the one ``rank_captain_candidates`` puts first.
B. ``squad_fit`` for triple captain crosses that id against the squad:
   ``captain_held`` (candidate in the squad) / ``captain_missing`` (not in
   it); no team → no fit, and the answer invites to link one (same rule as
   BB/WC/FH); linked but not fetched → "no pude cargar tu plantilla".
C. Composition: header (verdict + candidate) first, the model's body, then
   the particular sentence; when the user asked about another player the
   header says the verdict is about that player.
D. The sentence is read off the SERVED text (``ask_orchestrated`` with the
   real tool dispatch and a fake model), not off a variable.
Fake clients only; no network.
"""
from __future__ import annotations

import copy
import importlib
import socket
from types import SimpleNamespace as NS
from typing import Any

import pytest

import fpl_grounded_assistant  # noqa: F401  (tool self-registration)
from fpl_grounded_assistant import tool_dispatch
from fpl_grounded_assistant.chip_advisor import get_chip_advice
from fpl_grounded_assistant.chip_two_part import (
    INVITE_TRIPLE_CAPTAIN,
    PARTICULAR_PHRASE,
    compose_chip_answer,
    fold,
    general_header,
    particular_outcome,
    particular_phrase,
)
from fpl_grounded_assistant.opportunity_framing import transaction_hits
from fpl_grounded_assistant.orchestrator import ask_orchestrated

get_my_squad_module = importlib.import_module("fpl_grounded_assistant.get_my_squad")

_FDR = {13: 2, 14: 2, 1: 4, 8: 2, 11: 2}
TEAM_NAMES = {1: "Arsenal", 13: "Manchester City", 14: "Liverpool", 8: "Chelsea", 11: "Manchester Utd"}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i112 tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    def boom(*_a, **_k):
        raise AssertionError("picks fetch attempted")

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.setattr(get_my_squad_module, "get_entry_picks", boom)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)


@pytest.fixture
def tc_bootstrap(bootstrap) -> dict[str, Any]:
    bs = copy.deepcopy(bootstrap)
    bs["fixture_difficulty_map"] = dict(_FDR)
    return bs


@pytest.fixture
def linked(monkeypatch):
    """Replace load_linked_squad where tool_dispatch looks it up."""
    state: dict[str, Any] = {"result": None}

    def fake(bootstrap, gw=None):
        return state["result"]

    monkeypatch.setattr(tool_dispatch, "load_linked_squad", fake)
    return state


def _squad(elements: list[int]) -> list[dict[str, Any]]:
    """15 get_my_squad-shaped rows; ids >= 900 are not in the bootstrap."""
    ids = list(elements) + [e for e in range(901, 916)][: 15 - len(elements)]
    return [{"id": e, "pick_position": i + 1, "is_starter": i < 11} for i, e in enumerate(ids)]


def _top(bs: dict[str, Any]) -> int:
    top = get_chip_advice("triple_captain", bs)["signals"]["top_element"]
    assert isinstance(top, int)
    return top


def _run_linked(bs: dict[str, Any], linked, members: list[int] | None) -> dict[str, Any]:
    bs = copy.deepcopy(bs)
    bs["_my_team_id"] = 68643
    linked["result"] = (
        {"status": "fetch_failed"} if members is None else {"status": "ok", "players": _squad(members)}
    )
    return tool_dispatch.run_tool("get_chip_advice", {"chip": "triple_captain"}, bs)


# ---------------------------------------------------------------------------
# A. the best option, by id, is rank_captain_candidates' first
# ---------------------------------------------------------------------------

def test_top_element_is_the_scored_top_and_matches_the_captain_ranking(tc_bootstrap):
    out = get_chip_advice("triple_captain", tc_bootstrap)
    sig = out["signals"]
    by_id = {e["id"]: e for e in tc_bootstrap["elements"]}
    assert by_id[sig["top_element"]]["web_name"] == sig["top_player"]
    ranked = tool_dispatch.run_tool("rank_captain_candidates", {}, copy.deepcopy(tc_bootstrap))
    assert ranked["presentation"]["global_top"][0] == sig["top_element"]


# ---------------------------------------------------------------------------
# B. the squad cross
# ---------------------------------------------------------------------------

def test_candidate_in_the_linked_squad_is_held(tc_bootstrap, linked):
    top = _top(tc_bootstrap)
    out = _run_linked(tc_bootstrap, linked, [top])
    assert out["squad_source"] == "linked_team"
    assert out["squad_fit"] == {"held": [top], "missing_count": 0, "verdict": "captain_held"}
    assert particular_phrase(out) == PARTICULAR_PHRASE["captain_held"]


def test_candidate_outside_the_squad_is_missing(tc_bootstrap, linked):
    top = _top(tc_bootstrap)
    others = [e["id"] for e in tc_bootstrap["elements"] if e["id"] != top]
    out = _run_linked(tc_bootstrap, linked, others)
    assert out["squad_fit"] == {"held": [], "missing_count": 1, "verdict": "captain_missing"}
    assert particular_phrase(out) == PARTICULAR_PHRASE["captain_missing"]


def test_no_team_invites_like_the_other_chips(tc_bootstrap):
    out = get_chip_advice("triple_captain", tc_bootstrap)
    assert out["squad_source"] is None and out["squad_fit"] is None
    assert particular_outcome(out) == "invite"
    assert particular_phrase(out) == INVITE_TRIPLE_CAPTAIN
    # BB/WC/FH keep their own wording.
    assert PARTICULAR_PHRASE["invite"] != INVITE_TRIPLE_CAPTAIN


def test_linked_but_not_fetched_says_so(tc_bootstrap, linked):
    out = _run_linked(tc_bootstrap, linked, None)
    assert out["linked_squad_error"] == "fetch_failed" and out["squad_fit"] is None
    assert particular_phrase(out) == PARTICULAR_PHRASE["fetch_failed"]


def test_missing_context_has_no_fit_and_no_parts(tc_bootstrap, linked):
    bs = copy.deepcopy(tc_bootstrap)
    for el in bs["elements"]:
        el["status"] = "i"          # empty pool -> missing_context
    out = _run_linked(bs, linked, [1, 2])
    assert out["recommendation"] == "missing_context"
    assert out["squad_fit"] is None
    assert particular_outcome(out) is None
    assert general_header(out, TEAM_NAMES) is None


def test_the_phrases_obey_the_framing_rule():
    for phrase in (PARTICULAR_PHRASE["captain_held"], PARTICULAR_PHRASE["captain_missing"],
                   INVITE_TRIPLE_CAPTAIN):
        assert transaction_hits(phrase) == []


# ---------------------------------------------------------------------------
# C. composition
# ---------------------------------------------------------------------------

def test_header_names_the_candidate_then_body_then_sentence(tc_bootstrap, linked):
    top = _top(tc_bootstrap)
    out = _run_linked(tc_bootstrap, linked, [top])
    name = out["signals"]["top_player"]
    text = compose_chip_answer("Cuerpo del modelo.", out, TEAM_NAMES)
    header, body, closing = text.split("\n\n")
    assert header.startswith("**Triple Captain — jornada ")
    assert header.endswith(f"Mejor candidato: {name}.")
    assert body == "Cuerpo del modelo."
    assert fold(closing) == fold(PARTICULAR_PHRASE["captain_held"] + ".")


def test_a_named_player_who_is_not_the_top_gets_his_own_verdict_line(tc_bootstrap):
    out = get_chip_advice("triple_captain", tc_bootstrap)
    top_name = out["signals"]["top_player"]
    other = next(e["web_name"] for e in tc_bootstrap["elements"]
                 if e["web_name"] not in (top_name, "Johnson") and e["status"] == "a")
    asked = get_chip_advice("triple_captain", tc_bootstrap, player=other)
    header = general_header(asked, TEAM_NAMES)
    assert header.startswith(f"**Triple Captain con {other} — jornada ")
    assert header.endswith(f"Mejor candidato de la jornada: {top_name}.")


# ---------------------------------------------------------------------------
# D. read off the served text
# ---------------------------------------------------------------------------

def _served(bs: dict[str, Any]) -> str:
    queue = [NS(content=[NS(type="tool_use", id="c1", name="get_chip_advice",
                            input={"chip": "triple_captain"})]),
             NS(content=[NS(type="text", text="Cuerpo del modelo.")])]

    class _Client:
        def __init__(self):
            self.messages = self

        def create(self, **_k):
            return queue.pop(0) if queue else NS(content=[])

    result = ask_orchestrated("¿Uso el triple capitán?", bs, client=_Client(), _eval_client=None)
    return result.answer_text


@pytest.mark.parametrize("held", [True, False])
def test_served_text_carries_the_particular_sentence(tc_bootstrap, linked, held):
    top = _top(tc_bootstrap)
    bs = copy.deepcopy(tc_bootstrap)
    bs["_my_team_id"] = 68643
    members = [top] if held else [e["id"] for e in bs["elements"] if e["id"] != top]
    linked["result"] = {"status": "ok", "players": _squad(members)}
    text = _served(bs)
    want = PARTICULAR_PHRASE["captain_held" if held else "captain_missing"]
    unwanted = PARTICULAR_PHRASE["captain_missing" if held else "captain_held"]
    assert text.startswith("**Triple Captain — ")
    assert fold(want) in fold(text) and fold(unwanted) not in fold(text)
    assert fold(text).index(fold("Cuerpo del modelo")) < fold(text).index(fold(want))


def test_served_text_without_a_team_invites(tc_bootstrap):
    text = _served(copy.deepcopy(tc_bootstrap))
    assert text.startswith("**Triple Captain — ")
    assert fold(INVITE_TRIPLE_CAPTAIN) in fold(text)


# ---------------------------------------------------------------------------
# E. the E3 grader and the measurement row cover triple captain
# ---------------------------------------------------------------------------

def _load_script(name: str):
    import importlib.util
    import sys
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_i112_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _tc_trace(verdict: str | None = "captain_held") -> dict[str, Any]:
    return {"status": "ok", "chip": "triple_captain", "recommendation": "conditions_favorable",
            "squad_source": "linked_team" if verdict else None,
            "squad_fit": {"held": [], "missing_count": 0, "verdict": verdict} if verdict else None,
            "linked_squad_error": None, "favoured_teams": [], "favoured_players": []}


def test_grader_puts_triple_captain_in_the_denominator():
    grader = _load_script("grade_i108_chip_two_parts")
    good = ("**Triple Captain — jornada favorable.** Mejor candidato: Salah.\n\nCuerpo.\n\n"
            "Tu mejor candidato para el triple capitán ya está en tu plantilla.")
    row = {"question_id": "cvg-09", "rep": 0, "answer_text_full": good, "chip_trace": _tc_trace(),
           "chip_candidate": {"top_player": "Salah", "top_element": 2, "evaluated_player": None}}
    g = grader.grade_row(row, {})
    assert g["bucket"] == "denominator" and g["outcome"] == "captain_held" and g["pass"] is True
    unnamed = good.replace("Mejor candidato: Salah.", "")
    assert grader.grade_row({**row, "answer_text_full": unnamed}, {})["part1"] is False
    invite = good.replace("Tu mejor candidato para el triple capitán ya está en tu plantilla",
                          INVITE_TRIPLE_CAPTAIN[0].upper() + INVITE_TRIPLE_CAPTAIN[1:])
    g = grader.grade_row({**row, "answer_text_full": invite, "chip_trace": _tc_trace(None)}, {})
    assert g["outcome"] == "invite" and g["pass"] is True


def test_measurement_row_carries_the_candidate_outside_chip_trace():
    measure = _load_script("measure_tool_routing")
    trace = ({"name": "get_chip_advice", "output": {
        "status": "ok", "chip": "triple_captain", "recommendation": "conditions_favorable",
        "signals": {"top_player": "Salah", "top_element": 2, "evaluated_player": "Saka"},
        "squad_source": None, "squad_fit": None, "linked_squad_error": None}},)
    result = NS(tool_calls_trace=trace)
    assert measure.extract_chip_candidate(result) == {
        "top_player": "Salah", "top_element": 2, "evaluated_player": "Saka"}
    # chip_trace keeps the projection the Jev shadow shares (test_i116).
    assert "top_player" not in measure.extract_chip_trace(result)
    assert measure.extract_chip_candidate(NS(tool_calls_trace=())) is None


def test_run_one_writes_the_candidate_on_the_row(monkeypatch):
    measure = _load_script("measure_tool_routing")
    from fpl_grounded_assistant import orchestrator as orch_mod
    trace = ({"name": "get_chip_advice", "output": {
        "status": "ok", "chip": "triple_captain", "recommendation": "conditions_favorable",
        "signals": {"top_player": "Salah", "top_element": 2}}},)
    fake = NS(outcome="ok", tool_chosen="get_chip_advice", tool_args={}, tool_output=trace[0]["output"],
              tool_call_count=1, tool_calls_trace=trace, answer_text="x", error=None,
              primary_input_tokens=0, primary_output_tokens=0, primary_cache_read_tokens=0,
              total_tokens=0, synthesis_turn=True, rounds_used=1)
    monkeypatch.setattr(orch_mod, "ask_orchestrated", lambda *a, **k: fake)
    q = {"id": "cvg-09", "family": "chip_vs_gameweek", "acceptable_tools": ["get_chip_advice"],
         "control": True, "question": "¿Vale la pena el triple captain?"}
    row = measure.run_one(q, 0, {}, "k")
    assert row["exception"] is None
    assert row["chip_candidate"] == {"top_player": "Salah", "top_element": 2, "evaluated_player": None}

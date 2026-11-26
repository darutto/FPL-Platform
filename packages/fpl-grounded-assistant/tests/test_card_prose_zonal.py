"""
The card-prose rule on the player zonal card.

On «¿le vienen bien los próximos rivales a X?» the card was on screen and the prose
listed its matches again, one per line. A block of three or more lines that each name a
card match (gameweek + opponent + its own status) goes; lines with judgement stay; an
emptied answer is fine, the card has its own verdict.

Synthetic data only. The HTTP tests run the real orchestrator with a fake model client:
no provider, no network. The serialized bodies are also the UI test's fixtures
(``UPDATE_PLAYER_ZONAL_FIXTURES=1``).
"""
from __future__ import annotations

import json
import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import test_player_zonal_card as zc
from test_card_prose_rule import _Client, _text, _tool_use
from test_player_zonal_card import _store  # noqa: F401  (autouse: the synthetic store)

import fpl_server
from fpl_grounded_assistant import card_prose_zonal as zonal_rule
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.card_prose_rule import REASON_ROWS_RESTATED
from fpl_grounded_assistant.card_prose_zonal import trim_zonal_restatement
from fpl_grounded_assistant.final_response import (
    PlayerZonalCardMeta, PlayerZonalFixture, PlayerZonalOutlookMeta, PlayerZonalZone,
)
from fpl_grounded_assistant.quota import reset_quota

TOOL = "get_player_zonal_outlook"
QUESTION = zc.QUESTION


def _fx(gw, opponent, short, status, home=True):
    return PlayerZonalFixture(
        gameweek=gw, fixture_id=gw, opponent=opponent, opponent_short=short, is_home=home,
        status=status, matches=(),
    )


CARD = PlayerZonalCardMeta(
    id=1, web_name="Alder", team_short="CHE", position="FWD",
    zonal=PlayerZonalOutlookMeta(
        zones=(PlayerZonalZone(zone="in-box / central", share=0.8),), gw_from=12, gw_to=15,
        fixtures=(
            _fx(12, "Everton", "EVE", "favorable"),
            _fx(13, "Spurs", "TOT", "neutral", False),
            _fx(14, "Ipswich", "IPS", "no_data"),
            _fx(15, "Man City", "MCI", "favorable", False),
        ),
        verdict_kind="favorable", verdict="v",
    ),
)
R12 = "- **J12 vs Everton:** cruce favorable…"
R13 = "- **J13 vs Tottenham (fuera):** sin cruce destacado."
R14 = "- **J14 vs IPS:** sin datos del rival"
R15 = "- **J15 vs Manchester City:** cruce favorable en el centro del área, donde genera el 80 % de su xG sin penalti."
JUDGEMENT = "Alder llega en buen momento para aprovecharlo."


def trim(text, card=CARD):
    return trim_zonal_restatement(text, card, store_name="Ben Alder", club_terms=["Chelsea", "CHE"])


# -- what goes ------------------------------------------------------------------


def test_the_live_shape_goes_with_its_intro_and_the_judgement_stays():
    out = trim(f"Estos son sus cruces:\n\n{R12}\n{R13}\n{R14}\n{R15}\n\n{JUDGEMENT}")
    assert out.fired and out.text == JUDGEMENT and out.dropped_lines == 5


@pytest.mark.parametrize("lines", [
    ["GW12 vs EVE: favourable matchup", "GW13 away to Spurs: no standout matchup", "GW14 vs Ipswich: no data on the opponent"],
    ["1. J12, Everton en casa: favorable", "2. J13, TOT fuera: neutral", "3. J15, Man City: cruce favorable"],
    ["| J12 | Everton | Cruce favorable |", "| J13 | Spurs | Neutral |", "| J14 | Ipswich | Sin datos |"],
    ["Jornada 12 ante Everton: cruce zonal favorable", "Jornada 13 contra Spurs: sin ventaja clara",
     "Jornada 14 frente a Ipswich: sin datos zonales del rival"],
])
def test_other_ways_of_writing_a_row(lines):
    out = trim("\n".join(lines))
    assert out.fired and out.text == ""


@pytest.mark.parametrize("zone", [
    "en el centro del área", "en la zona central del área", "por el lado izquierdo del área", "en el área centro",
])
def test_the_cards_zone_names_are_not_judgement(zone):
    out = trim(f"{R12}\n{R13}\n{R14}\n- J15 vs Man City: cruce favorable {zone}")
    assert out.fired and out.text == ""


def test_a_heading_over_the_dropped_list_goes_too():
    out = trim(f"### Próximos rivales de Alder\n\n{R12}\n{R13}\n{R14}")
    assert out.fired and out.text == ""


# -- what stays -------------------------------------------------------------------


def test_a_row_with_judgement_stays_and_the_pure_rows_go():
    commented = "- **J15 vs Manchester City:** cruce favorable, pero llega tocado y puede no ser titular ese día"
    out = trim(f"Sus cruces:\n{R12}\n{R13}\n{R14}\n{commented}")
    assert out.fired and out.text == f"Sus cruces:\n{commented}"


@pytest.mark.parametrize("extra,goes", [("ojo con su estado hoy", True), ("ojo con su estado físico hoy", False)])
def test_five_words_beyond_the_card_is_a_row_six_is_judgement(extra, goes):
    last = f"- J15 vs Man City: favorable, {extra}"
    out = trim(f"{R12}\n{R13}\n{R14}\n{last}")
    assert out.fired and (out.text == "") is goes


def test_two_rows_are_not_a_block():
    text = f"{R12}\n{R13}\n\n{JUDGEMENT}"
    assert not trim(text).fired


def test_a_line_with_another_status_is_not_that_row():
    """The card says J13 is neutral and J14 has no data: prose calling them favourable
    is not a copy of the card, and is left for what it is."""
    text = f"{R12}\n- J13 vs Spurs: cruce favorable\n- J14 vs Ipswich: cruce favorable"
    assert not trim(text).fired


@pytest.mark.parametrize("lines", [
    ["- J12 vs Everton", "- J13 vs Spurs", "- J14 vs Ipswich"],                    # no status word
    ["- Everton: favorable", "- Spurs: neutral", "- Ipswich: sin datos"],          # no gameweek
    ["- J12: favorable", "- J13: neutral", "- J14: sin datos"],                    # no opponent
    ["- J22 vs Everton: favorable", "- J23 vs Spurs: neutral", "- J24 vs IPS: sin datos"],
])
def test_a_row_needs_its_gameweek_opponent_and_status(lines):
    assert not trim("\n".join(lines)).fired


def test_a_prose_sentence_naming_the_matches_stays():
    text = "Los cruces favorables llegan en la J12 ante Everton y en la J15 ante Man City, con la J13 neutral ante Spurs."
    assert not trim(text).fired


def test_a_card_with_two_matches_or_none_never_fires():
    for fixtures in (CARD.zonal.fixtures[:2], ()):
        card = replace(CARD, zonal=replace(CARD.zonal, fixtures=fixtures))
        assert not trim(f"{R12}\n{R13}\n{R14}", card).fired


# -- over HTTP ----------------------------------------------------------------------

PALMER_ROWS = (
    "- **J6 vs Bournemouth:** sin cruce destacado.\n"
    "- **J7 vs Everton (fuera):** cruce neutral…\n"
    "- **J8 vs Spurs:** cruce favorable en el centro del área, donde genera el 100 % de su xG."
)
PALMER_JUDGEMENT = "La ventana que más le conviene llega al final del tramo, así que vale la pena esperarla."


@pytest.fixture
def server(monkeypatch):
    fpl_server._init_bootstrap(zc._bootstrap())
    fpl_server._sessions.clear()
    reset_quota()
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    audit: list = []
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: audit.append(entry))
    client = TestClient(fpl_server.app)
    client.audit = audit  # type: ignore[attr-defined]
    yield client
    fpl_server._sessions.clear()
    reset_quota()


@pytest.fixture
def model(monkeypatch):
    """The real orchestrator with a fake model: one zonal call, then ``state['text']``."""
    state = {"text": "", "calls": [(TOOL, {"player": "Palmer"})]}
    real = orch_mod.ask_orchestrated

    def _wrapped(question, bootstrap, **kw):
        kw["client"] = _Client(_tool_use(*state["calls"]), default=_text(state["text"]))
        kw["provider"] = "anthropic"
        kw.pop("api_key", None)
        kw["_eval_client"] = None
        return real(question, bootstrap, **kw)

    monkeypatch.setattr(orch_mod, "ask_orchestrated", _wrapped)
    return state


def _post(server, route):
    headers = {"X-User-Id": f"cpz-{route}"}
    if route == "ask":
        res = server.post("/ask", json={"question": QUESTION}, headers=headers)
    else:
        sid = server.post("/session").json()["session_id"]
        res = server.post(f"/session/{sid}/ask", json={"question": QUESTION}, headers=headers)
    assert res.status_code == 200
    return res.json()


def _fixture(name, body):
    """The whole serialized body, pinned as the UI test's input."""
    wire = {k: v for k, v in body.items() if k != "debug"}
    if "session_id" in wire:
        wire["session_id"] = "00000000-0000-0000-0000-000000000000"
    path = zc.UI_FIXTURES / f"{name}.json"
    if os.environ.get("UPDATE_PLAYER_ZONAL_FIXTURES"):
        path.write_text(json.dumps(wire, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    assert path.exists(), f"missing {path.name}: run UPDATE_PLAYER_ZONAL_FIXTURES=1"
    assert json.loads(path.read_text(encoding="utf-8")) == wire


@pytest.mark.parametrize("route", ["ask", "session"])
def test_the_match_list_is_trimmed_and_the_card_is_untouched(server, model, route):
    model["text"] = f"Estos son sus próximos cruces:\n\n{PALMER_ROWS}\n\n{PALMER_JUDGEMENT}"
    body = _post(server, route)
    assert body["intent"] == "player_zonal_outlook"
    assert body["final_text"] == PALMER_JUDGEMENT
    assert [f["status"] for f in body["player_zonal"]["zonal"]["fixtures"]] == ["neutral", "neutral", "favorable"]
    entry = server.audit[-1]
    assert (entry.card_prose_reason, entry.card_prose_dropped_lines) == (REASON_ROWS_RESTATED, 4)
    assert entry.card_prose_raw_answer_text == model["text"]


@pytest.mark.parametrize("route", ["ask", "session"])
def test_only_the_list_leaves_an_empty_text_beside_the_card(server, model, route):
    model["text"] = f"### Próximos rivales de Palmer\n\n{PALMER_ROWS}"
    body = _post(server, route)
    assert body["final_text"] == "" and body["outcome"] == "ok" and body["supported"] is True
    assert body["player_zonal"]["zonal"]["verdict"]          # the card says its own verdict
    assert not body.get("table_conclusions")
    assert server.audit[-1].card_prose_reason == REASON_ROWS_RESTATED
    _fixture(f"prose-dropped-{route}", body)


def test_a_clean_answer_is_untouched_and_unaudited(server, model):
    model["text"] = PALMER_JUDGEMENT
    assert _post(server, "ask")["final_text"] == PALMER_JUDGEMENT
    assert server.audit[-1].card_prose_reason is None


def test_without_the_card_the_list_is_the_answer(server, model, monkeypatch):
    from fpl_grounded_assistant import player_snapshot_zonal as pz

    monkeypatch.setattr(pz, "element_for_store_player", lambda *a: None)
    model["text"] = PALMER_ROWS
    body = _post(server, "ask")
    assert body["player_zonal"] is None and body["final_text"] == PALMER_ROWS


@pytest.mark.parametrize("second", [(TOOL, {"player": "Defender"}), ("get_injury_list", {})])
def test_a_turn_that_read_something_else_too_is_never_touched(server, model, second):
    model["calls"] = [(TOOL, {"player": "Palmer"}), second]
    model["text"] = PALMER_ROWS
    body = _post(server, "ask")
    assert body["final_text"] == PALMER_ROWS
    assert server.audit[-1].card_prose_reason is None


def test_a_rule_that_raises_sends_the_original_text(server, model, monkeypatch):
    monkeypatch.setattr(zonal_rule, "trim_zonal_restatement", lambda *a, **k: 1 / 0)
    model["text"] = PALMER_ROWS
    assert _post(server, "ask")["final_text"] == PALMER_ROWS
    assert server.audit[-1].card_prose_reason is None

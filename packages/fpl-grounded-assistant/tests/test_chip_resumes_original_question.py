"""An ambiguity chip on a non-card tool re-asks the user's OWN question.

Prod, 2026-11-01: «¿Quién sustituye a Joao Pedro si no juega?» and «Compara los
toques y pases clave de Palmer y Saka» -> «¿Cuál de estos jugadores buscabas?» ->
tap «João Pedro (CHE)» / «Palmer (CHE)» -> the GENERIC player card. The stable-id
chip carries only an id and the backend answers an id with ``get_player_snapshot``.

get_position_changes / get_player_involvement now arm rewrite chips (no id): each
``send_text`` is the original question with the ambiguous mention replaced by the
candidate's full name, which the resolver matches whole. The ambiguity of «Joao
Pedro» itself is real: Costinha's FIRST name is "João Pedro" (exact), so two players
tie; it is not the substring rule.

No network, no paid call: the provider is a fake and the tools are the real ones.
"""
from __future__ import annotations

import copy
import socket
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.orch_config import FOOTBALL_INTELLIGENCE_ENABLED_ENV
from fpl_grounded_assistant.quota import reset_quota
from fpl_grounded_assistant.suggestions import KIND_PROMPT_REWRITE, replace_mention
from fpl_tool_contract import tool_resolve_player

from conftest import BOOTSTRAP


def _el(pid: int, first: str, second: str, web: str, team: int) -> dict:
    return {"id": pid, "first_name": first, "second_name": second, "web_name": web, "team": team,
            "team_code": team, "element_type": 4, "status": "a", "now_cost": 55,
            "selected_by_percent": "5.0", "form": "3.0", "expected_goals": "0.10",
            "expected_assists": "0.05", "expected_goal_involvements": "0.15"}


def _bootstrap() -> dict:
    b = copy.deepcopy(BOOTSTRAP)
    b["teams"] = b["teams"] + [{"id": 5, "short_name": "BHA", "name": "Brighton"}]
    b["elements"] = b["elements"] + [
        _el(91, "João Pedro", "Junqueira de Jesus", "João Pedro", 8),
        _el(92, "João Pedro", "Loureiro da Costa", "Costinha", 5),
        _el(93, "Cole", "Palmer", "Palmer", 8),
        _el(94, "Alex", "Palmer", "Palmer", 11),
    ]
    return b


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"must not touch the network: {address!r}")
        return real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.setenv(FOOTBALL_INTELLIGENCE_ENABLED_ENV, "1")  # the two tools sit behind this flag


class _SeqClient:
    def __init__(self, tool: str, args: dict) -> None:
        self.messages = self
        self.queue = [
            NS(content=[NS(type="tool_use", id="tu_1", name=tool, input=args)], stop_reason="tool_use",
               usage=NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)),
            NS(content=[NS(type="text", text="Which one did you mean?")], stop_reason="end_turn",
               usage=NS(input_tokens=120, output_tokens=20, cache_read_input_tokens=0)),
        ]

    def create(self, **_kwargs):
        if not self.queue:
            raise AssertionError("unexpected extra provider call")
        return self.queue.pop(0)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    fpl_server._init_bootstrap(_bootstrap())
    fpl_server._sessions.clear()
    reset_quota()
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    yield TestClient(fpl_server.app)
    fpl_server._sessions.clear()
    reset_quota()


def _ask(server, monkeypatch, question: str, tool: str, args: dict, user: str) -> dict:
    monkeypatch.setattr(orch_mod, "_get_anthropic_client", lambda **_k: _SeqClient(tool, args))
    return server.post("/ask", json={"question": question}, headers={"X-User-Id": user}).json()


# --- the two prod cases ------------------------------------------------------

def test_who_replaces_ambiguous_player_es(server, monkeypatch):
    q = "¿Quién sustituye a Joao Pedro si no juega?"
    body = _ask(server, monkeypatch, q, "get_position_changes", {"player": "Joao Pedro"}, "u-pc-es")
    assert body["outcome"] == "ambiguous"
    chips = body["suggestions"]
    assert {c["label"] for c in chips} == {"João Pedro (CHE)", "Costinha (BHA)"}
    assert {c["send_text"] for c in chips} == {
        "¿Quién sustituye a João Pedro Junqueira de Jesus si no juega?",
        "¿Quién sustituye a João Pedro Loureiro da Costa si no juega?",
    }
    assert all(c["kind"] == KIND_PROMPT_REWRITE and c.get("player_id") is None for c in chips)


def test_compare_involvement_with_one_ambiguous_player_es(server, monkeypatch):
    q = "Compara los toques y pases clave de Palmer y Saka"
    body = _ask(server, monkeypatch, q, "get_player_involvement", {"player": "Palmer"}, "u-inv-es")
    chips = body["suggestions"]
    assert body["outcome"] == "ambiguous"
    assert {c["label"] for c in chips} == {"Palmer (CHE)", "Palmer (MUN)"}
    assert {c["send_text"] for c in chips} == {
        "Compara los toques y pases clave de Cole Palmer y Saka",  # the other player is kept
        "Compara los toques y pases clave de Alex Palmer y Saka",
    }
    assert all(c["kind"] == KIND_PROMPT_REWRITE and c.get("player_id") is None for c in chips)


def test_ambiguity_in_the_player_slot_with_an_absent_player(server, monkeypatch):
    q = "Who covers if Joao Pedro misses out? Neto's role changes"
    body = _ask(server, monkeypatch, q, "get_position_changes",
                {"player": "Joao Pedro", "absent_player": "Palmer"}, "u-abs-en")
    assert {c["send_text"] for c in body["suggestions"]} == {
        "Who covers if João Pedro Junqueira de Jesus misses out? Neto's role changes",
        "Who covers if João Pedro Loureiro da Costa misses out? Neto's role changes",
    }


# --- EN, and the session path -----------------------------------------------

def test_english_question_on_the_session_path(server, monkeypatch):
    q = "Compare touches and key passes for Palmer and Saka"
    monkeypatch.setattr(orch_mod, "_get_anthropic_client",
                        lambda **_k: _SeqClient("get_player_involvement", {"player": "Palmer"}))
    sid = server.post("/session").json()["session_id"]
    body = server.post(f"/session/{sid}/ask", json={"question": q, "locale": "en"},
                       headers={"X-User-Id": "u-inv-en"}).json()
    assert {c["send_text"] for c in body["suggestions"]} == {
        "Compare touches and key passes for Cole Palmer and Saka",
        "Compare touches and key passes for Alex Palmer and Saka",
    }


# --- edges ---------------------------------------------------------------------

def test_mention_not_in_the_question_arms_no_chips(server, monkeypatch):
    body = _ask(server, monkeypatch, "who comes in for him?", "get_position_changes",
                {"player": "Joao Pedro"}, "u-nomention")
    assert body["suggestions"] is None


def test_full_name_in_the_chip_text_resolves_where_the_short_one_does_not():
    b = _bootstrap()
    assert tool_resolve_player("Joao Pedro", b)["status"] == "ambiguous"
    assert tool_resolve_player("João Pedro Junqueira de Jesus", b)["player_id"] == 91
    assert tool_resolve_player("João Pedro Loureiro da Costa", b)["player_id"] == 92


def test_replace_mention_is_accent_case_and_word_insensitive():
    assert replace_mention("¿Quién sustituye a joao pedro?", "João Pedro", "X") == "¿Quién sustituye a X?"
    assert replace_mention("Palmerston and Palmer", "Palmer", "Cole Palmer") == "Palmerston and Cole Palmer"
    assert replace_mention("nobody", "Palmer", "X") is None
    assert replace_mention("anything", "  ", "X") is None


# --- the snapshot-first path (the one prod most likely took) --------------------

def test_snapshot_first_with_a_real_question_arms_rewrite_chips(server, monkeypatch):
    q = "Compara los toques y pases clave de Palmer y Saka"
    body = _ask(server, monkeypatch, q, "get_player_snapshot", {"player_name": "Palmer"}, "u-snap-q")
    chips = body["suggestions"]
    assert {c["send_text"] for c in chips} == {
        "Compara los toques y pases clave de Cole Palmer y Saka",
        "Compara los toques y pases clave de Alex Palmer y Saka",
    }
    assert all(c["kind"] == KIND_PROMPT_REWRITE and c.get("player_id") is None for c in chips)


def test_form_first_with_a_real_question_arms_rewrite_chips(server, monkeypatch):
    q = "How is Palmer's form lately?"
    body = _ask(server, monkeypatch, q, "get_player_form", {"query": "Palmer"}, "u-form-q")
    assert {c["send_text"] for c in body["suggestions"]} == {
        "How is Cole Palmer's form lately?", "How is Alex Palmer's form lately?"}


@pytest.mark.parametrize("bare", ["Palmer", "\u00bfPalmer?", "palmer!"])
def test_a_bare_name_keeps_the_stable_id_chips(server, monkeypatch, bare):
    body = _ask(server, monkeypatch, bare, "get_player_snapshot", {"player_name": "Palmer"}, f"u-bare-{abs(hash(bare))}")
    chips = body["suggestions"]
    assert sorted(c["player_id"] for c in chips) == [93, 94]
    assert all(c.get("kind") in (None, "") for c in chips)


# --- loop guard -----------------------------------------------------------------

def test_identical_full_names_fall_back_to_todays_chips():
    from fpl_grounded_assistant.suggestions import question_resume_suggestions

    twins = [{"id": 1, "name": "Alex Palmer", "web_name": "Palmer", "team_short": "CHE"},
             {"id": 2, "name": "Alex Palmer", "web_name": "Palmer", "team_short": "MUN"}]
    assert question_resume_suggestions(twins, "Palmer", "Forma de Palmer") is None


def test_a_full_name_that_resolves_to_someone_else_falls_back():
    from fpl_grounded_assistant.suggestions import question_resume_suggestions

    swapped = [{"id": 93, "name": "Alex Palmer", "web_name": "Palmer", "team_short": "CHE"},  # resolves to 94
               {"id": 94, "name": "Cole Palmer", "web_name": "Palmer", "team_short": "MUN"}]  # resolves to 93
    assert question_resume_suggestions(swapped, "Palmer", "Forma de Palmer", _bootstrap()) is None


# --- the UI's fixture is the body this backend serves ----------------------------

import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402

_UI_FIXTURE = Path(__file__).resolve().parents[2] / "fpl-ui" / "__tests__" / "fixtures" / "chip-resume-bodies.json"
_PINNED = ("final_text", "outcome", "supported", "intent", "suggestions")
_CASES = {
    "position_changes": ("¿Quién sustituye a Joao Pedro si no juega?", "get_position_changes", {"player": "Joao Pedro"}),
    "involvement": ("Compara los toques y pases clave de Palmer y Saka", "get_player_involvement", {"player": "Palmer"}),
    "snapshot": ("Compara los toques y pases clave de Palmer y Saka", "get_player_snapshot", {"player_name": "Palmer"}),
    "form": ("¿Cómo viene la forma de Palmer?", "get_player_form", {"query": "Palmer"}),
}


def test_ui_fixture_matches_what_post_ask_serves(server, monkeypatch):
    bodies = {}
    for key, (question, tool, args) in _CASES.items():
        body = _ask(server, monkeypatch, question, tool, args, f"u-pin-{key}")
        bodies[key] = {k: body[k] for k in _PINNED}
    if os.environ.get("REGEN_CHIP_FIXTURE"):
        _UI_FIXTURE.write_text(json.dumps(bodies, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert json.loads(_UI_FIXTURE.read_text(encoding="utf-8")) == bodies

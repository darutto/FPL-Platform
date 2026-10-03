"""i127 -- ``llm_used`` says whether the model wrote the text served.

Prod, 2026-10-02: on the "no grounded tool" orchestrator branch (an ambiguous
player, a tool that came back not_found, a no-tool reply) the orchestrator ran
and billed, yet ``llm_used`` was False -- it was derived from the branch name,
so the UI stamped those turns "Determinístico".

Meaning on the orchestrator branches (both), read off what ran: a provider
call succeeded AND the served text is the model's own (``synthesis_turn``) AND
the final-text guard did not swap it for its own sentence. That is the meaning
``final_response`` documents for the field ("is final_text LLM-generated (and
accepted)"); a deterministic render() served after a failed synthesis is
"Determinístico", truthfully. Every other branch keeps its rule
(resource/route/prompt/orchestrator off -> False). The legacy ``respond()``
dispatcher presentation path does not go through these projections.

Every turn runs the REAL ``ask_orchestrated`` with a fake Anthropic-shaped
client and real tools, offline, and the field is read off the HTTP JSON body.
"""
from __future__ import annotations

import copy
import socket
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.quota import reset_quota

from conftest import BOOTSTRAP

_MARTINEZ = [
    {"id": 31, "first_name": "Emiliano", "second_name": "Martínez", "web_name": "Martínez",
     "team": 8, "team_code": 8, "element_type": 1, "status": "a", "now_cost": 50,
     "selected_by_percent": "10.0", "form": "4.0", "expected_goals": "0.00",
     "expected_assists": "0.00", "expected_goal_involvements": "0.00"},
    {"id": 32, "first_name": "Lisandro", "second_name": "Martínez", "web_name": "Martínez",
     "team": 11, "team_code": 12, "element_type": 2, "status": "a", "now_cost": 50,
     "selected_by_percent": "3.0", "form": "3.0", "expected_goals": "0.05",
     "expected_assists": "0.02", "expected_goal_involvements": "0.07"},
]

_HTML = "<!DOCTYPE html><html><head><title>x</title></head><body>" + "<p>x</p>" * 80 + "</body></html>"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i127 tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")


def _usage() -> NS:
    return NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)


def _tool_use(tool: str, args: dict) -> NS:
    return NS(content=[NS(type="tool_use", id="tu_1", name=tool, input=args)],
              stop_reason="tool_use", usage=_usage())


def _text(text: str) -> NS:
    return NS(content=[NS(type="text", text=text)] if text else [], stop_reason="end_turn", usage=_usage())


class _SeqClient:
    """Serves the queued responses, then empty turns (no text, no tool)."""

    def __init__(self, *responses: NS) -> None:
        self.messages = self
        self.queue = list(responses)

    def create(self, **_kwargs):
        return self.queue.pop(0) if self.queue else _text("")


def _provider(monkeypatch: pytest.MonkeyPatch, *responses: NS) -> None:
    monkeypatch.setattr(orch_mod, "_get_anthropic_client", lambda **_k: _SeqClient(*responses))


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    b = copy.deepcopy(BOOTSTRAP)
    b["elements"] = b["elements"] + copy.deepcopy(_MARTINEZ)
    fpl_server._init_bootstrap(b)
    fpl_server._sessions.clear()
    reset_quota()
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    yield TestClient(fpl_server.app)
    fpl_server._sessions.clear()
    reset_quota()


def _ask(server, question: str, user: str) -> dict:
    return server.post("/ask", json={"question": question, "debug": True}, headers={"X-User-Id": user}).json()


def _session_ask(server, question: str, user: str) -> dict:
    sid = server.post("/session").json()["session_id"]
    return server.post(f"/session/{sid}/ask", json={"question": question}, headers={"X-User-Id": user}).json()


# ---------------------------------------------------------------------------
# the prod defect: no-grounded-tool branch, the model wrote the text
# ---------------------------------------------------------------------------

def _ambiguous_turn(monkeypatch):
    _provider(monkeypatch, _tool_use("get_player_form", {"query": "Martínez"}),
              _text("Hay dos Martínez: ¿Emiliano (CHE) o Lisandro (MUN)?"))


def test_no_grounded_branch_with_model_text_is_llm_used_on_ask(server, monkeypatch):
    _ambiguous_turn(monkeypatch)
    body = _ask(server, "forma de Martínez", "u-i127-amb-a")
    assert body["debug"]["routing_trace"]["branch"] == "unsupported"   # premise: the branch that said False
    assert body["final_text"].startswith("Hay dos Martínez")
    assert body["llm_used"] is True


def test_no_grounded_branch_with_model_text_is_llm_used_on_session(server, monkeypatch):
    _ambiguous_turn(monkeypatch)
    body = _session_ask(server, "forma de Martínez", "u-i127-amb-s")
    assert body["final_text"].startswith("Hay dos Martínez")
    assert body["llm_used"] is True


def test_no_tool_model_reply_is_llm_used(server, monkeypatch):
    _provider(monkeypatch, _text("Solo puedo ayudarte con Fantasy Premier League."))
    body = _ask(server, "¿qué tiempo hace hoy?", "u-i127-notool")
    assert body["debug"]["routing_trace"]["branch"] == "unsupported"
    assert body["final_text"].startswith("Solo puedo ayudarte")
    assert body["llm_used"] is True


# ---------------------------------------------------------------------------
# grounded branch: model prose vs a deterministic render vs a guarded text
# ---------------------------------------------------------------------------

def test_grounded_synthesis_is_llm_used(server, monkeypatch):
    _provider(monkeypatch, _tool_use("get_current_gameweek", {}), _text("Estamos en la jornada 28."))
    body = _ask(server, "¿en qué jornada estamos?", "u-i127-syn")
    assert body["debug"]["routing_trace"]["branch"] == "orchestrator"
    assert body["synthesis_turn"] is True
    assert body["llm_used"] is True


def test_grounded_render_fallback_is_not_llm_used(server, monkeypatch):
    """Synthesis returned no text (nor did the extra round): the user reads
    render() of the tool output, not the model's words."""
    _provider(monkeypatch, _tool_use("get_current_gameweek", {}))
    body = _ask(server, "¿en qué jornada estamos?", "u-i127-render")
    assert body["debug"]["routing_trace"]["branch"] == "orchestrator"
    assert body["synthesis_turn"] is False
    assert body["llm_used"] is False


def test_guarded_text_is_not_llm_used(server, monkeypatch):
    """The model's text was blocked and replaced by the guard's own sentence."""
    _provider(monkeypatch, _tool_use("get_current_gameweek", {}), _text(_HTML))
    body = _ask(server, "¿en qué jornada estamos?", "u-i127-guard")
    assert "<html" not in body["final_text"].lower()
    assert body["synthesis_turn"] is True          # the model did write -- the guard swapped it
    assert body["llm_used"] is False


# ---------------------------------------------------------------------------
# deterministic branches keep their rule
# ---------------------------------------------------------------------------

def test_resource_branch_stays_deterministic(server, monkeypatch):
    _provider(monkeypatch)
    body = _ask(server, "@top_form", "u-i127-res-a")
    assert body["debug"]["routing_trace"]["branch"] == "resource"
    assert body["llm_used"] is False
    assert _session_ask(server, "@top_form", "u-i127-res-s")["llm_used"] is False


def test_orchestrator_disabled_stays_deterministic(server, monkeypatch):
    monkeypatch.setenv("FPL_ORCH_ENABLED", "0")
    body = _ask(server, "forma de Martínez", "u-i127-off")
    assert body["llm_used"] is False

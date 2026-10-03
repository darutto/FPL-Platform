"""i125(b) -- an evaluator retry that only renders never replaces a real answer.

Prod, 2026-10-02 (team_id=68643): «¿A quién capitaneo esta jornada? Dame un
top 3 numerado.» The primary answered from rank_captain_candidates with model
text; the evaluator rejected; the retry called get_gameweek_context, its
synthesis gave no text, and ``_apply_evaluator`` delivered that tool's bare
render() unconditionally -- «Jornada actual: GW5 ...», no captain.

Rule (narrowest change to #290's "unconditional delivery", decided in
review): keep the PRIMARY only when the retry ends in a render without
synthesis AND the primary had model text of its own. A retry that wrote text
-- even with another tool -- is still delivered; a primary with no model
text still yields to the retry's render. Every rejected turn stamps
``retry_delivery`` (retry_synthesis / primary_kept / retry_render) with what
it served, and that reaches routing_trace and the audit line.

The primary half is the real prod turn (tests/fixtures/
i125b_captain_turn_2026-10-02.json: its rank_captain_candidates output,
trimmed, and the model's real text). Fake Anthropic-shaped client, tools
served from fixtures, evaluator verdict forced -- no network, no paid call.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.evaluator import EvaluatorVerdict
from fpl_grounded_assistant.orchestrator import (
    RETRY_DELIVERIES,
    RETRY_DELIVERY_PRIMARY_KEPT,
    RETRY_DELIVERY_RETRY_RENDER,
    RETRY_DELIVERY_RETRY_SYNTHESIS,
    ask_orchestrated,
)
from fpl_grounded_assistant.renderer import render

from conftest import BOOTSTRAP

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "i125b_captain_turn_2026-10-02.json").read_text(encoding="utf-8")
)
QUESTION = FIXTURE["question"]
PRIMARY_TEXT = FIXTURE["primary_text"]
CAPTAIN_OUTPUT = FIXTURE["tool_output"]
GW_CONTEXT_OUTPUT = {
    "status": "ok",
    "current_gameweek": {"id": 5, "finished": True},
    "next_gameweek": {"id": 6, "deadline_time": "2026-10-03T10:00:00Z"},
}
RETRY_TEXT = "Top 3: 1. Groß, 2. Tarkowski, 3. Barnes."


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"i125(b) tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.delenv("FPL_EVAL_DISABLED", raising=False)

    outputs = {"rank_captain_candidates": CAPTAIN_OUTPUT, "get_gameweek_context": GW_CONTEXT_OUTPUT}

    def _fake_run_tool(name, args, bootstrap):
        return json.loads(json.dumps(outputs[name]))

    monkeypatch.setattr(orch_mod, "run_tool", _fake_run_tool)
    verdict = EvaluatorVerdict(approved=False, grounded=False, complete=False, safe=True,
                               retry_feedback="Cita los valores concretos.", tokens_used=17)
    monkeypatch.setattr(orch_mod, "evaluate_response", lambda **kwargs: verdict)


def _usage() -> NS:
    return NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)


def _tool_use(name: str, args: dict, cid: str) -> NS:
    return NS(content=[NS(type="tool_use", id=cid, name=name, input=args)], stop_reason="tool_use", usage=_usage())


def _text(text: str) -> NS:
    return NS(content=[NS(type="text", text=text)] if text else [], stop_reason="end_turn", usage=_usage())


class _Client:
    """Primary round, then the retry round. Empty turns once the queue ends."""

    def __init__(self, *responses: NS) -> None:
        self.messages = self
        self.queue = list(responses)

    def create(self, **_kwargs):
        return self.queue.pop(0) if self.queue else _text("")


class _PhasedClient:
    """Serves ``primary`` until the retry round starts -- recognised by the
    retry question the orchestrator builds ("Previous attempt feedback:") --
    then ``retry``. Independent of how many synthesis / extra-round calls the
    primary makes. Empty turns once a queue ends."""

    def __init__(self, primary: list, retry: list) -> None:
        self.messages = self
        self.primary, self.retry = list(primary), list(retry)

    def create(self, **kwargs):
        first = (kwargs.get("messages") or [{}])[0]
        content = first.get("content") if isinstance(first, dict) else None
        queue = self.retry if isinstance(content, str) and content.startswith("Previous attempt feedback:") else self.primary
        return queue.pop(0) if queue else _text("")


def _run(*responses: NS):
    return ask_orchestrated(QUESTION, BOOTSTRAP, client=_Client(*responses), _eval_client=object())


_PRIMARY = (_tool_use("rank_captain_candidates", FIXTURE["tool_args"], "c1"), _text(PRIMARY_TEXT))
_RETRY_TOOL = _tool_use("get_gameweek_context", {}, "c2")


# ---------------------------------------------------------------------------
# the prod shape
# ---------------------------------------------------------------------------

def test_prod_shape_serves_the_primary_captain_answer():
    r = _run(*_PRIMARY, _RETRY_TOOL, _text(""))
    assert r.retry_attempted is True
    assert r.retry_delivery == RETRY_DELIVERY_PRIMARY_KEPT
    assert r.answer_text == PRIMARY_TEXT
    assert r.answer_text != render("get_gameweek_context", GW_CONTEXT_OUTPUT)
    # the captains the tool ranked are named in what is served
    assert "Groß" in r.answer_text
    assert r.tool_chosen == "rank_captain_candidates"
    assert r.tool_output["ranked_candidates"][0]["web_name"] == "Groß"
    assert r.synthesis_turn is True
    # the retry ran and was billed: still in the trace and in the tokens
    names = [(e["name"], bool(e.get("retry"))) for e in r.tool_calls_trace]
    assert names == [("rank_captain_candidates", False), ("get_gameweek_context", True)]
    assert r.retry_input_tokens > 0


# ---------------------------------------------------------------------------
# what does not change
# ---------------------------------------------------------------------------

def test_synthesised_retry_with_another_tool_is_still_delivered():
    r = _run(*_PRIMARY, _RETRY_TOOL, _text(RETRY_TEXT))
    assert r.retry_delivery == RETRY_DELIVERY_RETRY_SYNTHESIS
    assert r.answer_text == RETRY_TEXT
    assert r.tool_chosen == "get_gameweek_context"


def test_primary_without_model_text_still_yields_to_the_retry_render():
    """Primary synthesis empty -> the primary itself is a render; today's
    behaviour stands: the retry's render is delivered."""
    client = _PhasedClient([_tool_use("rank_captain_candidates", FIXTURE["tool_args"], "c1")],
                           [_RETRY_TOOL, _text("")])
    r = ask_orchestrated(QUESTION, BOOTSTRAP, client=client, _eval_client=object())
    assert r.retry_attempted is True
    assert r.retry_delivery == RETRY_DELIVERY_RETRY_RENDER
    assert r.synthesis_turn is False
    assert r.answer_text == render("get_gameweek_context", GW_CONTEXT_OUTPUT)


def test_retry_text_without_a_tool_is_retry_synthesis():
    r = _run(*_PRIMARY, _text(RETRY_TEXT))
    assert r.retry_delivery == RETRY_DELIVERY_RETRY_SYNTHESIS
    assert r.answer_text == RETRY_TEXT


def test_empty_retry_without_a_tool_keeps_the_primary():
    r = _run(*_PRIMARY, _text(""))
    assert r.retry_delivery == RETRY_DELIVERY_PRIMARY_KEPT
    assert r.answer_text == PRIMARY_TEXT


def test_no_rejection_means_no_retry_delivery(monkeypatch):
    ok = EvaluatorVerdict(approved=True, grounded=True, complete=True, safe=True,
                          retry_feedback=None, tokens_used=5)
    monkeypatch.setattr(orch_mod, "evaluate_response", lambda **kwargs: ok)
    r = _run(*_PRIMARY)
    assert r.retry_attempted is False
    assert r.retry_delivery is None
    assert r.answer_text == PRIMARY_TEXT


def test_the_value_set_is_closed():
    assert RETRY_DELIVERIES == {"retry_synthesis", "primary_kept", "retry_render"}


# ---------------------------------------------------------------------------
# the stamp reaches routing_trace and the audit line (both HTTP surfaces)
# ---------------------------------------------------------------------------

@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    import fpl_server
    from fpl_grounded_assistant import harness as harness_mod
    from fpl_grounded_assistant.quota import reset_quota

    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setattr(harness_mod, "_build_eval_client", lambda *a, **k: object())
    fpl_server._init_bootstrap(json.loads(json.dumps(BOOTSTRAP)))
    fpl_server._sessions.clear()
    reset_quota()
    written: list = []
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: written.append(entry))
    yield TestClient(fpl_server.app), written
    fpl_server._sessions.clear()
    reset_quota()


def _serve(monkeypatch, *responses):
    monkeypatch.setattr(orch_mod, "_get_anthropic_client", lambda **_k: _Client(*responses))


def test_post_ask_serves_the_primary_and_stamps_trace_and_audit(server, monkeypatch):
    client, written = server
    _serve(monkeypatch, *_PRIMARY, _RETRY_TOOL, _text(""))
    body = client.post("/ask", json={"question": QUESTION, "debug": True},
                       headers={"X-User-Id": "u-i125b-ask"}).json()
    assert body["final_text"] == PRIMARY_TEXT
    assert body["debug"]["routing_trace"]["retry_delivery"] == RETRY_DELIVERY_PRIMARY_KEPT
    assert written[-1].retry_attempted is True
    assert written[-1].retry_delivery == RETRY_DELIVERY_PRIMARY_KEPT


def test_session_ask_stamps_the_audit_too(server, monkeypatch):
    client, written = server
    _serve(monkeypatch, *_PRIMARY, _RETRY_TOOL, _text(""))
    sid = client.post("/session").json()["session_id"]
    body = client.post(f"/session/{sid}/ask", json={"question": QUESTION},
                       headers={"X-User-Id": "u-i125b-sess"}).json()
    assert body["final_text"] == PRIMARY_TEXT
    assert written[-1].retry_delivery == RETRY_DELIVERY_PRIMARY_KEPT


def test_audit_line_serialises_the_field(tmp_path):
    from fpl_grounded_assistant import audit as audit_mod

    entry = audit_mod.make_audit_entry(question="q", branch="orchestrator", outcome="ok",
                                       retry_attempted=True, retry_delivery=RETRY_DELIVERY_PRIMARY_KEPT)
    audit_mod.write_audit_entry(entry, log_dir=str(tmp_path))
    lines = [json.loads(line) for p in tmp_path.rglob("*") if p.is_file()
             for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines and lines[-1]["retry_delivery"] == RETRY_DELIVERY_PRIMARY_KEPT

"""
Parity regression test: POST /ask vs POST /session/{id}/ask.

Bug (production, reproduced against the real chat UI): a user asked
"Evalua a mi equipo y que tan buena idea seria hacer bench boost en la
fecha 2" through the session endpoint and got back a raw gameweek-lookup
dump ("Jornada actual: GW1 (in_progress)...") instead of an answer, in
2 of 5 live runs. The same question through POST /ask never produced a
raw dump in 10/10 runs.

Root cause: the two endpoints ran different code. POST /ask was rewired
(mcp-graduation G1) to always route through harness.ask_v2(). POST
/session/{id}/ask still called ConversationSession.respond(), whose
internal ask_v2()-delegating helper (_try_session_orchestration_response)
only fired when ask_v2()'s ladder resolved through the "orchestrator"
branch -- for every OTHER branch (e.g. "route", a deterministic ladder
match, which is exactly the branch a bare gameweek-lookup tool call
produces) it returned None and the caller fell through to the legacy
ask_llm_safe() pipeline. That pipeline renders a single deterministic
tool's raw output with no LLM synthesis turn -- the raw dump.

The fix (G2): ConversationSession.respond() now routes every session turn
through ask_v2() unconditionally, exactly like POST /ask. This test pins
that both endpoints take the SAME routing path for the SAME question: the
same branch, the same tool-selection mechanism (a single mocked ask_v2 call
per endpoint, not a second independent pipeline), and the same synthesis
behaviour (identical final_text, outcome, intent, llm_used, review_passed,
route_source). It intentionally reproduces the exact question and exact
buggy raw-dump text from the incident, on the "route" branch -- the branch
category that triggered the regression (NOT "orchestrator", which already
worked before this fix; see _try_session_orchestration_response's old gate).

Session-only differences (session_id, rewritten_question, reference
resolution) are asserted explicitly rather than excluded from comparison.
"""
from __future__ import annotations

import os as _os
import sys as _sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG = _os.path.dirname(_HERE)
_PKGS = _os.path.dirname(_PKG)
for _p in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
    _os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_server  # noqa: E402
from fpl_grounded_assistant import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.quota import reset_quota  # noqa: E402

# The exact question and exact raw-dump text from the production incident.
_INCIDENT_QUESTION = (
    "Evalua a mi equipo y que tan buena idea seria hacer bench boost en la fecha 2"
)
_INCIDENT_ANSWER_TEXT = (
    "Jornada actual: GW1 (in_progress). "
    "Proxima jornada: GW2 (deadline: 2026-08-28T17:30:00Z)."
)


def _controlled_ask_v2(question: str, bootstrap, *args, **kwargs) -> dict:
    """Simulate ask_v2() resolving through the "route" branch (deterministic
    ladder match, zero LLM tokens) -- the exact branch category whose
    session-side handling regressed. Records every call so the test can
    assert both endpoints reached this SAME function with the SAME text."""
    _controlled_ask_v2.calls.append(question)  # type: ignore[attr-defined]
    return {
        "selected_tool": "get_gameweek_context",
        "tool_input": {},
        "raw_output": {"status": "ok"},
        "answer_text": _INCIDENT_ANSWER_TEXT,
        "outcome": "ok",
        "kind": "text",
        "routing_trace": {
            "branch": "route",
            "decision_kind": "text",
            "decision_outcome": "fallthrough",
            "router_hit": True,
            "classifier_called": False,
            "classifier_confidence": None,
            "orchestrator_called": False,
            "orchestrator_outcome": None,
            "grounded": True,
            "feature_flag_orch_enabled": True,
            "feature_flag_football_intelligence_enabled": False,
        },
        "tokens": {"total": 0},
    }


_controlled_ask_v2.calls = []  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _server_state(monkeypatch: pytest.MonkeyPatch):
    # _try_session_orchestration_response() only calls ask_v2() when
    # is_orch_enabled() is True (see its docstring) -- set explicitly so this
    # test doesn't depend on ambient env state left by other test files.
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    reset_quota()  # avoid cross-file quota-tracker pollution (a pre-existing
    # gap: no other test file resets it either, so a large combined run can
    # exhaust the free-tier daily cap before this test's own calls run)
    _controlled_ask_v2.calls.clear()  # type: ignore[attr-defined]
    yield
    fpl_server._sessions.clear()
    reset_quota()


@pytest.fixture
def client() -> TestClient:
    return TestClient(fpl_server.app)


def test_ask_and_session_ask_take_the_same_routing_path(client: TestClient):
    """Same question, same mocked ask_v2() branch -> same routing outcome
    through both endpoints, and both must have actually called ask_v2()
    (not a second, divergent pipeline)."""
    with patch("fpl_grounded_assistant.harness.ask_v2", side_effect=_controlled_ask_v2):
        ask_resp = client.post("/ask", json={"question": _INCIDENT_QUESTION})

        create_resp = client.post("/session")
        assert create_resp.status_code == 200
        session_id = create_resp.json()["session_id"]
        session_resp = client.post(
            f"/session/{session_id}/ask", json={"question": _INCIDENT_QUESTION}
        )

    assert ask_resp.status_code == 200
    assert session_resp.status_code == 200
    ask_body = ask_resp.json()
    session_body = session_resp.json()

    # --- Tool-selection mechanism parity: both endpoints reached ask_v2(),
    # each exactly once, with the identical (unrewritten -- no session state
    # to trigger a reference rewrite) question text. Before the fix, the
    # session endpoint never called ask_v2() at all for a "route"-branch
    # result -- it fell through to the legacy dispatcher pipeline instead.
    assert _controlled_ask_v2.calls == [_INCIDENT_QUESTION, _INCIDENT_QUESTION]  # type: ignore[attr-defined]

    # --- Synthesis-behaviour parity: identical rendered answer. This is the
    # direct regression pin -- before the fix, session_body["final_text"]
    # would NOT equal ask_body["final_text"] on this branch (it came from a
    # different pipeline that ignored the mock entirely).
    assert session_body["final_text"] == ask_body["final_text"] == _INCIDENT_ANSWER_TEXT

    # --- Same branch, same routing/synthesis semantics.
    for key in (
        "outcome",
        "intent",
        "supported",
        "llm_used",
        "review_passed",
        "route_source",
        "classifier_confidence",
        "route_conflict",
        "clarification_asked",
        "orch_outcome",
        "degraded",
    ):
        assert session_body[key] == ask_body[key], f"field {key!r} diverged between endpoints"

    assert ask_body["route_source"] == "deterministic"
    assert ask_body["llm_used"] is False
    assert ask_body["outcome"] == "ok"

    # --- Legitimate, session-only differences -- asserted explicitly, not
    # excluded from the comparison.
    assert "session_id" not in ask_body
    assert session_body["session_id"] == session_id
    # No prior session state existed, so reference resolution had nothing to
    # rewrite -- rewritten_question is only populated when the resolver
    # actually changed the text.
    assert session_body.get("rewritten_question") is None


def test_incident_question_never_surfaces_as_a_raw_gameweek_dump_via_session(
    client: TestClient,
):
    """Narrower regression pin at the literal bug-report marker: an answer
    beginning with "Jornada actual:" for a bench-boost evaluation question
    is the failure mode. With ask_v2() properly synthesising a real answer
    (not the raw "route"-branch tool dump used above), the session endpoint
    must surface that synthesis -- not silently re-derive its own text via
    the legacy pipeline."""
    synthesized_text = (
        "Para evaluar tu equipo necesito que me pases los 15 jugadores de tu plantilla."
    )

    def _controlled(question: str, bootstrap, *args, **kwargs) -> dict:
        return {
            "selected_tool": "get_gameweek_context",
            "tool_input": {},
            "raw_output": {"status": "ok"},
            "answer_text": synthesized_text,
            "outcome": "ok",
            "kind": "text",
            "routing_trace": {
                "branch": "orchestrator",
                "orchestrator_called": True,
                "orchestrator_outcome": "ok",
                "grounded": True,
            },
            "tokens": {"total": 250},
        }

    with patch("fpl_grounded_assistant.harness.ask_v2", side_effect=_controlled):
        create_resp = client.post("/session")
        session_id = create_resp.json()["session_id"]
        session_resp = client.post(
            f"/session/{session_id}/ask", json={"question": _INCIDENT_QUESTION}
        )

    assert session_resp.status_code == 200
    body = session_resp.json()
    assert not body["final_text"].startswith("Jornada actual:")
    assert body["final_text"] == synthesized_text

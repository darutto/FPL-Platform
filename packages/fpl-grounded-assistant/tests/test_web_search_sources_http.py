"""/ask over HTTP: snapshot + search_web in one turn must carry web_search sources (mocked only)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot
from fpl_grounded_assistant.orchestrator import OrchestratorResult

_BOOTSTRAP: list = []

RESULTS = [
    {"title": "Synthetic club update", "snippet": "s", "url": "https://example.test/a", "source": "example.test", "published": None},
    {"title": "", "snippet": "s", "url": "https://example.test/b", "source": "", "published": None},
]


def _orch() -> OrchestratorResult:
    snap_out = get_player_snapshot("Saka", _BOOTSTRAP[0])
    search_out = {"status": "ok", "results": RESULTS, "answer": None, "timestamp": "2026-11-20T10:00:00+00:00"}
    trace = (
        {"round": 1, "tool_call_id": "1", "name": "get_player_snapshot", "args": {"player_name": "Saka"},
         "output": snap_out, "success": True},
        {"round": 1, "tool_call_id": "2", "name": "search_web", "args": {"query": "Saka injury update"},
         "output": search_out, "success": True},
    )
    return OrchestratorResult(
        question="controlled", tool_chosen="get_player_snapshot", tool_args={"player_name": "Saka"},
        tool_output=snap_out, answer_text="FPL lo marca disponible.\nFuente web: https://example.test/a",
        llm_used=True, model="controlled", outcome="ok", synthesis_turn=True,
        tool_call_count=2, tool_calls_trace=trace,
    )


def test_ask_response_json_carries_sources_beside_the_snapshot(monkeypatch, bootstrap: dict):
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-key")  # reachability gate only; the orchestrator is mocked
    monkeypatch.setattr("fpl_grounded_assistant.harness._build_eval_client", lambda *a, **k: None)
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: _orch())
    _BOOTSTRAP[:] = [bootstrap]
    fpl_server._init_bootstrap(bootstrap)
    try:
        client = TestClient(fpl_server.app)
        r = client.post(
            "/ask",
            json={"question": "¿tiene lesión Saka?", "web_search_requested": True},
            headers={"X-User-Id": "ws-http", "X-User-Tier": "patreon_plus"},
        )
    finally:
        fpl_server._init_bootstrap(bootstrap)
    assert r.status_code == 200
    body = r.json()
    assert "http" not in body["final_text"]
    assert body["web_search"] is not None, {k: v for k, v in body.items() if k in ("outcome", "intent", "final_text")}
    assert body["intent"] == "player_snapshot" and body["player_snapshot"] is not None
    assert [x["url"] for x in body["web_search"]["results"]] == ["https://example.test/a", "https://example.test/b"]

"""Web-search sources next to other cards, URL-free prose, and the audit fields (mocked only)."""
from __future__ import annotations

import json

import pytest

import fpl_server
from fpl_grounded_assistant import audit
from fpl_grounded_assistant.harness import ask_v2
from fpl_grounded_assistant.harness_adapter import to_ask_response
from fpl_grounded_assistant.orchestrator import OrchestratorResult
from fpl_grounded_assistant.search_web import (
    strip_urls_from_prose,
    web_search_sources_from_trace,
)

RESULTS = [
    {"title": "Synthetic club update", "snippet": "s", "url": "https://example.test/a", "source": "example.test", "published": None},
    {"title": "Synthetic report", "snippet": "s", "url": "https://example.test/b", "source": "", "published": None},
]


def _trace(search_ok: bool = True) -> list[dict]:
    out = {"status": "ok", "results": RESULTS, "answer": None, "timestamp": "2026-11-20T10:00:00+00:00"}
    return [
        {"name": "get_player_snapshot", "args": {"player_name": "Saka"}, "output": {"status": "ok"}},
        {"name": "search_web", "args": {"query": "Saka injury update"}, "output": out if search_ok else {"status": "error"}},
    ]


# -- prose hygiene --------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Fuente web: https://example.test/a\nEl club dice que juega.", "El club dice que juega."),
        ("Per the club ([Synthetic update](https://example.test/a)) he is fit.", "Per the club (Synthetic update) he is fit."),
        ("He is fit. See https://example.test/a.", "He is fit. See"),
        ("Sources:\n- https://example.test/a\nHe is fit.", "He is fit."),
        ("No links here.", "No links here."),
    ],
)
def test_strip_urls_from_prose(text: str, expected: str):
    assert strip_urls_from_prose(text) == expected


def test_sources_come_from_the_trace_whatever_else_ran():
    got = web_search_sources_from_trace(_trace())
    assert got == {"topic": "Saka injury update", "results": RESULTS, "timestamp": "2026-11-20T10:00:00+00:00"}
    assert web_search_sources_from_trace(_trace(search_ok=False)) is None
    assert web_search_sources_from_trace([]) is None
    assert web_search_sources_from_trace(None) is None


# -- harness + adapter ------------------------------------------------------------

@pytest.fixture(autouse=True)
def _orch_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.harness._build_eval_client", lambda *a, **k: None)


def _orch(answer: str, trace: list[dict]) -> OrchestratorResult:
    return OrchestratorResult(
        question="controlled",
        tool_chosen="get_player_snapshot",
        tool_args={"player_name": "Saka"},
        tool_output={"status": "ok", "player": {"web_name": "Saka"}},
        answer_text=answer,
        llm_used=True,
        model="controlled",
        outcome="ok",
        synthesis_turn=True,
        tool_calls_trace=trace,
    )


def test_sources_reach_the_response_beside_the_snapshot_and_prose_has_no_url(monkeypatch, bootstrap: dict):
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *a, **k: _orch("FPL lo marca disponible.\nFuente web: https://example.test/a", _trace()),
    )
    d = ask_v2("¿tiene lesión Saka?", bootstrap, orch_client=object(), web_search_enabled=True)
    assert "http" not in d["answer_text"]
    response = to_ask_response(d, fpl_server.AskRequest(question="¿tiene lesión Saka?"), bootstrap)
    payload = response.web_search
    assert payload is not None
    assert [r["title"] for r in payload["results"]] == ["Synthetic club update", "Synthetic report"]
    assert payload["topic"] == "Saka injury update"
    assert "http" not in response.final_text


def test_no_search_no_sources(monkeypatch, bootstrap: dict):
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *a, **k: _orch("FPL lo marca disponible.", [_trace()[0]]),
    )
    d = ask_v2("¿tiene lesión Saka?", bootstrap, orch_client=object())
    assert d.get("web_search_sources") is None


# -- audit ------------------------------------------------------------------------

def test_audit_line_carries_the_web_search_fields(tmp_path):
    entry = audit.make_audit_entry(
        question="q", branch="orchestrator", outcome="ok",
        web_search_enabled=True, search_web_ran=False, player_lookup_diverted="availability_intent",
    )
    audit.write_audit_entry(entry, log_dir=str(tmp_path))
    files = list(tmp_path.glob("*.ndjson")) or list(tmp_path.glob("*"))
    row = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
    assert row["web_search_enabled"] is True
    assert row["search_web_ran"] is False
    assert row["player_lookup_diverted"] == "availability_intent"
    assert entry.web_search_enabled is True and entry.search_web_ran is False


def test_audit_line_without_the_fields_is_unchanged():
    entry = audit.make_audit_entry(question="q", branch="route", outcome="ok")
    assert entry.web_search_enabled is None and entry.player_lookup_diverted is None

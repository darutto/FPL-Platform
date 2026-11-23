"""POST /eo/poll and the ``pending`` marker: the deterministic retry of a computing EO answer.

No network and no model: the tool functions are replaced by fakes and the provider boundary raises if touched.
Synthetic data only.
"""
from __future__ import annotations

import os
import sys

import pytest

_PKGS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (os.path.join(_PKGS, "fpl-grounded-assistant"), os.path.join(_PKGS, "fpl-tool-runner"),
           os.path.join(_PKGS, "fpl-player-registry")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi.testclient import TestClient  # noqa: E402

import fpl_server  # noqa: E402
from fpl_grounded_assistant import eo_poll  # noqa: E402


@pytest.fixture(autouse=True)
def _no_model(monkeypatch):
    """Any orchestrator / provider call from the poll path is a failure."""
    import fpl_grounded_assistant.orchestrator as orch

    def boom(*a, **k):
        raise AssertionError("the poll path must not reach the model")

    for name in ("run_orchestrator", "ask_orchestrated"):
        if hasattr(orch, name):
            monkeypatch.setattr(orch, name, boom)
    monkeypatch.setattr(fpl_server, "_EO_POLL_GATE", eo_poll.RateGate(2.0))
    monkeypatch.delenv("FPL_INTERNAL_TOKEN", raising=False)


def _stats(owned, eo, cap=0.0):
    return {"owned_pct": owned, "captain_pct": cap, "bench_pct": 0.0, "eo": eo}


def _ready_output():
    """A real ``ok`` near-rank result (synthetic players), so the real composer builds the card."""
    from fpl_grounded_assistant import near_rank_eo_tool as tool

    boot = {"teams": [{"id": t, "short_name": f"T{t}"} for t in range(1, 5)],
            "elements": [{"id": i, "web_name": f"P{i}", "second_name": f"S{i}", "team": (i % 4) + 1} for i in range(1, 21)]}
    data = {"gw": 12, "user_rank": 1000, "n_sampled": 100, "players": {"1": _stats(90.0, 95.0), "2": _stats(80.0, 140.0, 50.0)}}
    return tool.shape_result(data, boot, [], {"status": "ok", "players": [{"id": 5}]})


CARD_OK = _ready_output()


def _client(monkeypatch, tool_result, calls):
    def fake_near(boot, **k):
        calls.append(("near", boot.get("_my_team_id")))
        return tool_result

    def fake_league(boot, **k):
        calls.append(("league", boot.get("_my_team_id"), boot.get("_my_league_id")))
        return tool_result

    monkeypatch.setattr("fpl_grounded_assistant.near_rank_eo_tool.get_near_rank_eo", fake_near)
    monkeypatch.setattr("fpl_grounded_assistant.league_eo_tool.get_league_eo", fake_league)
    monkeypatch.setattr(fpl_server, "_bootstrap", {"events": []})
    return TestClient(fpl_server.app)


H = {"X-User-Id": "user_abc"}


def test_marker_for_the_two_tools_only():
    assert eo_poll.pending_marker("get_near_rank_eo", {"status": "computing", "eta_s": 25}) == {
        "tool": "get_near_rank_eo", "eta_s": 25, "poll_s": 4, "max_s": 60}
    m = eo_poll.pending_marker("get_league_eo", {"status": "computing", "eta_s": 25, "league_id": 77})
    assert m["league_id"] == 77 and m["tool"] == "get_league_eo"
    assert eo_poll.pending_marker("get_league_eo", {"status": "computing", "eta_s": 25, "league_id": None}) is None
    assert eo_poll.pending_marker("get_tier_eo", {"status": "computing"}) is None
    assert eo_poll.pending_marker("get_near_rank_eo", {"status": "ok"}) is None


def test_anonymous_is_401_and_starts_no_job(monkeypatch):
    calls = []
    c = _client(monkeypatch, {"status": "computing", "eta_s": 20}, calls)
    body = {"tool": "get_near_rank_eo", "team_id": 5}
    assert c.post("/eo/poll", json=body).status_code == 401
    assert c.post("/eo/poll", json=body, headers={"X-User-Id": "anonymous"}).status_code == 401
    assert calls == []


def test_internal_token_is_required_when_configured(monkeypatch):
    monkeypatch.setenv("FPL_INTERNAL_TOKEN", "s3cret")
    calls = []
    c = _client(monkeypatch, {"status": "computing", "eta_s": 20}, calls)
    body = {"tool": "get_near_rank_eo", "team_id": 5}
    assert c.post("/eo/poll", json=body, headers=H).status_code == 401
    assert c.post("/eo/poll", json=body, headers={**H, "X-Internal-Token": "wrong"}).status_code == 401
    assert calls == []
    assert c.post("/eo/poll", json=body, headers={**H, "X-Internal-Token": "s3cret"}).status_code == 200


def test_rate_limit_is_429_and_starts_no_second_job(monkeypatch):
    calls = []
    c = _client(monkeypatch, {"status": "computing", "eta_s": 20}, calls)
    body = {"tool": "get_near_rank_eo", "team_id": 5}
    assert c.post("/eo/poll", json=body, headers=H).status_code == 200
    assert c.post("/eo/poll", json=body, headers=H).status_code == 429
    assert len(calls) == 1
    # another user is not throttled by the first
    assert c.post("/eo/poll", json=body, headers={"X-User-Id": "user_other"}).status_code == 200


@pytest.mark.parametrize("body", [
    {"tool": "get_my_squad", "team_id": 5},
    {"tool": "get_near_rank_eo", "team_id": "5"},
    {"tool": "get_near_rank_eo", "team_id": 0},
    {"tool": "get_near_rank_eo", "team_id": 5, "league_id": -1},
    {"tool": "get_near_rank_eo", "team_id": 10 ** 12},
    {"tool": "get_near_rank_eo", "team_id": 5, "extra": 1},
])
def test_only_validated_ints_and_two_tools(monkeypatch, body):
    calls = []
    c = _client(monkeypatch, {"status": "computing", "eta_s": 20}, calls)
    assert c.post("/eo/poll", json=body, headers=H).status_code == 422
    assert calls == []


def test_computing_then_ready_with_card_text_and_chips(monkeypatch):
    calls = []
    c = _client(monkeypatch, {"status": "computing", "eta_s": 20}, calls)
    r = c.post("/eo/poll", json={"tool": "get_near_rank_eo", "team_id": 5}, headers=H).json()
    assert r == {"status": "computing", "eta_s": 20, "poll_s": 4}
    monkeypatch.setattr(fpl_server, "_EO_POLL_GATE", eo_poll.RateGate(2.0))
    c = _client(monkeypatch, CARD_OK, calls)
    r = c.post("/eo/poll", json={"tool": "get_near_rank_eo", "team_id": 5, "locale": "en"}, headers=H).json()
    assert r["status"] == "ready"
    assert r["text"].startswith("Ready: ") and "GW 12" in r["text"]
    assert r["generic_card"]["title"]
    assert "badge_tones" in r["generic_card"]


def test_league_id_reaches_the_tool_and_a_picker_is_unavailable(monkeypatch):
    calls = []
    c = _client(monkeypatch, {"status": "ok", "stage": "needs_league", "leagues": []}, calls)
    r = c.post("/eo/poll", json={"tool": "get_league_eo", "team_id": 5, "league_id": 77}, headers=H).json()
    assert calls == [("league", 5, 77)]
    assert r["status"] == "unavailable" and r["reason"] == "needs_league"


def test_disabled_flag_is_reported(monkeypatch):
    calls = []
    c = _client(monkeypatch, {"status": "disabled", "code": "x"}, calls)
    assert c.post("/eo/poll", json={"tool": "get_near_rank_eo", "team_id": 5}, headers=H).json() == {"status": "disabled"}


# -- the marker through the harness and the /ask wire --------------------------------------------------------------

def _orch(tool_name, raw, outcome="ok"):
    from fpl_grounded_assistant.orchestrator import OrchestratorResult

    trace = ({"round": 1, "tool_call_id": "1", "name": tool_name, "args": {}, "output": raw, "success": True},)
    return OrchestratorResult(question="q", tool_chosen=tool_name, tool_args={}, tool_output=raw,
                              answer_text="Se esta calculando; pregunta de nuevo en unos segundos.", llm_used=True,
                              model="controlled", outcome=outcome, synthesis_turn=True, tool_call_count=1,
                              tool_calls_trace=trace)


@pytest.mark.parametrize("tool_name,raw,expected", [
    ("get_near_rank_eo", {"status": "computing", "tier": "near", "eta_s": 30},
     {"tool": "get_near_rank_eo", "eta_s": 30, "poll_s": 4, "max_s": 60}),
    ("get_league_eo", {"status": "computing", "tier": "league", "eta_s": 30, "league_id": 9},
     {"tool": "get_league_eo", "league_id": 9, "eta_s": 30, "poll_s": 4, "max_s": 60}),
])
def test_a_computing_turn_carries_pending_and_keeps_the_model_text(monkeypatch, tool_name, raw, expected):
    from fpl_grounded_assistant import harness
    from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP

    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.harness._build_eval_client", lambda *a, **k: None)
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: _orch(tool_name, raw))
    d = harness.ask_v2("EO de mi liga", dict(STANDARD_BOOTSTRAP), orch_client=object(), team_id=555, locale="es")
    assert d["pending"] == expected
    assert "pregunta de nuevo" in d["answer_text"]  # clients that do not poll keep the existing text


@pytest.mark.parametrize("tool_name,raw,expected", [
    ("get_near_rank_eo", {"status": "computing", "tier": "near", "eta_s": 30},
     {"tool": "get_near_rank_eo", "eta_s": 30, "poll_s": 4, "max_s": 60}),
    ("get_league_eo", {"status": "computing", "tier": "league", "eta_s": 30, "league_id": 9},
     {"tool": "get_league_eo", "league_id": 9, "eta_s": 30, "poll_s": 4, "max_s": 60}),
])
def test_the_real_computing_outcome_carries_pending(monkeypatch, tool_name, raw, expected):
    """A computing result is not ok: the orchestrator reports tool_result_error and the turn takes the
    'no grounded tool' branch, which is where the marker must be attached too (it was not)."""
    from fpl_grounded_assistant import harness
    from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP

    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.harness._build_eval_client", lambda *a, **k: None)
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated",
                        lambda *a, **k: _orch(tool_name, raw, outcome="tool_result_error"))
    d = harness.ask_v2("EO de mi liga", dict(STANDARD_BOOTSTRAP), orch_client=object(), team_id=555, locale="es")
    assert d["routing_trace"]["branch"] == "unsupported"
    assert d["pending"] == expected


def test_the_marker_is_read_from_the_last_poll_tool_call_in_a_multi_call_trace(monkeypatch):
    from fpl_grounded_assistant import harness
    from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP

    base = _orch("get_league_eo", {"status": "computing", "league_id": 9, "eta_s": 30}, outcome="tool_result_error")
    trace = (
        {"round": 1, "tool_call_id": "1", "name": "get_my_squad", "args": {}, "output": {"status": "ok"}, "success": True},
        {"round": 1, "tool_call_id": "2", "name": "get_league_eo", "args": {},
         "output": {"status": "computing", "tier": "league", "eta_s": 30, "league_id": 9}, "success": False},
    )
    import dataclasses

    orch = dataclasses.replace(base, tool_calls_trace=trace, tool_call_count=2)
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.harness._build_eval_client", lambda *a, **k: None)
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: orch)
    d = harness.ask_v2("EO de mi liga", dict(STANDARD_BOOTSTRAP), orch_client=object(), team_id=555, locale="es")
    assert d["pending"] == {"tool": "get_league_eo", "league_id": 9, "eta_s": 30, "poll_s": 4, "max_s": 60}


def test_a_failed_tool_without_computing_has_no_pending(monkeypatch):
    from fpl_grounded_assistant import harness
    from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP

    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.harness._build_eval_client", lambda *a, **k: None)
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated",
                        lambda *a, **k: _orch("get_league_eo", {"status": "no_team_connected"}, outcome="tool_result_error"))
    d = harness.ask_v2("EO de mi liga", dict(STANDARD_BOOTSTRAP), orch_client=object(), team_id=555, locale="es")
    assert "pending" not in d


def test_a_ready_turn_has_no_pending(monkeypatch):
    from fpl_grounded_assistant import harness
    from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP

    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.harness._build_eval_client", lambda *a, **k: None)
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated",
                        lambda *a, **k: _orch("get_near_rank_eo", CARD_OK))
    d = harness.ask_v2("EO cerca de mi puesto", dict(STANDARD_BOOTSTRAP), orch_client=object(), team_id=555, locale="es")
    assert "pending" not in d


def test_pending_reaches_the_ask_wire_and_is_null_otherwise():
    from fpl_grounded_assistant.harness_adapter import to_ask_response

    base = {"answer_text": "x", "selected_tool": "get_near_rank_eo", "outcome": "ok", "kind": "text",
            "routing_trace": {"branch": "orchestrator", "grounded": True, "orchestrator_outcome": "ok"}}
    marker = {"tool": "get_near_rank_eo", "eta_s": 30, "poll_s": 4, "max_s": 60}
    req = fpl_server.AskRequest(question="q")
    assert to_ask_response({**base, "pending": marker}, req).model_dump()["pending"] == marker
    assert to_ask_response(base, req).model_dump()["pending"] is None

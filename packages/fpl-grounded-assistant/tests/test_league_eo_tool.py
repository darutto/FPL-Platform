"""get_league_eo: flag, session inputs, picker, non-blocking, and the league_id / main_league_id plumbing
(synthetic data, no network, no LLM)."""
from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant import harness
from fpl_grounded_assistant import league_eo as core
from fpl_grounded_assistant import league_eo_tool as tool
from fpl_grounded_assistant import near_rank_eo as ne
from fpl_grounded_assistant import orchestrator
from fpl_grounded_assistant.harness import ask_v2
from fpl_grounded_assistant.orch_config import LEAGUE_EO_ENABLED_ENV, is_league_eo_enabled
from fpl_grounded_assistant.orchestrator import OrchestratorResult
from fpl_grounded_assistant.tool_schema_registry import LEAGUE_EO_SCHEMA, TOOL_NAMES, get_offered_tool_names
from fpl_tool_runner import TOOL_REGISTRY

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
BOOT = {
    "events": [
        {"id": 1, "deadline_time": "2026-08-14T17:30:00Z"},
        {"id": 11, "deadline_time": "2026-11-20T10:00:00Z"},
        {"id": 12, "deadline_time": "2026-11-28T10:00:00Z"},
    ],
    "teams": [{"id": 1, "short_name": "AAA"}, {"id": 2, "short_name": "BBB"}],
    "elements": [
        {"id": 1, "web_name": "Alpha", "second_name": "Alphason", "team": 1},
        {"id": 2, "web_name": "Beta", "second_name": "Betason", "team": 2},
    ],
}
DATA = {
    "gw": 11, "league_id": 42, "league_name": "Friends", "league_size": 12, "exact": True, "approx": False,
    "n_sampled": 12, "label": "exact, n=12",
    "players": {
        "1": {"owned_pct": 90.0, "captain_pct": 50.0, "bench_pct": 0.0, "eo": 140.0},
        "2": {"owned_pct": 20.0, "captain_pct": 0.0, "bench_pct": 5.0, "eo": 20.0},
    },
}
L1 = {"id": 42, "name": "Friends", "size": 12}
L2 = {"id": 77, "name": "Work Mates", "size": 48}


class FakeService:
    """Answers per (league_id, league_name) like the real one; records every call."""

    def __init__(self, leagues, results=None):
        self.leagues, self.results, self.calls = leagues, results or {}, []

    def status(self, season, gw, entry_id, league_id=None, *, league_name=None, valid_until=None):
        self.calls.append({"season": season, "gw": gw, "entry": entry_id, "league_id": league_id,
                           "league_name": league_name, "valid_until": valid_until})
        if league_id is None and not league_name:
            return {"status": "ready", "data": {"leagues": self.leagues}}
        league, why = core.resolve_league(self.leagues, league_id, league_name)
        if league is None:
            return {"status": "unavailable", "reason": why}
        return self.results.get(league["id"], {"status": "computing", "eta_s": 30})


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv(LEAGUE_EO_ENABLED_ENV, raising=False)
    # the ready path loads the user's squad from the FPL API: no test may reach the network for it
    monkeypatch.setattr(tool, "load_linked_squad", lambda bootstrap, gw: None)
    tool.set_service(None)
    yield
    tool.set_service(None)


def on(monkeypatch):
    monkeypatch.setenv(LEAGUE_EO_ENABLED_ENV, "1")


def boot(team=555, league=None):
    out = dict(BOOT)
    if team:
        out["_my_team_id"] = team
    if league:
        out["_my_league_id"] = league
    return out


# -- flag ---------------------------------------------------------------------------------------

def test_flag_default_off_and_the_tool_is_not_offered():
    assert is_league_eo_enabled() is False
    assert "get_league_eo" not in get_offered_tool_names(False)
    assert "get_league_eo" not in TOOL_NAMES
    assert "get_league_eo" not in str(orchestrator._build_tools(None, football_intelligence_enabled=False))


def test_flag_on_offers_the_tool_in_every_provider_format(monkeypatch):
    on(monkeypatch)
    assert "get_league_eo" in get_offered_tool_names(False, league_eo_enabled=True)
    for provider in (None, "openai", "gemini"):
        assert "get_league_eo" in str(orchestrator._build_tools(provider, football_intelligence_enabled=False))
    assert TOOL_REGISTRY.get_spec("get_league_eo") is not None and LEAGUE_EO_SCHEMA.name == "get_league_eo"


def test_the_two_eo_flags_are_independent(monkeypatch):
    on(monkeypatch)
    text = str(orchestrator._build_tools(None, football_intelligence_enabled=False))
    assert "get_near_rank_eo" not in text


def test_a_direct_call_with_the_flag_off_is_disabled_and_starts_nothing():
    svc = FakeService([L1])
    tool.set_service(svc)
    assert tool.get_league_eo(boot(), now=NOW) == {"status": "disabled", "code": "league_eo_disabled"}
    assert svc.calls == []


# -- session inputs ---------------------------------------------------------------------------------

def test_no_team_means_no_team_connected(monkeypatch):
    on(monkeypatch)
    svc = FakeService([L1])
    tool.set_service(svc)
    assert tool.get_league_eo(boot(team=None), now=NOW)["status"] == "no_team_connected"
    assert svc.calls == []


def test_the_stored_league_id_and_gw_and_valid_until_reach_the_service(monkeypatch):
    on(monkeypatch)
    svc = FakeService([L1, L2])
    tool.set_service(svc)
    tool.get_league_eo(boot(league=77), now=NOW)
    call = svc.calls[0]
    assert (call["season"], call["gw"], call["entry"], call["league_id"], call["league_name"]) == ("2026-2027", 11, 555, 77, None)
    assert call["valid_until"] == datetime(2026, 11, 28, 10, tzinfo=timezone.utc).timestamp()


def test_a_league_name_wins_over_the_stored_id(monkeypatch):
    on(monkeypatch)
    svc = FakeService([L1, L2], {42: {"status": "ready", "data": DATA}})
    tool.set_service(svc)
    out = tool.get_league_eo(boot(league=77), league_name="friends", now=NOW)
    assert out["status"] == "ok" and out["league_id"] == 42
    assert svc.calls[0]["league_name"] == "friends"


# -- picker --------------------------------------------------------------------------------------------

def test_several_leagues_and_no_choice_asks_which(monkeypatch):
    on(monkeypatch)
    tool.set_service(FakeService([L1, L2]))
    out = tool.get_league_eo(boot(), now=NOW)
    assert out["status"] == "ok" and out["stage"] == "needs_league"
    assert out["leagues"] == [{"league_id": 42, "name": "Friends", "size": 12},
                              {"league_id": 77, "name": "Work Mates", "size": 48}]


def test_exactly_one_league_is_used_without_asking(monkeypatch):
    on(monkeypatch)
    svc = FakeService([L1], {42: {"status": "ready", "data": DATA}})
    tool.set_service(svc)
    out = tool.get_league_eo(boot(), now=NOW)
    assert out["status"] == "ok" and out["league_id"] == 42
    assert [c["league_id"] for c in svc.calls] == [None, 42]


def test_no_private_league_says_so(monkeypatch):
    on(monkeypatch)
    tool.set_service(FakeService([]))
    assert tool.get_league_eo(boot(), now=NOW) == {"status": "no_league", "code": "no_private_league"}


def test_a_stale_stored_league_falls_back_to_the_picker(monkeypatch):
    on(monkeypatch)
    tool.set_service(FakeService([L1, L2]))
    assert tool.get_league_eo(boot(league=999), now=NOW)["stage"] == "needs_league"


def test_an_unknown_or_ambiguous_name_is_reported_not_guessed(monkeypatch):
    on(monkeypatch)
    tool.set_service(FakeService([{"id": 1, "name": "Mates A", "size": 9}, {"id": 2, "name": "Mates B", "size": 9}]))
    assert tool.get_league_eo(boot(), league_name="mates", now=NOW) == {"status": "unavailable", "reason": "league_ambiguous"}
    assert tool.get_league_eo(boot(), league_name="nope", now=NOW) == {"status": "unavailable", "reason": "league_not_found"}


# -- statuses and shaping ----------------------------------------------------------------------------

def test_computing_unavailable_and_service_errors(monkeypatch):
    on(monkeypatch)
    tool.set_service(FakeService([L1]))
    out = tool.get_league_eo(boot(league=42), now=NOW)
    assert out["status"] == "computing" and out["eta_s"] == 30 and "do not guess" in out["message"]
    tool.set_service(FakeService([L1], {42: {"status": "unavailable", "reason": "league_too_large"}}))
    assert tool.get_league_eo(boot(league=42), now=NOW) == {"status": "unavailable", "reason": "league_too_large"}

    class Boom:
        def status(self, *a, **k):
            raise RuntimeError("synthetic")

    tool.set_service(Boom())
    assert tool.get_league_eo(boot(league=42), now=NOW) == {"status": "unavailable", "reason": "error"}


def test_ready_result_has_the_label_and_the_named_players(monkeypatch):
    on(monkeypatch)
    tool.set_service(FakeService([L1], {42: {"status": "ready", "data": DATA}}))
    out = tool.get_league_eo(boot(league=42), player_names=["beta", "Nobody"], now=NOW)
    assert out["status"] == "ok" and out["label"] == "exact, n=12" and out["league_name"] == "Friends"
    assert [r["player"] for r in out["top_players"]] == ["Alpha", "Beta"]
    assert out["top_players"][0] == {"player": "Alpha", "team": "AAA", "eo": 140.0, "owned_pct": 90.0, "captain_pct": 50.0}
    assert [r["player"] for r in out["named_players"]] == ["Beta"]


def test_handler_through_the_registry_never_blocks(monkeypatch):
    on(monkeypatch)
    gate = threading.Event()  # never set during the call: a blocking tool would hang here

    def hang(url):
        gate.wait(30)
        return 500, None, {}

    tool.set_service(core.LeagueEOService(hang, limiter=ne.RateLimiter(0.0, sleep=lambda s: None),
                                          sleep=lambda s: None, workers=1))
    result = tool._handler({"league_name": "  ", "player_names": ["Alpha"]}, boot())
    assert result["status"] == "computing"
    gate.set()


# -- league_id plumbing: request -> harness -> bootstrap ---------------------------------------------------

def test_ask_v2_injects_the_league_id_on_a_copy_and_leaves_the_shared_bootstrap_alone(monkeypatch, bootstrap: dict):
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.harness._build_eval_client", lambda *a, **k: None)
    seen: list[dict] = []

    def capture(*a, **k):
        seen.append(k.get("bootstrap") if "bootstrap" in k else a[1])
        return OrchestratorResult(question="q", tool_chosen=None, tool_args={}, tool_output=None,
                                  answer_text="ok", llm_used=True, model="controlled", outcome="ok")

    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", capture)
    ask_v2("hola equipo", bootstrap, orch_client=object(), team_id=555, league_id=4242)
    assert seen[-1]["_my_league_id"] == 4242 and seen[-1]["_my_team_id"] == 555
    assert "_my_league_id" not in bootstrap and "_my_team_id" not in bootstrap  # the shared dict is untouched
    ask_v2("hola equipo", bootstrap, orch_client=object(), team_id=555)
    assert "_my_league_id" not in seen[-1]  # no league, no key


def test_ask_request_takes_main_league_id_as_a_strict_int():
    assert fpl_server.AskRequest(question="x", main_league_id=77).main_league_id == 77
    assert fpl_server.AskRequest(question="x").main_league_id is None
    with pytest.raises(Exception):
        fpl_server.AskRequest(question="x", main_league_id="77")


def test_ask_over_http_passes_main_league_id_to_ask_v2(monkeypatch, bootstrap: dict):
    captured: dict = {}
    real = harness.ask_v2

    def spy(*a, **k):
        captured.update(k)
        return real(*a, **k)

    monkeypatch.setattr(harness, "ask_v2", spy)  # fpl_server imports it inside the handler
    fpl_server._init_bootstrap(bootstrap)
    try:
        r = TestClient(fpl_server.app).post(
            "/ask", json={"question": "hola", "team_id": 555, "main_league_id": 4242},
            headers={"X-User-Id": "league-http", "X-User-Tier": "patreon_plus"})
    finally:
        fpl_server._init_bootstrap(bootstrap)
    assert r.status_code == 200
    assert captured["league_id"] == 4242 and captured["team_id"] == 555

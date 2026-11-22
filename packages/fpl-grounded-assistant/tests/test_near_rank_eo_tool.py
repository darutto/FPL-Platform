"""get_near_rank_eo tool: flag, team id, non-blocking status, shaping (synthetic data, no network)."""
from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from fpl_grounded_assistant import near_rank_eo as core
from fpl_grounded_assistant import near_rank_eo_tool as tool
from fpl_grounded_assistant import orchestrator
from fpl_grounded_assistant.orch_config import NEAR_RANK_EO_ENABLED_ENV, is_near_rank_eo_enabled
from fpl_grounded_assistant.tool_schema_registry import (
    NEAR_RANK_EO_SCHEMA,
    TOOL_NAMES,
    get_offered_tool_names,
)
from fpl_tool_runner import TOOL_REGISTRY

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
BOOT = {
    "events": [
        {"id": 1, "deadline_time": "2026-08-14T17:30:00Z"},
        {"id": 11, "deadline_time": "2026-11-20T10:00:00Z"},
        {"id": 12, "deadline_time": "2026-11-28T10:00:00Z"},
        {"id": 13, "deadline_time": "2026-12-05T10:00:00Z"},
    ],
    "teams": [{"id": 1, "short_name": "AAA"}, {"id": 2, "short_name": "BBB"}],
    "elements": [
        {"id": 1, "web_name": "Alpha", "second_name": "Alphason", "team": 1},
        {"id": 2, "web_name": "Beta", "second_name": "Betason", "team": 2},
        {"id": 3, "web_name": "Gamma", "second_name": "Gammason", "team": 1},
    ],
}
DATA = {
    "gw": 11, "user_rank": 1234, "n_sampled": 125,
    "players": {
        "1": {"owned_pct": 80.0, "captain_pct": 50.0, "bench_pct": 0.0, "eo": 130.0},
        "2": {"owned_pct": 40.0, "captain_pct": 0.0, "bench_pct": 5.0, "eo": 40.0},
        "3": {"owned_pct": 10.0, "captain_pct": 0.0, "bench_pct": 1.0, "eo": 10.0},
    },
}


class FakeService:
    def __init__(self, result):
        self.result, self.calls = result, []

    def status(self, season, gw, entry_id, *, valid_until=None):
        self.calls.append((season, gw, entry_id, valid_until))
        return self.result


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv(NEAR_RANK_EO_ENABLED_ENV, raising=False)
    # the ready path loads the user's squad from the FPL API: no test may reach the network for it
    monkeypatch.setattr(tool, "load_linked_squad", lambda bootstrap, gw: None)
    tool.set_service(None)
    yield
    tool.set_service(None)


def on(monkeypatch):
    monkeypatch.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")


def boot(team=555):
    return {**BOOT, "_my_team_id": team} if team else dict(BOOT)


# -- flag -----------------------------------------------------------------------------------

def test_flag_default_is_off_and_the_tool_is_not_offered(monkeypatch):
    assert is_near_rank_eo_enabled() is False
    assert "get_near_rank_eo" not in get_offered_tool_names(False)
    assert "get_near_rank_eo" not in TOOL_NAMES  # the base registry is unchanged
    names = [t["name"] for t in orchestrator._build_tools(None, football_intelligence_enabled=False)]
    assert "get_near_rank_eo" not in names


def test_flag_on_offers_the_tool_everywhere_it_must_be(monkeypatch):
    on(monkeypatch)
    assert "get_near_rank_eo" in get_offered_tool_names(False, near_rank_eo_enabled=True)
    for provider in (None, "openai", "gemini"):
        payload = orchestrator._build_tools(provider, football_intelligence_enabled=False)
        flat = str(payload)
        assert "get_near_rank_eo" in flat
    assert TOOL_REGISTRY.get_spec("get_near_rank_eo") is not None
    assert NEAR_RANK_EO_SCHEMA.name == "get_near_rank_eo"


def test_a_direct_call_with_the_flag_off_is_disabled_and_starts_nothing():
    svc = FakeService({"status": "computing", "eta_s": 30})
    tool.set_service(svc)
    assert tool.get_near_rank_eo(boot(), now=NOW) == {"status": "disabled", "code": "near_rank_eo_disabled"}
    assert svc.calls == []


# -- team id and gameweek ---------------------------------------------------------------------

def test_no_team_means_no_team_connected_and_no_job(monkeypatch):
    on(monkeypatch)
    svc = FakeService({"status": "computing", "eta_s": 30})
    tool.set_service(svc)
    assert tool.get_near_rank_eo(boot(team=None), now=NOW)["status"] == "no_team_connected"
    assert svc.calls == []


def test_gw_is_the_latest_passed_deadline_and_valid_until_is_the_next_one():
    gw, valid_until = tool.gw_and_valid_until(BOOT["events"], NOW)
    assert gw == 11
    assert valid_until == datetime(2026, 11, 28, 10, tzinfo=timezone.utc).timestamp()
    assert tool.gw_and_valid_until([], NOW) == (None, None)
    assert tool.gw_and_valid_until([{"id": 1, "deadline_time": "2027-01-01T00:00:00Z"}], NOW)[0] is None


def test_the_service_gets_season_gw_team_and_valid_until(monkeypatch):
    on(monkeypatch)
    svc = FakeService({"status": "computing", "eta_s": 30})
    tool.set_service(svc)
    tool.get_near_rank_eo(boot(), now=NOW)
    season, gw, team, valid_until = svc.calls[0]
    assert (season, gw, team) == ("2026-2027", 11, 555)
    assert valid_until == datetime(2026, 11, 28, 10, tzinfo=timezone.utc).timestamp()


def test_no_passed_deadline_is_unavailable(monkeypatch):
    on(monkeypatch)
    tool.set_service(FakeService({"status": "computing", "eta_s": 30}))
    early = datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert tool.get_near_rank_eo(boot(), now=early) == {"status": "unavailable", "reason": "no_gameweek"}


# -- statuses -------------------------------------------------------------------------------------

def test_computing_tells_the_model_not_to_guess(monkeypatch):
    on(monkeypatch)
    tool.set_service(FakeService({"status": "computing", "eta_s": 30}))
    out = tool.get_near_rank_eo(boot(), now=NOW)
    assert out["status"] == "computing" and out["eta_s"] == 30
    assert "do not guess" in out["message"]


def test_unavailable_reason_passes_through_and_a_service_error_never_raises(monkeypatch):
    on(monkeypatch)
    tool.set_service(FakeService({"status": "unavailable", "reason": "no_rank"}))
    assert tool.get_near_rank_eo(boot(), now=NOW) == {"status": "unavailable", "reason": "no_rank"}

    class Boom:
        def status(self, *a, **k):
            raise RuntimeError("synthetic")

    tool.set_service(Boom())
    assert tool.get_near_rank_eo(boot(), now=NOW) == {"status": "unavailable", "reason": "error"}


def test_ready_returns_top_players_and_the_named_ones(monkeypatch):
    on(monkeypatch)
    tool.set_service(FakeService({"status": "ready", "data": DATA}))
    out = tool.get_near_rank_eo(boot(), player_names=["gamma", "Nobody"], now=NOW)
    assert out["status"] == "ok" and out["approx"] is True and out["label"] == "approx., n=125"
    assert [r["player"] for r in out["top_players"]] == ["Alpha", "Beta", "Gamma"]
    assert out["top_players"][0] == {"player": "Alpha", "team": "AAA", "eo": 130.0, "owned_pct": 80.0, "captain_pct": 50.0,
                                     "user_owns": None}  # no squad in this test
    assert [r["player"] for r in out["named_players"]] == ["Gamma"]
    assert out["user_rank"] == 1234 and "entry" not in str(out)


def test_top_list_is_capped(monkeypatch):
    on(monkeypatch)
    many = {str(i): {"owned_pct": 1.0, "captain_pct": 0.0, "bench_pct": 0.0, "eo": float(i)} for i in range(1, 60)}
    out = tool.shape_result({**DATA, "players": many}, BOOT, [])
    assert len(out["top_players"]) == tool.TOP_N and out["top_players"][0]["eo"] == 59.0


# -- the tool runner and never blocking ---------------------------------------------------------

def test_handler_runs_through_the_tool_registry_and_never_blocks(monkeypatch):
    on(monkeypatch)
    gate = threading.Event()  # never set: the FPL fetch would hang forever if anyone waited for it

    def hang(url):
        gate.wait(30)
        return 500, None, {}

    tool.set_service(core.NearRankEOService(hang, limiter=core.RateLimiter(0.0, sleep=lambda s: None),
                                            sleep=lambda s: None, workers=1))
    spec = TOOL_REGISTRY.get_spec("get_near_rank_eo")
    handler = TOOL_REGISTRY.get_handler("get_near_rank_eo") if hasattr(TOOL_REGISTRY, "get_handler") else None
    result = (handler or tool._handler)({"player_names": ["Alpha"]}, boot())
    assert result["status"] == "computing"  # returned at once, the job is still hanging in the background
    assert spec.output_schema["properties"]["status"] == {"type": "string"}
    gate.set()

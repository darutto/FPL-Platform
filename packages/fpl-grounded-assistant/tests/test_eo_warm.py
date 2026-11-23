"""EO precompute (eo_warm), POST /eo/warm and the turn hook. No network, no model; synthetic data only.

Real NearRankEOService / LeagueEOService objects are used with an executor that only RECORDS submitted jobs, so
single-flight, the caps and the started counter are the production ones and nothing ever runs.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

_PKGS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (os.path.join(_PKGS, "fpl-grounded-assistant"), os.path.join(_PKGS, "fpl-tool-runner"),
           os.path.join(_PKGS, "fpl-player-registry")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi.testclient import TestClient  # noqa: E402

import fpl_server  # noqa: E402
from fpl_grounded_assistant import eo_poll, eo_warm, league_eo_tool, near_rank_eo_tool  # noqa: E402
from fpl_grounded_assistant.league_eo import LeagueEOService  # noqa: E402
from fpl_grounded_assistant.near_rank_eo import NearRankEOService  # noqa: E402
from fpl_grounded_assistant.orch_config import LEAGUE_EO_ENABLED_ENV, NEAR_RANK_EO_ENABLED_ENV  # noqa: E402

EVENTS = [{"id": 1, "deadline_time": "2026-08-14T17:30:00Z"},
          {"id": 11, "deadline_time": "2026-11-20T10:00:00Z"},
          {"id": 12, "deadline_time": "2026-12-05T10:00:00Z"}]
BOOT = {"events": EVENTS}
NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


class Recorder:
    """An executor that records what would run and never runs it."""

    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        self.jobs.append(args[0])


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in (NEAR_RANK_EO_ENABLED_ENV, LEAGUE_EO_ENABLED_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("FPL_INTERNAL_TOKEN", raising=False)
    eo_warm.reset()
    near_rec, league_rec = Recorder(), Recorder()

    def no_net(*a, **k):
        raise AssertionError("no network in these tests")

    near_rank_eo_tool.set_service(NearRankEOService(fetch=no_net, executor=near_rec))
    league_eo_tool.set_service(LeagueEOService(fetch=no_net, executor=league_rec))
    monkeypatch.setattr(fpl_server, "_EO_WARM_GATE", eo_poll.RateGate(30.0))
    monkeypatch.setattr(fpl_server, "_EO_POLL_GATE", eo_poll.RateGate(2.0))
    yield near_rec, league_rec
    near_rank_eo_tool.set_service(None)
    league_eo_tool.set_service(None)
    eo_warm.reset()


def on(monkeypatch, near=True, league=True):
    if near:
        monkeypatch.setenv(NEAR_RANK_EO_ENABLED_ENV, "1")
    if league:
        monkeypatch.setenv(LEAGUE_EO_ENABLED_ENV, "1")


# -- the function ----------------------------------------------------------------------------------------------

def test_both_flags_off_starts_nothing_and_memoises_nothing(_env, monkeypatch):
    near, league = _env
    assert eo_warm.warm(BOOT, 5, 77, user_key="u1", now=NOW) == {"near": False, "league": False}
    assert near.jobs == [] and league.jobs == []
    on(monkeypatch)
    assert eo_warm.warm(BOOT, 5, 77, user_key="u1", now=NOW) == {"near": True, "league": True}  # not blocked by the earlier call


def test_starts_one_near_and_one_league_job_and_counts_them(_env, monkeypatch):
    near, league = _env
    on(monkeypatch)
    assert eo_warm.warm(BOOT, 5, 77, user_key="u1", now=NOW) == {"near": True, "league": True}
    assert len(near.jobs) == 1 and len(league.jobs) == 1
    assert eo_warm.counters()["near_started"] == 1 and eo_warm.counters()["league_started"] == 1


def test_only_the_enabled_kind_starts(_env, monkeypatch):
    near, league = _env
    on(monkeypatch, near=True, league=False)
    assert eo_warm.warm(BOOT, 5, 77, user_key="u1", now=NOW) == {"near": True, "league": False}
    assert league.jobs == []


def test_no_league_id_means_no_league_job(_env, monkeypatch):
    near, league = _env
    on(monkeypatch)
    assert eo_warm.warm(BOOT, 5, None, user_key="u1", now=NOW) == {"near": True, "league": False}
    assert league.jobs == []


def test_a_user_is_warmed_once_per_gameweek_per_target(_env, monkeypatch):
    near, league = _env
    on(monkeypatch)
    for _ in range(5):
        eo_warm.warm(BOOT, 5, 77, user_key="u1", now=NOW)  # e.g. every /ask turn
    assert len(near.jobs) == 1 and len(league.jobs) == 1
    assert eo_warm.counters()["memo_skips"] >= 8
    skips = eo_warm.counters()["memo_skips"]
    eo_warm.warm(BOOT, 5, 88, user_key="u1", now=NOW)      # a changed main league is a new target, not a memo skip
    assert eo_warm.counters()["memo_skips"] == skips + 1   # only the near target (same team) was skipped
    assert len(near.jobs) == 1
    later = datetime(2026, 12, 6, tzinfo=timezone.utc)      # next gameweek
    eo_warm.warm(BOOT, 5, 88, user_key="u1", now=later)
    assert len(near.jobs) == 2


def test_two_users_on_the_same_team_share_one_job(_env, monkeypatch):
    near, _ = _env
    on(monkeypatch)
    eo_warm.warm(BOOT, 5, None, user_key="u1", now=NOW)
    again = eo_warm.warm(BOOT, 5, None, user_key="u2", now=NOW)
    assert len(near.jobs) == 1 and again["near"] is False  # single-flight: it joined the running job


def test_the_job_cap_still_applies(_env, monkeypatch):
    on(monkeypatch, league=False)
    near_rank_eo_tool.set_service(NearRankEOService(fetch=lambda *a: None, executor=Recorder(), max_queued=2))
    results = [eo_warm.warm(BOOT, team, None, user_key=f"u{team}", now=NOW)["near"] for team in (1, 2, 3, 4)]
    assert results == [True, True, False, False]  # beyond max_queued the service answers busy and starts nothing


def test_a_failing_service_never_raises(monkeypatch):
    on(monkeypatch)

    class Boom:
        started = 0

        def status(self, *a, **k):
            raise RuntimeError("boom")

    near_rank_eo_tool.set_service(Boom())
    assert eo_warm.warm(BOOT, 5, 77, user_key="u1", now=NOW) == {"near": False, "league": False}


def test_no_gameweek_or_bad_team_starts_nothing(_env, monkeypatch):
    near, _ = _env
    on(monkeypatch)
    assert eo_warm.warm({"events": []}, 5, None, user_key="u1", now=NOW) == {"near": False, "league": False}
    assert eo_warm.warm(BOOT, 0, None, user_key="u1", now=NOW) == {"near": False, "league": False}
    assert eo_warm.warm(BOOT, 5, None, user_key="", now=NOW) == {"near": False, "league": False}
    assert near.jobs == []


# -- the route -------------------------------------------------------------------------------------------------

H = {"X-User-Id": "user_abc"}


def client(monkeypatch):
    monkeypatch.setattr(fpl_server, "_bootstrap", {**BOOT})
    monkeypatch.setattr(eo_warm, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))
    return TestClient(fpl_server.app)


def test_warm_route_anonymous_is_401_and_starts_nothing(_env, monkeypatch):
    near, _ = _env
    on(monkeypatch)
    c = client(monkeypatch)
    assert c.post("/eo/warm", json={"team_id": 5}).status_code == 401
    assert c.post("/eo/warm", json={"team_id": 5}, headers={"X-User-Id": "anonymous"}).status_code == 401
    monkeypatch.setenv("FPL_INTERNAL_TOKEN", "s3cret")
    assert c.post("/eo/warm", json={"team_id": 5}, headers=H).status_code == 401
    assert near.jobs == []


def test_warm_route_starts_jobs_and_is_rate_limited_per_user(_env, monkeypatch):
    near, league = _env
    on(monkeypatch)
    c = client(monkeypatch)
    r = c.post("/eo/warm", json={"team_id": 5, "league_id": 77}, headers=H)
    assert r.status_code == 200 and r.json() == {"started": {"near": True, "league": True}}
    assert c.post("/eo/warm", json={"team_id": 6, "league_id": 78}, headers=H).status_code == 429
    assert len(near.jobs) == 1 and len(league.jobs) == 1   # the refused call started nothing
    assert c.post("/eo/warm", json={"team_id": 6}, headers={"X-User-Id": "user_other"}).status_code == 200
    assert len(near.jobs) == 2


@pytest.mark.parametrize("body", [{"team_id": "5"}, {"team_id": 0}, {"team_id": 5, "league_id": -1},
                                  {"team_id": 10 ** 12}, {"team_id": 5, "x": 1}, {}])
def test_warm_route_validates_ints_only(_env, monkeypatch, body):
    near, _ = _env
    on(monkeypatch)
    assert client(monkeypatch).post("/eo/warm", json=body, headers=H).status_code == 422
    assert near.jobs == []


def test_flags_off_the_route_answers_and_starts_nothing(_env, monkeypatch):
    near, league = _env
    r = client(monkeypatch).post("/eo/warm", json={"team_id": 5, "league_id": 7}, headers=H)
    assert r.status_code == 200 and r.json() == {"started": {"near": False, "league": False}}
    assert near.jobs == [] and league.jobs == []


def test_healthz_shows_counters_without_ids(_env, monkeypatch):
    on(monkeypatch)
    c = client(monkeypatch)
    c.post("/eo/warm", json={"team_id": 5}, headers=H)
    body = c.get("/healthz").json()
    assert body["eo_warm"] == {"near_started": 1, "league_started": 0, "memo_skips": 0}


# -- the turn hook ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/ask"])
def test_a_turn_with_a_team_id_warms_before_routing_and_anonymous_does_not(_env, monkeypatch, path):
    calls = []
    monkeypatch.setattr(eo_warm, "warm", lambda boot, team, league, **k: calls.append((team, league, k["user_key"])) or {})
    monkeypatch.setattr("fpl_grounded_assistant.harness.ask_v2", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop here")))
    monkeypatch.setattr(fpl_server, "_bootstrap", {**BOOT})
    c = TestClient(fpl_server.app, raise_server_exceptions=False)
    c.post(path, json={"question": "hola", "team_id": 5, "main_league_id": 77}, headers=H)
    assert len(calls) == 1 and calls[0][:2] == (5, 77) and calls[0][2] != "user_abc"  # the hashed id, never the raw one
    c.post(path, json={"question": "hola", "team_id": 5})                              # anonymous
    c.post(path, json={"question": "hola"}, headers=H)                                 # no team
    assert len(calls) == 1


# -- review fixes -----------------------------------------------------------------------------------------------

def test_a_failed_warm_gives_the_claim_back(monkeypatch):
    on(monkeypatch, league=False)

    class Boom:
        started = 0

        def status(self, *a, **k):
            raise RuntimeError("boom")

    near_rank_eo_tool.set_service(Boom())
    eo_warm.warm(BOOT, 5, None, user_key="u1", now=NOW)
    rec = Recorder()
    near_rank_eo_tool.set_service(NearRankEOService(fetch=lambda *a: None, executor=rec))
    assert eo_warm.warm(BOOT, 5, None, user_key="u1", now=NOW)["near"] is True  # not locked out for the gameweek


def test_busy_service_gives_the_claim_back(monkeypatch):
    on(monkeypatch, league=False)
    near_rank_eo_tool.set_service(NearRankEOService(fetch=lambda *a: None, executor=Recorder(), max_queued=0))
    assert eo_warm.warm(BOOT, 5, None, user_key="u1", now=NOW)["near"] is False
    rec = Recorder()
    near_rank_eo_tool.set_service(NearRankEOService(fetch=lambda *a: None, executor=rec))
    assert eo_warm.warm(BOOT, 5, None, user_key="u1", now=NOW)["near"] is True


def test_varying_client_team_ids_cannot_start_unbounded_jobs(_env, monkeypatch):
    near, _ = _env
    on(monkeypatch, league=False)
    for team in range(1, 11):
        eo_warm.warm(BOOT, team, None, user_key="u1", now=NOW)
    assert len(near.jobs) == eo_warm.MAX_TARGETS_PER_KIND

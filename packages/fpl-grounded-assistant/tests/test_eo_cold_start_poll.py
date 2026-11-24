"""EO auto-retry from a COLD start: ask -> serialized /ask JSON -> /eo/poll until the terminal status.

#696 and #700 stubbed the tool output and so never saw the drop: with no stored main league the first
``computing`` answer carried no league, ``pending_marker`` returned None, and the UI never polled. Here nothing
between the tool and the wire is stubbed:

* the REAL ``LeagueEOService`` / ``NearRankEOService`` over a fake FPL API (jobs queue in ``Deferred`` and finish
  between polls, as in prod where they run on threads),
* the REAL orchestrator, harness, adapter and ``AskResponse``, with only the model provider replaced by a
  scripted Anthropic-shaped client (one tool call, then prose),
* the poll body built from the ``pending`` JSON exactly as ``lib/use-eo-poll.ts`` builds it.

Synthetic ids and numbers only. No network (non-loopback connects fail), no paid call.
"""
from __future__ import annotations

import copy
import socket
import threading
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant import eo_poll, eo_warm, league_eo_tool, near_rank_eo_tool
from fpl_grounded_assistant import near_rank_eo as ne
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.league_eo import LeagueEOService
from fpl_grounded_assistant.near_rank_eo import NearRankEOService
from fpl_grounded_assistant.quota import reset_quota

from conftest import BOOTSTRAP

USER = 7_000_001
RANK = 1_234_567
LEAGUE_A, LEAGUE_B = 4242, 4343          # the user's private leagues
STALE = 999_001                          # a stored league the user no longer belongs to
H = {"X-User-Id": "u-cold-start"}
EVENTS = [{"id": 11, "deadline_time": "2026-11-01T10:00:00Z"}, {"id": 12, "deadline_time": "2099-01-01T10:00:00Z"}]


def picks_for(entry: int) -> dict:
    ids = list(range(1, 16))
    if entry % 2:
        ids[1] = 99
    return {"active_chip": None, "picks": [
        {"element": e, "position": i + 1, "multiplier": 0 if i >= 11 else (2 if i == 0 else 1), "is_captain": i == 0}
        for i, e in enumerate(ids)]}


def row(lid, size, name):
    return {"id": lid, "name": name, "league_type": "x", "scoring": "c", "rank_count": size}


class FplApi:
    """One fake FPL API for both services: entry (league list), history, overall + league standings, picks."""

    def __init__(self, leagues):
        self.leagues, self.urls, self.lock = leagues, [], threading.Lock()

    def __call__(self, url):
        with self.lock:
            self.urls.append(url)
        if "/history/" in url:
            return 200, {"current": [{"event": 11, "overall_rank": RANK}]}, {}
        if "/standings/" in url:
            page = int(url.rsplit("=", 1)[1])
            if f"/leagues-classic/{ne.OVERALL_LEAGUE}/" in url:
                rows = [{"rank": (page - 1) * 50 + (i // 2) * 2 + 1, "entry": 1_000_000 + (page - 1) * 50 + i + 1,
                         "player_name": "Hidden Name"} for i in range(50)]
                if page == ne.rank_page(RANK):
                    rows[10]["entry"] = USER
                return 200, {"standings": {"results": rows}}, {}
            rows = [{"entry": 2_000_000 + i, "player_name": "Hidden Name", "rank": i + 1} for i in range(12)]
            return 200, {"standings": {"results": rows, "has_next": False}}, {}
        if "/picks/" in url:
            return 200, picks_for(int(url.split("/entry/")[1].split("/")[0])), {}
        return 200, {"leagues": {"classic": self.leagues, "h2h": []}}, {}


class Deferred:
    """Jobs wait here until the test lets 'time pass' (a poll tick); then they all run to completion."""

    def __init__(self):
        self.queue = []

    def submit(self, fn, *args):
        self.queue.append((fn, args))

    def run_all(self):
        while self.queue:
            fn, args = self.queue.pop(0)
            fn(*args)


class Scripted:
    """The model provider: one tool call, then a 'not ready yet' sentence. Anything more is a failure."""

    def __init__(self, tool, args):
        self.messages = self
        self.queue = [
            NS(content=[NS(type="tool_use", id="tu_1", name=tool, input=args)], stop_reason="tool_use",
               usage=NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)),
            NS(content=[NS(type="text", text="Se esta calculando; pregunta de nuevo en unos segundos.")],
               stop_reason="end_turn", usage=NS(input_tokens=120, output_tokens=20, cache_read_input_tokens=0)),
        ]

    def create(self, **_kwargs):
        if not self.queue:
            raise AssertionError("unexpected extra provider call")
        return self.queue.pop(0)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    real = socket.socket.connect

    def loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"no network in these tests: {address!r}")
        return real(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    for name, value in (("FPL_ORCH_ENABLED", "1"), ("FPL_ORCH_PROVIDER", "anthropic"),
                        ("ANTHROPIC_API_KEY", "test-key-never-used"), ("FPL_EVAL_DISABLED", "1"),
                        ("FPL_LEAGUE_EO_ENABLED", "1"), ("FPL_NEAR_RANK_EO_ENABLED", "1")):
        monkeypatch.setenv(name, value)
    for name in ("FPL_JEV_MODE", "FPL_ORCH_LOOP_ENABLED", "FPL_INTERNAL_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    # these tests are about the cold path, so the warm-up (its own tests) must not pre-fill the services
    monkeypatch.setattr(eo_warm, "warm", lambda *a, **k: {"near": False, "league": False})
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    for module in (near_rank_eo_tool, league_eo_tool):
        monkeypatch.setattr(module, "_season", lambda b: "2026-2027")
        monkeypatch.setattr(module, "load_linked_squad", lambda b, gw: None)  # never the FPL API
    monkeypatch.setattr(fpl_server, "_EO_POLL_GATE", eo_poll.RateGate(0.0))
    reset_quota()
    yield
    near_rank_eo_tool.set_service(None)
    league_eo_tool.set_service(None)
    fpl_server._sessions.clear()
    reset_quota()


class Stack:
    def __init__(self, monkeypatch, leagues):
        self.jobs = Deferred()
        self.fake = FplApi(leagues)
        quiet = ne.RateLimiter(0.0, sleep=lambda s: None)
        league_eo_tool.set_service(LeagueEOService(self.fake, limiter=quiet, sleep=lambda s: None,
                                                   executor=self.jobs, workers=1))
        near_rank_eo_tool.set_service(NearRankEOService(self.fake, limiter=quiet, sleep=lambda s: None,
                                                        executor=self.jobs, workers=1))
        boot = copy.deepcopy(BOOTSTRAP)
        boot["events"] = EVENTS
        fpl_server._init_bootstrap(boot)
        fpl_server._sessions.clear()
        self.client = TestClient(fpl_server.app)
        self.monkeypatch = monkeypatch

    def ask(self, tool, args, main_league_id=None):
        self.monkeypatch.setattr(orch_mod, "_get_anthropic_client", lambda **_k: Scripted(tool, args))
        body = {"question": "¿Qué EO hay en mi liga?", "team_id": USER}
        if main_league_id is not None:
            body["main_league_id"] = main_league_id
        res = self.client.post("/ask", json=body, headers=H)
        assert res.status_code == 200, res.text
        return res.json()  # the serialized wire body

    def poll_until_terminal(self, pending, locale="es", limit=6):
        """What lib/use-eo-poll.ts does: build the body from the marker, post, wait a tick on `computing`."""
        seen = []
        for _ in range(limit):
            self.jobs.run_all()  # a tick passes: queued jobs finish
            body = {"tool": pending["tool"], "team_id": USER, "locale": locale}
            if pending.get("league_id") is not None:
                body["league_id"] = pending["league_id"]
            if pending.get("league_name"):
                body["league_name"] = pending["league_name"]
            res = self.client.post("/eo/poll", json=body, headers=H)
            assert res.status_code == 200, res.text
            reply = res.json()
            seen.append(reply["status"])
            if reply["status"] != "computing":
                return reply, seen
        raise AssertionError(f"the poll never ended: {seen}")


ONE = [row(LEAGUE_A, 12, "Friends")]
TWO = [row(LEAGUE_A, 12, "Friends"), row(LEAGUE_B, 20, "Work Mates")]


def assert_ready(reply):
    assert reply["status"] == "ready" and reply["generic_card"]["rows"], reply
    assert reply["text"].startswith("Listo:")


# -- league ---------------------------------------------------------------------------------------------------

def test_stored_league_marker_and_poll_to_ready(monkeypatch):
    s = Stack(monkeypatch, TWO)
    body = s.ask("get_league_eo", {}, main_league_id=LEAGUE_B)
    assert body["pending"]["tool"] == "get_league_eo" and body["pending"]["league_id"] == LEAGUE_B
    reply, seen = s.poll_until_terminal(body["pending"])
    assert_ready(reply)
    assert seen[-1] == "ready"


def test_no_stored_league_and_a_single_league_polls_to_ready(monkeypatch):
    s = Stack(monkeypatch, ONE)
    body = s.ask("get_league_eo", {})
    assert body["pending"] is not None, "a computing league answer with no stored league must still carry a marker"
    assert body["pending"]["tool"] == "get_league_eo" and "league_id" not in body["pending"]
    assert "pregunta de nuevo" in body["final_text"]
    reply, seen = s.poll_until_terminal(body["pending"])
    assert_ready(reply)


def test_no_stored_league_and_several_leagues_ends_with_the_picker(monkeypatch):
    s = Stack(monkeypatch, TWO)
    body = s.ask("get_league_eo", {})
    assert body["pending"] is not None and "league_id" not in body["pending"]
    reply, seen = s.poll_until_terminal(body["pending"])
    assert reply["status"] == "needs_league", seen
    assert reply["text"] == "¿De qué liga quieres el EO?"
    chips = reply["suggestions"]
    assert {c["label"] for c in chips} == {"Friends", "Work Mates"}
    assert all(c["kind"] == "league_pick" and c["league_id"] in (LEAGUE_A, LEAGUE_B) for c in chips)
    assert {c["send_text"] for c in chips} == {"EO en Friends", "EO en Work Mates"}


def test_picker_text_follows_the_locale(monkeypatch):
    s = Stack(monkeypatch, TWO)
    body = s.ask("get_league_eo", {})
    reply, _ = s.poll_until_terminal(body["pending"], locale="en")
    assert reply["status"] == "needs_league" and reply["text"] == "Which league do you want the EO for?"
    assert {c["send_text"] for c in reply["suggestions"]} == {"EO in Friends", "EO in Work Mates"}


def test_stale_stored_league_with_one_league_falls_back_to_it(monkeypatch):
    s = Stack(monkeypatch, ONE)
    body = s.ask("get_league_eo", {}, main_league_id=STALE)
    assert body["pending"] is not None
    reply, _ = s.poll_until_terminal(body["pending"])
    assert_ready(reply)
    assert "Friends" in reply["generic_card"]["title"]


def test_stale_stored_league_with_several_leagues_ends_with_the_picker(monkeypatch):
    s = Stack(monkeypatch, TWO)
    body = s.ask("get_league_eo", {}, main_league_id=STALE)
    reply, _ = s.poll_until_terminal(body["pending"])
    assert reply["status"] == "needs_league"


def test_stale_league_on_a_warm_list_is_not_echoed(monkeypatch):
    """Once the leagues list is cached the tool KNOWS the stored id is stale: it must not echo it."""
    s = Stack(monkeypatch, ONE)
    first = s.ask("get_league_eo", {}, main_league_id=STALE)
    s.jobs.run_all()                                   # the list is now cached
    second = s.ask("get_league_eo", {}, main_league_id=STALE)
    assert second["pending"] is not None and second["pending"].get("league_id") != STALE
    assert first["pending"]["league_id"] == STALE      # cold: unknowable, the poll resolves it (tests above)


def test_named_league_marker_carries_the_name_and_polls_to_ready(monkeypatch):
    s = Stack(monkeypatch, TWO)
    body = s.ask("get_league_eo", {"league_name": "Work Mates"})
    assert body["pending"]["league_name"] == "Work Mates" and "league_id" not in body["pending"]
    reply, _ = s.poll_until_terminal(body["pending"])
    assert_ready(reply)
    assert "Work Mates" in reply["generic_card"]["title"]


def test_named_league_wins_over_a_stored_one(monkeypatch):
    s = Stack(monkeypatch, TWO)
    body = s.ask("get_league_eo", {"league_name": "Work Mates"}, main_league_id=LEAGUE_A)
    assert body["pending"].get("league_id") != LEAGUE_A
    reply, _ = s.poll_until_terminal(body["pending"])
    assert "Work Mates" in reply["generic_card"]["title"]


# -- near rank ------------------------------------------------------------------------------------------------

def test_near_rank_marker_and_poll_to_ready(monkeypatch):
    s = Stack(monkeypatch, ONE)
    body = s.ask("get_near_rank_eo", {})
    assert body["pending"]["tool"] == "get_near_rank_eo"
    reply, _ = s.poll_until_terminal(body["pending"])
    assert_ready(reply)


# -- the poll route's own bounds ------------------------------------------------------------------------------

@pytest.mark.parametrize("extra", [{"league_name": "x" * 101}, {"league_name": 5}, {"league_name": ["a"]}, {"nope": 1}])
def test_poll_body_is_bounded_and_forbids_extras(monkeypatch, extra):
    s = Stack(monkeypatch, ONE)
    res = s.client.post("/eo/poll", json={"tool": "get_league_eo", "team_id": USER, **extra}, headers=H)
    assert res.status_code == 422 and s.jobs.queue == []


def test_poll_without_a_session_still_starts_no_job(monkeypatch):
    s = Stack(monkeypatch, ONE)
    res = s.client.post("/eo/poll", json={"tool": "get_league_eo", "team_id": USER, "league_name": "Friends"})
    assert res.status_code == 401 and s.jobs.queue == []

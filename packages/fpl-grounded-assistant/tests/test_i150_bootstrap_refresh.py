"""
tests/test_i150_bootstrap_refresh.py
====================================
i150: the FPL bootstrap is refreshed periodically instead of frozen at startup.

Scenarios: refresh OK (swap + derived caches cleared), refresh fails (previous
kept, error recorded), invalid bootstrap rejected (empty lists / missing
team_fixtures / GW regression), concurrency (readers never see a half-built
bootstrap; overlapping refreshes serialise), interval config, /healthz.

No network: every fetch is an injected stub.
"""
from __future__ import annotations

import threading
import time

import pytest

import fpl_server


def _bs(gw: int = 6, marker: str = "old", **over):
    bs = {
        "marker": marker,
        "elements": [{"id": 1, "web_name": "Haaland"}],
        "teams": [{"id": 13, "name": "Man City"}],
        "events": [
            {"id": gw - 1, "finished": True, "is_current": False, "is_next": False},
            {"id": gw, "finished": False, "is_current": True, "is_next": False},
            {"id": gw + 1, "finished": False, "is_current": False, "is_next": True},
        ],
        "team_fixtures": {13: []},
    }
    bs.update(over)
    return bs


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(fpl_server, "_bootstrap", None)
    monkeypatch.setattr(fpl_server, "_bootstrap_loaded_at", None)
    monkeypatch.setattr(fpl_server, "_bootstrap_refresh_state", {
        "refresh_count": 0, "failure_count": 0,
        "last_ok_at": None, "last_error": None, "last_error_at": None,
    })
    monkeypatch.delenv("FPL_BOOTSTRAP_REFRESH_SECONDS", raising=False)
    yield
    fpl_server._stop_bootstrap_refresh()


# --- refresh OK -------------------------------------------------------------

def test_refresh_ok_swaps_and_stamps():
    fpl_server._init_bootstrap(_bs(marker="old"))
    new = _bs(gw=7, marker="new")
    assert fpl_server._refresh_bootstrap_once(lambda: new) is True
    assert fpl_server._bootstrap is new
    st = fpl_server._bootstrap_refresh_state
    assert st["refresh_count"] == 1 and st["last_error"] is None
    assert st["last_ok_at"] is not None


def test_refresh_ok_clears_derived_caches():
    import importlib
    gff = importlib.import_module("fpl_grounded_assistant.get_fixtures_for_gw")
    gff._fixture_cache[6] = [{"finished": False}]
    fpl_server._init_bootstrap(_bs())
    assert fpl_server._refresh_bootstrap_once(lambda: _bs(marker="new"))
    assert gff._fixture_cache == {}


def test_refresh_heals_a_server_that_started_without_bootstrap():
    assert fpl_server._bootstrap is None
    assert fpl_server._refresh_bootstrap_once(lambda: _bs(marker="new")) is True
    assert fpl_server._bootstrap["marker"] == "new"


def test_refresh_ok_clears_fallback_provenance(monkeypatch):
    monkeypatch.setattr(fpl_server, "_LAST_BOOTSTRAP_PROVENANCE", object())
    fpl_server._init_bootstrap(_bs())
    fpl_server._refresh_bootstrap_once(lambda: _bs(marker="new"))
    assert fpl_server._LAST_BOOTSTRAP_PROVENANCE is None


# --- refresh fails ----------------------------------------------------------

def test_refresh_failure_keeps_previous_and_records_error():
    old = _bs(marker="old")
    fpl_server._init_bootstrap(old)

    def boom():
        raise ConnectionError("fpl down")

    assert fpl_server._refresh_bootstrap_once(boom) is False
    assert fpl_server._bootstrap is old
    st = fpl_server._bootstrap_refresh_state
    assert st["failure_count"] == 1
    assert "ConnectionError" in st["last_error"] and st["last_error_at"]


def test_failure_does_not_clear_caches():
    import importlib
    gff = importlib.import_module("fpl_grounded_assistant.get_fixtures_for_gw")
    gff._fixture_cache[6] = [{"x": 1}]
    fpl_server._init_bootstrap(_bs())
    fpl_server._refresh_bootstrap_once(lambda: (_ for _ in ()).throw(OSError("x")))
    assert gff._fixture_cache == {6: [{"x": 1}]}
    gff._fixture_cache.clear()


def test_success_after_failure_clears_last_error():
    fpl_server._init_bootstrap(_bs())
    fpl_server._refresh_bootstrap_once(lambda: (_ for _ in ()).throw(OSError("x")))
    fpl_server._refresh_bootstrap_once(lambda: _bs(marker="new"))
    st = fpl_server._bootstrap_refresh_state
    assert st["last_error"] is None and st["failure_count"] == 1


# --- invalid is rejected ----------------------------------------------------

@pytest.mark.parametrize("bad, reason", [
    (_bs(elements=[]), "empty_elements"),
    (_bs(teams=[]), "empty_teams"),
    (_bs(events=[]), "empty_events"),
    (_bs(elements=None), "empty_elements"),
    (_bs(team_fixtures=None), "missing_team_fixtures"),
    (_bs(gw=3), "gw_regressed_6_to_3"),
    ("not a dict", "not_a_dict"),
])
def test_invalid_bootstrap_rejected(bad, reason):
    old = _bs(marker="old")
    fpl_server._init_bootstrap(old)
    assert fpl_server._refresh_bootstrap_once(lambda: bad) is False
    assert fpl_server._bootstrap is old
    assert reason in fpl_server._bootstrap_refresh_state["last_error"]


def test_gw_moving_forward_or_season_end_is_accepted():
    fpl_server._init_bootstrap(_bs(gw=6))
    over = _bs(gw=38)
    for e in over["events"]:
        e["finished"] = True          # season over: current GW resolves to None
    assert fpl_server._validate_new_bootstrap(over, fpl_server._bootstrap) is None


# --- concurrency ------------------------------------------------------------

def test_readers_never_see_a_half_built_bootstrap():
    """Each candidate is internally consistent (marker == every element tag);
    hammer readers while swaps happen and check no reader sees a mix."""
    def make(tag):
        return _bs(marker=tag, elements=[{"id": 1, "tag": tag}],
                   teams=[{"id": 13, "tag": tag}])

    fpl_server._init_bootstrap(make("a"))
    stop = threading.Event()
    seen_mixed = []

    def reader():
        while not stop.is_set():
            bs = fpl_server._bootstrap          # one read, as the handlers do
            tags = {bs["marker"], bs["elements"][0]["tag"], bs["teams"][0]["tag"]}
            if len(tags) != 1:
                seen_mixed.append(tags)

    readers = [threading.Thread(target=reader) for _ in range(4)]
    for t in readers:
        t.start()
    for i in range(200):
        fpl_server._refresh_bootstrap_once(lambda i=i: make(f"t{i}"))
    stop.set()
    for t in readers:
        t.join()
    assert seen_mixed == []
    assert fpl_server._bootstrap_refresh_state["refresh_count"] == 200


def test_overlapping_refreshes_serialise():
    fpl_server._init_bootstrap(_bs())
    active, peak = [0], [0]
    guard = threading.Lock()

    def slow():
        with guard:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        with guard:
            active[0] -= 1
        return _bs(marker="new")

    ts = [threading.Thread(target=fpl_server._refresh_bootstrap_once, args=(slow,))
          for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert peak[0] == 1
    assert fpl_server._bootstrap_refresh_state["refresh_count"] == 5


# --- interval config + thread ----------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    (None, 900.0), ("", 900.0), ("abc", 900.0),
    ("0", 0.0), ("-5", 0.0),
    ("10", 60.0),            # floored
    ("600", 600.0),
])
def test_interval_config(monkeypatch, raw, expected):
    if raw is not None:
        monkeypatch.setenv("FPL_BOOTSTRAP_REFRESH_SECONDS", raw)
    assert fpl_server._bootstrap_refresh_interval() == expected


def test_disabled_starts_no_thread(monkeypatch):
    monkeypatch.setenv("FPL_BOOTSTRAP_REFRESH_SECONDS", "0")
    fpl_server._start_bootstrap_refresh()
    assert fpl_server._bootstrap_refresh_thread is None


def test_lifespan_starts_thread_without_fetching_then_stops(monkeypatch):
    """Entering the lifespan with an injected bootstrap must not touch the
    network (the loop waits one interval first) and must stop cleanly."""
    from fastapi.testclient import TestClient

    def no_net(*a, **k):
        raise AssertionError("network call during lifespan")

    monkeypatch.setattr(fpl_server, "assemble_captain_context", no_net)
    fpl_server._init_bootstrap(_bs())
    with TestClient(fpl_server.app):
        t = fpl_server._bootstrap_refresh_thread
        assert t is not None and t.is_alive()
    assert fpl_server._bootstrap_refresh_thread is None
    assert not t.is_alive()


# --- /healthz ---------------------------------------------------------------

def test_healthz_exposes_age_and_last_error():
    from fastapi.testclient import TestClient
    fpl_server._init_bootstrap(_bs())
    fpl_server._refresh_bootstrap_once(lambda: (_ for _ in ()).throw(OSError("fpl 503")))
    with TestClient(fpl_server.app) as c:
        body = c.get("/healthz").json()["bootstrap"]
    assert body["loaded"] is True
    assert body["age_seconds"] is not None and body["age_seconds"] >= 0
    assert "OSError" in body["last_error"]
    assert body["failure_count"] == 1
    assert body["refresh_interval_s"] == 900.0

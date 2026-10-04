"""i134 -- an empty fixture fetch is "no data", never "20 teams blank", and is not cached.

Found by the i133 probe: on 2026-10-03 three local servers answered
«GW6 en blanco para 20 equipos»; ``get_gameweek_context`` reports exactly that
(5 alerts x 20 teams) when every fetch in its window returns ``[]``, and
``_fixture_cache`` (no TTL) kept the empty list for the life of the process.

Pinned here, one guard at a time:
  * a live ``[]`` is returned but not cached; a normal fetch still is;
  * the gameweek context skips an empty GW instead of calling it all-blank,
    from the live path and from the override path;
  * a REAL partial blank (2 teams without a fixture) is still reported;
  * when FPL recovers, the next call sees the real fixtures.
FPL is faked; no network.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import fpl_grounded_assistant  # noqa: F401  (registers tools)


def _live():
    """The modules as they are NOW. Other test files reload them, so names bound
    at import time can point at a stale copy whose ``get_fixtures`` nobody calls.
    The fetch namespace is read off the function the context actually calls."""
    ctx = sys.modules["fpl_grounded_assistant.get_gameweek_context"]
    return ctx, SimpleNamespace(mod=ctx._fetch_fixtures_for_gw.__globals__)


class _Gff:
    """``gff.<name>`` on whatever namespace the context's fetch helper lives in."""
    def __getattr__(self, name):
        return _live()[1].mod[name]


gff = _Gff()


def get_gameweek_context(*a, **k):
    return _live()[0].get_gameweek_context(*a, **k)


def _clear_context_cache():
    _live()[0]._clear_context_cache()

TEAMS = [{"id": i, "name": f"Team {i}", "short_name": f"T{i:02d}"} for i in range(1, 21)]
EVENTS = [{"id": gw, "deadline_time": None, "finished": gw <= 5, "is_current": gw == 5,
           "is_next": gw == 6, "is_previous": gw == 4} for gw in range(1, 39)]
BOOTSTRAP = {"teams": TEAMS, "events": EVENTS}


def _round(gw: int, playing: range = range(1, 21)) -> list[dict]:
    ids = list(playing)
    return [{"id": gw * 100 + k, "event": gw, "team_h": ids[2 * k], "team_a": ids[2 * k + 1],
             "team_h_difficulty": 3, "team_a_difficulty": 3} for k in range(len(ids) // 2)]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    gff._fixture_cache.clear()
    _clear_context_cache()
    monkeypatch.delenv("FPL_FORCE_FALLBACK_TOOLS", raising=False)
    yield
    gff._fixture_cache.clear()
    _clear_context_cache()


def _fpl(monkeypatch, by_gw):
    calls = []

    def fake(gw):
        calls.append(gw)
        return by_gw(gw)
    monkeypatch.setitem(_live()[1].mod, "get_fixtures", fake)
    return calls


# --- (b) the cache ---------------------------------------------------------

def test_an_empty_live_fetch_is_returned_but_not_cached(monkeypatch):
    calls = _fpl(monkeypatch, lambda gw: [])
    assert gff._fetch_fixtures_for_gw(6, BOOTSTRAP, None) == []
    assert 6 not in gff._fixture_cache
    gff._fetch_fixtures_for_gw(6, BOOTSTRAP, None)
    assert calls == [6, 6]                       # asked FPL again, not the cache


def test_a_normal_fetch_is_still_cached(monkeypatch):
    calls = _fpl(monkeypatch, _round)
    assert len(gff._fetch_fixtures_for_gw(6, BOOTSTRAP, None)) == 10
    assert len(gff._fixture_cache[6]) == 10
    gff._fetch_fixtures_for_gw(6, BOOTSTRAP, None)
    assert calls == [6]                          # second read came from the cache


# --- (a) the gameweek context ---------------------------------------------

def test_empty_fetches_do_not_become_twenty_team_blanks(monkeypatch):
    _fpl(monkeypatch, lambda gw: [])
    out = get_gameweek_context(BOOTSTRAP)
    assert out["status"] == "ok" and out["next_gw"] == 6
    assert out["blank_gw_alerts"] == []
    assert not any(a["count"] == 20 for a in out["blank_gw_alerts"])
    assert gff._fixture_cache == {}


def test_after_fpl_recovers_the_real_fixtures_are_read(monkeypatch):
    state = {"down": True}
    _fpl(monkeypatch, lambda gw: [] if state["down"] else _round(gw, range(1, 19) if gw == 7 else range(1, 21)))
    assert get_gameweek_context(BOOTSTRAP)["blank_gw_alerts"] == []
    state["down"] = False
    _clear_context_cache()                       # its own 10-minute cache, not the bug
    out = get_gameweek_context(BOOTSTRAP)
    assert out["blank_gw_alerts"] == [{"gw": 7, "blank_teams": ["T19", "T20"], "count": 2}]


def test_a_real_partial_blank_is_still_reported(monkeypatch):
    _fpl(monkeypatch, lambda gw: _round(gw, range(1, 19)) if gw == 8 else _round(gw))
    out = get_gameweek_context(BOOTSTRAP)
    assert out["blank_gw_alerts"] == [{"gw": 8, "blank_teams": ["T19", "T20"], "count": 2}]


def test_an_empty_override_gw_is_skipped_too():
    out = get_gameweek_context(BOOTSTRAP, fixtures={gw: ([] if gw == 6 else _round(gw)) for gw in range(6, 11)})
    assert out["blank_gw_alerts"] == []

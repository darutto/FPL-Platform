"""/fixtures/competitions served from the synced licensed store (cups) plus the PL fixtures. No network."""
from __future__ import annotations

import pandas as pd
import pytest

import fpl_server  # noqa: F401  (puts the sibling packages on sys.path)
from fpl_grounded_assistant import competition_calendar as cc

SNAP_COLS = ["competition", "season", "source", "fetched_at", "complete_as_of", "postponed", "unmapped_count"]
REC_COLS = ["competition", "season", "club", "opponent", "opponent_code", "kickoff_utc", "venue", "status",
            "source", "fetched_at", "gameweek"]
NOW_ISO = "2099-01-01T00:00:00Z"


class FakeHandle:
    def __init__(self, snaps, recs):
        self._t = {"cup_snapshots": pd.DataFrame(snaps, columns=SNAP_COLS), "cup_records": pd.DataFrame(recs, columns=REC_COLS)}

    def manifest(self):
        return {"build_id": "b1", "built_at": "2026-10-27T06:00:00Z"}

    def table(self, name):
        return self._t[name]


def _fa(club, opp, code, when, venue="H"):
    return ["FA", "2026-2027", club, opp, code, when, venue, "scheduled", "licensed", "2026-10-27T06:00:00Z", None]


def _install(monkeypatch, snaps, recs):
    import football_intelligence.distribution.licensed_runtime as lr
    monkeypatch.delenv(cc.ENV_ALLOW, raising=False)
    cc._licensed_cache.clear()
    monkeypatch.setattr(lr, "handle_from_env", lambda: FakeHandle(snaps, recs))
    monkeypatch.setattr(cc, "_pl_snapshot", _pl_stub)


def _pl_stub(season, fetched_at):
    from football_intelligence.public_calendar import CompetitionSnapshot, FixtureRecord
    mk = lambda club, opp, venue, when, gw: FixtureRecord("PL", season, club, opp, opp, when, venue, "scheduled", "fpl_api", fetched_at, gw)
    return CompetitionSnapshot("PL", season, "fpl_api", fetched_at, None, (
        mk("ARS", "CHE", "H", "2099-01-03T15:00:00Z", 20), mk("CHE", "ARS", "A", "2099-01-03T15:00:00Z", 20)))


def _snap(comp="FA", complete_as_of=None):
    return [comp, "2026-2027", "licensed", "2026-10-27T06:00:00Z", complete_as_of, 0, 0]


def test_premium_gets_the_cup_match_with_provenance_and_partial_coverage(monkeypatch):
    _install(monkeypatch, [_snap()], [_fa("ARS", "Luton", "LUT", "2099-01-01T19:45:00Z")])
    out = cc.competitions_response("patreon_basic", "ARS", None, None)
    assert out["available"] and out["tier"] == "premium"
    assert out["data"]["provenance"] == "licensed_starter" and out["data"]["coverage"]["FA"] == "partial"
    assert out["data"]["coverage"]["EFL"] == "missing"
    arsenal = out["teams"]["ARS"]
    assert [(m["competition"], m["opponent_code"]) for m in arsenal["matches"]] == [("FA", "LUT")]
    assert [m["gameweek"] for m in arsenal["pl_matches"]] == [20]


def test_partial_cups_never_issue_a_rotation_notice(monkeypatch):
    _install(monkeypatch, [_snap()], [_fa("ARS", "Luton", "LUT", "2099-01-01T19:45:00Z")])
    pl = cc.competitions_response("patreon_premium", "ARS", None, None)["teams"]["ARS"]["pl_matches"]
    assert [m["rotation"] for m in pl] == [False]  # a hole is not "no match"


def test_free_tier_stays_the_constant(monkeypatch):
    _install(monkeypatch, [_snap()], [_fa("ARS", "Luton", "LUT", "2099-01-01T19:45:00Z")])
    assert cc.competitions_response("free", None, None, None) == {"available": True, "tier": "free"}
    assert cc.competitions_response("patreon_tribuna", None, None, None) == {"available": True, "tier": "free"}


def test_an_unsynced_store_is_unavailable_not_empty(monkeypatch):
    import football_intelligence.distribution.licensed_runtime as lr
    monkeypatch.delenv(cc.ENV_ALLOW, raising=False)
    cc._licensed_cache.clear()

    def boom():
        raise FileNotFoundError("no pointer")
    monkeypatch.setattr(lr, "handle_from_env", boom)
    assert cc.competitions_response("patreon_premium", None, None, None) == {"available": False}

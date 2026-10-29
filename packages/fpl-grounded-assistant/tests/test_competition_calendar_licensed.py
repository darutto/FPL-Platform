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


def _layer(tmp_path, monkeypatch, matches=None, provenance="manual_curated"):
    import json
    path = tmp_path / "europe.json"
    path.write_text(json.dumps({
        "schema_version": 1, "provenance": provenance, "list_date": "2026-10-27", "coverage": "partial", "frozen": True,
        "competitions": ["UCL"], "matches": matches if matches is not None else [
            {"competition": "UCL", "club": "ARS", "opponent": "Equipo Uno", "opponent_code": "", "date": "2099-01-01",
             "venue": "A", "kickoff_known": False}]}), encoding="utf-8")
    monkeypatch.setenv(cc.ENV_MANUAL, str(path))
    cc._manual_cache.clear()


def test_manual_europe_is_layered_with_its_own_provenance_and_no_rest_or_notice(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [_fa("ARS", "Luton", "LUT", "2099-01-01T19:45:00Z")])
    _layer(tmp_path, monkeypatch)
    out = cc.competitions_response("patreon_basic", "ARS", None, None)
    assert out["data"]["provenance"] == "licensed_starter+manual_curated"
    assert out["data"]["manual"] == {"provenance": "manual_curated", "list_date": "2026-10-27", "coverage": "partial",
                                     "frozen": True, "competitions": ["UCL"]}
    ucl = [m for m in out["teams"]["ARS"]["matches"] if m["competition"] == "UCL"]
    assert len(ucl) == 1 and ucl[0]["kickoff_known"] is False and ucl[0]["gameweek"] == 20
    assert ucl[0]["rest_whole_days_before"] is None and ucl[0]["previous_competition"] is None
    assert [m["rotation"] for m in out["teams"]["ARS"]["pl_matches"]] == [False]


def test_a_verified_europe_time_gives_rest_hours_and_the_notice_on_a_partial_calendar(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [_fa("ARS", "Luton", "LUT", "2098-12-20T19:45:00Z")])
    _layer(tmp_path, monkeypatch, matches=[
        {"competition": "UCL", "club": "ARS", "opponent": "Equipo Uno", "opponent_code": "", "date": "2099-01-01",
         "venue": "A", "kickoff_known": True, "kickoff_utc": "2099-01-01T20:00:00Z"}])
    out = cc.competitions_response("patreon_basic", "ARS", None, None)
    ucl = [m for m in out["teams"]["ARS"]["matches"] if m["competition"] == "UCL"][0]
    assert ucl["kickoff_utc"] == "2099-01-01T20:00:00Z" and "kickoff_known" not in ucl
    assert ucl["previous_competition"] == "FA" and ucl["rest_whole_days_before"] == 12
    pl = out["teams"]["ARS"]["pl_matches"][0]
    # 2099-01-01 20:00 -> 2099-01-03 15:00 is 43 h: 1 whole day, after a European match -> notice, in spite of coverage partial
    assert (pl["rest_hours_before"], pl["rest_whole_days_before"], pl["previous_competition"], pl["rotation"]) == (43, 1, "UCL", True)


def test_an_unverified_time_never_feeds_rest_or_notice(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [_fa("ARS", "Luton", "LUT", "2098-12-20T19:45:00Z")])
    _layer(tmp_path, monkeypatch, matches=[
        {"competition": "UCL", "club": "ARS", "opponent": "Equipo Uno", "opponent_code": "", "date": "2099-01-02",
         "venue": "A", "kickoff_known": False}])
    pl = cc.competitions_response("patreon_basic", "ARS", None, None)["teams"]["ARS"]["pl_matches"][0]
    assert pl["previous_competition"] == "FA" and pl["rotation"] is False


def test_free_tier_sees_nothing_of_the_manual_layer(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [_fa("ARS", "Luton", "LUT", "2099-01-01T19:45:00Z")])
    _layer(tmp_path, monkeypatch)
    assert cc.competitions_response("free", None, None, None) == {"available": True, "tier": "free"}


def test_a_layer_with_another_provenance_or_no_file_is_ignored(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [_fa("ARS", "Luton", "LUT", "2099-01-01T19:45:00Z")])
    _layer(tmp_path, monkeypatch, provenance="live_trial_local")
    out = cc.competitions_response("patreon_basic", "ARS", None, None)
    assert out["data"]["provenance"] == "licensed_starter" and "manual" not in out["data"]
    monkeypatch.setenv(cc.ENV_MANUAL, str(tmp_path / "missing.json"))
    cc._manual_cache.clear()
    assert "manual" not in cc.competitions_response("patreon_basic", "ARS", None, None)["data"]


def test_the_window_filters_manual_matches(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [_fa("ARS", "Luton", "LUT", "2099-01-01T19:45:00Z")])
    _layer(tmp_path, monkeypatch)
    out = cc.competitions_response("patreon_basic", "ARS", "2099-02-01", None)
    assert [m["competition"] for m in out["teams"]["ARS"]["matches"]] == []

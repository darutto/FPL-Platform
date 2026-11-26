"""/fixtures/competitions with Europe from StrikerAPI (flag FPL_EUROPE_CALENDAR_STRIKERAPI). No network.

Synthetic snapshot file in the job's shape, a fake licensed store and a stub for the Premier League fixtures.
"""
from __future__ import annotations

import json
from datetime import timedelta, timezone

import pytest

import fpl_server  # noqa: F401  (puts the sibling packages on sys.path)
from fpl_grounded_assistant import competition_calendar as cc

from test_competition_calendar_licensed import _fa, _install, _layer, _snap

SEASON = "2026-2027"
PL_SATURDAY = "2099-01-03T15:00:00Z"          # the stub's Premier League match (ARS v CHE)
TUESDAY = "2098-12-30T20:00:00Z"              # 91 hours before it: 3 whole days


def _ago(**kw):
    return (cc.datetime.now(timezone.utc) - timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(comp, club, code, kickoff, fetched):
    return {"competition": comp, "season": SEASON, "club": club, "opponent": f"Synthetic {code}",
            "opponent_code": code, "kickoff_utc": kickoff, "venue": "H", "status": "scheduled",
            "source": "strikerapi_calendar", "fetched_at": fetched, "gameweek": None}


def _comp(records, fetched, complete_as_of=None):
    return {"fetched_at": fetched, "complete_as_of": complete_as_of, "postponed": 0, "unmapped": [], "records": records}


def _europe_file(tmp_path, monkeypatch, competitions, *, flag="1", **over):
    payload = {"schema_version": 1, "provenance": "strikerapi_calendar", "season": SEASON,
               "built_at": _ago(hours=1), "competitions": competitions, **over}
    path = tmp_path / "strikerapi-europe.json"      # the manual layer helper writes europe.json
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv(cc.ENV_EUROPE_PATH, str(path))
    if flag is None:
        monkeypatch.delenv(cc.ENV_EUROPE_FLAG, raising=False)
    else:
        monkeypatch.setenv(cc.ENV_EUROPE_FLAG, flag)


def _ucl(club="ARS", kickoff=TUESDAY, **kw):
    fetched = _ago(**(kw or {"hours": 1}))
    return {"UCL": _comp([_record("UCL", club, "SYN", kickoff, fetched)], fetched)}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "_refresh_europe_file", lambda season: None)      # never R2
    monkeypatch.setattr(cc, "_europe_season", lambda: SEASON)
    monkeypatch.delenv(cc.ENV_EUROPE_FLAG, raising=False)
    monkeypatch.setenv(cc.ENV_MANUAL, str(tmp_path / "no-manual-layer.json"))
    cc._manual_cache.clear()
    cc._licensed_cache.clear()
    yield
    cc._licensed_cache.clear()
    cc._manual_cache.clear()


def _premium(team="ARS"):
    return cc.competitions_response("patreon_premium", team, None, None)


def _arsenal_pl(out):
    return out["teams"]["ARS"]["pl_matches"][0]


# -- flag off -------------------------------------------------------------------

@pytest.mark.parametrize("flag", [None, "0", "false", ""])
def test_flag_off_is_byte_identical_and_reads_nothing(monkeypatch, tmp_path, flag):
    _install(monkeypatch, [_snap()], [_fa("ARS", "Luton", "LUT", "2099-01-01T19:45:00Z")])
    without = json.dumps(_premium(None), sort_keys=True)
    cc._licensed_cache.clear()
    _europe_file(tmp_path, monkeypatch, _ucl(), flag=flag)

    def never(season):
        raise AssertionError("the flag is off: nothing of the new source may run")

    monkeypatch.setattr(cc, "_refresh_europe_file", never)
    # the cup row's fetch stamp is taken from the clock: compare with it normalised
    assert json.dumps(_premium(None), sort_keys=True) == without
    assert cc._europe_layer(cc.datetime.now()) is None


# -- flag on --------------------------------------------------------------------

def test_a_verified_champions_tuesday_before_a_league_saturday_fires_the_notice(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [])
    _europe_file(tmp_path, monkeypatch, _ucl())
    out = _premium()
    pl = _arsenal_pl(out)
    assert (pl["rotation"], pl["rest_whole_days_before"], pl["rest_hours_before"], pl["previous_competition"]) == (
        True, 3, 91, "UCL")
    assert [(m["competition"], m["opponent_code"], m["kickoff_utc"]) for m in out["teams"]["ARS"]["matches"]] == [
        ("UCL", "SYN", TUESDAY)]
    assert out["data"]["provenance"] == "licensed_starter+strikerapi_calendar"
    assert out["data"]["europe"]["provenance"] == "strikerapi_calendar"
    assert out["data"]["coverage"]["UCL"] == "partial" and out["data"]["coverage"]["UEL"] == "missing"


def test_completeness_is_untouched_the_calendar_stays_incomplete(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [])
    fetched = _ago(hours=1)
    _europe_file(tmp_path, monkeypatch, {
        c: _comp([_record(c, "ARS" if c == "UCL" else "CHE", "SYN", TUESDAY, fetched)], fetched, "2099-05-30")
        for c in ("UCL", "UEL", "UECL")})
    _premium()
    pl = [m for m in cc._licensed_cache["calendar"]["value"]["ARS"] if m["is_pl"]]
    assert [m["calendar_complete"] for m in pl] == [False]      # the cups are partial: unchanged rule


@pytest.mark.parametrize("competitions", [
    # the Champions League reply was rejected / never stored: Arsenal's European match is unknown
    {"UEL": None},
    # it is stored but unusable
    {"UCL": {"fetched_at": "yesterday", "records": []}, "UEL": None},
])
def test_no_notice_when_the_previous_european_match_is_unknown(monkeypatch, tmp_path, competitions):
    _install(monkeypatch, [_snap()], [_fa("ARS", "Luton", "LUT", "2098-12-30T19:45:00Z")])
    fetched = _ago(hours=1)
    good = _comp([_record("UEL", "CHE", "SYN", TUESDAY, fetched)], fetched)
    _europe_file(tmp_path, monkeypatch, {k: (good if v is None else v) for k, v in competitions.items()})
    pl = _arsenal_pl(_premium())
    # the closest KNOWN match is a cup on a partial calendar: no notice, as before
    assert pl["rotation"] is False and pl["previous_competition"] == "FA"
    assert [m for m in cc._licensed_cache["calendar"]["value"]["ARS"] if m.get("europe_prior")] == []


def test_a_cup_between_europe_and_the_league_match_does_not_inherit_the_notice(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [_fa("ARS", "Luton", "LUT", "2099-01-01T19:45:00Z")])
    _europe_file(tmp_path, monkeypatch, _ucl())
    pl = _arsenal_pl(_premium())
    assert pl["previous_competition"] == "FA" and pl["rotation"] is False


def test_a_long_rest_after_europe_does_not_warn(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [])
    _europe_file(tmp_path, monkeypatch, _ucl(kickoff="2098-12-26T20:00:00Z"))
    assert _arsenal_pl(_premium())["rotation"] is False


@pytest.mark.parametrize("over", [
    {"season": "2025-2026"}, {"provenance": "licensed_starter"}, {"provenance": "live_trial_local"},
    {"schema_version": 2},
])
def test_a_file_of_another_season_source_or_shape_is_ignored(monkeypatch, tmp_path, over):
    _install(monkeypatch, [_snap()], [])
    _europe_file(tmp_path, monkeypatch, _ucl(), **over)
    out = _premium()
    assert out["data"]["provenance"] == "licensed_starter" and "europe" not in out["data"]
    assert out["teams"]["ARS"]["matches"] == []


def test_a_stale_snapshot_is_not_used_and_the_manual_layer_applies(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [])
    _layer(tmp_path, monkeypatch)
    manual_only = _premium()
    cc._licensed_cache.clear()
    _europe_file(tmp_path, monkeypatch, _ucl(days=9))
    out = _premium()
    assert out["data"]["provenance"] == manual_only["data"]["provenance"]
    assert out["data"]["provenance"].endswith("+manual_curated") and "europe" not in out["data"]
    assert out["teams"] == manual_only["teams"]


def test_the_new_source_replaces_the_manual_layer_per_competition_never_both(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [])
    rows = [
        {"competition": comp, "club": "ARS", "venue": "A", "opponent": f"Manual {comp}", "opponent_code": "MAN",
         "date": day, "kickoff_known": True, "kickoff_utc": f"{day}T19:00:00Z"}
        for comp, day in (("UCL", "2098-12-23"), ("UEL", "2098-12-16"))
    ]
    _layer(tmp_path, monkeypatch, matches=rows)
    _europe_file(tmp_path, monkeypatch, _ucl())
    out = _premium()
    assert sorted((m["competition"], m["opponent_code"]) for m in out["teams"]["ARS"]["matches"]) == [
        ("UCL", "SYN"), ("UEL", "MAN")]
    assert out["data"]["provenance"] == "licensed_starter+strikerapi_calendar+manual_curated"
    assert out["data"]["manual"]["matches"] == 1
    assert _arsenal_pl(out)["rotation"] is True          # still the verified Champions Tuesday


def test_when_every_manual_competition_is_covered_the_manual_layer_is_gone(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [])
    _layer(tmp_path, monkeypatch, matches=[
        {"competition": "UCL", "club": "ARS", "venue": "A", "opponent": "Manual", "opponent_code": "MAN",
         "date": "2098-12-23", "kickoff_known": True, "kickoff_utc": "2098-12-23T19:00:00Z"}])
    _europe_file(tmp_path, monkeypatch, _ucl())
    out = _premium()
    assert out["data"]["provenance"] == "licensed_starter+strikerapi_calendar" and "manual" not in out["data"]


def test_the_free_payload_stays_the_constant_with_the_flag_on(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [])
    _europe_file(tmp_path, monkeypatch, _ucl())
    for tier in ("free", "patreon_tribuna"):
        assert cc.competitions_response(tier, None, None, None) == {"available": True, "tier": "free"}


def test_a_new_snapshot_is_not_hidden_by_the_cached_calendar(monkeypatch, tmp_path):
    _install(monkeypatch, [_snap()], [])
    _europe_file(tmp_path, monkeypatch, _ucl())
    assert _premium()["teams"]["ARS"]["matches"][0]["kickoff_utc"] == TUESDAY
    _europe_file(tmp_path, monkeypatch, _ucl(kickoff="2098-12-29T20:00:00Z", minutes=5))
    assert _premium()["teams"]["ARS"]["matches"][0]["kickoff_utc"] == "2098-12-29T20:00:00Z"

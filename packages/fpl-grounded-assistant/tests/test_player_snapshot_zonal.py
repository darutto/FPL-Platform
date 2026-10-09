"""
Bloque 10 -- the zonal section inside ``get_player_snapshot``.

Every test runs without network: the store is an in-memory frame (or a tmp
parquet), fixture state is injected through ``bootstrap["_gw_fixtures"]`` or
the ``_FETCH_ALL_FIXTURES`` seam, and the clock is replaced where TTLs matter.

The identity, isolation, fixture-state and no_data guards each have a test
written so that removing the guard fails it (the mutation list is in the PR).
"""
from __future__ import annotations

import copy
import json
import os as _os
import sys as _sys

import pandas as pd
import pytest

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG = _os.path.dirname(_HERE)
_PKGS = _os.path.dirname(_PKG)
for _p in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
    _os.path.join(_PKGS, "fpl-pipeline"),
    _os.path.join(_PKGS, "fpl-tactical"),
    _os.path.join(_PKGS, "fpl-historical"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_grounded_assistant  # noqa: E402,F401
from fpl_grounded_assistant import player_snapshot_zonal as pz  # noqa: E402
from fpl_grounded_assistant.final_response import (  # noqa: E402
    _extract_player_snapshot_meta,
)
from fpl_grounded_assistant.get_player_snapshot import get_player_snapshot  # noqa: E402
from fpl_grounded_assistant.renderer import render  # noqa: E402
from fpl_grounded_assistant.zonal_weakness import CURRENT_SEASON, zone_of  # noqa: E402

CENTRAL = "in-box / central"
CHE, BOU, EVE, TOT, IPS, ARS = 1, 2, 3, 4, 5, 6


# ---------------------------------------------------------------------------
# Fixtures: store, bootstrap, calendar
# ---------------------------------------------------------------------------

def _row(shooting, conceding, player, x=0.92, y=0.50, xg=0.20, match_id=1,
         situation="Open Play"):
    return {
        "season": CURRENT_SEASON, "match_id": match_id,
        "date": "2026-09-01T15:00:00", "shooting_team": shooting,
        "conceding_team": conceding, "player": player, "is_home_shot": True,
        "minute": 10, "x": x, "y": y, "xg": xg, "situation": situation,
        "shot_type": "Right Foot", "result": "Saved Shot",
    }


def _shots(shooting, conceding, player, n, **kw):
    return [_row(shooting, conceding, player, **kw) for _ in range(n)]


def store_df(extra=()):
    assert zone_of(0.92, 0.50) == CENTRAL
    rows = []
    rows += _shots("Chelsea", "Brentford", "Cole Palmer", 12, match_id=1)
    rows += _shots("Chelsea", "Brentford", "Ruben Diaz", 12, match_id=1)
    rows += _shots("Everton", "Chelsea", "Dan Defender", 12, match_id=2)
    rows += _shots("Chelsea", "Brentford", "Nine Shots", 9, match_id=1)
    rows += _shots("Chelsea", "Brentford", "Zed Zero", 12, match_id=1, xg=0.0)
    # long range only: counts toward the total, belongs to no zone
    rows += _shots("Chelsea", "Brentford", "Tom Spread", 12, match_id=1, x=0.55)
    rows += _shots("Bournemouth", "Brentford", "Sam Transfer", 12, match_id=3)
    rows += _shots("Chelsea", "Brentford", "Pat Roe", 12, match_id=1)
    rows += _shots("Chelsea", "Brentford", "Joe Same", 12, match_id=1)
    rows += _shots("Chelsea", "Brentford", "Ana Twin", 12, match_id=1)
    rows += _shots("Chelsea", "Brentford", "Ána Twin", 12, match_id=1)
    rows += _shots("Arsenal", "Brentford", "Gabriel", 12, match_id=4)
    # Tottenham leaks central in-box; Everton / Bournemouth barely concede.
    rows += _shots("Burnley", "Tottenham", "Filler A", 10, match_id=5, xg=0.30)
    rows += _shots("Burnley", "Tottenham", "Filler A", 10, match_id=6, xg=0.30)
    rows += _shots("Burnley", "Bournemouth", "Filler B", 1, match_id=7, xg=0.02)
    rows += _shots("Burnley", "Everton", "Filler C", 1, match_id=8, xg=0.02)
    rows += list(extra)
    return pd.DataFrame(rows)


def _el(id_, first, second, web, team, etype=3, **kw):
    el = {
        "id": id_, "first_name": first, "second_name": second, "web_name": web,
        "team": team, "team_code": team, "element_type": etype, "status": "a",
        "now_cost": 90, "selected_by_percent": "10.0", "form": "5.0",
        "total_points": 40, "points_per_game": "5.0", "minutes": 450,
        "expected_goals": "1.0", "expected_assists": "0.5",
        "expected_goal_involvements": "1.5", "ict_index": "30.0",
        "news": "", "news_added": None, "chance_of_playing_this_round": None,
    }
    el.update(kw)
    return el


def make_bootstrap(gw_fixtures=None):
    teams = [
        {"id": CHE, "name": "Chelsea", "short_name": "CHE"},
        {"id": BOU, "name": "Bournemouth", "short_name": "BOU"},
        {"id": EVE, "name": "Everton", "short_name": "EVE"},
        {"id": TOT, "name": "Spurs", "short_name": "TOT"},
        {"id": IPS, "name": "Ipswich", "short_name": "IPS"},
        {"id": ARS, "name": "Arsenal", "short_name": "ARS"},
    ]
    elements = [
        _el(10, "Cole", "Palmer", "Palmer", CHE),
        _el(11, "Alex", "Palmer", "Palmer", IPS),
        _el(12, "Rúben", "Díaz", "Díaz", CHE),
        _el(13, "Dan", "Defender", "Defender", EVE, etype=2),
        _el(14, "Nine", "Shots", "Shots", CHE),
        _el(15, "Zed", "Zero", "Zero", CHE),
        _el(16, "Tom", "Spread", "Spread", CHE),
        _el(17, "Sam", "Transfer", "Transfer", CHE),
        _el(18, "Pat", "Roeberts", "Roeberts", CHE),
        _el(19, "Joe", "Same", "Same", CHE),
        _el(20, "Joe", "Same", "Same", BOU),
        _el(21, "Ana", "Twin", "Twin", CHE),
        _el(22, "Gabriel dos Santos", "Magalhães", "Gabriel", ARS, etype=2),
        _el(23, "Gil", "Goalkeeper", "Goalkeeper", CHE, etype=1),
        _el(24, "Cleo", "Sheet", "Sheet", IPS),   # Ipswich: absent from the store
    ]
    return {
        "teams": teams,
        "elements": elements,
        "element_types": [
            {"id": 1, "singular_name_short": "GKP"}, {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"}, {"id": 4, "singular_name_short": "FWD"},
        ],
        "events": [{"id": 1, "deadline_time": "2026-08-15T17:30:00Z",
                    "is_current": True, "finished": False}],
        "team_fixtures": {},
        "_gw_fixtures": gw_fixtures if gw_fixtures is not None else default_calendar(),
    }


_FID = [100]


def fx(gw, home, away, state="pending", kickoff="2026-10-10T15:00:00Z"):
    """state: pending | live | done | provisional | unknown"""
    _FID[0] += 1
    flags = {
        "pending": (False, False, False), "live": (True, False, False),
        "done": (True, True, True), "provisional": (True, False, True),
    }
    row = {"id": _FID[0], "event": gw, "team_h": home, "team_a": away,
           "kickoff_time": kickoff}
    if state == "unknown":
        row.update(started=None, finished=None, finished_provisional=None)
    else:
        s, f, p = flags[state]
        row.update(started=s, finished=f, finished_provisional=p)
    return row


def cal(*rows):
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(str(r["event"]), []).append(r)
    return out


def default_calendar():
    """Today's shape: GW5 over, GW6-8 pending, GW9 outside the window."""
    return cal(
        fx(5, CHE, ARS, "done"), fx(5, BOU, EVE, "done"),
        fx(6, CHE, BOU), fx(7, EVE, CHE), fx(8, CHE, TOT), fx(9, CHE, IPS),
    )


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    pz.reset_caches()
    monkeypatch.setattr(pz, "_STORE_OVERRIDE", store_df())

    def _no_network():
        raise AssertionError("test tried to reach the network")

    monkeypatch.setattr(pz, "_FETCH_ALL_FIXTURES", _no_network)
    yield
    pz.reset_caches()


def snap(pid, bootstrap=None):
    return get_player_snapshot(pid, bootstrap or make_bootstrap())


def zonal_of(pid, bootstrap=None):
    res = snap(pid, bootstrap)
    assert res["status"] == "ok"
    return res["player"].get("zonal")


def compose(pid, bootstrap=None):
    bs = bootstrap or make_bootstrap()
    return pz.compose_player_zonal(next(e for e in bs["elements"] if e["id"] == pid), bs)


def reason_of(pid, bootstrap=None):
    return compose(pid, bootstrap).reason


# ---------------------------------------------------------------------------
# Happy path, window and units
# ---------------------------------------------------------------------------

def test_palmer_gets_zonal_with_window_of_pending_matches():
    z = zonal_of(10)
    assert z is not None
    assert z["window"] == {"gw_from": 6, "gw_to": 8}
    assert [f["gameweek"] for f in z["fixtures"]] == [6, 7, 8]
    assert [f["opponent_short"] for f in z["fixtures"]] == ["BOU", "EVE", "TOT"]
    assert all(isinstance(f["fixture_id"], int) for f in z["fixtures"])
    assert [f["is_home"] for f in z["fixtures"]] == [True, False, True]


def test_share_is_a_fraction_and_a_favorable_cross_is_named():
    z = zonal_of(10)
    assert z["zones"] == [{"zone": CENTRAL, "share": 1.0}]
    assert all(0.0 <= zz["share"] <= 1.0 for zz in z["zones"])
    tot = next(f for f in z["fixtures"] if f["opponent_short"] == "TOT")
    assert tot["status"] == "favorable"
    assert 0.0 < tot["matches"][0]["player_share"] <= 1.0
    assert z["verdict_kind"] == "favorable"
    assert "J8" in z["verdict"] and "Spurs" in z["verdict"]


def test_today_current_gameweek_finished_window_starts_at_next():
    cal_ = cal(fx(5, CHE, ARS, "done"), fx(5, BOU, EVE, "provisional"),
               fx(6, CHE, BOU), fx(7, CHE, EVE), fx(8, TOT, CHE))
    z = zonal_of(10, make_bootstrap(cal_))
    assert z["window"] == {"gw_from": 6, "gw_to": 8}
    assert 5 not in [f["gameweek"] for f in z["fixtures"]]


def test_partially_played_gameweek_keeps_only_the_pending_match():
    cal_ = cal(fx(6, CHE, BOU, "done"), fx(6, EVE, CHE), fx(7, CHE, TOT), fx(8, CHE, BOU))
    z = zonal_of(10, make_bootstrap(cal_))
    assert z["window"]["gw_from"] == 6
    assert [(f["gameweek"], f["opponent_short"]) for f in z["fixtures"]] == [
        (6, "EVE"), (7, "TOT"), (8, "BOU")]


def test_in_play_match_is_excluded_and_window_starts_after_it():
    cal_ = cal(fx(6, CHE, BOU, "live"), fx(7, CHE, EVE), fx(8, CHE, TOT), fx(9, CHE, BOU))
    z = zonal_of(10, make_bootstrap(cal_))
    assert z["window"] == {"gw_from": 7, "gw_to": 9}
    assert 6 not in [f["gameweek"] for f in z["fixtures"]]


def test_provisionally_finished_match_counts_as_finished():
    cal_ = cal(fx(6, CHE, BOU, "provisional"), fx(7, CHE, EVE))
    z = zonal_of(10, make_bootstrap(cal_))
    assert z["window"]["gw_from"] == 7


def test_kickoff_time_is_not_the_state():
    """A far-future kickoff on a started match and a past one on a pending
    match: only the explicit flags decide."""
    cal_ = cal(fx(6, CHE, BOU, "live", kickoff="2099-01-01T00:00:00Z"),
               fx(7, CHE, EVE, "pending", kickoff="2000-01-01T00:00:00Z"))
    z = zonal_of(10, make_bootstrap(cal_))
    assert [f["gameweek"] for f in z["fixtures"]] == [7]


def test_blank_gameweek_has_no_rows_and_no_invented_rival():
    cal_ = cal(fx(6, CHE, BOU), fx(8, CHE, EVE), fx(9, CHE, TOT))
    z = zonal_of(10, make_bootstrap(cal_))
    assert z["window"] == {"gw_from": 6, "gw_to": 8}
    assert [f["gameweek"] for f in z["fixtures"]] == [6, 8]


def test_double_gameweek_lists_both_matches():
    cal_ = cal(fx(6, CHE, BOU), fx(7, CHE, EVE), fx(7, TOT, CHE), fx(8, CHE, BOU))
    z = zonal_of(10, make_bootstrap(cal_))
    assert [f["gameweek"] for f in z["fixtures"]].count(7) == 2
    assert len({f["fixture_id"] for f in z["fixtures"]}) == len(z["fixtures"])


def test_postponed_fixture_without_gameweek_is_not_invented():
    cal_ = {"6": [fx(6, CHE, BOU)], "7": [fx(7, CHE, EVE)]}
    cal_["unscheduled"] = [fx(None, CHE, TOT)]
    z = zonal_of(10, make_bootstrap(cal_))
    assert "TOT" not in [f["opponent_short"] for f in z["fixtures"]]


def test_unknown_fixture_state_omits_the_section_with_a_reason():
    cal_ = cal(fx(6, CHE, BOU, "unknown"), fx(7, CHE, EVE))
    assert zonal_of(10, make_bootstrap(cal_)) is None
    assert reason_of(10, make_bootstrap(cal_)) == "fixture_state_unknown"


def test_unknown_state_inside_the_window_omits_too():
    cal_ = cal(fx(6, CHE, BOU), fx(7, CHE, EVE, "unknown"))
    assert reason_of(10, make_bootstrap(cal_)) == "fixture_state_unknown"


def test_no_pending_fixtures_omits():
    cal_ = cal(fx(37, CHE, BOU, "done"), fx(38, CHE, EVE, "done"))
    assert reason_of(10, make_bootstrap(cal_)) == "no_pending_fixtures"


def test_calendar_absent_for_the_team_omits():
    cal_ = cal(fx(6, EVE, BOU))
    assert reason_of(10, make_bootstrap(cal_)) == "no_calendar"


def test_all_rivals_without_store_data_is_availability_not_neutral():
    cal_ = cal(fx(6, CHE, IPS), fx(7, IPS, CHE), fx(8, CHE, IPS))
    z = zonal_of(10, make_bootstrap(cal_))
    assert {f["status"] for f in z["fixtures"]} == {"no_data"}
    assert z["verdict_kind"] == "no_data"
    assert "destacado" not in z["verdict"]
    text = render("get_player_snapshot", {"status": "ok", "player": {"web_name": "P", "zonal": z}})
    assert text.count("sin datos zonales del rival") == 3
    assert "sin cruce destacado" not in text


def test_a_single_no_data_row_is_not_rendered_as_neutral():
    cal_ = cal(fx(6, CHE, IPS), fx(7, CHE, EVE), fx(8, CHE, BOU))
    z = zonal_of(10, make_bootstrap(cal_))
    row = next(f for f in z["fixtures"] if f["opponent_short"] == "IPS")
    assert row["status"] == "no_data"
    assert z["verdict_kind"] == "neutral"
    text = render("get_player_snapshot", {"status": "ok", "player": {"web_name": "P", "zonal": z}})
    assert "J6 vs Ipswich (casa): sin datos zonales del rival" in text


# ---------------------------------------------------------------------------
# Profile eligibility
# ---------------------------------------------------------------------------

def test_nine_shots_has_no_profile_and_ten_has(monkeypatch):
    assert zonal_of(14) is None
    assert reason_of(14) == "no_store_profile"
    monkeypatch.setattr(
        pz, "_STORE_OVERRIDE",
        store_df(_shots("Chelsea", "Everton", "Nine Shots", 1, match_id=1)),
    )
    pz.reset_caches()
    assert zonal_of(14) is not None


def test_player_with_zero_xg_has_no_profile():
    assert zonal_of(15) is None


def test_no_zone_over_threshold_omits_the_section():
    assert reason_of(16) == "no_zone_over_threshold"
    assert zonal_of(16) is None


def test_defender_with_a_profile_gets_the_section_and_a_goalkeeper_without_does_not():
    z = zonal_of(13)
    assert z is not None and z["zones"]
    assert zonal_of(23) is None


def test_penalties_do_not_count_toward_the_profile(monkeypatch):
    monkeypatch.setattr(
        pz, "_STORE_OVERRIDE",
        store_df(_shots("Chelsea", "Everton", "Pen Taker", 20, match_id=9, situation="Penalty")),
    )
    bs = make_bootstrap()
    bs["elements"].append(_el(30, "Pen", "Taker", "Taker", CHE))
    assert zonal_of(30, bs) is None


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def test_accented_fpl_name_matches_the_unaccented_store_name():
    res = compose(12)
    assert res.store_player == "Ruben Diaz"
    assert res.method == "full_name_team_match"


def test_homonym_in_another_team_in_the_bootstrap_omits():
    assert reason_of(19) == "bootstrap_name_collision"
    assert zonal_of(19) is None and zonal_of(20) is None


def test_two_store_names_that_normalise_equal_omit():
    assert reason_of(21) == "store_name_collision"
    assert zonal_of(21) is None


def test_two_elements_named_palmer_resolve_by_full_name_not_surname():
    assert zonal_of(10) is not None
    assert zonal_of(11) is None       # Alex Palmer has no store profile


def test_near_miss_same_team_never_matches_by_substring():
    """'Pat Roeberts' (CHE) vs store 'Pat Roe' (CHE): same team, substring of
    each other -- must not be the same person."""
    assert zonal_of(18) is None
    assert reason_of(18) == "no_store_profile"


def test_transfer_with_stale_store_team_is_omitted_not_given_the_old_calendar():
    """Sam Transfer shot for Bournemouth, plays for Chelsea now: no reliable
    link, so no section -- and never Bournemouth's calendar."""
    assert reason_of(17) == "team_mismatch"
    assert zonal_of(17) is None


def test_team_control_refuses_when_the_bootstrap_team_differs_from_the_store():
    bs = make_bootstrap()
    next(e for e in bs["elements"] if e["id"] == 10)["team"] = EVE
    assert reason_of(10, bs) == "team_mismatch"


def test_calendar_is_the_bootstrap_team_not_the_store_club():
    """Rows are built from the element's team in the bootstrap: every row is a
    Chelsea match, and the other teams' fixtures are never read."""
    cal_ = cal(fx(6, CHE, BOU), fx(6, EVE, TOT), fx(7, CHE, EVE), fx(8, ARS, CHE))
    z = zonal_of(10, make_bootstrap(cal_))
    ids = {f["id"]: f for rows in cal_.values() for f in rows}
    for row in z["fixtures"]:
        assert CHE in (ids[row["fixture_id"]]["team_h"], ids[row["fixture_id"]]["team_a"])
    assert [f["opponent_short"] for f in z["fixtures"]] == ["BOU", "EVE", "ARS"]


def test_resolver_method_needs_unique_candidate_and_matching_team():
    arsenal = make_bootstrap(cal(fx(6, ARS, BOU), fx(7, ARS, EVE)))
    res = compose(22, arsenal)
    assert res.method == "resolver_exact_team_match"
    assert res.store_player == "Gabriel"
    bs = make_bootstrap()
    next(e for e in bs["elements"] if e["id"] == 22)["team"] = CHE
    assert reason_of(22, bs) == "team_mismatch"


def test_resolver_method_with_two_store_candidates_omits(monkeypatch):
    monkeypatch.setattr(
        pz, "_STORE_OVERRIDE",
        store_df(_shots("Arsenal", "Everton", "Gabriel Jesus", 12, match_id=4)),
    )
    monkeypatch.setattr(
        pz, "resolve_store_player",
        lambda name, bs: next(e for e in bs["elements"] if e["id"] == 22),
    )
    assert reason_of(22) == "store_candidates_multiple"


# ---------------------------------------------------------------------------
# Isolation: a zonal failure never touches the card
# ---------------------------------------------------------------------------

def _base(res):
    return {"status": res["status"],
            "player": {k: v for k, v in res["player"].items() if k != "zonal"}}


def test_every_omission_leaves_the_base_payload_identical(monkeypatch):
    baseline = _base(snap(10))
    for store in ("does/not/exist.parquet", None):
        monkeypatch.setattr(pz, "_STORE_OVERRIDE", store)
        pz.reset_caches()
        res = snap(10)
        assert res["status"] == "ok"
        assert "zonal" not in res["player"]
        assert _base(res) == baseline


def test_calculation_exception_drops_only_the_zonal_key(monkeypatch):
    baseline = _base(snap(10))

    def boom(*a, **k):
        raise RuntimeError("engine blew up")

    monkeypatch.setattr(pz, "build_player_outlook", boom)
    res = snap(10)
    assert res["status"] == "ok" and "zonal" not in res["player"]
    assert _base(res) == baseline
    assert reason_of(10) == "exception:RuntimeError"


def test_corrupt_store_drops_only_the_zonal_key(tmp_path, monkeypatch):
    bad = tmp_path / "understat_shots.parquet"
    bad.write_bytes(b"not a parquet file")
    monkeypatch.setattr(pz, "_STORE_OVERRIDE", bad)
    res = snap(10)
    assert res["status"] == "ok" and "zonal" not in res["player"]


def test_invalid_zonal_data_is_discarded_not_served(monkeypatch):
    real = pz.build_player_outlook

    def bad_status(*a, **k):
        out = real(*a, **k)
        out["outlook"][0]["status"] = "who_knows"
        return out

    monkeypatch.setattr(pz, "build_player_outlook", bad_status)
    assert reason_of(10) == "invalid_zonal_payload"
    assert zonal_of(10) is None


def test_out_of_range_share_is_discarded(monkeypatch):
    real = pz.player_zone_list
    monkeypatch.setattr(
        pz, "player_zone_list",
        lambda info: [{"zone": z["zone"], "share": 100.0} for z in real(info)],
    )
    assert reason_of(10) == "invalid_zonal_payload"


def test_snapshot_meta_survives_a_malformed_zonal_block():
    raw = copy.deepcopy(snap(10))
    raw["player"]["zonal"] = {"zones": "garbage"}
    meta = _extract_player_snapshot_meta(raw)
    assert meta is not None and meta.zonal is None and meta.web_name == "Palmer"


def test_status_and_meta_are_unchanged_when_the_calendar_fetch_fails(monkeypatch):
    bs = make_bootstrap()
    del bs["_gw_fixtures"]

    def down():
        raise TimeoutError("fpl down")

    monkeypatch.setattr(pz, "_FETCH_ALL_FIXTURES", down)
    res = snap(10, bs)
    assert res["status"] == "ok" and "zonal" not in res["player"]
    assert _extract_player_snapshot_meta(res).zonal is None


# ---------------------------------------------------------------------------
# Fixture-state provider: cache, timeouts, empties
# ---------------------------------------------------------------------------

def _flat(c):
    return [f for rows in c.values() for f in rows]


def _no_inject():
    bs = make_bootstrap()
    del bs["_gw_fixtures"]
    return bs


def test_provider_caches_for_60_seconds_and_refetches_when_expired(monkeypatch):
    now = {"t": 1000.0}
    calls = []
    monkeypatch.setattr(pz, "_MONOTONIC", lambda: now["t"])
    monkeypatch.setattr(
        pz, "_FETCH_ALL_FIXTURES", lambda: calls.append(1) or _flat(default_calendar()))
    bs = _no_inject()
    assert zonal_of(10, bs) is not None and len(calls) == 1
    now["t"] += 59.0
    zonal_of(10, bs)
    assert len(calls) == 1                      # still warm
    now["t"] += 2.0                             # 61 s: expired
    zonal_of(10, bs)
    assert len(calls) == 2


@pytest.mark.parametrize("payload", [[], None, {"oops": 1}, [{"id": 1}], "<html>"])
def test_empty_or_malformed_response_is_never_cached(monkeypatch, payload):
    calls = []

    def fetch():
        calls.append(1)
        return payload if len(calls) == 1 else _flat(default_calendar())

    monkeypatch.setattr(pz, "_FETCH_ALL_FIXTURES", fetch)
    bs = _no_inject()
    assert zonal_of(10, bs) is None
    assert zonal_of(10, bs) is not None         # the bad answer did not stick
    assert len(calls) == 2


def test_empty_response_reason_is_recorded(monkeypatch):
    monkeypatch.setattr(pz, "_FETCH_ALL_FIXTURES", lambda: [])
    assert reason_of(10, _no_inject()) == "fixtures_response_invalid"


def test_timeout_omits_and_is_not_cached(monkeypatch):
    calls = []

    def fetch():
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("slow")
        return _flat(default_calendar())

    monkeypatch.setattr(pz, "_FETCH_ALL_FIXTURES", fetch)
    bs = _no_inject()
    assert reason_of(10, bs) == "fixtures_fetch_failed"
    assert zonal_of(10, bs) is not None
    assert len(calls) == 2


def test_http_fetch_uses_a_short_timeout_and_no_retries(monkeypatch):
    seen = {}

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"team_h": 1, "team_a": 2}]

    import requests

    def fake_get(url, timeout):
        seen.update(url=url, timeout=timeout)
        return R()

    monkeypatch.setattr(requests, "get", fake_get)
    pz._fetch_all_fixtures_http()
    assert seen["timeout"] <= 3.0 and seen["url"].endswith("/fixtures/")


def test_injected_fixtures_win_and_never_touch_the_network():
    assert zonal_of(10) is not None           # the autouse seam would raise


def test_each_finished_flag_alone_excludes_a_fixture():
    base = {"id": 1, "event": 6, "team_h": CHE, "team_a": BOU}
    assert pz.classify_fixture({**base, "started": False, "finished": False,
                                "finished_provisional": False}) == "pending"
    assert pz.classify_fixture({**base, "started": False, "finished": True,
                                "finished_provisional": False}) == "done"
    assert pz.classify_fixture({**base, "started": False, "finished": False,
                                "finished_provisional": True}) == "done"
    assert pz.classify_fixture({**base, "started": True, "finished": False,
                                "finished_provisional": False}) == "live"


def test_a_fixture_with_a_missing_flag_is_unknown_not_pending():
    f = fx(6, CHE, BOU)
    del f["started"]
    assert pz.classify_fixture(f) == "unknown"
    f2 = fx(6, CHE, BOU)
    f2["finished"] = "false"
    assert pz.classify_fixture(f2) == "unknown"


# ---------------------------------------------------------------------------
# Provenance and the store cache
# ---------------------------------------------------------------------------

def _write_store(tmp_path, season):
    d = tmp_path / "seasons" / season
    d.mkdir(parents=True)
    path = d / "understat_shots.parquet"
    store_df().to_parquet(path, index=False)
    (d / "_tactical_latest.json").write_text(json.dumps({
        "season": season, "ingested_at": "2026-10-05T07:12:42Z",
        "n_matches": 50, "n_shots": 1398,
    }), encoding="utf-8")
    return path


def test_old_season_store_is_shown_with_a_visible_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(pz, "_STORE_OVERRIDE", _write_store(tmp_path, "2025-2026"))
    z = zonal_of(10)
    assert z is not None
    assert z["data_provenance"]["status"] == "stale_season"
    text = render("get_player_snapshot", {"status": "ok", "player": {"web_name": "Palmer", "zonal": z}})
    assert z["data_provenance"]["label"] in text


def test_thin_current_season_label_is_carried(tmp_path, monkeypatch):
    monkeypatch.setattr(pz, "_STORE_OVERRIDE", _write_store(tmp_path, "2026-2027"))
    z = zonal_of(10)
    assert z["data_provenance"]["status"] == "thin"
    assert z["data_provenance"]["label"]


def test_store_is_read_once_per_store_version(tmp_path, monkeypatch):
    path = _write_store(tmp_path, "2026-2027")
    monkeypatch.setattr(pz, "_STORE_OVERRIDE", path)
    reads = []
    real = pz._load_shots
    monkeypatch.setattr(pz, "_load_shots", lambda s: reads.append(1) or real(s))
    zonal_of(10)
    zonal_of(12)
    zonal_of(13)
    assert len(reads) == 1
    store_df(_shots("Chelsea", "Everton", "New Guy", 12, match_id=11)).to_parquet(path, index=False)
    zonal_of(10)
    assert len(reads) == 2                    # version changed -> re-read


# ---------------------------------------------------------------------------
# Contract: dataclass, serialisation, TS parity, renderer, prompt
# ---------------------------------------------------------------------------

def test_meta_carries_zonal_and_serialises_with_fractions():
    from fpl_server import _player_snapshot_meta_dict
    meta = _extract_player_snapshot_meta(snap(10))
    assert meta.zonal is not None and meta.zonal.gw_from == 6
    d = _player_snapshot_meta_dict(meta)
    z = d["zonal"]
    assert z["zones"][0]["share"] == 1.0
    assert set(z) == {"zones", "gw_from", "gw_to", "fixtures", "verdict_kind",
                      "verdict", "data_provenance"}
    assert set(z["fixtures"][0]) == {
        "gameweek", "fixture_id", "opponent", "opponent_short", "is_home", "status", "matches"}
    json.dumps(d)                               # JSON-clean


def test_meta_without_zonal_serialises_null():
    from fpl_server import _player_snapshot_meta_dict
    meta = _extract_player_snapshot_meta(snap(14))
    assert meta is not None and meta.zonal is None
    assert _player_snapshot_meta_dict(meta)["zonal"] is None


def test_typescript_mirror_declares_every_serialised_field():
    ts = open(_os.path.join(_PKGS, "fpl-ui", "lib", "types.ts"), encoding="utf-8").read()
    i = ts.index("export interface PlayerZonalOutlookMeta")
    block = ts[i - 3000:i + 1800]
    for key in ("zones", "gw_from", "gw_to", "fixtures", "verdict_kind", "verdict",
                "data_provenance", "fixture_id", "opponent_short", "player_share",
                "delta_vs_avg", "share", "status", "is_home", "gameweek"):
        assert key in block, key
    assert "zonal?: PlayerZonalOutlookMeta | null" in ts


def test_renderer_text_path_shows_zonal_with_percent_and_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(pz, "_STORE_OVERRIDE", _write_store(tmp_path, "2026-2027"))
    text = render("get_player_snapshot", snap(10))
    assert "Zonas" in text and "próximas 3 jornadas" in text
    assert "100% de su xG sin penalti" in text
    assert "J8 vs Spurs (casa): favorable" in text
    assert "muestra corta" in text


def test_renderer_without_zonal_is_the_old_card_text():
    with_z = render("get_player_snapshot", snap(10))
    res = snap(10)
    res["player"].pop("zonal")
    without = render("get_player_snapshot", res)
    assert without in with_z and "Zonas" not in without
    res["player"]["zonal"] = {"fixtures": [{}], "zones": [{}], "window": {}}
    assert render("get_player_snapshot", res) == without     # malformed -> silent


def test_prompt_rule_exists_for_the_llm_path():
    from fpl_grounded_assistant import orchestrator
    src = open(orchestrator.__file__, encoding="utf-8").read()
    assert "PLAYER_ZONAL" in src and "next 3 gameweeks" in src

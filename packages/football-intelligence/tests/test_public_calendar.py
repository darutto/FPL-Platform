"""Public-data calendar, phase F1: hand-written sample data only. No network, no clock, no files."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from football_intelligence import live_trial_calendar as ltc
from football_intelligence import public_calendar as pc
from football_intelligence.public_calendar import (
    PL_CLUB_ALIASES,
    UNKNOWN_CODE,
    SourceMatch,
    build_public_calendar,
    calendar_status,
    convert_matches,
    normalize_club_name,
    pl_club_code,
    snapshot_status,
)

NOW = datetime(2026, 10, 21, 12, 0, 0)
FETCHED = "2026-10-20T06:00:00Z"
SEASON = "2026-2027"


def _convert(competition, matches, *, complete_as_of="2026-12-31", fetched_at=FETCHED, **kw):
    return convert_matches(matches, competition=competition, season=SEASON, source="hand-written",
                           fetched_at=fetched_at, complete_as_of=complete_as_of, **kw)


def _ucl(*rows, **kw):
    return _convert("UCL", [SourceMatch("UCL", h, a, k, **extra) for h, a, k, *rest in rows
                            for extra in [rest[0] if rest else {}]], **kw)


def _pl(*rows):
    return _convert("PL", [SourceMatch("PL", h, a, k, gameweek=gw) for h, a, k, gw in rows])


# -- club names -------------------------------------------------------------

def test_twenty_clubs_and_no_alias_belongs_to_two_of_them():
    assert len(PL_CLUB_ALIASES) == 20
    seen: dict[str, str] = {}
    for code, names in PL_CLUB_ALIASES.items():
        for name in names:
            assert seen.setdefault(normalize_club_name(name), code) == code


@pytest.mark.parametrize("name, code", [
    ("Arsenal", "ARS"), ("ARSENAL FC", "ARS"), ("Nott'm Forest", "NFO"), ("Nottingham Forest", "NFO"),
    ("nottm  forest", "NFO"), ("Manchester City", "MCI"), ("Man Utd", "MUN"), ("Spurs", "TOT"),
    ("Tottenham Hotspur", "TOT"), ("Brighton & Hove Albion", "BHA"), ("Leeds United", "LEE"),
])
def test_known_names_map_to_fpl_codes(name, code):
    assert pl_club_code(name) == code


@pytest.mark.parametrize("name", ["Real Madrid", "Manchester", "Newcastle Jets", "Bayern München", ""])
def test_other_names_are_not_guessed(name):
    assert pl_club_code(name) is None


def test_names_are_compared_without_accents_or_punctuation():
    assert normalize_club_name("Bayern München") == normalize_club_name("Bayern Munchen")
    assert normalize_club_name("Nott'm Forest") == "nott m forest"


# -- the converter ----------------------------------------------------------

def test_a_match_becomes_one_record_per_premier_league_side_with_the_venue():
    snap = _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}))
    assert [(r.club, r.venue, r.opponent, r.opponent_code) for r in snap.records] == [("ARS", "H", "Real Madrid", "RMA")]
    r = snap.records[0]
    assert (r.competition, r.season, r.source, r.fetched_at, r.status) == ("UCL", SEASON, "hand-written", FETCHED, "scheduled")


def test_a_match_between_two_premier_league_clubs_gives_both_sides():
    snap = _convert("FA", [SourceMatch("FA", "Chelsea", "Man City", "2026-11-08T14:00:00Z")])
    assert sorted((r.club, r.venue, r.opponent_code) for r in snap.records) == [("CHE", "H", "MCI"), ("MCI", "A", "CHE")]


def test_a_match_without_a_premier_league_side_is_dropped():
    assert _ucl(("Real Madrid", "Bayern Munchen", "2026-10-21T19:00:00Z")).records == ()


def test_opponent_code_comes_from_the_source_then_the_injected_table_else_it_is_flagged_not_guessed():
    snap = _ucl(
        ("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}),
        ("Liverpool", "Bayern Munchen", "2026-10-22T19:00:00Z"),
        ("Chelsea", "Zzyzx Rovers", "2026-10-22T19:00:00Z"),
        known_codes={"Bayern München": "BAY"},
    )
    codes = {r.club: r.opponent_code for r in snap.records}
    assert codes == {"ARS": "RMA", "LIV": "BAY", "CHE": UNKNOWN_CODE}
    assert snap.unmapped == ("Zzyzx Rovers",)


@pytest.mark.parametrize("bad", ["RM", "REAL", "R1M", ""])
def test_a_malformed_source_code_is_not_used(bad):
    snap = _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": bad}))
    assert snap.records[0].opponent_code == UNKNOWN_CODE and snap.unmapped == ("Real Madrid",)


def test_postponed_matches_are_counted_and_not_recorded():
    snap = _convert("UCL", [
        SourceMatch("UCL", "Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", away_code="RMA"),
        SourceMatch("UCL", "Liverpool", "Real Madrid", "2026-10-22T19:00:00Z", status="postponed", away_code="RMA"),
    ])
    assert [r.club for r in snap.records] == ["ARS"] and snap.postponed == 1


@pytest.mark.parametrize("kickoff", ["2026-10-21 19:00:00", "2026-10-21T19:00:00", "tomorrow", ""])
def test_a_malformed_kickoff_fails_loudly(kickoff):
    with pytest.raises(ValueError):
        _convert("UCL", [SourceMatch("UCL", "Arsenal", "Real Madrid", kickoff)])


def test_wrong_competition_status_or_fetch_time_fail_loudly():
    with pytest.raises(ValueError):
        _convert("UCL", [SourceMatch("UEL", "Arsenal", "Real Madrid", "2026-10-21T19:00:00Z")])
    with pytest.raises(ValueError):
        _convert("UCL", [SourceMatch("UCL", "Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", status="live")])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        _convert("XYZ", [])
    with pytest.raises(ValueError):
        _convert("UCL", [], fetched_at="yesterday")


def test_records_come_out_in_kickoff_order():
    snap = _ucl(("Liverpool", "Real Madrid", "2026-10-22T19:00:00Z", {"away_code": "RMA"}),
                ("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}))
    assert [r.kickoff_utc for r in snap.records] == ["2026-10-21T19:00:00Z", "2026-10-22T19:00:00Z"]


# -- completeness -----------------------------------------------------------

def test_status_is_complete_partial_stale_or_missing():
    complete = _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}))
    partial = _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}), complete_as_of=None)
    old = _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}), fetched_at="2026-10-01T06:00:00Z")
    assert snapshot_status(complete, NOW) == "complete"
    assert snapshot_status(partial, NOW) == "partial"
    assert snapshot_status(old, NOW) == "stale"  # stale wins over complete
    assert snapshot_status(None, NOW) == "missing"


def test_the_stale_limit_is_exact_and_adjustable():
    snap = _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}), fetched_at="2026-10-13T12:00:00Z")
    assert snapshot_status(snap, NOW) == "complete"  # exactly 8 days
    assert snapshot_status(snap, NOW + timedelta(seconds=1)) == "stale"
    assert snapshot_status(snap, NOW, stale_after=timedelta(days=2)) == "stale"


def test_calendar_status_reports_every_covered_competition():
    ucl = _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}))
    status = calendar_status([ucl], ["UCL", "FA"], NOW)
    assert status["UCL"] == {"status": "complete", "source": "hand-written", "fetched_at": FETCHED,
                             "complete_as_of": "2026-12-31", "unmapped": []}
    assert status["FA"] == {"status": "missing", "source": None, "fetched_at": None, "complete_as_of": None, "unmapped": []}


# -- the calendar -----------------------------------------------------------

def _sample(**ucl_kw):
    """Arsenal: PL Sat 17 Oct, UCL Wed 21 Oct, PL Sat 24 Oct (3 whole days after Europe)."""
    ucl = _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}), **ucl_kw)
    pl = _pl(("Arsenal", "Chelsea", "2026-10-17T14:00:00Z", 8), ("Chelsea", "Arsenal", "2026-10-24T14:00:00Z", 9))
    return [pl, ucl]


def test_the_calendar_has_the_shape_competition_calendar_consumes():
    cal = build_public_calendar(_sample(), now=NOW)
    assert set(cal) == set(PL_CLUB_ALIASES)
    keys = {"kickoff_utc", "week", "gameweek", "competition", "is_pl", "venue", "opponent", "opponent_code",
            "rest_whole_days_before", "previous_competition", "rest_days_before", "rest_days_after"}
    for matches in cal.values():
        for m in matches:
            assert keys <= set(m) <= keys | {"calendar_complete"}
            assert ("calendar_complete" in m) == m["is_pl"]


def test_rest_days_use_the_same_definition_as_the_trial_calendar():
    ars = build_public_calendar(_sample(), now=NOW)["ARS"]
    assert [m["competition"] for m in ars] == ["PL", "UCL", "PL"]
    assert [m["rest_whole_days_before"] for m in ars] == [None, 4, 2]  # Sat 14:00 -> Wed 19:00 = 4d5h; Wed 19:00 -> Sat 14:00 = 2d19h
    assert ars[2]["previous_competition"] == "UCL" and ars[1]["rest_days_after"] == 2.8
    # the shared tail is the trial calendar's own function
    assert pc.finish_calendar is ltc.finish_calendar


def test_non_pl_matches_take_the_gameweek_that_follows_them():
    ars = build_public_calendar(_sample(), now=NOW)["ARS"]
    assert [m["gameweek"] for m in ars] == [8, 9, 9]
    assert ars[1]["week"] == "2026-10-19"


def test_postponed_pl_and_cup_matches_are_not_in_the_calendar():
    pl = _convert("PL", [SourceMatch("PL", "Arsenal", "Chelsea", "2026-10-17T14:00:00Z", gameweek=8),
                         SourceMatch("PL", "Chelsea", "Arsenal", "2026-10-24T14:00:00Z", status="postponed", gameweek=9)])
    ars = build_public_calendar([pl, _sample()[1]], now=NOW)["ARS"]
    assert [m["competition"] for m in ars] == ["PL", "UCL"]


def test_a_match_after_the_last_gameweek_has_no_gameweek():
    ucl = _ucl(("Arsenal", "Real Madrid", "2026-12-01T19:00:00Z", {"away_code": "RMA"}))
    assert build_public_calendar([_sample()[0], ucl], now=NOW)["ARS"][-1]["gameweek"] is None


def test_clubs_without_matches_still_have_an_empty_calendar():
    assert build_public_calendar(_sample(), now=NOW)["LIV"] == []


# -- missing data is not "no match" ----------------------------------------

def _pl_flags(cal):
    return {m["calendar_complete"] for ms in cal.values() for m in ms if m["is_pl"]}


def test_a_complete_and_fresh_calendar_is_marked_complete():
    assert _pl_flags(build_public_calendar(_sample(), now=NOW)) == {True}


def test_a_partial_competition_marks_every_pl_match_incomplete():
    assert _pl_flags(build_public_calendar(_sample(complete_as_of=None), now=NOW)) == {False}


def test_a_stale_competition_marks_every_pl_match_incomplete():
    assert _pl_flags(build_public_calendar(_sample(fetched_at="2026-10-01T06:00:00Z"), now=NOW)) == {False}


def test_a_covered_competition_without_a_snapshot_is_missing_and_marks_incomplete():
    cal = build_public_calendar(_sample(), now=NOW, covered=["UCL", "FA"])
    assert _pl_flags(cal) == {False}


def test_covering_less_than_you_have_is_allowed_and_an_uncovered_partial_does_not_count():
    fa = _convert("FA", [SourceMatch("FA", "Arsenal", "Man City", "2026-11-08T14:00:00Z")], complete_as_of=None)
    cal = build_public_calendar([*_sample(), fa], now=NOW, covered=["UCL"])
    assert _pl_flags(cal) == {True}
    assert [m["competition"] for m in cal["ARS"]][-1] == "FA"  # it is still in the calendar


def test_without_any_other_competition_the_claim_is_vacuous_and_says_so_only_by_what_is_covered():
    assert _pl_flags(build_public_calendar([_sample()[0]], now=NOW)) == {True}
    assert _pl_flags(build_public_calendar([_sample()[0]], now=NOW, covered=["UCL"])) == {False}


def test_two_snapshots_of_the_same_competition_are_refused():
    ucl = _sample()[1]
    with pytest.raises(ValueError):
        build_public_calendar([ucl, ucl], now=NOW)


# -- complete_as_of is a bound, not a yes/no flag ----------------------------

def _flags_by_day(cal, club="ARS"):
    return {m["kickoff_utc"][:10]: m["calendar_complete"] for m in cal[club] if m["is_pl"]}


def _season_pl(*days):
    rows = [("Arsenal", "Chelsea", f"{day}T14:00:00Z", i + 1) for i, day in enumerate(days)]
    return _pl(*rows)


def test_a_pl_match_before_the_bound_is_complete_and_one_after_it_is_not():
    ucl = _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}), complete_as_of="2026-11-30")
    pl = _season_pl("2026-10-24", "2026-11-28", "2026-12-20")
    flags = _flags_by_day(build_public_calendar([pl, ucl], now=NOW))
    assert flags == {"2026-10-24": True, "2026-11-28": True, "2026-12-20": False}


def test_the_bound_is_inclusive_and_compares_dates_not_times():
    ucl = _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}), complete_as_of="2026-11-30")
    pl = _convert("PL", [SourceMatch("PL", "Arsenal", "Chelsea", "2026-11-30T20:00:00Z", gameweek=1),
                         SourceMatch("PL", "Chelsea", "Arsenal", "2026-12-01T00:00:00Z", gameweek=2)])
    assert _flags_by_day(build_public_calendar([pl, ucl], now=NOW)) == {"2026-11-30": True, "2026-12-01": False}


def test_with_two_competitions_the_earliest_bound_rules():
    ucl = _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}), complete_as_of="2026-12-31")
    fa = _convert("FA", [SourceMatch("FA", "Arsenal", "Man City", "2026-11-08T14:00:00Z")], complete_as_of="2026-11-15")
    pl = _season_pl("2026-11-10", "2026-11-20", "2026-12-05")
    flags = _flags_by_day(build_public_calendar([pl, ucl, fa], now=NOW))
    assert flags == {"2026-11-10": True, "2026-11-20": False, "2026-12-05": False}


def test_a_bound_never_rescues_a_partial_or_stale_competition():
    pl = _season_pl("2026-10-24")
    ok = _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}), complete_as_of="2026-12-31")
    partial = _convert("FA", [SourceMatch("FA", "Arsenal", "Man City", "2026-11-08T14:00:00Z")], complete_as_of=None)
    stale = _convert("FA", [SourceMatch("FA", "Arsenal", "Man City", "2026-11-08T14:00:00Z")],
                     complete_as_of="2026-12-31", fetched_at="2026-10-01T06:00:00Z")
    for other in (partial, stale):
        assert _flags_by_day(build_public_calendar([pl, ok, other], now=NOW)) == {"2026-10-24": False}


def test_a_malformed_bound_fails_loudly():
    for bad in ("2026-13-01", "30/11/2026", "November", ""):
        with pytest.raises(ValueError):
            _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}), complete_as_of=bad)


def test_calendar_status_keeps_complete_and_exposes_the_bound():
    ucl = _ucl(("Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", {"away_code": "RMA"}), complete_as_of="2026-11-30")
    entry = calendar_status([ucl], ["UCL"], NOW)["UCL"]
    assert entry["status"] == "complete" and entry["complete_as_of"] == "2026-11-30"

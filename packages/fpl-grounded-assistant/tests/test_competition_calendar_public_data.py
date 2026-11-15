"""The public-data calendar through competition_calendar: same consumer, rotation suppressed on a hole. No network."""
from __future__ import annotations

from datetime import datetime

import pytest

import fpl_server  # noqa: F401  (puts the sibling packages on sys.path, as test_fixtures_competitions does)
from fpl_grounded_assistant import competition_calendar as cc
from football_intelligence.public_calendar import SourceMatch, build_public_calendar, convert_matches

NOW = datetime(2026, 10, 21, 12, 0, 0)


def _snapshots(complete_as_of):
    ucl = convert_matches(
        [SourceMatch("UCL", "Arsenal", "Real Madrid", "2026-10-21T19:00:00Z", away_code="RMA")],
        competition="UCL", season="2026-2027", source="hand-written", fetched_at="2026-10-20T06:00:00Z",
        complete_as_of=complete_as_of)
    pl = convert_matches(
        [SourceMatch("PL", "Arsenal", "Chelsea", "2026-10-17T14:00:00Z", gameweek=8),
         SourceMatch("PL", "Chelsea", "Arsenal", "2026-10-24T14:00:00Z", gameweek=9)],
        competition="PL", season="2026-2027", source="hand-written", fetched_at="2026-10-20T06:00:00Z",
        complete_as_of="2026-12-31")
    return [pl, ucl]


@pytest.fixture()
def serve(monkeypatch):
    def _serve(calendar):
        monkeypatch.setattr(cc, "_calendar", lambda: calendar)
    return _serve


def _premium(team="ARS"):
    return cc.competitions_response("patreon_premium", team, None, None)["teams"]["ARS"]


def test_the_public_calendar_is_served_by_the_existing_consumer(serve):
    serve(build_public_calendar(_snapshots("2026-12-31"), now=NOW))
    arsenal = _premium()
    assert [(m["competition"], m["opponent_code"], m["venue"]) for m in arsenal["matches"]] == [("UCL", "RMA", "H")]
    assert [m["gameweek"] for m in arsenal["pl_matches"]] == [8, 9]


def test_a_complete_calendar_warns_of_rotation_after_europe(serve):
    serve(build_public_calendar(_snapshots("2026-12-31"), now=NOW))
    flags = {m["gameweek"]: m["rotation"] for m in _premium()["pl_matches"]}
    assert flags == {8: False, 9: True}  # Wed 19:00 -> Sat 14:00 is 2 whole days after a UCL match


def test_a_partial_competition_suppresses_the_rotation_warning(serve):
    serve(build_public_calendar(_snapshots(None), now=NOW))
    arsenal = _premium()
    assert [m["rotation"] for m in arsenal["pl_matches"]] == [False, False]
    assert [m["competition"] for m in arsenal["matches"]] == ["UCL"]  # the match itself is still shown


def test_a_stale_competition_suppresses_the_rotation_warning(serve):
    serve(build_public_calendar(_snapshots("2026-12-31"), now=datetime(2026, 11, 20)))
    assert [m["rotation"] for m in _premium()["pl_matches"]] == [False, False]


def test_a_calendar_without_the_flag_behaves_as_before(serve):
    calendar = build_public_calendar(_snapshots("2026-12-31"), now=NOW)
    for matches in calendar.values():
        for m in matches:
            m.pop("calendar_complete", None)
    serve(calendar)
    assert {m["gameweek"]: m["rotation"] for m in _premium()["pl_matches"]} == {8: False, 9: True}


def test_a_pl_match_after_the_guaranteed_window_does_not_warn(serve):
    # Complete only to 2026-10-23: the Saturday 24 Oct match is outside the guarantee, so no rotation call is made.
    serve(build_public_calendar(_snapshots("2026-10-23"), now=NOW))
    assert {m["gameweek"]: m["rotation"] for m in _premium()["pl_matches"]} == {8: False, 9: False}

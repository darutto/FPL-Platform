"""StrikerAPI ``list_games`` -> calendar snapshot: the converter and its completeness rule.

Synthetic games in the shape of a real reply (invented clubs apart from the Premier League names, invented
dates and ids); no network, no vendor rows.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from football_intelligence import strikerapi_calendar as sc
from football_intelligence.public_calendar import (
    UNKNOWN_CODE, CompetitionSnapshot, FixtureRecord, build_public_calendar,
)

SEASON = "2026-2027"
FETCHED = "2026-11-26T08:00:00Z"


def game(i, *, status="scheduled", stage="League Phase", starts="2027-01-27T20:00:00.000Z",
         home=("Arsenal", "ARS"), away=None):
    away = away or (f"Synthetic FC {i}", f"S{i % 10}X"[:3])
    return {
        "game_id": f"g{i}", "stage": stage, "season": 2026, "date": (starts or "")[:10], "starts_at": starts,
        "status": status, "status_detail": None, "venue": "x", "city": "x", "neutral_site": False,
        "attendance": None, "result": None,
        "home": {"team_id": i, "name": home[0], "abbrev": home[1], "score": None},
        "away": {"team_id": 1000 + i, "name": away[0], "abbrev": away[1], "score": None},
    }


def league_phase(n=144, last="2027-01-27T20:00:00.000Z", **kw):
    """n games: all on 2026-10-20 except the last one, which is on *last*."""
    games = [game(i, starts="2026-10-20T19:00:00.000Z", home=(f"Home {i}", "HOM"), **kw) for i in range(n - 1)]
    games.append(game(n - 1, starts=last, **kw))
    return games


def convert(games, comp="UCL", whole=True):
    return sc.convert_competition(games, competition=comp, season=SEASON, fetched_at=FETCHED, paged_to_end=whole)


# -- rows ---------------------------------------------------------------------

def test_a_premier_league_game_becomes_a_club_record_in_utc():
    snap = convert([game(1, away=("Synthetic Rovers", "SYN"))])
    (r,) = snap.records
    assert (r.club, r.opponent, r.opponent_code, r.venue, r.kickoff_utc, r.status, r.source) == (
        "ARS", "Synthetic Rovers", "SYN", "H", "2027-01-27T20:00:00Z", "scheduled", sc.PROVENANCE)


def test_final_is_played_and_the_pl_aliases_map_the_real_spellings():
    games = [game(1, status="final", home=("Brighton & Hove Albion", "BHA"), away=("AFC Bournemouth", "BOU"))]
    snap = convert(games)
    assert sorted((r.club, r.venue, r.status) for r in snap.records) == [("BHA", "H", "played"), ("BOU", "A", "played")]


def test_an_opponent_without_a_three_letter_code_is_unmapped_never_guessed():
    snap = convert([game(1, away=("Synthetic United", "SY1")), game(2, away=("Synthetic City", None))])
    assert {r.opponent_code for r in snap.records} == {UNKNOWN_CODE}
    assert snap.unmapped == ("Synthetic City", "Synthetic United")


def test_postponed_is_skipped_and_counted():
    snap = convert([game(1, status="postponed"), game(2)])
    assert len(snap.records) == 1 and snap.postponed == 1


@pytest.mark.parametrize("broken", [
    {"status": "abandoned"}, {"status": "cancelled"}, {"status": "live"}, {"status": None},
    {"starts_at": None}, {"starts_at": "2027-01-27 20:00"}, {"starts_at": "soon"},
    {"starts_at": "2027-01-27T20:00:00+01:00"}, {"starts_at": "2027-01-27T20:00:00"},
    {"game_id": ""}, {"home": {"name": "", "abbrev": "X"}}, {"away": None},
])
def test_one_bad_row_rejects_the_whole_competition(broken):
    games = [game(1), {**game(2), **broken}]
    with pytest.raises(sc.SourceRejected):
        convert(games)


def test_a_bad_row_that_has_no_premier_league_side_still_rejects():
    with pytest.raises(sc.SourceRejected):
        convert([game(1), game(2, status="mystery", home=("Home", "HOM"))])


def test_a_duplicated_game_id_and_an_empty_reply_are_rejected():
    with pytest.raises(sc.SourceRejected):
        convert([game(1), game(1)])
    with pytest.raises(sc.SourceRejected):
        convert([])


# -- completeness -------------------------------------------------------------

@pytest.mark.parametrize("comp,n", [("UCL", 144), ("UEL", 144), ("UECL", 108)])
def test_a_whole_league_phase_is_complete_up_to_its_last_date(comp, n):
    assert convert(league_phase(n), comp).complete_as_of == "2027-01-27"


@pytest.mark.parametrize("games,whole", [
    (league_phase(143), True),            # one game short
    (league_phase(145), True),            # more than the stage can have
    (league_phase(144), False),           # paging did not reach the end
])
def test_a_short_or_unpaged_list_claims_nothing(games, whole):
    assert convert(games, whole=whole).complete_as_of is None


def test_a_postponed_league_phase_game_claims_nothing():
    games = league_phase()
    games[3] = {**games[3], "status": "postponed"}
    assert convert(games).complete_as_of is None


def test_an_unknown_knockout_stage_never_extends_the_bound():
    games = league_phase() + [game(500, stage="Knockout Play-offs", starts="2027-02-17T20:00:00.000Z")]
    snap = convert(games)
    assert snap.complete_as_of == "2027-01-27"
    assert any(r.kickoff_utc.startswith("2027-02-17") for r in snap.records)   # still shown


def _pl(club, kickoff, gw):
    return FixtureRecord("PL", SEASON, club, "SYN", "SYN", kickoff, "H", "scheduled", "fpl_api", FETCHED, gw)


def test_between_matchday_eight_and_the_draw_a_later_january_match_is_not_complete():
    ucl = convert(league_phase(last="2027-01-20T20:00:00.000Z"))
    pl = CompetitionSnapshot("PL", SEASON, "fpl_api", FETCHED, None,
                             (_pl("ARS", "2027-01-17T15:00:00Z", 22), _pl("ARS", "2027-01-30T15:00:00Z", 23)))
    calendar = build_public_calendar([ucl, pl], now=datetime(2026, 11, 27), covered=("UCL",))
    flags = {m["kickoff_utc"][:10]: m["calendar_complete"] for m in calendar["ARS"] if m["is_pl"]}
    assert flags == {"2027-01-17": True, "2027-01-30": False}


# -- the stored shape ----------------------------------------------------------

def test_the_stored_snapshot_round_trips():
    snap = convert(league_phase())
    again = sc.snapshot_from_dict("UCL", SEASON, sc.snapshot_to_dict(snap))
    assert again == snap


@pytest.mark.parametrize("change", [
    lambda d: d["records"][0].update(source="licensed_starter"),
    lambda d: d["records"][0].update(competition="UEL"),
    lambda d: d["records"][0].update(season="2025-2026"),
    lambda d: d["records"][0].update(kickoff_utc="later"),
    lambda d: d.update(fetched_at="yesterday"),
    lambda d: d.update(complete_as_of="January"),
])
def test_a_tampered_stored_snapshot_is_refused(change):
    data = sc.snapshot_to_dict(convert(league_phase()))
    change(data)
    with pytest.raises((ValueError, KeyError, TypeError)):
        sc.snapshot_from_dict("UCL", SEASON, data)

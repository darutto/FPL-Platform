"""The synthetic recording ``--dry-run`` replays: no token, no network, nothing captured from the provider.

Shapes follow sportmonks-client CONTRACT.md; every player name and id is invented. The clubs are real Premier
League names because the alias table maps clubs by name. Two clubs, one PL fixture on the recording's Saturday
(predicted XI in the daily read, confirmed with the bench in the poll read), one Carabao tie, one UCL tie that
the store drops.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sportmonks_client.transport import TransportResponse

from .fpl import FplFeed

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
SEASON_ID = 25000
ARS, CHE = 900001, 900002

_PEOPLE = {  # provider id -> (FPL element id or None, first, second, birth date, club, grid slot, position)
    780001: (5001, "Arlo", "Quintavalle", "1998-01-01", ARS, "1:1", "Goalkeeper"),
    780002: (5002, "Bram", "Vesterholt", "1997-02-02", ARS, "2:1", "Right Back"),
    780003: (5003, "Cato", "Wyndham-Ross", "1996-03-03", ARS, "2:2", "Centre Back"),
    780004: (5004, "Dario", "Xelto", "1995-04-04", ARS, "2:3", "Left Back"),
    780005: (None, "Ezio", "Unpaired", "1994-05-05", ARS, None, None),
    780011: (5011, "Finn", "Zalewski-Orr", "2000-01-01", CHE, "1:1", "Goalkeeper"),
    780012: (5012, "Gus", "Abbotsleigh", "1999-02-02", CHE, "2:1", "Left Back"),
    780013: (5013, "Hal", "Brinkworth", "1993-03-03", CHE, "2:2", "Centre Back"),
    780014: (5014, "Ivo", "Colebrook", "1992-04-04", CHE, "2:3", "Right Back"),
}


def _club(tid: int) -> dict[str, Any]:
    return {"id": tid, "name": {ARS: "Arsenal", CHE: "Chelsea"}[tid], "short_code": {ARS: "ARS", CHE: "CHE"}[tid]}


def _participant(tid: int, location: str) -> dict[str, Any]:
    return {**_club(tid), "meta": {"location": location}}


def _pl_fixture(confirmed: bool) -> dict[str, Any]:
    lineups = [{"id": 10 + i, "player_id": pid, "team_id": club, "type_id": 11, "formation_field": slot,
                "player_name": f"{first} {second}", "detailedposition": {"id": i, "name": position}}
               for i, (pid, (_, first, second, _born, club, slot, position)) in enumerate(_PEOPLE.items()) if slot]
    if confirmed:
        lineups.append({"id": 99, "player_id": 780005, "team_id": ARS, "type_id": 12, "formation_field": None,
                        "player_name": "Ezio Unpaired"})
    return {"id": 860001, "league_id": 8, "starting_at": "2026-10-24 14:00:00", "state": {"developer_name": "NS"},
            "participants": [_participant(ARS, "home"), _participant(CHE, "away")], "lineups": lineups,
            "formations": [{"participant_id": ARS, "formation": "4-3-3"}, {"participant_id": CHE, "formation": "3-4-3"}],
            "metadata": [{"type_id": 572, "values": {"confirmed": confirmed}}]}


def _squad(club: int) -> list[dict[str, Any]]:
    return [{"id": pid + 1, "player_id": pid, "team_id": club, "jersey_number": n,
             "player": {"id": pid, "name": f"{first} {second}", "display_name": f"{first[0]}. {second}",
                        "date_of_birth": born}}
            for n, (pid, (_, first, second, born, c, *_rest)) in enumerate(_PEOPLE.items(), 1) if c == club]


def _cup(fid: int, league: int, home: dict[str, Any], away: dict[str, Any],
         when: str = "2026-10-29 19:45:00") -> dict[str, Any]:
    return {"id": fid, "league_id": league, "starting_at": when, "state": {"developer_name": "NS"},
            "participants": [{**home, "meta": {"location": "home"}}, {**away, "meta": {"location": "away"}}]}


_INVENTED_TOWN = {"id": 910001, "name": "Invented Town", "short_code": "IVT"}
_FICTIONAL_FC = {"id": 910002, "name": "Fictional FC", "short_code": "FFC"}

PROVIDER: dict[str, Any] = {
    "seasons": {"data": [{"id": SEASON_ID, "is_current": True}, {"id": 24000, "is_current": False}]},
    f"teams/seasons/{SEASON_ID}": {"data": [_club(ARS), _club(CHE)]},
    f"squads/teams/{ARS}": {"data": _squad(ARS)},
    f"squads/teams/{CHE}": {"data": _squad(CHE)},
    f"teams/{ARS}": {"data": {**_club(ARS), "sidelined": [
        {"id": 650001, "player_id": 780003, "team_id": ARS, "category": "injury", "start_date": "2026-10-01",
         "end_date": None, "games_missed": 2, "completed": False}]}},
    f"teams/{CHE}": {"data": {**_club(CHE), "sidelined": []}},
    # a club's cups are read over a long look-ahead (fetch.CUP_LOOKAHEAD_DAYS), not the 14-day window
    f"fixtures/between/2026-10-24/2027-06-20/{ARS}": {"data": [
        _cup(870001, 27, _club(ARS), _INVENTED_TOWN), _cup(870002, 2, _club(ARS), _FICTIONAL_FC),
        _cup(870003, 27, _club(ARS), _FICTIONAL_FC, when="2026-12-16 20:00:00")]},
    f"fixtures/between/2026-10-24/2027-06-20/{CHE}": {"data": []},
    "fixtures/between/2026-10-24/2026-11-06": {"data": [_pl_fixture(confirmed=False)]},
    "fixtures/between/2026-10-17/2026-10-23": {"data": []},
    "fixtures/between/2026-10-24/2026-10-24": {"data": [_pl_fixture(confirmed=True)]},
}

FEED = FplFeed(
    bootstrap={"teams": [{"id": 1, "short_name": "ARS"}, {"id": 2, "short_name": "CHE"}],
               "events": [{"id": 9, "deadline_time": "2026-10-24T12:30:00Z"}],
               "elements": [{"id": el, "first_name": first, "second_name": second, "web_name": second,
                             "birth_date": born, "team": 1 if club == ARS else 2, "minutes": 450}
                            for el, first, second, born, club, *_ in _PEOPLE.values() if el]},
    fixtures=[{"id": 3001, "team_h": 1, "team_a": 2, "kickoff_time": "2026-10-24T14:00:00Z", "event": 9}],
)


# --- backfill dry run: one finished match before the recording's Saturday, with a stale "not confirmed" flag -----------
BACKFILL_DAY = "2026-10-10"
BACKFILL_FEED = FplFeed(
    bootstrap=FEED.bootstrap,
    fixtures=[{"id": 3000, "team_h": 2, "team_a": 1, "kickoff_time": f"{BACKFILL_DAY}T14:00:00Z", "event": 7},
              *FEED.fixtures],
)


def _finished_fixture() -> dict[str, Any]:
    fixture = _pl_fixture(confirmed=False)  # the provider's flag is still false after full time
    return {**fixture, "id": 860000, "starting_at": f"{BACKFILL_DAY} 14:00:00", "state": {"developer_name": "FT"},
            "participants": [_participant(CHE, "home"), _participant(ARS, "away")]}


BACKFILL_PROVIDER: dict[str, Any] = {**PROVIDER, f"fixtures/between/{BACKFILL_DAY}/2026-10-23": {"data": [_finished_fixture()]}}


class RecordedTransport:
    """Answers each request from :data:`PROVIDER` by its path; anything unrecorded is a 404."""

    def __init__(self, recording: Mapping[str, Any] = PROVIDER) -> None:
        self.recording = recording

    def request(self, method: str, url: str, *, params: Mapping[str, Any], timeout: float) -> TransportResponse:
        path = url.split("/v3/football/", 1)[-1]
        if path not in self.recording:
            return TransportResponse(404, {}, {"message": "not recorded"})
        return TransportResponse(200, {}, self.recording[path])


def identifiers() -> set[str]:
    """Every name and id in the recording that must never appear in the job's output (the logs are public)."""
    out: set[str] = set()
    for pid, (el, first, second, *_rest) in _PEOPLE.items():
        out |= {str(pid), first, second, f"{first} {second}"} | ({str(el)} if el else set())
    return out | {str(ARS), str(CHE), "860000", "860001", "870001", "870002", "650001", "Invented Town", "Fictional FC"}

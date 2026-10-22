"""B3 step 1: licensed matchday store, provider records -> derived tables.

Synthetic data only: the record shapes are the ones CONTRACT.md (sportmonks-client) documents, the names
and ids are invented. No trial or production capture is ever committed.
"""
from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from football_intelligence.ingestion.licensed.derive import FplFixture, derive, lineup_confirmed, team_codes_from

OBSERVED = "2026-10-24T12:00:00Z"
ARS, CHE, AVL = 900001, 900002, 900003
#: Provider player id -> FPL element id; 700099 has no pair on purpose.
CROSSWALK = {700001 + i: 501 + i for i in range(14)}
UNMATCHED = 700099
FPL = [FplFixture(301, "ARS", "CHE"), FplFixture(302, "AVL", "ARS")]
TEAMS = {ARS: "ARS", CHE: "CHE", AVL: "AVL"}


def _team(tid, name, location, short=None):
    return {"id": tid, "name": name, "short_code": short or name[:3].upper(), "meta": {"location": location}}


def _row(rid, pid, team, slot=None, position=None, starter=True):
    return {"id": rid, "player_id": pid, "team_id": team, "type_id": 11 if starter else 12,
            "formation_field": slot, "player_name": f"Invented Player {pid}",
            **({"detailedposition": {"id": 1, "name": position}} if position else {})}


def _pl_fixture(confirmed=False, metadata=True):
    home = [_row(1, 700001, ARS, "1:1", "Goalkeeper"), _row(2, 700002, ARS, "2:1", "Right Back"),
            _row(3, 700003, ARS, "2:2", "Centre Back"), _row(4, 700004, ARS, "2:3", "Centre Back"),
            _row(5, 700005, ARS, "2:4", "Left Back"), _row(6, 700006, ARS, starter=False),
            _row(7, UNMATCHED, ARS, "3:1", "Right Midfield")]
    away = [_row(11, 700011, CHE, "1:1", "Goalkeeper"), _row(12, 700012, CHE, "2:1", "Left Back"),
            _row(13, 700013, CHE, "2:2", "Centre Back"), _row(14, 700014, CHE, "2:3", "Right Back")]
    return {"id": 800001, "league_id": 8, "starting_at": "2026-10-24 14:00:00", "state": {"developer_name": "NS"},
            "participants": [_team(ARS, "Arsenal", "home"), _team(CHE, "Chelsea", "away")],
            "lineups": home + away,
            "formations": [{"participant_id": ARS, "formation": "4-3-3"}, {"participant_id": CHE, "formation": "3-4-3"}],
            "metadata": [{"type_id": 572, "values": {"confirmed": confirmed}}] if metadata else []}


def _derive(**over):
    args = dict(observed_at=OBSERVED, season="2026-27", pl_fixtures=[_pl_fixture()], squads=[], sidelined=[],
                team_fixtures=[], fpl_fixtures=FPL, team_codes=TEAMS, crosswalk=CROSSWALK)
    args.update(over)
    return derive(**args)


# ---------------------------------------------------------------- lineups

def test_snapshots_are_keyed_by_the_fpl_fixture_and_carry_the_providers_flag():
    out = _derive()
    assert [(s["fixture_id"], s["team"], s["formation"], s["confirmed"]) for s in out.lineup_snapshots] == [
        (301, "ARS", "4-3-3", False), (301, "CHE", "3-4-3", False)]
    ars = out.lineup_snapshots[0]
    assert (ars["n_starters"], ars["n_bench"], ars["state"], ars["observed_at"]) == (6, 1, "scheduled", OBSERVED)


@pytest.mark.parametrize("fixture,expected", [
    ({"metadata": [{"type_id": 572, "values": {"confirmed": True}}]}, True),
    ({"metadata": [{"type_id": 572, "values": {"confirmed": False}}]}, False),
    ({"metadata": [{"type_id": 572, "values": {"confirmed": "yes"}}]}, None),
    ({"metadata": [{"type_id": 1, "values": {"confirmed": True}}]}, None),
    ({}, None),
])
def test_confirmed_is_the_providers_flag_never_inferred(fixture, expected):
    assert lineup_confirmed(fixture) is expected


def test_side_follows_the_grid_rule_home_and_away_mirrored():
    side = {s["element"]: s["side"] for s in _derive().lineup_slots}
    assert side[CROSSWALK[700002]] == "right"   # home right back, col 1
    assert side[CROSSWALK[700005]] == "left"    # home left back, last col
    assert side[CROSSWALK[700003]] is None      # inner column
    assert side[CROSSWALK[700001]] is None      # goalkeeper row
    assert side[CROSSWALK[700012]] == "left"    # away col 1 is the away team's left
    assert side[CROSSWALK[700014]] == "right"


def test_the_bench_has_no_position_grid_or_side():
    bench = [s for s in _derive().lineup_slots if not s["starter"]]
    assert bench == [{"fixture_id": 301, "team": "ARS", "observed_at": OBSERVED, "element": CROSSWALK[700006],
                      "starter": False, "detailed_position": None, "grid_slot": None, "side": None}]


def test_an_unmatched_player_is_dropped_and_counted():
    out = _derive()
    assert all(s["element"] in CROSSWALK.values() for s in out.lineup_slots)
    assert out.report.players_unmatched == 1 and out.report.lineup_rows_seen == 11


def test_a_fixture_with_no_fpl_pair_is_dropped_and_counted():
    out = _derive(fpl_fixtures=[FplFixture(302, "AVL", "ARS")])
    assert out.lineup_snapshots == () and out.report.fixtures_unmatched == 1


def test_a_malformed_observed_at_fails():
    with pytest.raises(ValueError):
        _derive(observed_at="2026-10-24 12:00")


# --------------------------------------------------------- sidelined and squads

def test_sidelined_is_deduplicated_by_sideline_id_and_keyed_by_fpl_ids():
    row = {"id": 650001, "player_id": 700003, "team_id": ARS, "category": "injury", "start_date": "2026-10-01",
           "end_date": None, "games_missed": 2, "completed": False}
    out = _derive(sidelined=[row, dict(row), {**row, "id": 650002, "team_id": 999999},
                             {**row, "id": 650003, "team_id": 999999, "player_id": UNMATCHED}])
    assert out.sidelined == ({"element": CROSSWALK[700003], "team": "ARS", "category": "injury",
                              "start_date": "2026-10-01", "end_date": None, "games_missed": 2, "completed": False,
                              "observed_at": OBSERVED},)
    assert out.report.sidelined_duplicates == 1 and out.report.teams_unmatched == 1
    # The unmatched-club rows are dropped on the club; they do not count as unmatched players.
    assert out.report.players_unmatched == 1  # only the lineup's own unmatched player


def test_squads_keep_matched_players_of_pl_clubs():
    out = _derive(squads=[{"player_id": 700002, "team_id": ARS, "jersey_number": 2},
                          {"player_id": UNMATCHED, "team_id": ARS, "jersey_number": 99}])
    assert out.squad_membership == ({"team": "ARS", "element": CROSSWALK[700002], "jersey_number": 2,
                                     "observed_at": OBSERVED},)


# ---------------------------------------------------------------- cups

def _cup(fid, league, home, away, when="2026-10-29 19:45:00", state="NS"):
    return {"id": fid, "league_id": league, "starting_at": when, "state": {"developer_name": state},
            "participants": [_team(home[0], home[1], "home", *home[2:]), _team(away[0], away[1], "away", *away[2:])]}


def test_cups_keep_fa_and_efl_drop_europe_and_are_always_partial():
    rows = [_cup(1, 27, (ARS, "Arsenal"), (910001, "Invented Town", "IVT")),
            _cup(1, 27, (ARS, "Arsenal"), (910001, "Invented Town", "IVT")),   # same tie, second club's call
            _cup(2, 24, (910002, "Made Up Rovers", "MUR"), (CHE, "Chelsea"), when="2027-01-09 15:00:00"),
            _cup(3, 2, (ARS, "Arsenal"), (910003, "Fictional FC", "FFC")),      # UCL: public sources, not here
            _cup(4, 8, (ARS, "Arsenal"), (CHE, "Chelsea")),                     # PL: not a cup
            _cup(5, 27, (AVL, "Aston Villa"), (910004, "Nowhere United", "NWU"), state="POSTPONED")]
    out = _derive(team_fixtures=rows)
    by = {c.competition: c for c in out.cup_snapshots}
    assert set(by) == {"FA", "EFL"}
    assert all(c.complete_as_of is None and not c.is_complete for c in out.cup_snapshots)
    assert [(r.club, r.opponent_code, r.venue, r.kickoff_utc) for r in by["EFL"].records] == [
        ("ARS", "IVT", "H", "2026-10-29T19:45:00Z")]
    assert by["EFL"].postponed == 1
    assert [(r.club, r.venue) for r in by["FA"].records] == [("CHE", "A")]
    assert out.report.other_competitions_dropped == 1 and out.report.cup_fixtures_kept == 3


# ------------------------------------------------------------- identity rules

def test_team_codes_come_from_the_alias_table_never_guessed():
    assert team_codes_from([{"id": ARS, "name": "Arsenal FC"}, {"id": 910001, "name": "Invented Town"}]) == {ARS: "ARS"}
    with pytest.raises(ValueError, match="one FPL code"):
        team_codes_from([{"id": ARS, "name": "Arsenal"}, {"id": 1, "name": "Arsenal FC"}])


def test_no_provider_id_or_player_name_survives_into_the_tables():
    out = _derive(squads=[{"player_id": 700002, "team_id": ARS, "jersey_number": 2}],
                  sidelined=[{"id": 650001, "player_id": 700003, "team_id": ARS, "category": "injury"}])
    text = json.dumps([out.lineup_snapshots, out.lineup_slots, out.sidelined, out.squad_membership], default=str)
    for provider_id in [*CROSSWALK, UNMATCHED, ARS, CHE, 800001, 650001]:
        assert str(provider_id) not in text
    assert "Invented Player" not in text
    assert "7000" not in json.dumps(asdict(out.report))

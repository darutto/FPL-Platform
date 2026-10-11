"""The live-trial adapter, on a small synthetic capture (no live data in the repository)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from football_intelligence.distribution.runtime import RuntimeBuildHandle
from football_intelligence.distribution.service import publish_build
from football_intelligence.distribution.store import InMemoryArtifactStore
from football_intelligence.features.registry_v2 import ROLE_MAPPING_VERSION_V3
from football_intelligence.features.store_v2 import build_features_v2, validate_feature_build_v2
from football_intelligence.ingestion import live_trial as lt
from football_intelligence.ingestion.builder import validate_build
from football_intelligence.ingestion.builder_v2 import validate_context_build
from football_intelligence.ingestion.team_registry import load_team_registry
from football_intelligence.provenance import LIVE_TRIAL_LOCAL, LiveTrialProvenanceRefused

SEED = Path(lt.__file__).parent / "team_registry_seed.json"


def _participant(pid, name, where, country=462):
    return {"id": pid, "name": name, "short_code": name[:3].upper(), "country_id": country, "gender": "male",
            "meta": {"location": where}}


def _fixture(fid, league, home, away, when, state="FT", stage="Regular Season", leg="1/1", round_name=None, season=100):
    return {"id": fid, "league_id": league, "season_id": season, "starting_at": when, "leg": leg,
            "state": {"developer_name": state}, "stage": {"name": stage},
            "round": {"name": round_name} if round_name else None,
            "participants": [_participant(home[0], home[1], "home", home[2]), _participant(away[0], away[1], "away", away[2])]}


def _lineup(lid, player, team, kind, position, minutes=None, slot="2:1"):
    details = [] if minutes is None else [{"type_id": 119, "data": {"value": minutes}}]
    return {"id": lid, "player_id": player, "team_id": team, "type_id": kind, "formation_field": slot if kind == 11 else None,
            "detailedposition": {"name": position} if kind == 11 else None, "details": details}


def make_capture():
    arsenal, beta, foreign = (1, "Arsenal", 462), (2, "Beta FC", 462), (50, "Gamma Calcio", 251)
    players, pairs, elements, squads = [], [], [], []
    names = {1: ["Ann Able", "Bob Baker", "Cy Cook", "Dee Dunn"], 2: ["Eve East", "Fay Ford", "Gus Gray", "Hal Hunt"]}
    pid = 1000
    for club, who in names.items():
        for index, name in enumerate(who):
            pid += 1
            players.append({"id": pid, "name": name, "squad_team_id": club})
            elements.append({"id": pid - 900, "first_name": name.split()[0], "second_name": name.split()[1],
                             "web_name": name.split()[1], "team": club + 10, "element_type": 3, "birth_date": f"199{index}-01-0{club}",
                             "status": "a", "news": "", "chance_of_playing_next_round": None,
                             "chance_of_playing_this_round": None, "minutes": 90})
            pairs.append({"sportmonks_id": str(pid), "fpl_id": pid - 900, "method": "full_name_birth_date"})
            squads.append({"id": pid + 5000, "team_id": club, "player_id": pid, "start": "2026-07-01", "end": "2030-06-30"})
    # one provider player with no identity pair
    players.append({"id": 2000, "name": "Nobody Known", "squad_team_id": 1})
    squads.append({"id": 7000, "team_id": 1, "player_id": 2000, "start": "2026-07-01", "end": None})

    team_fixtures = [
        _fixture(1, 8, arsenal, beta, "2026-08-22 14:00:00", round_name="1"),
        _fixture(2, 8, beta, arsenal, "2026-12-01 20:00:00", state="NS", round_name="15"),
        _fixture(3, 2, foreign, arsenal, "2026-09-16 19:00:00", stage="League Stage"),
        _fixture(4, 27, arsenal, beta, "2026-09-23 18:45:00", stage="3rd Round"),
        _fixture(5, 2286, beta, foreign, "2026-08-27 19:00:00", stage="Play-offs", leg="1/2"),
        _fixture(6, 2286, foreign, beta, "2026-09-03 19:00:00", stage="Play-offs", leg="2/2"),
    ]
    detail = [{
        "id": 1,
        "formations": [{"id": 31, "participant_id": 1, "formation": "4-3-3"}, {"id": 32, "participant_id": 2, "formation": "4-4-2"}],
        "lineups": [
            _lineup(101, 1001, 1, 11, "Right Back", 90),
            _lineup(102, 1002, 1, 11, "Attacking Midfield", 70),
            _lineup(103, 1003, 1, 12, None, 20),       # came on: an appearance
            _lineup(104, 1004, 1, 12, None, None),     # unused substitute: not an appearance
            _lineup(105, 1005, 2, 11, "Centre Back", None),   # on the field without minutes: dropped and counted
            _lineup(106, 1006, 2, 11, "Left Midfield", 90),
            _lineup(107, 2000, 1, 11, "Attacker", 90),        # provider player with no pair
        ],
        "events": [{"id": 900, "type_id": 18, "participant_id": 1, "player_id": 1003, "related_player_id": 1002, "minute": 70},
                   {"id": 901, "type_id": 19, "participant_id": 1, "player_id": 1001, "related_player_id": None, "minute": 50}],
    }]
    return {"schema_version": 1, "scope": {"season_id": 100}, "teams": [{"id": 1, "name": "Arsenal", "country_id": 462, "gender": "male", "short_code": "ARS"},
                                                                     {"id": 2, "name": "Beta FC", "country_id": 462, "gender": "male", "short_code": "BET"}],
            "squads": squads, "players": players, "team_fixtures": team_fixtures, "match_detail": detail,
            "countries": {"462": "England", "251": "Italy"}, "fpl": {"elements": elements, "teams": []},
            "identity_pairs": pairs}


@pytest.fixture
def capture():
    return make_capture()


# ---------------------------------------------------------------- teams

def test_slug_folds_accents_and_specials():
    assert lt.slug("Tromsø IL") == "tromso-il" and lt.slug("Universitatea Craiova") == "universitatea-craiova"
    assert lt.slug("Atlético  Madrid!") == "atletico-madrid"
    with pytest.raises(lt.LiveTrialAdapterError):
        lt.slug("!!!")


def test_every_club_gets_a_trial_local_seed_and_never_a_governed_one(capture):
    registry, index = lt.build_team_registry(capture)
    assert set(index) == {1, 2, 50}
    assert {seed.status for seed in registry.teams} == {lt.TRIAL_SEED_STATUS}
    assert registry.resolve("sportmonks", "50", "2026-09-01") == index[50]
    assert registry.resolve("fpl", "11", "2026-09-01") == index[1], "Premier League clubs carry their FPL id"
    assert registry.resolve("fpl", "50", "2026-09-01") is None, "an opponent has no other provider"


def test_a_club_keeps_the_identity_the_checked_in_seed_already_gave_it(capture):
    registry, index = lt.build_team_registry(capture)
    governed = {t.registry_key: t.canonical_team_id for t in load_team_registry(SEED).teams}
    assert index[1] == governed["england|arsenal|men|senior"]


def test_no_trial_local_seed_is_in_the_checked_in_registry():
    text = SEED.read_text(encoding="utf-8")
    assert lt.TRIAL_SEED_STATUS not in text and "trial-local" not in text


def test_two_provider_clubs_with_one_key_stop_the_build(capture):
    capture["team_fixtures"].append(_fixture(9, 2, (51, "Gamma  Calcio", 251), (1, "Arsenal", 462), "2026-10-01 19:00:00"))
    with pytest.raises(lt.LiveTrialAdapterError, match="share the registry key"):
        lt.build_team_registry(capture)


def test_a_club_without_a_known_country_stops_the_build(capture):
    capture["team_fixtures"].append(_fixture(9, 2, (52, "Delta SC", 9999), (1, "Arsenal", 462), "2026-10-01 19:00:00"))
    with pytest.raises(lt.LiveTrialAdapterError, match="no known country"):
        lt.build_team_registry(capture)


def test_the_fpl_crosswalk_needs_three_unanimous_pairs_per_club(capture):
    assert lt.club_crosswalk(capture) == {1: 11, 2: 12}
    thin = copy.deepcopy(capture)
    thin["identity_pairs"] = [p for p in thin["identity_pairs"] if int(p["sportmonks_id"]) not in (1001, 1002)]
    with pytest.raises(lt.LiveTrialAdapterError, match="unanimous"):
        lt.build_team_registry(thin)
    split = copy.deepcopy(capture)
    split["fpl"]["elements"][0]["team"] = 99
    with pytest.raises(lt.LiveTrialAdapterError, match="unanimous"):
        lt.build_team_registry(split)


# ---------------------------------------------------------------- fixtures

def test_league_meetings_are_numbered_by_date_and_cups_by_stage_and_leg(capture):
    keys = lt.derive_fixture_keys(capture["team_fixtures"][:2])
    assert keys == {1: "league-home-meeting-1", 2: "league-home-meeting-2"}
    cups = lt.derive_fixture_keys(capture["team_fixtures"][2:])
    assert cups == {3: "cup-league-stage-single", 4: "cup-3rd-round-single", 5: "cup-play-offs-leg-1", 6: "cup-play-offs-leg-2"}


def test_every_key_is_in_the_governed_grammar(capture):
    from football_intelligence.ingestion.keys import validate_fixture_key
    for key in lt.derive_fixture_keys(capture["team_fixtures"]).values():
        validate_fixture_key(key)


def test_a_third_league_meeting_or_an_odd_leg_stops_the_build(capture):
    third = _fixture(9, 8, (1, "Arsenal", 462), (2, "Beta FC", 462), "2027-03-01 15:00:00")
    with pytest.raises(lt.LiveTrialAdapterError, match="more than two"):
        lt.derive_fixture_keys(capture["team_fixtures"][:2] + [third])
    with pytest.raises(lt.LiveTrialAdapterError, match="leg"):
        lt.derive_fixture_keys([_fixture(8, 2, (1, "Arsenal", 462), (2, "Beta FC", 462), "2026-09-01 19:00:00", leg="3/3")])


@pytest.mark.parametrize("state,status", [
    ("NS", "scheduled"), ("FT", "completed"), ("AET", "completed"), ("FT_PEN", "completed"),
    ("INPLAY_2ND_HALF", "live"), ("HT", "live"), ("POSTPONED", "postponed"), ("CANCELLED", "cancelled"),
    ("ABANDONED", "abandoned"), ("SOMETHING_NEW", "unknown")])
def test_provider_states_map_to_canonical_statuses(state, status):
    assert lt.fixture_status({"state": {"developer_name": state}}) == status


def test_stage_names_map_and_the_unmappable_are_unknown_on_purpose():
    stage = lambda n: lt.context_stage({"stage": {"name": n}})
    assert (stage("Regular Season"), stage("League Stage"), stage("2nd Qualifying Round"), stage("8th Finals")) == \
        ("league", "league_phase", "qualification", "round_of_16")
    assert stage("3rd Round") == "unknown" and stage("Play-offs") == "unknown"


def test_canonical_fixtures_carry_stable_distinct_identity(capture):
    _, index = lt.build_team_registry(capture)
    one = lt.canonical_fixtures(capture, index)
    two = lt.canonical_fixtures(copy.deepcopy(capture), index)
    assert [f["fixture_id"] for f in one] == [f["fixture_id"] for f in two]
    assert len({f["fixture_id"] for f in one}) == 6
    first = next(f for f in one if f["provider_id"] == 1)
    assert first["gameweek"] == 1 and first["status"] == "completed" and first["kickoff_utc"] == "2026-08-22T14:00:00Z"


# ---------------------------------------------------------------- replay source

def _source(capture):
    _, index = lt.build_team_registry(capture)
    fixtures = lt.canonical_fixtures(capture, index)
    return lt.replay_source(capture, fixtures, 8, captured_at="2026-10-11T00:00:00Z")


def test_the_source_is_stamped_live_trial_local(capture):
    source, _ = _source(capture)
    assert source["_fixture"]["assumption_status"] == LIVE_TRIAL_LOCAL


def test_only_players_who_took_the_field_become_appearances_and_minutes_are_the_providers(capture):
    source, report = _source(capture)
    rows = {r["player_id"]: r for r in source["lineups"]}
    assert set(rows) == {1001, 1002, 1003, 1006, 2000}, "unused substitute and minutes-less starter are not appearances"
    assert (rows[1001]["minutes"], rows[1002]["minutes"], rows[1003]["minutes"]) == (90, 70, 20)
    assert rows[1003]["started"] is False and rows[1001]["started"] is True
    assert report["dropped_lineup_rows"] == {"on_field_without_minutes": 1, "unused_substitute": 1}


def test_lineups_carry_the_team_formation_the_grid_slot_and_the_live_position(capture):
    source, _ = _source(capture)
    row = next(r for r in source["lineups"] if r["player_id"] == 1002)
    assert (row["formation"], row["grid_slot"], row["position"]) == ("4-3-3", "2:1", "Attacking Midfield")
    assert {f["formation"] for f in source["formations"]} == {"4-3-3", "4-4-2"}


def test_substitutions_come_from_type_18_events_with_on_and_off_the_right_way_round(capture):
    source, _ = _source(capture)
    assert source["substitutions"] == [{"id": 900, "fixture_id": 1, "team_id": 1, "player_off_id": 1002,
                                        "player_on_id": 1003, "minute": 70}]


def test_a_fixture_that_is_not_completed_contributes_no_lineups(capture):
    capture["team_fixtures"][0]["state"]["developer_name"] = "INPLAY_2ND_HALF"
    source, _ = _source(capture)
    assert source["lineups"] == [] and source["substitutions"] == []


def test_identity_is_the_mapping_pairs_and_nothing_else(capture):
    source, _ = _source(capture)
    assert {c["sportmonks_id"] for c in source["player_crosswalks"]} == {str(p["sportmonks_id"]) for p in capture["identity_pairs"]}
    assert "2000" not in {c["sportmonks_id"] for c in source["player_crosswalks"]}


# ---------------------------------------------------------------- context

def test_scheduling_knowledge_follows_the_stated_assumptions(capture):
    _, index = lt.build_team_registry(capture)
    fixtures = lt.canonical_fixtures(capture, index)
    payload = lt.context_payload(capture, fixtures, index, captured_at="2026-10-11T00:00:00Z")["canonical"]
    done = next(f for f in fixtures if f["provider_id"] == 1)
    rows = [r for r in payload["fixture_schedule_snapshots"] if r["fixture_id"] == done["fixture_id"]]
    assert {(r["observed_at_utc"], r["status"]) for r in rows} == {
        (lt.SCHEDULE_PUBLISHED_AT, "scheduled"), ("2026-08-22T17:00:00Z", "completed")}
    future = next(f for f in fixtures if f["provider_id"] == 2)
    assert [r["status"] for r in payload["fixture_schedule_snapshots"] if r["fixture_id"] == future["fixture_id"]] == ["scheduled"]
    assert {r["assumption_status"] for table in payload.values() for r in table} == {LIVE_TRIAL_LOCAL}
    assert payload["team_standing_snapshots"] == []


def test_tiers_follow_the_competition(capture):
    _, index = lt.build_team_registry(capture)
    tiers = {f["league_id"]: f["context_tier"] for f in lt.canonical_fixtures(capture, index)}
    assert tiers == {8: "league", 2: "continental", 27: "domestic_cup", 2286: "continental"}


# ---------------------------------------------------------------- the whole build

@pytest.fixture
def store(tmp_path, capture):
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(capture), encoding="utf-8")
    report = lt.build_store(path, tmp_path / "store", captured_at="2026-10-11T00:00:00Z")
    return tmp_path / "store", report


def test_the_whole_build_validates_and_every_store_is_live_trial_local(store):
    root, report = store
    pl = validate_build(root / "v1/premier-league/builds/live-trial")
    assert pl["assumption_status_summary"] == {LIVE_TRIAL_LOCAL: 1} and pl["source"]["source_kind"] == "local-live-trial"
    assert pl["row_counts"]["fixtures"] == 2 and pl["row_counts"]["lineups"] == 4
    assert pl["quarantine_counts"]["unmatched_player"] == 1, "the provider player with no pair is quarantined, not minted"
    context = validate_context_build(root / "context/builds-v2/live-trial")
    assert context["assumption_status"] == LIVE_TRIAL_LOCAL
    assert report["trial_local_seeds"] == 3 and {c["competition"] for c in report["competitions"]} == {
        "premier-league", "champions-league", "conference-league", "efl-cup"}


def test_the_report_has_counts_and_no_names(store):
    _, report = store
    text = json.dumps(report)
    assert "Arsenal" not in text and "Able" not in text and "Gamma" not in text


def test_no_publication_or_serving_path_accepts_the_built_stores(store):
    root, _ = store
    with pytest.raises(LiveTrialProvenanceRefused):
        publish_build(InMemoryArtifactStore(), "football", root / "v1/premier-league/builds/live-trial")
    # the serving handle cannot even read a locally built pointer, and the trial's own handle opens nothing else
    from football_intelligence.distribution.errors import RemoteValidationError
    with pytest.raises(RemoteValidationError):
        RuntimeBuildHandle(root / "v1/premier-league").manifest()
    assert lt.LiveTrialBuildHandle(root / "v1/premier-league").manifest()["build_id"] == "live-trial"


def test_the_trial_handle_refuses_a_store_that_is_not_live_trial(tmp_path):
    from football_intelligence.ingestion.builder import build_from_fixture
    fixture = Path(__file__).parent / "fixtures" / "sportmonks_replay_v1.json"
    build_from_fixture(fixture, tmp_path, build_id="mock")
    with pytest.raises(lt.LiveTrialAdapterError, match="only live_trial_local"):
        lt.LiveTrialBuildHandle(tmp_path).manifest()


def test_features_build_on_the_live_stores_with_the_v3_map(store, tmp_path):
    root, _ = store
    base = lt.LiveTrialBuildHandle(root / "v1/premier-league")
    context = root / "context/builds-v2/live-trial"
    features = tmp_path / "features"
    build_features_v2(base, context, features, feature_build_id="live-trial", built_at="2026-10-11T00:00:00Z",
                      role_map_version=ROLE_MAPPING_VERSION_V3, assumption_status=LIVE_TRIAL_LOCAL)
    manifest = validate_feature_build_v2(features / "builds-v2/live-trial", base, context)
    assert manifest["assumption_status"] == LIVE_TRIAL_LOCAL
    summary = pd.read_parquet(features / "builds-v2/live-trial/datasets/player_role_window_summary.parquet")
    assert set(summary.role_mapping_version) == {ROLE_MAPPING_VERSION_V3}


def test_a_second_build_with_the_same_capture_is_identical(tmp_path, capture):
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(capture), encoding="utf-8")
    one = lt.build_store(path, tmp_path / "a", captured_at="2026-10-11T00:00:00Z")
    two = lt.build_store(path, tmp_path / "b", captured_at="2026-10-11T00:00:00Z")
    assert one == two
    first = json.loads((tmp_path / "a/v1/premier-league/builds/live-trial/manifest.json").read_text())
    second = json.loads((tmp_path / "b/v1/premier-league/builds/live-trial/manifest.json").read_text())
    assert first["content_hashes"] == second["content_hashes"]


def test_the_published_date_assumption_is_pinned_and_precedes_every_fixture(capture):
    assert lt.SCHEDULE_PUBLISHED_AT == "2026-06-01T00:00:00Z" and lt.RESULT_KNOWN_AFTER_HOURS == 3
    _, index = lt.build_team_registry(capture)
    fixtures = lt.canonical_fixtures(capture, index)
    assert all(f["kickoff_utc"] > lt.SCHEDULE_PUBLISHED_AT for f in fixtures)

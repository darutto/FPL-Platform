from __future__ import annotations
import copy, json, socket
from pathlib import Path
import pytest
from football_intelligence.ingestion.builder_v2 import build_context_v2, replay_context_v2
from football_intelligence.ingestion.context_v2 import (BANDS, ContextValidationError, active_teams,
    normalize_context, rank_table, select_schedule, select_standings)

FIXTURE = Path(__file__).parent / "fixtures/canonical_context_v2.json"
def payload(): return json.loads(FIXTURE.read_text())["canonical"]
def normalized(value=None): return normalize_context(value or payload())

def test_fixture_schedule_strict_independent_as_of_and_future_known():
    tables, _ = normalized(); early = select_schedule(tables["fixture_schedule_snapshots"], "2026-07-01T00:00:00Z")
    assert len(early) == 1 and early[0]["scheduled_kickoff_utc"] == "2026-07-10T15:00:00Z"
    assert select_schedule(tables["fixture_schedule_snapshots"], "2026-06-01T00:00:00Z") == ()
    assert select_schedule(tables["fixture_schedule_snapshots"], "2026-07-06T00:00:00Z")[0]["status"] == "postponed"

def test_equal_timestamp_duplicate_collapses_and_conflict_fails_order_neutrally():
    value = payload(); value["fixture_schedule_snapshots"].append(copy.deepcopy(value["fixture_schedule_snapshots"][0]))
    assert len(normalized(value)[0]["fixture_schedule_snapshots"]) == 2
    value["fixture_schedule_snapshots"][-1]["status"] = "cancelled"
    with pytest.raises(ContextValidationError, match="conflicting"): normalized(value)
    value["fixture_schedule_snapshots"].reverse()
    with pytest.raises(ContextValidationError, match="conflicting"): normalized(value)

def test_latest_incomplete_standings_falls_back_without_mixing():
    tables, warnings = normalized(); selected = select_standings(tables["team_standing_snapshots"], tables["competition_memberships"], "comp_1", "season_1", "2026-07-01T00:00:00Z")
    assert len(selected) == 4 and {r["as_of_utc"] for r in selected} == {"2026-06-01T00:00:00Z"}
    assert [r["team_id"] for r in selected] == ["team_b", "team_a", "team_c", "team_d"]
    assert warnings == ()

def test_no_complete_table_is_explicit_empty_and_rows_cannot_define_membership():
    value = payload(); value["competition_memberships"] = value["competition_memberships"][:-1]
    tables, _ = normalized(value)
    selected = select_standings(tables["team_standing_snapshots"], tables["competition_memberships"], "comp_1", "season_1", "2026-07-01T00:00:00Z")
    assert selected == ()
    value = payload(); value["team_standing_snapshots"] = [r for r in value["team_standing_snapshots"] if r["team_id"] != "team_d"]
    tables, _ = normalized(value)
    assert select_standings(tables["team_standing_snapshots"], tables["competition_memberships"], "comp_1", "season_1", "2026-07-01T00:00:00Z") == ()

@pytest.mark.parametrize(("winner", "loser"), [
    # Every lower-priority field favors the loser, isolating adjusted points.
    ({"team_id":"z","points_before_deduction":7,"points_deduction":0,"goal_difference":0,"goals_for":0,"wins":0},
     {"team_id":"a","points_before_deduction":6,"points_deduction":0,"goal_difference":9,"goals_for":9,"wins":9}),
    # Goals scored, wins, and canonical ID favor the loser, isolating goal difference.
    ({"team_id":"z","points_before_deduction":6,"points_deduction":0,"goal_difference":2,"goals_for":2,"wins":1},
     {"team_id":"a","points_before_deduction":6,"points_deduction":0,"goal_difference":1,"goals_for":9,"wins":9}),
    # Wins and canonical ID favor the loser, isolating goals scored.
    ({"team_id":"z","points_before_deduction":6,"points_deduction":0,"goal_difference":1,"goals_for":2,"wins":1},
     {"team_id":"a","points_before_deduction":6,"points_deduction":0,"goal_difference":1,"goals_for":1,"wins":9}),
    # Canonical ID favors the loser, isolating wins.
    ({"team_id":"z","points_before_deduction":6,"points_deduction":0,"goal_difference":1,"goals_for":2,"wins":2},
     {"team_id":"a","points_before_deduction":6,"points_deduction":0,"goal_difference":1,"goals_for":2,"wins":1}),
    # All numeric inputs tie, isolating canonical team ID.
    ({"team_id":"a","points_before_deduction":6,"points_deduction":0,"goal_difference":1,"goals_for":2,"wins":1},
     {"team_id":"z","points_before_deduction":6,"points_deduction":0,"goal_difference":1,"goals_for":2,"wins":1}),
])
def test_literal_ranking_tiebreaks_are_independently_causal(winner, loser):
    assert rank_table((loser, winner))[0]["team_id"] == winner["team_id"]

def test_deduction_observed_disagreement_warning_and_missing_observed_allowed():
    value = payload(); rows = value["team_standing_snapshots"][:4]; rows[0]["points_deduction"] = 7
    rows[0]["observed_position"] = None
    _, warnings = normalized(value)
    assert warnings and all(set(w) == {"reason","competition_id","season_id","as_of_utc","team_id"} for w in warnings)

@pytest.mark.parametrize("n,expected", [(1,["top"]),(2,["top","lower_mid"]),(3,["top","upper_mid","lower_mid"]),(4,list(BANDS)),(5,["top","top","upper_mid","lower_mid","bottom"])])
def test_quartile_formula_all_boundaries(n, expected):
    rows = tuple({"team_id":f"t{i}","points_before_deduction":n-i,"points_deduction":0,"goal_difference":0,"goals_for":0,"wins":0} for i in range(n))
    assert [r["league_position_band"] for r in rank_table(rows)] == expected

def test_membership_changes_are_effective_time_aware():
    tables, _ = normalized(); memberships = list(tables["competition_memberships"]); memberships[3] = {**memberships[3], "effective_from_utc":"2026-06-15T00:00:00Z"}
    assert active_teams(memberships,"comp_1","season_1","2026-06-01T00:00:00Z") == ("team_a","team_b","team_c")
    assert len(active_teams(memberships,"comp_1","season_1","2026-06-20T00:00:00Z")) == 4

def test_standings_as_of_equal_to_cutoff_is_excluded():
    tables, _ = normalized()
    selected = select_standings(tables["team_standing_snapshots"], tables["competition_memberships"], "comp_1", "season_1", "2026-06-01T00:00:00Z")
    assert selected == ()
    assert len(select_standings(tables["team_standing_snapshots"], tables["competition_memberships"], "comp_1", "season_1", "2026-06-01T00:00:01Z")) == 4

def test_membership_effective_from_is_inclusive_and_effective_to_is_exclusive():
    tables, _ = normalized(); memberships = list(tables["competition_memberships"])
    memberships[3] = {**memberships[3], "effective_from_utc":"2026-06-15T00:00:00Z", "effective_to_utc":"2026-06-20T00:00:00Z"}
    assert "team_d" not in active_teams(memberships,"comp_1","season_1","2026-06-14T23:59:59Z")
    assert "team_d" in active_teams(memberships,"comp_1","season_1","2026-06-15T00:00:00Z")
    assert "team_d" in active_teams(memberships,"comp_1","season_1","2026-06-19T23:59:59Z")
    assert "team_d" not in active_teams(memberships,"comp_1","season_1","2026-06-20T00:00:00Z")

def test_missing_ranking_input_and_nonactive_contamination_rejected_as_context():
    value = payload(); value["team_standing_snapshots"][0]["wins"] = None
    tables, _ = normalized(value); assert select_standings(tables["team_standing_snapshots"],tables["competition_memberships"],"comp_1","season_1","2026-06-10T00:00:00Z") == ()

def test_reversed_input_stable_build_hashes_warnings_replay_roots_and_no_network(tmp_path, monkeypatch):
    first = build_context_v2(FIXTURE,tmp_path/"one",build_id="same",built_at="2026-07-01T00:00:00Z")
    changed = json.loads(FIXTURE.read_text()); [changed["canonical"][name].reverse() for name in changed["canonical"]]
    reverse = tmp_path/"reverse.json"; reverse.write_text(json.dumps(changed))
    second = build_context_v2(reverse,tmp_path/"two",build_id="same",built_at="2026-07-01T00:00:00Z")
    assert first["content_hashes"] == second["content_hashes"] and first["parquet_byte_hashes"] == second["parquet_byte_hashes"]
    replay = replay_context_v2(tmp_path/"one/builds-v2/same/manifest.json",FIXTURE,tmp_path/"three")
    assert replay["parquet_byte_hashes"] == first["parquet_byte_hashes"]
    monkeypatch.setattr(socket,"socket",lambda *a,**k: (_ for _ in ()).throw(AssertionError("network")))
    assert build_context_v2(FIXTURE,tmp_path/"offline",build_id="offline")["build_id"] == "offline"

def test_invalid_build_never_activates_and_v1_pointer_is_untouched(tmp_path):
    (tmp_path/"_football_latest.json").write_text("v1")
    with pytest.raises(RuntimeError): build_context_v2(FIXTURE,tmp_path,build_id="bad",fail_after_write=True)
    assert not (tmp_path/"_football_v2_latest.json").exists() and (tmp_path/"_football_latest.json").read_text() == "v1"

@pytest.mark.parametrize("build_id", ["../escape", "UPPER", "double--dash", "", None])
def test_build_id_containment_grammar(build_id, tmp_path):
    with pytest.raises(ValueError, match="build_id"):
        build_context_v2(FIXTURE, tmp_path, build_id=build_id)

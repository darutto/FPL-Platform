"""The M1-M3 checks: their statistics and their independent calendar, on tiny hand-made inputs."""
from __future__ import annotations

import json

import pytest

from football_data_contract.enums import AvailabilityState
from football_intelligence.features.registry_v2 import ROLE_MAPPING_VERSION_V3
from football_intelligence.features.store_v2 import build_features_v2
from football_intelligence.ingestion import live_trial_checks as chk
from football_intelligence.ingestion import live_trial as lt
from football_intelligence.modules.contracts import ModuleStatus
from football_intelligence.provenance import LIVE_TRIAL_LOCAL

from test_live_trial_adapter import capture, make_capture, store  # noqa: F401  (fixtures)


# ---------------------------------------------------------------- statistics

def test_brier_is_the_mean_squared_error_and_empty_is_none():
    assert chk.brier([(1.0, 1), (0.0, 0)]) == 0.0
    assert chk.brier([(0.5, 1), (0.5, 0)]) == 0.25
    assert chk.brier([(0.9, 0)]) == pytest.approx(0.81)
    assert chk.brier([]) is None


def test_calibration_bands_keep_empty_bands_and_put_one_in_the_top_band():
    bands = chk.calibration_bands([(0.05, 0), (0.05, 1), (0.95, 1), (1.0, 1), (0.6, 0)])
    by_band = {b["band"]: b for b in bands}
    assert by_band["0.0-0.1"]["n"] == 2 and by_band["0.0-0.1"]["observed_rate"] == 0.5
    assert by_band["0.9-1.0"]["n"] == 2 and by_band["0.9-1.0"]["observed_rate"] == 1.0
    assert by_band["0.3-0.5"]["n"] == 0 and by_band["0.3-0.5"]["mean_predicted"] is None
    assert sum(b["n"] for b in bands) == 5


def test_agreement_counts_exact_matches():
    assert chk.agreement([("a", "a"), ("a", "b"), ("c", "c")]) == {"n": 3, "agree": 2, "rate": 2 / 3}
    assert chk.agreement([]) == {"n": 0, "agree": 0, "rate": None}


@pytest.mark.parametrize("slot,width,home,side", [
    ("2:1", 4, True, "right"), ("2:4", 4, True, "left"),      # home: col 1 is the team's right
    ("2:1", 4, False, "left"), ("2:4", 4, False, "right"),    # away is mirrored
    ("2:2", 4, True, None), ("2:3", 4, False, None),          # inner cells say no side
    ("1:1", 1, True, None),                                   # the goalkeeper's row
    ("4:1", 2, True, None),                                   # a row too narrow to have an edge
    (None, 4, True, None), ("garbage", 4, True, None), ("x:y", 4, True, None)])
def test_a_grid_cell_speaks_for_a_side_only_on_the_edge_of_a_wide_row(slot, width, home, side):
    assert chk.grid_side(slot, width, home) == side


def test_live_positions_map_to_role_and_flank_through_the_v3_map():
    assert (chk.role_of("Right Midfield"), chk.flank_of("Right Midfield")) == ("winger", "right")
    assert (chk.role_of("Attacking Midfield"), chk.flank_of("Attacking Midfield")) == ("attacking_midfield", "center")
    assert (chk.role_of("Centre Back"), chk.flank_of("Centre Back")) == ("center_back", "center")
    assert chk.role_of(None) is None and chk.role_of("Sweeper-keeper") is None and chk.flank_of("Nope") is None


# ---------------------------------------------------------------- the independent calendar

def _f(fid, kickoff, status="completed", league=8, weight=1.0, continental=False):
    return {"id": fid, "league_id": league, "kickoff": kickoff, "status": status, "weight": weight, "continental": continental}


CUT = "2026-10-10T14:00:00Z"


def test_trailing_window_is_inclusive_at_21_days_and_leading_ends_at_21_days():
    calendar = [_f(1, "2026-09-19T14:00:00Z"),                      # exactly 21 days before: in
                _f(2, "2026-09-19T13:59:00Z"),                      # a minute earlier: out
                _f(3, "2026-10-31T14:00:00Z", "scheduled"),         # exactly 21 days after: in
                _f(4, "2026-10-31T14:01:00Z", "scheduled")]         # a minute later: out of the window
    out = chk.expected_context(calendar, CUT, target_id=99, known_after_hours=3)
    assert (out["trailing"], out["n_trailing"]) == (1.0, 1)
    assert (out["leading"], out["n_leading"]) == (1.0, 1)


def test_a_result_is_known_only_after_the_assumed_delay():
    just_played = [_f(1, "2026-10-10T11:30:00Z")]                  # kicked off 2.5 h before the cutoff
    assert chk.expected_context(just_played, CUT, 99, 3)["n_trailing"] == 0
    assert chk.expected_context(just_played, CUT, 99, 2)["n_trailing"] == 1


def test_continental_fixtures_weigh_more_and_the_target_never_counts_as_leading():
    calendar = [_f(1, "2026-10-07T19:00:00Z", league=2, weight=1.25, continental=True),
                _f(2, "2026-10-14T19:00:00Z", "scheduled", league=2, weight=1.25, continental=True),
                _f(99, "2026-10-10T14:00:00Z", "scheduled")]
    out = chk.expected_context(calendar, CUT, 99, 3)
    assert (out["trailing"], out["leading"]) == (1.25, 1.25)


def test_rest_days_use_the_nearest_known_fixture_either_side_and_ignore_same_kickoff():
    calendar = [_f(1, "2026-10-04T14:00:00Z"), _f(2, "2026-09-01T14:00:00Z"),
                _f(3, "2026-10-17T14:00:00Z", "scheduled"), _f(4, "2026-12-01T14:00:00Z", "scheduled"),
                _f(5, CUT, "scheduled")]
    out = chk.expected_context(calendar, CUT, 5, 3)
    assert out["previous_rest_days"] == 6.0 and out["next_rest_days"] == 7.0


def test_no_anchor_is_none_not_zero():
    out = chk.expected_context([_f(99, CUT, "scheduled")], CUT, 99, 3)
    assert out["previous_rest_days"] is None and out["next_rest_days"] is None and out["trailing"] == 0.0


# ---------------------------------------------------------------- the runners, end to end on the synthetic store

@pytest.fixture
def run(store, tmp_path):  # noqa: F811
    root, _ = store
    base_handle = lt.LiveTrialBuildHandle(root / "v1/premier-league")
    context = root / "context/builds-v2/live-trial"
    features = tmp_path / "features"
    build_features_v2(base_handle, context, features, feature_build_id="live-trial", built_at="2026-10-11T00:00:00Z",
                      role_map_version=ROLE_MAPPING_VERSION_V3, assumption_status=LIVE_TRIAL_LOCAL)
    frames = chk.load_frames(features / "builds-v2/live-trial")
    return frames, chk.load_base(root / "v1/premier-league"), root


def test_the_frames_index_the_validated_feature_rows(run):
    frames, base, _ = run
    assert frames.manifest["assumption_status"] == LIVE_TRIAL_LOCAL
    assert len(frames.player_index) == len(frames.player) and len(frames.team_index) == len(frames.team)


def test_m2_runner_reports_counts_and_marks_thin_history_as_missing_not_wrong(run):
    frames, base, _ = run
    aggregate, detail = chk.run_m2(frames, base, 1)
    assert aggregate["starters"] == sum(1 for d in detail if d["started"]) == 3
    assert aggregate["module_missing_context"] == aggregate["starters"], "one prior match is not enough history"
    assert aggregate["role_agreement"] == {"n": 0, "agree": 0, "rate": None}
    assert all(d["status"] == ModuleStatus.MISSING_CONTEXT.value for d in detail if d["started"])
    assert {d["actual_role"] for d in detail if d["started"]} == {"full_back", "attacking_midfield", "winger"}


def test_m1_runner_scores_every_squad_member_against_who_actually_started(run):
    frames, base, _ = run
    aggregate, detail = chk.run_m1(frames, base, 1)
    assert aggregate["squad_members_evaluated"] == len(detail) > 0
    assert {d["started"] for d in detail} <= {0, 1}
    assert aggregate["module_ok"] + aggregate["module_missing_context"] == aggregate["squad_members_evaluated"]


def test_m3_runner_recomputes_the_calendar_independently_and_it_matches(run, capture):  # noqa: F811
    frames, base, root = run
    _, index = lt.build_team_registry(capture)
    aggregate, detail = chk.run_m3(frames, base, capture, index, known_after_hours=lt.RESULT_KNOWN_AFTER_HOURS)
    assert aggregate["team_fixtures"] == len(detail) == 4
    assert aggregate["trailing_matches_calendar"]["rate"] == 1.0 and aggregate["leading_matches_calendar"]["rate"] == 1.0
    assert aggregate["previous_rest_matches_calendar"]["agree"] == aggregate["previous_rest_matches_calendar"]["n"]
    assert aggregate["next_rest_matches_calendar"]["agree"] == aggregate["next_rest_matches_calendar"]["n"]


def test_the_aggregates_carry_no_name_and_are_json(run, capture):  # noqa: F811
    frames, base, _ = run
    _, index = lt.build_team_registry(capture)
    parts = [chk.run_m2(frames, base, 1)[0], chk.run_m1(frames, base, 1)[0],
             chk.run_m3(frames, base, capture, index, known_after_hours=3)[0]]
    text = json.dumps(parts, default=str)
    assert "Able" not in text and "Arsenal" not in text and "Beta" not in text


# ---------------------------------------------------------------- Leo's six, the review sample, the table

def _m2row(pid, **over):
    base = {"fixture_id": "F", "team_id": "T", "player_id": pid, "name": pid, "started": True, "status": "ok", "nominal": "MID",
            "actual_position": "Right Midfield", "actual_role": "winger", "actual_flank": "right", "grid_slot": "4:1", "grid_side": "right",
            "predicted_role": "winger", "predicted_flank": "right", "out_of_position": 0.0, "role_change": False, "reason_codes": []}
    base.update(over)
    return base


def test_the_flank_vocabulary_of_the_module_is_translated_to_the_stores(run):  # noqa: F811
    from football_data_contract.enums import Flank
    assert chk._flank_text(Flank.CENTRAL) == "center" and chk._flank_text(Flank.LEFT) == "left" and chk._flank_text(None) is None


def test_leo_validated_sides_are_compared_with_what_was_played_and_with_the_prediction():
    rows = [_m2row("p1", predicted_role="winger", predicted_flank="right"),                                  # saka: both agree
            _m2row("p2", actual_role="winger", actual_flank="left", predicted_role="winger", predicted_flank="right"),  # madueke: predicted the wrong side
            _m2row("p3", actual_role="center_back", actual_flank="center", predicted_role=None, predicted_flank=None, status="missing_context")]
    out = chk.check_leo_validated(rows, {"saka": "p1", "madueke": "p2", "konsa": "p3"})
    assert out["n_expected"] == 6 and out["n_found"] == 3
    assert out["actual_matches_leo"] == 3 and out["predicted_matches_leo"] == 1 and out["module_ok"] == 2
    assert {r["player"] for r in out["rows"] if r["actual"] is None} == {"gabriel", "rice", "lewis-skelly"}


def _m1row(pid, team="T", prob=0.9, started=1, minutes=90, **over):
    base = {"fixture_id": "F", "team_id": team, "player_id": pid, "name": pid, "status": "ok", "start_probability": prob,
            "expected_minutes": 70.0, "share": prob, "history": 5, "started": started, "minutes": minutes, "later_absent": False}
    base.update(over)
    return base


def test_the_review_sample_covers_the_asked_cases_without_repeating_a_player():
    m1 = [_m1row("a", prob=0.95), _m1row("b", team="EU", prob=0.5, started=0, minutes=0), _m1row("c", prob=0.9, started=0, minutes=0),
          _m1row("d", prob=0.6), _m1row("e", prob=0.05, started=1), _m1row("f", prob=0.6)]
    m2 = [_m2row("d", out_of_position=0.5)]
    sample = chk.review_sample(m1, m2, european_teams={"EU"}, newcomers={"d"}, leo_players={"f"})
    by = {r["player_id"]: r["category"] for r in sample}
    assert by["a"] == "fixed_starter" and by["b"] == "rotation_european_club"
    assert by["c"] == "large_miss" and by["e"] == "large_miss" and by["f"] == "leo_team"
    assert by["d"] == "out_of_position", "a player in two categories is listed once, under the first"
    assert len(sample) == len({(r["fixture_id"], r["player_id"]) for r in sample})


def test_a_player_the_module_could_not_score_is_never_in_the_sample():
    sample = chk.review_sample([_m1row("a", status="missing_context")], [], european_teams=set(), newcomers={"a"}, leo_players={"a"})
    assert sample == []


def test_the_review_table_is_short_and_has_an_empty_column_for_the_answer():
    sample = [{"category": "fixed_starter", "fixture_id": "F", "player_id": "a", "team_id": "T", "name": "Ann Able",
               "start_probability": 0.92, "expected_minutes": 83.0, "predicted_role": "winger", "predicted_flank": "right",
               "started": 1, "minutes": 90, "actual_position": "Right Midfield"}]
    table = chk.render_review_table(sample, {"T": "Alpha FC"}, limit=10)
    lines = table.strip().splitlines()
    assert len(lines) == 3 and lines[0].count("|") == lines[2].count("|")
    assert "92% / 83 min / winger (right)" in lines[2] and "started, 90 min, Right Midfield" in lines[2] and lines[2].endswith("|  |")


# ---------------------------------------------------------------- the M2 baseline: the same position as his last start

def _base_with(rows):
    """rows: (fixture_id, kickoff, player_id, started, detailed_position)."""
    import pandas as pd
    fixtures = pd.DataFrame({"fixture_id": [r[0] for r in rows], "kickoff_utc": [r[1] for r in rows]}).drop_duplicates("fixture_id")
    lineups = pd.DataFrame({"fixture_id": [r[0] for r in rows], "player_id": [r[2] for r in rows],
                            "started": [r[3] for r in rows], "detailed_position": [r[4] for r in rows]})
    return chk.Base(fixtures, lineups, None, None)


def test_the_baseline_is_the_position_of_the_most_recent_start_strictly_before_the_target():
    base = _base_with([("a", "2026-08-01T15:00:00Z", "p", True, "Right Back"),
                       ("b", "2026-08-08T15:00:00Z", "p", True, "Centre Back"),
                       ("c", "2026-08-15T15:00:00Z", "p", False, "Attacker"),      # a substitute appearance is not a start
                       ("d", "2026-08-22T15:00:00Z", "p", True, "Left Back")])      # the target itself
    starts = chk.last_starts(base)
    assert chk.last_start_position(starts, "p", "2026-08-22T15:00:00Z") == "Centre Back"
    assert chk.last_start_position(starts, "p", "2026-08-08T15:00:00Z") == "Right Back", "strictly before: the same kickoff is excluded"
    assert chk.last_start_position(starts, "p", "2026-08-01T15:00:00Z") is None, "no earlier start: the baseline abstains"
    assert chk.last_start_position(starts, "nobody", "2026-09-01T00:00:00Z") is None


def test_the_baseline_ignores_input_order_and_missing_positions():
    base = _base_with([("b", "2026-08-08T15:00:00Z", "p", True, "Centre Back"), ("a", "2026-08-01T15:00:00Z", "p", True, None)])
    starts = chk.last_starts(base)
    assert chk.last_start_position(starts, "p", "2026-09-01T00:00:00Z") == "Centre Back"
    assert chk.last_start_position(starts, "p", "2026-08-05T00:00:00Z") is None


def test_the_m2_aggregate_reports_the_baseline_beside_the_module_and_on_the_same_players(run):  # noqa: F811
    frames, base, _ = run
    aggregate, detail = chk.run_m2(frames, base, 1)
    block = aggregate["baseline_same_position_as_last_start"]
    assert set(block) == {"answers", "of_starters", "role_agreement_all_it_answers", "flank_agreement_all_it_answers", "like_for_like_subset"}
    assert block["like_for_like_subset"]["n"] == 0, "no module answer in the synthetic store, so nothing to compare on"
    assert all("baseline_role" in d and "baseline_flank" in d for d in detail)

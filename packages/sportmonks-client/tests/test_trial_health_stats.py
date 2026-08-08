"""FI-8 S5: injuries/suspensions/coaches (trial_injuries.py) and fixture/player
match statistics plus the pre/during/post recording scaffold (trial_stats.py).

Every test that removes or blanks the underlying mock data and asserts the
targeted objective degrades *and* only its own shape entry disappears is the
falsification the plan's "read it twice" rule demands (standing DoD item 10):
a shape entry appended unconditionally is an assertion wearing an
observation's name.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import trial_injuries  # noqa: E402
import trial_stats  # noqa: E402
from _trial_common import (  # noqa: E402
    DEGRADED, EXAMPLES_DIR, EXIT_CONFIG, EXIT_OK, EXIT_UNMET, MODE_MOCK,
    NOT_APPLICABLE, OBSERVED, UNMET,
)
from trial_stats import SampleDiff, StatSample, diff_samples  # noqa: E402

# ==============================================================================
# trial_injuries.py
# ==============================================================================


def _run_injuries(tmp_path, **kwargs):
    if kwargs:
        original = trial_injuries.mock_transport
        trial_injuries.mock_transport = lambda: original(**kwargs)
    try:
        code = trial_injuries.main(["--out", str(tmp_path)])
    finally:
        if kwargs:
            trial_injuries.mock_transport = original
    return code, json.loads((tmp_path / "reports" / "trial_injuries.json").read_text(encoding="utf-8"))


def _shape_names(payload):
    return {s["name"] for s in payload["observed_shapes"]}


def _objective(payload, obj_id, title):
    for o in payload["objectives"]:
        if o["id"] == obj_id and o["title"] == title:
            return o
    raise AssertionError(f"no objective ({obj_id}, {title!r}) in {payload['objectives']}")


def test_default_mock_run_reports_three_separately_statused_objectives(tmp_path):
    code, payload = _run_injuries(tmp_path)
    assert code == EXIT_OK
    ids_titles = [(o["id"], o["title"]) for o in payload["objectives"]]
    assert ids_titles == [
        (11, "Injuries"), (11, "Suspensions"), (12, "Coaches and manager records"),
    ]
    assert all(o["status"] == OBSERVED for o in payload["objectives"])
    assert _shape_names(payload) == {
        "injury_record_fields", "injury_freshness_field",
        "suspension_record_fields", "coach_record_fields",
    }


def test_injury_records_carrying_freshness_are_observed(tmp_path):
    _, payload = _run_injuries(tmp_path)
    injuries = _objective(payload, 11, "Injuries")
    assert "2 carry a 'updated_at' freshness timestamp, 0 do not" in injuries["evidence"]


def test_injury_record_with_no_timestamp_is_degraded_not_defaulted_to_fresh(tmp_path):
    """S5 DoD 2, falsified directly: strip the freshness field from every
    injury record and confirm the objective degrades and the freshness shape
    vanishes -- while the sibling shapes (fields list, suspensions, coaches)
    are untouched."""
    code, payload = _run_injuries(tmp_path, injuries=[
        {"id": 51, "player_id": 101, "type_id": 1, "expected_return": None},
    ])
    assert code == EXIT_UNMET
    injuries = _objective(payload, 11, "Injuries")
    assert injuries["status"] == DEGRADED
    assert "0 carry a 'updated_at' freshness timestamp, 1 do not" in injuries["evidence"]
    assert "never defaulted to fresh" in injuries["evidence"]

    shapes = _shape_names(payload)
    assert "injury_freshness_field" not in shapes
    assert "injury_record_fields" in shapes  # the sibling shape survives
    assert "suspension_record_fields" in shapes
    assert "coach_record_fields" in shapes
    assert _objective(payload, 11, "Suspensions")["status"] == OBSERVED
    assert _objective(payload, 12, "Coaches and manager records")["status"] == OBSERVED


def test_injury_record_with_null_timestamp_is_treated_as_no_timestamp(tmp_path):
    """A present-but-null freshness field carries no freshness information and
    must not be defaulted to fresh either."""
    code, payload = _run_injuries(tmp_path, injuries=[
        {"id": 51, "player_id": 101, "type_id": 1, "expected_return": None, "updated_at": None},
    ])
    injuries = _objective(payload, 11, "Injuries")
    assert injuries["status"] == DEGRADED
    assert "0 carry a 'updated_at' freshness timestamp, 1 do not" in injuries["evidence"]
    assert "injury_freshness_field" not in _shape_names(payload)


def test_partial_freshness_is_counted_not_rounded(tmp_path):
    code, payload = _run_injuries(tmp_path, injuries=[
        {"id": 51, "player_id": 101, "type_id": 1, "updated_at": "2026-08-01T09:00:00Z"},
        {"id": 52, "player_id": 102, "type_id": 1},
        {"id": 53, "player_id": 103, "type_id": 1},
    ])
    injuries = _objective(payload, 11, "Injuries")
    assert injuries["status"] == DEGRADED
    assert "3 injury record(s)" in injuries["evidence"]
    assert "1 carry a 'updated_at' freshness timestamp, 2 do not" in injuries["evidence"]
    # freshness shape still appears -- at least one record does carry it
    assert "injury_freshness_field" in _shape_names(payload)


def test_no_injury_records_is_unmet_and_drops_the_injury_shapes_only(tmp_path):
    code, payload = _run_injuries(tmp_path, injuries=[])
    assert code == EXIT_UNMET
    injuries = _objective(payload, 11, "Injuries")
    assert injuries["status"] == UNMET
    assert injuries["evidence"] == "no injury records observed"
    shapes = _shape_names(payload)
    assert "injury_record_fields" not in shapes
    assert "injury_freshness_field" not in shapes
    assert "suspension_record_fields" in shapes
    assert "coach_record_fields" in shapes
    assert _objective(payload, 11, "Suspensions")["status"] == OBSERVED
    assert _objective(payload, 12, "Coaches and manager records")["status"] == OBSERVED


def test_no_suspension_records_is_unmet_and_drops_only_the_suspension_shape(tmp_path):
    code, payload = _run_injuries(tmp_path, suspensions=[])
    assert code == EXIT_UNMET
    suspensions = _objective(payload, 11, "Suspensions")
    assert suspensions["status"] == UNMET
    assert suspensions["evidence"] == "no suspension records observed"
    shapes = _shape_names(payload)
    assert "suspension_record_fields" not in shapes
    assert "injury_record_fields" in shapes
    assert "coach_record_fields" in shapes
    assert _objective(payload, 11, "Injuries")["status"] == OBSERVED
    assert _objective(payload, 12, "Coaches and manager records")["status"] == OBSERVED


def test_no_coach_records_is_unmet_and_drops_only_the_coach_shape(tmp_path):
    code, payload = _run_injuries(tmp_path, coaches=[])
    assert code == EXIT_UNMET
    coaches = _objective(payload, 12, "Coaches and manager records")
    assert coaches["status"] == UNMET
    assert coaches["evidence"] == "no coach records observed"
    shapes = _shape_names(payload)
    assert "coach_record_fields" not in shapes
    assert "injury_record_fields" in shapes
    assert "suspension_record_fields" in shapes
    assert _objective(payload, 11, "Injuries")["status"] == OBSERVED
    assert _objective(payload, 11, "Suspensions")["status"] == OBSERVED


def test_injury_record_fields_shape_reflects_fields_actually_present(tmp_path):
    _, payload = _run_injuries(tmp_path, injuries=[
        {"id": 51, "player_id": 101, "updated_at": "2026-08-01T09:00:00Z"},
    ])
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["injury_record_fields"] == "id, player_id, updated_at"
    assert "type_id" not in shapes["injury_record_fields"]


def test_coach_record_fields_reflect_the_actual_payload(tmp_path):
    _, payload = _run_injuries(tmp_path, coaches=[{"id": 99, "name": "Someone"}])
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["coach_record_fields"] == "id, name"
    assert "team_id" not in shapes["coach_record_fields"]


def test_injuries_exits_config_when_token_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    code = trial_injuries.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    assert code == EXIT_CONFIG
    payload = json.loads((tmp_path / "reports" / "trial_injuries.json").read_text(encoding="utf-8"))
    assert all(o["status"] == UNMET for o in payload["objectives"])


def test_injuries_mock_output_is_byte_stable(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    trial_injuries.main(["--out", str(first)])
    trial_injuries.main(["--out", str(second)])
    for name in ("trial_injuries.json", "trial_injuries.md"):
        assert (first / "reports" / name).read_bytes() == (second / "reports" / name).read_bytes()


def test_injuries_committed_example_matches_a_fresh_mock_run(tmp_path):
    trial_injuries.main(["--out", str(tmp_path)])
    for name in ("trial_injuries.json", "trial_injuries.md"):
        fresh = (tmp_path / "reports" / name).read_text(encoding="utf-8")
        committed = (EXAMPLES_DIR / name).read_text(encoding="utf-8")
        assert fresh == committed, f"{name} drifted from trial-reports/examples/"


# ==============================================================================
# trial_stats.py
# ==============================================================================


def _run_stats(tmp_path, **kwargs):
    if kwargs:
        original = trial_stats.mock_transport
        trial_stats.mock_transport = lambda: original(**kwargs)
    try:
        code = trial_stats.main(["--out", str(tmp_path)])
    finally:
        if kwargs:
            trial_stats.mock_transport = original
    return code, json.loads((tmp_path / "reports" / "trial_stats.json").read_text(encoding="utf-8"))


def test_default_mock_run_reports_team_and_player_stats_separately(tmp_path):
    code, payload = _run_stats(tmp_path)
    assert code == EXIT_OK
    ids_titles = [(o["id"], o["title"]) for o in payload["objectives"]]
    assert ids_titles == [
        (13, "Fixture-level team statistics"),
        (14, "Player match statistics"),
        (15, "Data update timing before, during, and after matches"),
        (16, "Post-match corrections"),
    ]
    team = _objective(payload, 13, "Fixture-level team statistics")
    player = _objective(payload, 14, "Player match statistics")
    assert team["status"] == OBSERVED and player["status"] == OBSERVED
    assert "fixture_id=2/2, team_id=2/2, type_id=2/2, value=2/2" in team["evidence"]
    assert "fixture_id=2/2, player_id=2/2, type_id=2/2, value=2/2" in player["evidence"]
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["team_statistics_fields"] == "fixture_id, team_id, type_id, value"
    assert shapes["player_statistics_fields"] == "fixture_id, player_id, type_id, value"


def test_objectives_15_and_16_are_always_not_applicable_in_mock_mode(tmp_path):
    """S5 DoD 4: this is a modal statement about what mock mode can measure,
    not a fact about the payload -- it must hold regardless of what the team
    and player statistics fixtures contain."""
    for kwargs in ({}, {"team_stats": []}, {"player_stats": []}, {"team_stats": [], "player_stats": []}):
        _, payload = _run_stats(tmp_path, **kwargs)
        assert _objective(payload, 15, "Data update timing before, during, and after matches") == {
            "id": 15, "title": "Data update timing before, during, and after matches",
            "status": NOT_APPLICABLE, "evidence": "requires FI-9 live observation",
        }
        assert _objective(payload, 16, "Post-match corrections") == {
            "id": 16, "title": "Post-match corrections",
            "status": NOT_APPLICABLE, "evidence": "requires FI-9 live observation",
        }


def test_team_statistics_field_missing_entirely_degrades_and_shrinks_only_that_shape(tmp_path):
    code, payload = _run_stats(tmp_path, team_stats=[
        {"id": 91, "fixture_id": 1001, "team_id": 1, "type_id": 42},
        {"id": 92, "fixture_id": 1001, "team_id": 2, "type_id": 42},
    ])
    assert code == EXIT_UNMET
    team = _objective(payload, 13, "Fixture-level team statistics")
    assert team["status"] == DEGRADED
    assert "missing entirely: value" in team["evidence"]
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["team_statistics_fields"] == "fixture_id, team_id, type_id"
    assert "value" not in shapes["team_statistics_fields"]
    # the player-stats objective and shape are untouched
    assert _objective(payload, 14, "Player match statistics")["status"] == OBSERVED
    assert shapes["player_statistics_fields"] == "fixture_id, player_id, type_id, value"


def test_no_team_statistics_is_unmet_and_drops_only_that_shape(tmp_path):
    code, payload = _run_stats(tmp_path, team_stats=[])
    assert code == EXIT_UNMET
    team = _objective(payload, 13, "Fixture-level team statistics")
    assert team["status"] == UNMET
    assert team["evidence"] == "no fixture-level team statistics records observed"
    shapes = {s["name"] for s in payload["observed_shapes"]}
    assert "team_statistics_fields" not in shapes
    assert "player_statistics_fields" in shapes
    assert _objective(payload, 14, "Player match statistics")["status"] == OBSERVED


def test_no_player_statistics_is_unmet_and_drops_only_that_shape(tmp_path):
    code, payload = _run_stats(tmp_path, player_stats=[])
    assert code == EXIT_UNMET
    player = _objective(payload, 14, "Player match statistics")
    assert player["status"] == UNMET
    assert player["evidence"] == "no player match statistics records observed"
    shapes = {s["name"] for s in payload["observed_shapes"]}
    assert "player_statistics_fields" not in shapes
    assert "team_statistics_fields" in shapes
    assert _objective(payload, 13, "Fixture-level team statistics")["status"] == OBSERVED


def test_player_statistics_field_missing_entirely_degrades_and_shrinks_only_that_shape(tmp_path):
    code, payload = _run_stats(tmp_path, player_stats=[
        {"id": 1011, "fixture_id": 1001, "player_id": 101, "type_id": 52},
    ])
    assert code == EXIT_UNMET
    player = _objective(payload, 14, "Player match statistics")
    assert player["status"] == DEGRADED
    assert "missing entirely: value" in player["evidence"]
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["player_statistics_fields"] == "fixture_id, player_id, type_id"
    assert _objective(payload, 13, "Fixture-level team statistics")["status"] == OBSERVED


def test_stats_exits_config_when_token_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    code = trial_stats.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    assert code == EXIT_CONFIG
    payload = json.loads((tmp_path / "reports" / "trial_stats.json").read_text(encoding="utf-8"))
    assert _objective(payload, 13, "Fixture-level team statistics")["status"] == UNMET
    assert _objective(payload, 14, "Player match statistics")["status"] == UNMET
    assert _objective(payload, 15, "Data update timing before, during, and after matches")["status"] == NOT_APPLICABLE
    assert _objective(payload, 16, "Post-match corrections")["status"] == NOT_APPLICABLE


def test_stats_mock_output_is_byte_stable(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    trial_stats.main(["--out", str(first)])
    trial_stats.main(["--out", str(second)])
    for name in ("trial_stats.json", "trial_stats.md"):
        assert (first / "reports" / name).read_bytes() == (second / "reports" / name).read_bytes()


def test_stats_committed_example_matches_a_fresh_mock_run(tmp_path):
    trial_stats.main(["--out", str(tmp_path)])
    for name in ("trial_stats.json", "trial_stats.md"):
        fresh = (tmp_path / "reports" / name).read_text(encoding="utf-8")
        committed = (EXAMPLES_DIR / name).read_text(encoding="utf-8")
        assert fresh == committed, f"{name} drifted from trial-reports/examples/"


# --- The pre/during/post recording scaffold (S5 DoD 4) ------------------------
#
# These two samples are hand-written, not produced by running trial_stats.py
# twice: MOCK_CLOCK makes repeated mock runs overwrite the same snapshot
# filename (_trial_common.py), so two mock runs can never stand in for two
# independent live samples of one fixture.

def test_diff_samples_detects_changed_and_added_stats():
    before = StatSample(
        fixture_id=1001, phase="during", captured_at="2026-08-01T15:30:00Z",
        team_stats={(1, 42): 50, (2, 42): 40},
        player_stats={(101, 52): 2},
    )
    after = StatSample(
        fixture_id=1001, phase="post", captured_at="2026-08-01T17:05:00Z",
        team_stats={(1, 42): 55, (2, 42): 40, (1, 88): 3},
        player_stats={(101, 52): 3, (102, 52): 1},
    )
    diff = diff_samples(before, after)
    assert diff == SampleDiff(
        fixture_id=1001, from_phase="during", to_phase="post",
        changed_team_stats=(((1, 42), 50, 55),),
        added_team_stats=((1, 88),),
        removed_team_stats=(),
        changed_player_stats=(((101, 52), 2, 3),),
        added_player_stats=((102, 52),),
        removed_player_stats=(),
    )


def test_diff_samples_reports_removed_stats():
    before = StatSample(1001, "pre", "2026-08-01T14:00:00Z", team_stats={(1, 42): 50})
    after = StatSample(1001, "during", "2026-08-01T15:00:00Z", team_stats={})
    diff = diff_samples(before, after)
    assert diff.removed_team_stats == ((1, 42),)
    assert diff.changed_team_stats == ()
    assert diff.added_team_stats == ()


def test_diff_samples_with_identical_stats_reports_no_changes():
    sample_a = StatSample(1001, "pre", "t1", team_stats={(1, 42): 50}, player_stats={(101, 52): 2})
    sample_b = StatSample(1001, "during", "t2", team_stats={(1, 42): 50}, player_stats={(101, 52): 2})
    diff = diff_samples(sample_a, sample_b)
    assert diff.changed_team_stats == () and diff.changed_player_stats == ()
    assert diff.added_team_stats == () and diff.removed_team_stats == ()


def test_diff_samples_rejects_two_samples_of_different_fixtures():
    a = StatSample(1001, "pre", "t1")
    b = StatSample(1002, "post", "t2")
    with pytest.raises(ValueError, match="same fixture"):
        diff_samples(a, b)

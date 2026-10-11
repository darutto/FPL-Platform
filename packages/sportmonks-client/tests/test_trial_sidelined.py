"""trial_sidelined: the polled current-bajas list and its diff."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import trial_sidelined  # noqa: E402
from _trial_common import EXIT_OK, EXIT_UNMET, MODE_MOCK, OBSERVED, UNMET, make_client  # noqa: E402
from sportmonks_client.errors import SportmonksRequestError  # noqa: E402


def _row(i, **fields):
    return {"id": i, "player_id": 100 + i, "type_id": 1, "category": "injury", "team_id": 1,
            "season_id": None, "start_date": "2026-10-01", "end_date": None,
            "games_missed": 1, "completed": False, **fields}


def _pass(tmp_path, rows, now):
    client = make_client(MODE_MOCK, transport=trial_sidelined.mock_transport(current_sidelined={"data": rows}))
    return trial_sidelined.collect(client, MODE_MOCK, tmp_path, now=now)


def _shapes(report):
    return {s.name: s.shape for s in report.observed_shapes}


def _events(tmp_path):
    path = tmp_path / "events.ndjson"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_the_shape_entry_reports_the_fields_that_arrived(tmp_path):
    one = _pass(tmp_path / "a", [_row(1)], "2026-10-11T08:00:00Z")
    two = _pass(tmp_path / "b", [_row(1, extra_field=3)], "2026-10-11T08:00:00Z")
    assert _shapes(one)["current_sidelined"] != _shapes(two)["current_sidelined"]
    assert "extra_field" in _shapes(two)["current_sidelined"]


def test_a_missing_family_is_unmet_and_drops_its_shape(tmp_path):
    client = make_client(MODE_MOCK, transport=trial_sidelined.mock_transport(
        current_sidelined=SportmonksRequestError("gone", endpoint="teams/1", status_code=404)))
    report = trial_sidelined.collect(client, MODE_MOCK, tmp_path, now="2026-10-11T08:00:00Z")
    assert report.objectives[0].status == UNMET and not report.observed_shapes
    assert not (tmp_path / "state.json").exists(), "a failed pass must not overwrite the previous state"


def test_the_first_pass_is_a_baseline_and_reports_no_new_absences(tmp_path):
    report = _pass(tmp_path, [_row(1), _row(2)], "2026-10-11T08:00:00Z")
    assert report.objectives[0].status == OBSERVED
    assert "baseline of 2 row(s)" in _shapes(report)["poll_pass"]
    assert _events(tmp_path) == []


def test_a_second_pass_reports_what_appeared_left_and_changed(tmp_path):
    _pass(tmp_path, [_row(1), _row(2)], "2026-10-11T08:00:00Z")
    report = _pass(tmp_path, [_row(2, end_date="2026-10-20"), _row(3)], "2026-10-11T20:00:00Z")
    assert "1 appeared, 1 gone, 1 changed since pass 1" in _shapes(report)["poll_pass"]
    by_kind = {e["event"]: e for e in _events(tmp_path)}
    assert by_kind["appeared"]["id"] == "3" and by_kind["appeared"]["seen_at"] == "2026-10-11T20:00:00Z"
    assert by_kind["gone"]["id"] == "1"
    assert (by_kind["changed"]["field"], by_kind["changed"]["after"]) == ("end_date", "2026-10-20")


def test_an_identical_pass_reports_nothing_new(tmp_path):
    _pass(tmp_path, [_row(1)], "2026-10-11T08:00:00Z")
    report = _pass(tmp_path, [_row(1)], "2026-10-11T20:00:00Z")
    assert "0 appeared, 0 gone, 0 changed" in _shapes(report)["poll_pass"]
    assert _events(tmp_path) == []


def test_the_report_carries_no_row_and_no_timestamp(tmp_path):
    report = _pass(tmp_path, [_row(1)], "2026-10-11T08:00:00Z")
    text = json.dumps([o.__dict__ for o in report.objectives]) + json.dumps(_shapes(report)) + json.dumps(report.warnings)
    assert "2026-10-11T08" not in text and "101" not in text.replace("1 open", "")


def test_a_mock_run_exits_zero_and_writes_a_report(tmp_path):
    assert trial_sidelined.main(["--out", str(tmp_path)]) == EXIT_OK
    assert (tmp_path / "reports" / "trial_sidelined.json").exists()
    assert (tmp_path / "sidelined" / "state.json").exists()

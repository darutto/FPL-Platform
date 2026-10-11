"""live_capture: the local capture is assembled purely, refuses mock, and carries no secret."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import live_capture  # noqa: E402
from _trial_common import EXIT_REFUSED, MOCK_SCOPE, TrialRefusal  # noqa: E402


def _assemble(**over):
    base = dict(scope=MOCK_SCOPE, teams=[{"id": 1}], squads=[{"id": 2}], players=[{"id": 3}],
                team_fixtures=[{"id": 4}], match_detail=[{"id": 5}], countries={32: "Spain"},
                fpl_elements=[{"id": 9, "first_name": "A", "second_name": "B", "web_name": "B", "team": 1,
                               "element_type": 3, "birth_date": "2000-01-01", "status": "a", "news": "",
                               "chance_of_playing_next_round": None, "chance_of_playing_this_round": None,
                               "minutes": 90, "photo": "dropped.jpg", "now_cost": 55}],
                fpl_teams=[{"id": 1, "code": 3, "name": "Arsenal", "short_name": "ARS", "strength": 4}],
                pairs=[("10", 9, "full_name_birth_date")])
    base.update(over)
    return live_capture.assemble(**base)


def test_the_capture_has_every_section_the_adapter_reads():
    capture = _assemble()
    assert set(capture) == {"schema_version", "scope", "teams", "squads", "players", "team_fixtures",
                            "match_detail", "countries", "fpl", "identity_pairs"}
    assert capture["scope"]["league_id"] == 8 and capture["scope"]["team_ids"] == (1,)


def test_only_the_named_fpl_fields_are_kept():
    fpl = _assemble()["fpl"]
    assert set(fpl["elements"][0]) == set(live_capture.FPL_ELEMENT_FIELDS)
    assert "photo" not in fpl["elements"][0] and "strength" not in fpl["teams"][0]


def test_identity_pairs_are_typed_and_keep_their_method():
    assert _assemble()["identity_pairs"] == [{"sportmonks_id": "10", "fpl_id": 9, "method": "full_name_birth_date"}]


def test_the_capture_is_json_and_does_not_contain_a_token_field():
    text = json.dumps(_assemble(), ensure_ascii=False)
    assert "api_token" not in text and "SPORTMONKS" not in text


def test_missing_identity_pairs_stop_the_capture_with_a_pointer_to_the_mapping_run(tmp_path):
    with pytest.raises(TrialRefusal, match="trial_mapping --live"):
        live_capture.load_pairs(tmp_path)


def test_pairs_are_read_from_the_mapping_reports(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/trial_mapping_pairs.json").write_text(json.dumps(
        {"schema_version": 1, "items": [{"sportmonks_id": "1", "fpl_id": 2, "method": "m"}]}))
    assert live_capture.load_pairs(tmp_path) == [("1", 2, "m")]


def test_capture_is_live_only_and_needs_the_acknowledgement(tmp_path, capsys):
    assert live_capture.main(["--out", str(tmp_path)]) == EXIT_REFUSED
    assert live_capture.main(["--live", "--out", str(tmp_path)]) == EXIT_REFUSED
    assert not (tmp_path / "capture").exists()

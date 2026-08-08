"""FI-8 S3: `trial_entities.py` and `trial_fixtures.py`.

Mirrors `test_trial_harness.py`'s pattern: every construction site is proven
derived, not asserted, by a deletion test that blanks or swaps the underlying
mock data and checks that (a) the objective degrades and (b) the change is
isolated to the entry that describes that fact -- the other entries stay
byte-identical to a baseline run. That isolation check is what proves an entry
is computed from its own family's/query's data rather than from a shared
proxy.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import trial_entities  # noqa: E402
import trial_fixtures  # noqa: E402
from _trial_common import (  # noqa: E402
    DEGRADED, EXAMPLES_DIR, EXIT_OK, EXIT_UNMET, OBSERVED, UNMET, ReplayTransport,
    load_fixture, response,
)
from sportmonks_client.client import ENDPOINTS  # noqa: E402


# --- trial_entities.py ---------------------------------------------------------

def _run_entities(tmp_path, overrides=None):
    original = trial_entities.mock_transport
    trial_entities.mock_transport = lambda: original(overrides)
    try:
        code = trial_entities.main(["--out", str(tmp_path)])
    finally:
        trial_entities.mock_transport = original
    return code, json.loads((tmp_path / "reports" / "trial_entities.json").read_text(encoding="utf-8"))


def test_mock_run_sweeps_all_15_families(tmp_path):
    code, payload = _run_entities(tmp_path)
    assert code == EXIT_OK
    names = {s["name"] for s in payload["observed_shapes"]}
    assert names == {f"family:{family}" for family in ENDPOINTS}
    assert len(names) == 15


def test_every_family_reports_reachable_status_count_and_ids(tmp_path):
    _, payload = _run_entities(tmp_path)
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["family:leagues"] == "status=reachable records=1 provider_ids={8}"
    assert shapes["family:seasons"] == "status=reachable records=1 provider_ids={23614}"


def test_objective_1_is_observed_when_leagues_and_seasons_are_reachable(tmp_path):
    _, payload = _run_entities(tmp_path)
    objective = payload["objectives"][0]
    assert objective["id"] == 1 and objective["status"] == OBSERVED
    assert "leagues: reachable" in objective["evidence"]
    assert "seasons: reachable" in objective["evidence"]


def test_emptying_leagues_degrades_objective_1_and_only_that_shape_changes(tmp_path):
    """Standing DoD item 10 for the `leagues` family and objective 1.

    The deletion experiment: swap only `leagues` for `edge_cases.json`'s empty
    envelope. If objective 1's status or the `family:leagues` shape were a
    literal (or gated on something other than the leagues response), this
    would not change; if any other family's entry were coupled to leagues'
    data, it would change too. Neither happens.
    """
    baseline_code, baseline = _run_entities(tmp_path / "baseline")
    empty = load_fixture("edge_cases.json")["empty"]
    code, payload = _run_entities(tmp_path / "swapped", overrides={"leagues": empty})

    assert baseline_code == EXIT_OK
    assert code == EXIT_UNMET
    objective = payload["objectives"][0]
    assert objective["status"] == DEGRADED
    assert "leagues: empty (0 records" in objective["evidence"]
    assert "leagues family empty" in objective["evidence"]

    baseline_shapes = {s["name"]: s["shape"] for s in baseline["observed_shapes"]}
    swapped_shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert swapped_shapes["family:leagues"] == "status=empty records=0 provider_ids={none}"
    assert swapped_shapes["family:leagues"] != baseline_shapes["family:leagues"]
    for family in ENDPOINTS:
        if family == "leagues":
            continue
        assert swapped_shapes[f"family:{family}"] == baseline_shapes[f"family:{family}"], (
            f"family:{family} changed when only leagues' data was swapped"
        )


def test_emptying_seasons_degrades_objective_1_and_only_that_shape_changes(tmp_path):
    """Same experiment, the other half of objective 1's scope."""
    baseline_code, baseline = _run_entities(tmp_path / "baseline")
    empty = load_fixture("edge_cases.json")["empty"]
    code, payload = _run_entities(tmp_path / "swapped", overrides={"seasons": empty})

    assert code == EXIT_UNMET
    objective = payload["objectives"][0]
    assert objective["status"] == DEGRADED
    assert "seasons: empty (0 records" in objective["evidence"]
    assert "leagues: reachable" in objective["evidence"], "leagues' own fact must be unaffected"

    baseline_shapes = {s["name"]: s["shape"] for s in baseline["observed_shapes"]}
    swapped_shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert swapped_shapes["family:seasons"] == "status=empty records=0 provider_ids={none}"
    for family in ENDPOINTS:
        if family == "seasons":
            continue
        assert swapped_shapes[f"family:{family}"] == baseline_shapes[f"family:{family}"]


def test_a_malformed_envelope_is_reported_unavailable_not_a_crash(tmp_path):
    """A family the parser rejects degrades the objective and records why,
    rather than the script raising -- the frozen contract's "shape reporting
    over shape assertion" rule, applied to the sweep."""
    malformed = load_fixture("edge_cases.json")["malformed_envelope"]
    code, payload = _run_entities(tmp_path, overrides={"leagues": malformed})
    assert code == EXIT_UNMET
    objective = payload["objectives"][0]
    assert objective["status"] == DEGRADED
    assert "leagues: unavailable" in objective["evidence"]
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["family:leagues"].startswith("status=unavailable records=0 provider_ids={none} reason=")
    assert "SportmonksSchemaError" in shapes["family:leagues"]


def test_a_non_objective_family_going_empty_does_not_move_objective_1(tmp_path):
    """`teams` is swept and reported, but objective 1 is scoped to
    leagues/seasons only. This is the isolation half of standing DoD item 10:
    a fact outside an objective's scope must not silently move its status."""
    empty = load_fixture("edge_cases.json")["empty"]
    code, payload = _run_entities(tmp_path, overrides={"teams": empty})
    assert code == EXIT_OK
    objective = payload["objectives"][0]
    assert objective["status"] == OBSERVED
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["family:teams"] == "status=empty records=0 provider_ids={none}"


def test_provider_id_set_reflects_multiple_records(tmp_path):
    """The `provider_ids` fragment is a real set, not a single hardcoded id --
    proven by a family with more than one record."""
    two_leagues = {"data": [{"id": 8, "name": "Premier League"}, {"id": 9, "name": "Championship"}]}
    _, payload = _run_entities(tmp_path, overrides={"leagues": two_leagues})
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["family:leagues"] == "status=reachable records=2 provider_ids={8,9}"


# --- trial_fixtures.py ----------------------------------------------------------

def _run_fixtures(tmp_path, **kwargs):
    original = trial_fixtures.mock_transport
    trial_fixtures.mock_transport = lambda: original(**kwargs)
    try:
        code = trial_fixtures.main(["--out", str(tmp_path)])
    finally:
        trial_fixtures.mock_transport = original
    return code, json.loads((tmp_path / "reports" / "trial_fixtures.json").read_text(encoding="utf-8"))


def test_mock_run_observes_both_objectives_separately(tmp_path):
    code, payload = _run_fixtures(tmp_path)
    assert code == EXIT_OK
    ids = [o["id"] for o in payload["objectives"]]
    assert ids == [2, 3]
    assert payload["objectives"][0]["status"] == OBSERVED
    assert payload["objectives"][1]["status"] == OBSERVED
    assert "league_id=8 season_id=23614" in payload["objectives"][0]["evidence"]
    assert "across leagues [2, 24]" in payload["objectives"][1]["evidence"]


def test_emptying_season_fixtures_unmets_objective_2_only(tmp_path):
    """Standing DoD item 10: objectives 2 and 3 are distinct facts, so blanking
    one query's data must degrade only its own objective and drop only its own
    shape -- proven against a same-run baseline, not by inspection."""
    baseline_code, baseline = _run_fixtures(tmp_path / "baseline")
    empty = load_fixture("edge_cases.json")["empty"]
    code, payload = _run_fixtures(tmp_path / "swapped", season_fixtures=empty)

    assert baseline_code == EXIT_OK
    assert code == EXIT_UNMET
    assert payload["objectives"][0]["status"] == UNMET
    assert "no fixtures returned for the Premier League season query" in payload["objectives"][0]["evidence"]
    assert payload["objectives"][1] == baseline["objectives"][1], "objective 3 must be unaffected"

    baseline_shapes = {s["name"] for s in baseline["observed_shapes"]}
    swapped_shapes = {s["name"] for s in payload["observed_shapes"]}
    assert "season_fixtures" in baseline_shapes
    assert "season_fixtures" not in swapped_shapes, "the shape must disappear when its data is empty"
    assert "cross_competition_leagues" in swapped_shapes, "the unrelated shape must survive"


def test_emptying_cross_competition_fixtures_unmets_objective_3_only(tmp_path):
    baseline_code, baseline = _run_fixtures(tmp_path / "baseline")
    empty = load_fixture("edge_cases.json")["empty"]
    code, payload = _run_fixtures(tmp_path / "swapped", cross_competition_fixtures=empty)

    assert code == EXIT_UNMET
    assert payload["objectives"][1]["status"] == UNMET
    assert "no fixtures returned for the cross-competition query" in payload["objectives"][1]["evidence"]
    assert payload["objectives"][0] == baseline["objectives"][0], "objective 2 must be unaffected"

    swapped_shapes = {s["name"] for s in payload["observed_shapes"]}
    assert "cross_competition_leagues" not in swapped_shapes
    assert "season_fixtures" in swapped_shapes


def test_fixtures_confined_to_the_premier_league_degrade_objective_3():
    """The check that makes objective 3 a real "cross-competition" fact rather
    than "any fixtures for a club": if every returned fixture is still
    league_id=8, that is not cross-competition coverage, even though records
    came back non-empty."""
    only_pl = {
        "data": [{
            "id": 9001, "league_id": trial_fixtures.PL_LEAGUE_ID, "season_id": 1,
            "participants": [{"id": trial_fixtures.PL_CLUB_ID, "name": "Team A"}, {"id": 2, "name": "Team B"}],
        }],
    }
    status, evidence = trial_fixtures.classify_cross_competition_fixtures(
        tuple(_parse(only_pl)), None,
    )
    assert status == DEGRADED
    assert "no competition outside the Premier League was observed" in evidence


def test_fixtures_missing_the_requested_club_degrade_objective_3():
    """The second half of objective 3's check: cross-competition fixtures that
    do not actually involve the requested Premier League club are not evidence
    of that club's cross-competition coverage."""
    other_club = {
        "data": [{
            "id": 9002, "league_id": 24, "season_id": 1,
            "participants": [{"id": 99, "name": "Someone Else"}, {"id": 100, "name": "Another Team"}],
        }],
    }
    status, evidence = trial_fixtures.classify_cross_competition_fixtures(
        tuple(_parse(other_club)), None,
    )
    assert status == DEGRADED
    assert "did not include club id 1" in evidence


def test_season_fixtures_with_a_wrong_league_id_degrade_objective_2():
    """Objective 2's own shape check: a fixture returned under the "PL season"
    query that does not actually carry the Premier League's league id is a
    shape mismatch worth recording, not silently accepted."""
    wrong_league = {
        "data": [{"id": 9003, "league_id": 999, "season_id": trial_fixtures.PL_SEASON_ID, "participants": []}],
    }
    status, evidence = trial_fixtures.classify_season_fixtures(tuple(_parse(wrong_league)), None)
    assert status == DEGRADED
    assert "did not carry league_id=8/season_id=23614" in evidence


def test_a_malformed_fixtures_envelope_degrades_rather_than_crashes(tmp_path):
    malformed = load_fixture("edge_cases.json")["malformed_envelope"]
    code, payload = _run_fixtures(tmp_path, season_fixtures=malformed)
    assert code == EXIT_UNMET
    assert payload["objectives"][0]["status"] == DEGRADED
    assert "payload rejected by the parser" in payload["objectives"][0]["evidence"]


def _parse(envelope):
    """Parse a raw envelope dict into `Fixture` records the way the client
    would, for the classifier unit tests that don't need a full script run."""
    from sportmonks_client.models import Fixture, parse_entity
    return [parse_entity(Fixture, item, "fixtures") for item in envelope["data"]]


# --- Frozen-contract inheritance (both scripts) ---------------------------------

@pytest.mark.parametrize("script,module", [
    ("trial_entities", trial_entities),
    ("trial_fixtures", trial_fixtures),
])
def test_report_schema_keys_are_exactly_the_frozen_set(tmp_path, script, module):
    module.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{script}.json").read_text(encoding="utf-8"))
    assert list(payload) == ["script", "mode", "objectives", "observed_shapes", "warnings"]
    assert list(payload["objectives"][0]) == ["id", "title", "status", "evidence"]


@pytest.mark.parametrize("script,module", [
    ("trial_entities", trial_entities),
    ("trial_fixtures", trial_fixtures),
])
def test_mock_output_is_byte_stable_across_runs(tmp_path, script, module):
    first, second = tmp_path / "a", tmp_path / "b"
    module.main(["--out", str(first)])
    module.main(["--out", str(second)])
    for name in (f"{script}.json", f"{script}.md"):
        assert (first / "reports" / name).read_bytes() == (second / "reports" / name).read_bytes()


@pytest.mark.parametrize("script,module", [
    ("trial_entities", trial_entities),
    ("trial_fixtures", trial_fixtures),
])
def test_committed_example_matches_a_fresh_mock_run(tmp_path, script, module):
    module.main(["--out", str(tmp_path)])
    for name in (f"{script}.json", f"{script}.md"):
        fresh = (tmp_path / "reports" / name).read_text(encoding="utf-8")
        committed = (EXAMPLES_DIR / name).read_text(encoding="utf-8")
        assert fresh == committed, f"{name} drifted from trial-reports/examples/"

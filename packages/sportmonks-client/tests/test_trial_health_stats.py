"""FI-8 S5a: injuries, suspensions, and coach records.

Written against standing DoD items 12 and 13 from the start rather than
retrofitted: every failure path asserts the whole objective tuple by `==`, and
a rejected token is pinned as never reportable as a missing endpoint.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import trial_injuries  # noqa: E402
from _trial_common import (  # noqa: E402
    DEGRADED, EXAMPLES_DIR, EXIT_CONFIG, EXIT_OK, EXIT_REFUSED, EXIT_UNMET,
    MODE_MOCK, OBSERVED, UNMET, make_client, response,
)
from sportmonks_client.client import ENDPOINTS  # noqa: E402
from sportmonks_client.errors import SportmonksRequestError  # noqa: E402

SCRIPT = trial_injuries.SCRIPT
#: Both objectives this script owns, in emitted order.
OBJECTIVE_IDS = (11, 12)


def _collect(**overrides):
    transport = trial_injuries.mock_transport(**overrides)
    return trial_injuries.collect(make_client(MODE_MOCK, transport=transport), MODE_MOCK)


def _shapes(report):
    return {shape.name: shape.shape for shape in report.observed_shapes}


def _statuses(report):
    return {objective.id: objective.status for objective in report.objectives}


def _evidence(report, objective_id):
    return next(o.evidence for o in report.objectives if o.id == objective_id)


def _injury(**fields):
    return {"id": 51, "player_id": 101, "type_id": 1, **fields}


# --- End to end ----------------------------------------------------------------

def test_a_mock_run_exits_zero_and_writes_both_artifacts(tmp_path):
    assert trial_injuries.main(["--out", str(tmp_path)]) == EXIT_OK
    assert sorted(p.name for p in (tmp_path / "reports").iterdir()) == [
        f"{SCRIPT}.json", f"{SCRIPT}.md",
    ]


def test_mock_is_the_default_mode(tmp_path):
    trial_injuries.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert payload["mode"] == MODE_MOCK


def test_live_without_the_acknowledgement_refuses(tmp_path, capsys):
    assert trial_injuries.main(["--live", "--out", str(tmp_path)]) == EXIT_REFUSED
    assert capsys.readouterr().out.startswith("REFUSED:")


def test_a_mock_run_is_byte_stable_across_repeats(tmp_path):
    trial_injuries.main(["--out", str(tmp_path / "a")])
    trial_injuries.main(["--out", str(tmp_path / "b")])
    for suffix in ("json", "md"):
        name = f"{SCRIPT}.{suffix}"
        assert (tmp_path / "a" / "reports" / name).read_bytes() == \
               (tmp_path / "b" / "reports" / name).read_bytes()


def test_the_committed_example_matches_a_fresh_mock_run(tmp_path):
    """The frozen contract commits one mock report per script so
    `TRIAL_STATUS.md`'s evidence pointer resolves to something. A committed copy
    nobody re-derives is a stale artifact wearing an evidence pointer's name.

    This example was missing entirely until this change. The copy on the
    unmerged `feat/fi8-s5-health-stats` branch predates S5a's rewrite and
    reports the three families under different objective titles and different
    shape names than `main` now emits, so it was regenerated, not copied.
    """
    trial_injuries.main(["--out", str(tmp_path)])
    for suffix in ("json", "md"):
        name = f"{SCRIPT}.{suffix}"
        assert (EXAMPLES_DIR / name).read_bytes() == \
               (tmp_path / "reports" / name).read_bytes()


def test_the_objective_titles_match_the_trial_dashboard():
    from _trial_common import PACKAGE_ROOT
    dashboard = (PACKAGE_ROOT / "TRIAL_STATUS.md").read_text(encoding="utf-8")
    rows = {
        int(cells[1]): cells[2].strip()
        for line in dashboard.splitlines()
        if (cells := line.split("|")) and len(cells) > 3 and cells[1].strip().isdigit()
    }
    assert rows[11] == trial_injuries.OBJECTIVE_11
    assert rows[12] == trial_injuries.OBJECTIVE_12


# --- Standing DoD item 12: failure paths asserted whole ------------------------

def test_live_without_a_token_exits_three_and_says_so_in_the_report(tmp_path, monkeypatch):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    code = trial_injuries.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert [(o["id"], o["status"], o["evidence"]) for o in payload["objectives"]] == [
        (objective_id, UNMET, "configuration incomplete; no request was issued")
        for objective_id in OBJECTIVE_IDS
    ]


def test_a_rejected_token_exits_three_and_says_something_different(tmp_path, monkeypatch):
    build = trial_injuries.mock_transport
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(trial_injuries, "mock_transport", lambda **_: _with_401(build()))
    code = trial_injuries.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert [(o["id"], o["status"], o["evidence"]) for o in payload["objectives"]] == [
        (objective_id, UNMET, "authentication rejected by the provider")
        for objective_id in OBJECTIVE_IDS
    ]


def test_the_two_exit_three_reasons_are_not_interchangeable(tmp_path, monkeypatch):
    build = trial_injuries.mock_transport
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    trial_injuries.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path / "cfg")])
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(trial_injuries, "mock_transport", lambda **_: _with_401(build()))
    trial_injuries.main(["--out", str(tmp_path / "auth")])

    def _reason(where):
        payload = json.loads(
            (tmp_path / where / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
        return payload["objectives"][0]["evidence"]

    assert _reason("cfg") == "configuration incomplete; no request was issued"
    assert _reason("auth") == "authentication rejected by the provider"
    assert _reason("cfg") != _reason("auth")


# --- Standing DoD item 13: the taxonomy -----------------------------------------

def _with_401(transport):
    transport._by_endpoint[ENDPOINTS["injuries"][0]] = response({}, status=401)
    return transport


def test_a_rejected_token_is_never_reported_as_a_missing_family(tmp_path, monkeypatch):
    """A 401 is a credential fact, not a fact about the injuries endpoint. The
    broad `except SportmonksError` that would swallow it is the S3 defect
    (standing DoD item 13), and here it would tell a §12 reader that the
    provider carries no injury data."""
    build = trial_injuries.mock_transport
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(trial_injuries, "mock_transport", lambda **_: _with_401(build()))
    code = trial_injuries.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert payload["observed_shapes"] == []
    assert "no injuries record returned" not in json.dumps(payload)


# --- The three families ---------------------------------------------------------

def test_each_family_shape_reports_the_fields_that_arrived():
    """Three families, three different payloads, three different entries —
    asserted by equality and by pairwise distinctness, so a renderer ignoring
    its input cannot pass."""
    report = _collect(
        injuries={"data": [_injury(updated_at="2026-01-01T00:00:00Z")]},
        suspensions={"data": [{"id": 61, "player_id": 101, "games_remaining": 2}]},
        coaches={"data": [{"id": 71, "name": "A"}, {"id": 72, "name": "B", "team_id": 1}]},
    )
    shapes = _shapes(report)
    assert shapes["injuries"] == "1 record(s); record{id,player_id,type_id,updated_at}"
    assert shapes["suspensions"] == "1 record(s); record{id,player_id,games_remaining}"
    assert shapes["coaches"] == "2 record(s); record{id,name+team_id}"
    assert len({shapes["injuries"], shapes["suspensions"], shapes["coaches"]}) == 3


def test_an_absent_family_drops_its_shape_and_blocks_the_objective():
    report = _collect(suspensions={"data": []})
    assert "suspensions" not in _shapes(report)
    assert _statuses(report) == {11: UNMET, 12: OBSERVED}
    assert _evidence(report, 11).endswith("— no suspensions record returned")


def test_a_refusing_family_is_reported_as_a_failure_not_as_emptiness():
    report = _collect(
        coaches=SportmonksRequestError("gone", endpoint="coaches", status_code=404))
    assert _statuses(report) == {11: OBSERVED, 12: UNMET}
    assert _evidence(report, 12).endswith("— coaches request failed: SportmonksRequestError")


def test_objective_eleven_takes_the_worse_of_its_two_observations():
    """The DoD asks for injuries and suspensions to be separately statused; the
    brief gives them one id. The guard against the collapse is that objective 11
    cannot read `observed` unless both did, and names which fell short."""
    both = _collect()
    injuries_only = _collect(suspensions={"data": []})
    suspensions_only = _collect(injuries={"data": []})
    assert _statuses(both)[11] == OBSERVED
    assert _statuses(injuries_only)[11] == UNMET
    assert _statuses(suspensions_only)[11] == UNMET
    assert _evidence(injuries_only, 11) != _evidence(suspensions_only, 11)


# --- Freshness ------------------------------------------------------------------

def test_the_freshness_entry_names_the_field_that_supplied_the_value():
    """Two corpora using two different candidate names, two different entries.
    A hardcoded field name passes neither."""
    first = _collect(injuries={"data": [_injury(updated_at="2026-01-01T00:00:00Z")]})
    second = _collect(injuries={"data": [_injury(last_updated="2026-02-02T00:00:00Z")]})
    assert _shapes(first)["injury_freshness"] == "field=updated_at; 1/1 record(s) stamped"
    assert _shapes(second)["injury_freshness"] == "field=last_updated; 1/1 record(s) stamped"


def test_records_with_no_freshness_field_are_reported_not_defaulted_to_fresh():
    """An injury record of unknown age must never read as fresh: §12 would grant
    it full confidence. The entry is emitted precisely so the absence is
    visible rather than inferred from a missing entry."""
    report = _collect(injuries={"data": [_injury(), _injury(id=52)]})
    assert _shapes(report)["injury_freshness"] == "field=none found; 0/2 record(s) stamped"
    assert _statuses(report)[11] == DEGRADED


def test_partial_stamping_degrades_rather_than_rounding_either_way():
    report = _collect(injuries={"data": [
        _injury(updated_at="2026-01-01T00:00:00Z"), _injury(id=52),
    ]})
    assert _shapes(report)["injury_freshness"] == "field=updated_at; 1/2 record(s) stamped"
    assert _statuses(report)[11] == DEGRADED
    assert "1 of 2 injury record(s) carry none of the candidate freshness fields" \
        in _evidence(report, 11)


def test_missing_timestamps_degrade_but_a_missing_family_is_unmet():
    """`degraded` and `unmet` are different facts: injuries of unknown age is a
    partial observation, no injuries at all is not an observation."""
    stale = _collect(injuries={"data": [_injury()]})
    absent = _collect(injuries={"data": []})
    assert (_statuses(stale)[11], _statuses(absent)[11]) == (DEGRADED, UNMET)


def test_the_candidate_fields_are_searched_in_order():
    report = _collect(injuries={"data": [
        _injury(updated_at="2026-01-01T00:00:00Z", last_updated="2026-02-02T00:00:00Z"),
    ]})
    assert _shapes(report)["injury_freshness"] == "field=updated_at; 1/1 record(s) stamped"


def test_a_null_freshness_value_does_not_count_as_stamped():
    report = _collect(injuries={"data": [_injury(updated_at=None)]})
    assert _shapes(report)["injury_freshness"] == "field=none found; 0/1 record(s) stamped"


def test_a_degraded_objective_exits_one(tmp_path, monkeypatch):
    build = trial_injuries.mock_transport
    monkeypatch.setattr(
        trial_injuries, "mock_transport",
        lambda **_: build(injuries={"data": [_injury()]}),
    )
    assert trial_injuries.main(["--out", str(tmp_path)]) == EXIT_UNMET


def test_an_empty_envelope_from_edge_cases_exits_one(tmp_path, monkeypatch):
    from _trial_common import load_fixture
    empty = load_fixture("edge_cases.json")["empty"]
    build = trial_injuries.mock_transport
    monkeypatch.setattr(trial_injuries, "mock_transport", lambda **_: build(injuries=empty))
    assert trial_injuries.main(["--out", str(tmp_path)]) == EXIT_UNMET


# --- The synthesized rehearsal --------------------------------------------------

def test_the_synthesized_freshness_is_declared_in_the_report(tmp_path):
    trial_injuries.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert trial_injuries.SYNTHETIC_WARNING in payload["warnings"]


def test_the_synthesis_uses_a_candidate_name_the_script_would_actually_find():
    """A synthesis writing a field outside the search list would rehearse
    nothing: the run would degrade in mock and the gap would look like a
    provider fact.

    The subset assertion this replaces was **satisfied by the empty set**, so a
    synthesis that added nothing at all passed it — the one outcome the
    docstring is about. Measured rather than reasoned: making
    `_with_synthetic_freshness` return its input unchanged left this test green
    while four others in this file failed.

    That is why the severity is low and the defect is still real. The no-op is
    caught, so this was never a hole in coverage; it was an assertion that did
    not test its own docstring, and a subset check against a non-empty
    allowlist is the shape that failure always takes.
    """
    payload = trial_injuries._with_synthetic_freshness({"data": [_injury()]})
    added = set(payload["data"][0]) - set(_injury())
    assert len(added) == 1, "the synthesis must add exactly one field"
    field = added.pop()
    assert field in trial_injuries.FRESHNESS_FIELDS
    assert payload["data"][0][field] is not None, (
        "a candidate field carrying None is not stamped -- `freshness_of` skips "
        "null values, so synthesizing one would rehearse nothing while looking "
        "like it had"
    )


# --- The declaration -------------------------------------------------------------

def test_every_entry_is_declared_and_names_a_test_that_exists():
    report = _collect()
    assert set(trial_injuries.DECLARED_SHAPES) == set(_shapes(report))
    for names in trial_injuries.DECLARED_SHAPES.values():
        for name in names:
            assert name in globals(), name

"""FI-8 S5a: injuries, suspensions, and coach records (`trial_injuries.py`),
and S5b: fixture-level team and player match statistics plus the pre/during/post
recording scaffold (`trial_stats.py`).

Written against standing DoD items 12 and 13 from the start rather than
retrofitted: every failure path asserts the whole objective tuple by `==`, and
a rejected token is pinned as never reportable as a missing endpoint.

The two scripts are independent — S5b was extracted onto `main` after S5a — so
each half owns its own helpers below rather than sharing a rewritten set.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import _trial_common  # noqa: E402
import trial_injuries  # noqa: E402
import trial_stats  # noqa: E402
from _trial_common import (  # noqa: E402
    DEGRADED, EXAMPLES_DIR, EXIT_CONFIG, EXIT_OK, EXIT_REFUSED, EXIT_UNMET,
    MODE_MOCK, NOT_APPLICABLE, OBSERVED, UNMET, ReplayTransport, make_client,
    response,
)
from sportmonks_client.client import ENDPOINTS  # noqa: E402
from sportmonks_client.config import SportmonksConfig  # noqa: E402
from sportmonks_client.errors import SportmonksRequestError  # noqa: E402
from trial_stats import SampleDiff, StatSample, diff_samples  # noqa: E402

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


# ==============================================================================
# trial_stats.py  (S5b â€” objectives 13-16)
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
    return code, json.loads(
        (tmp_path / "reports" / "trial_stats.json").read_text(encoding="utf-8"))


def _stats_objective(payload, obj_id, title):
    for objective in payload["objectives"]:
        if objective["id"] == obj_id and objective["title"] == title:
            return objective
    raise AssertionError(f"no objective ({obj_id}, {title!r}) in {payload['objectives']}")


# --- End to end ----------------------------------------------------------------

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
    team = _stats_objective(payload, 13, "Fixture-level team statistics")
    player = _stats_objective(payload, 14, "Player match statistics")
    assert team["status"] == OBSERVED and player["status"] == OBSERVED
    assert "fixture_id=2/2, team_id=2/2, type_id=2/2, value=2/2" in team["evidence"]
    assert "fixture_id=2/2, player_id=2/2, type_id=2/2, value=2/2" in player["evidence"]
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["team_statistics_fields"] == "fixture_id, team_id, type_id, value"
    assert shapes["player_statistics_fields"] == "fixture_id, player_id, type_id, value"


def test_a_stats_mock_run_writes_both_artifacts(tmp_path):
    assert trial_stats.main(["--out", str(tmp_path)]) == EXIT_OK
    assert sorted(p.name for p in (tmp_path / "reports").iterdir()) == [
        "trial_stats.json", "trial_stats.md",
    ]


def test_stats_mock_is_the_default_mode(tmp_path):
    _, payload = _run_stats(tmp_path)
    assert payload["mode"] == MODE_MOCK


def test_stats_live_without_the_acknowledgement_refuses(tmp_path):
    assert trial_stats.main(["--live", "--out", str(tmp_path)]) == EXIT_REFUSED


# --- S5 DoD 3: per-field presence counts ---------------------------------------

@pytest.mark.parametrize(
    "family,objective_id,title",
    [("team_stats", 13, "Fixture-level team statistics"),
     ("player_stats", 14, "Player match statistics")],
)
def test_partial_field_presence_is_counted_not_rounded(tmp_path, family, objective_id, title):
    """S5 DoD 3's per-field presence counts, made falsifiable.

    Every stats fixture in this file had a field on *all* records or on *none*,
    so `presence[name]` could be replaced with `len(records)` and the suite
    stayed green - a 3-record payload with `value` on one record would report
    `value=3/3`. `trial_injuries.py` has the analogue
    (`test_partial_stamping_degrades_rather_than_rounding_either_way`); the
    sibling script did not, and a review found it by seeding.

    k must be neither 0 nor n, or the assertion is satisfiable by a literal.
    """
    id_field = "team_id" if family == "team_stats" else "player_id"
    records = [
        {"id": 1, "fixture_id": 900, id_field: 10, "type_id": 5, "value": 3},
        {"id": 2, "fixture_id": 900, id_field: 11, "type_id": 5},
        {"id": 3, "fixture_id": 900, id_field: 12, "type_id": 5},
    ]
    _, payload = _run_stats(tmp_path, **{family: records})
    evidence = _stats_objective(payload, objective_id, title)["evidence"]
    assert "value=1/3" in evidence, "a partial presence count must be k/n, not n/n"
    assert "value=3/3" not in evidence
    assert "3 record(s)" in evidence, "the record count is derived, not a literal"


def test_a_null_stat_value_does_not_count_as_present(tmp_path):
    """`_field_presence` counted key presence, not value presence: a record
    carrying `value: null` was scored the same as one carrying a real value.
    `trial_squads.py`/`trial_fixtures.py` already read `null` as absent
    everywhere else in this package; this closes the one place `trial_stats.py`
    did not."""
    _, payload = _run_stats(tmp_path, team_stats=[
        {"id": 91, "fixture_id": 1001, "team_id": 1, "type_id": 42, "value": None},
        {"id": 92, "fixture_id": 1001, "team_id": 2, "type_id": 42, "value": 45},
    ])
    team = _stats_objective(payload, 13, "Fixture-level team statistics")
    assert "value=1/2" in team["evidence"], "a null value must not count as present"
    assert "value=2/2" not in team["evidence"]
    assert team["status"] == OBSERVED, "value is present on at least one record"


def test_stats_record_count_tracks_the_payload(tmp_path):
    """The record count in `evidence` survived seeding as a literal - the same
    defect closed for suspensions and coaches, left open in the sibling script."""
    _, payload = _run_stats(tmp_path, team_stats=[
        {"id": 1, "fixture_id": 900, "team_id": 10, "type_id": 5, "value": 3},
    ])
    evidence = _stats_objective(payload, 13, "Fixture-level team statistics")["evidence"]
    assert "1 record(s)" in evidence
    assert "2 record(s)" not in evidence


# --- Standing DoD item 10: the shape entries must be droppable -------------------

def test_team_statistics_field_missing_entirely_degrades_and_shrinks_only_that_shape(tmp_path):
    code, payload = _run_stats(tmp_path, team_stats=[
        {"id": 91, "fixture_id": 1001, "team_id": 1, "type_id": 42},
        {"id": 92, "fixture_id": 1001, "team_id": 2, "type_id": 42},
    ])
    assert code == EXIT_UNMET
    team = _stats_objective(payload, 13, "Fixture-level team statistics")
    assert team["status"] == DEGRADED
    assert "missing entirely: value" in team["evidence"]
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["team_statistics_fields"] == "fixture_id, team_id, type_id"
    assert "value" not in shapes["team_statistics_fields"]
    # the player-stats objective and shape are untouched
    assert _stats_objective(payload, 14, "Player match statistics")["status"] == OBSERVED
    assert shapes["player_statistics_fields"] == "fixture_id, player_id, type_id, value"


def test_player_statistics_field_missing_entirely_degrades_and_shrinks_only_that_shape(tmp_path):
    code, payload = _run_stats(tmp_path, player_stats=[
        {"id": 1011, "fixture_id": 1001, "player_id": 101, "type_id": 52},
    ])
    assert code == EXIT_UNMET
    player = _stats_objective(payload, 14, "Player match statistics")
    assert player["status"] == DEGRADED
    assert "missing entirely: value" in player["evidence"]
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["player_statistics_fields"] == "fixture_id, player_id, type_id"
    assert _stats_objective(payload, 13, "Fixture-level team statistics")["status"] == OBSERVED


def test_no_team_statistics_is_unmet_and_drops_only_that_shape(tmp_path):
    code, payload = _run_stats(tmp_path, team_stats=[])
    assert code == EXIT_UNMET
    team = _stats_objective(payload, 13, "Fixture-level team statistics")
    assert team["status"] == UNMET
    assert team["evidence"] == "no fixture-level team statistics records observed"
    shapes = {s["name"] for s in payload["observed_shapes"]}
    assert "team_statistics_fields" not in shapes
    assert "player_statistics_fields" in shapes
    assert _stats_objective(payload, 14, "Player match statistics")["status"] == OBSERVED


def test_no_player_statistics_is_unmet_and_drops_only_that_shape(tmp_path):
    code, payload = _run_stats(tmp_path, player_stats=[])
    assert code == EXIT_UNMET
    player = _stats_objective(payload, 14, "Player match statistics")
    assert player["status"] == UNMET
    assert player["evidence"] == "no player match statistics records observed"
    shapes = {s["name"] for s in payload["observed_shapes"]}
    assert "player_statistics_fields" not in shapes
    assert "team_statistics_fields" in shapes
    assert _stats_objective(payload, 13, "Fixture-level team statistics")["status"] == OBSERVED


# --- S5 DoD 4: objectives 15 and 16 are modal, not payload-derived ---------------

def test_objectives_15_and_16_are_always_not_applicable_in_mock_mode(tmp_path):
    """S5 DoD 4: this is a modal statement about what mock mode can measure,
    not a fact about the payload -- it must hold regardless of what the team
    and player statistics fixtures contain."""
    for kwargs in ({}, {"team_stats": []}, {"player_stats": []},
                   {"team_stats": [], "player_stats": []}):
        _, payload = _run_stats(tmp_path, **kwargs)
        assert _stats_objective(
            payload, 15, "Data update timing before, during, and after matches") == {
            "id": 15, "title": "Data update timing before, during, and after matches",
            "status": NOT_APPLICABLE, "evidence": "requires FI-9 live observation",
        }
        assert _stats_objective(payload, 16, "Post-match corrections") == {
            "id": 16, "title": "Post-match corrections",
            "status": NOT_APPLICABLE, "evidence": "requires FI-9 live observation",
        }


# --- Standing DoD item 13: the taxonomy -----------------------------------------

def test_stats_exits_config_when_token_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    code = trial_stats.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    assert code == EXIT_CONFIG
    payload = json.loads(
        (tmp_path / "reports" / "trial_stats.json").read_text(encoding="utf-8"))
    assert [(o["id"], o["status"], o["evidence"]) for o in payload["objectives"]] == [
        (13, UNMET, "configuration incomplete; no request was issued"),
        (14, UNMET, "configuration incomplete; no request was issued"),
        (15, NOT_APPLICABLE, "requires FI-9 live observation"),
        (16, NOT_APPLICABLE, "requires FI-9 live observation"),
    ]


def _stats_client_serving(monkeypatch, served, **config_kwargs):
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(
        trial_stats, "make_client",
        lambda mode, **kw: _trial_common.make_client(
            mode, transport=ReplayTransport([served] * 12),
            config=SportmonksConfig(api_token="DUMMY-TRIAL-TOKEN", **config_kwargs),
            out_dir=kw.get("out_dir"),
        ),
    )


def test_a_rejected_token_exits_three_not_one(monkeypatch, tmp_path):
    """The taxonomy defect that sank the sibling slice S3.

    There, `main()` had the correct config/auth handlers but an inner
    per-family `except SportmonksError` swallowed a 401 into a per-family
    "unavailable" classification, so an authentication failure exited **1** --
    "the provider does not have this data" -- instead of **3** -- "stop, your
    token is wrong". A materially different trial conclusion on day one.

    This script has no inner catch, which review confirmed by probe. This pins
    it, because "no inner catch today" is not a property anything checked.
    """
    _stats_client_serving(monkeypatch, response({}, status=401))
    code = trial_stats.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    assert code == EXIT_CONFIG, "an authentication failure is exit 3, never exit 1"


def test_a_throttled_provider_degrades_rather_than_reporting_misconfiguration(
    monkeypatch, tmp_path
):
    """The payload-preserving half of the taxonomy rule, which shipped untested.

    Being rate-limited is not a misconfiguration -- for objective 17 it is
    evidence. Only config and auth reach exit 3; every other provider failure
    is a degraded observation.
    """
    _stats_client_serving(monkeypatch, response({}, status=429), max_retries=0)
    code = trial_stats.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    assert code != EXIT_CONFIG, "a throttled provider is not a configuration failure"
    payload = json.loads(
        (tmp_path / "reports" / "trial_stats.json").read_text(encoding="utf-8"))
    assert any(o["status"] == DEGRADED for o in payload["objectives"])


def test_a_rejected_payload_is_recorded_not_discarded(monkeypatch, tmp_path):
    """The frozen contract requires a degraded observation to carry "the payload
    recorded, not discarded".

    The script previously recorded only the exception class name, so a
    `SportmonksSchemaError` -- section 17's top risk, and the single thing FI-8
    exists to rehearse -- told the FI-9 operator nothing about the payload that
    caused it. `trial_auth.py` froze the `rejected_envelope` entry for exactly
    this.
    """
    _stats_client_serving(monkeypatch, response(
        {"data": [{"id": 1}], "pagination": {"current_page": 1, "has_more": "yes"}}))
    code = trial_stats.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    assert code != EXIT_CONFIG, "a shape difference is not a configuration failure"
    payload = json.loads(
        (tmp_path / "reports" / "trial_stats.json").read_text(encoding="utf-8"))
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert "rejected_envelope" in shapes, "the refused payload must be recorded"
    assert "pagination{current_page,has_more}" in shapes["rejected_envelope"]


# --- Byte stability and the committed example -----------------------------------

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

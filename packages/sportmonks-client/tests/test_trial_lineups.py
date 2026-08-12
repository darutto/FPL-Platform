"""FI-8 S4b: lineups, formations, the formation grid, and substitutions.

The highest-risk slice in the phase, and the risk is not that the script
crashes — it is that it reports a confident answer to a question the provider
has not been asked. So the tests here are weighted toward the two ways that
happens: a grid shape asserted rather than recorded, and a substitution
direction inverted while every count stays plausible.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import trial_lineups  # noqa: E402
from _trial_common import (  # noqa: E402
    DEGRADED, EXIT_CONFIG, EXIT_OK, EXIT_REFUSED, EXIT_UNMET, MODE_MOCK, OBSERVED,
    UNMET, load_fixture, make_client, response,
)
from sportmonks_client.client import ENDPOINTS  # noqa: E402
from sportmonks_client.errors import SportmonksRequestError  # noqa: E402

SCRIPT = trial_lineups.SCRIPT
#: Every objective this script owns, in emitted order.
OBJECTIVE_IDS = (6, 7, 8, 9, 10)


def _collect(**overrides):
    transport = trial_lineups.mock_transport(**overrides)
    return trial_lineups.collect(make_client(MODE_MOCK, transport=transport), MODE_MOCK)


def _shapes(report):
    return {shape.name: shape.shape for shape in report.observed_shapes}


def _statuses(report):
    return {objective.id: objective.status for objective in report.objectives}


def _evidence(report, objective_id):
    return next(o.evidence for o in report.objectives if o.id == objective_id)


def _lineup(**fields):
    return {"id": 21, "fixture_id": 1001, "player_id": 101, "type_id": 11,
            "detailed_position_id": 24, "formation_field": "1:4", **fields}


def _sub(**fields):
    return {"id": 41, "fixture_id": 1001, "player_in_id": 102,
            "player_out_id": 101, "minute": 70, **fields}


def _pool(*records):
    return {"data": list(records)}


# --- End to end ----------------------------------------------------------------

def test_a_mock_run_exits_zero_and_writes_both_artifacts(tmp_path):
    assert trial_lineups.main(["--out", str(tmp_path)]) == EXIT_OK
    assert sorted(p.name for p in (tmp_path / "reports").iterdir()) == [
        f"{SCRIPT}.json", f"{SCRIPT}.md",
    ]


def test_mock_is_the_default_mode(tmp_path):
    trial_lineups.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert payload["mode"] == MODE_MOCK


def test_live_without_the_acknowledgement_refuses(tmp_path, capsys):
    assert trial_lineups.main(["--live", "--out", str(tmp_path)]) == EXIT_REFUSED
    assert capsys.readouterr().out.startswith("REFUSED:")


def test_a_mock_run_is_byte_stable_across_repeats(tmp_path):
    trial_lineups.main(["--out", str(tmp_path / "a")])
    trial_lineups.main(["--out", str(tmp_path / "b")])
    for suffix in ("json", "md"):
        name = f"{SCRIPT}.{suffix}"
        assert (tmp_path / "a" / "reports" / name).read_bytes() == \
               (tmp_path / "b" / "reports" / name).read_bytes()


def test_the_committed_example_matches_a_fresh_mock_run(tmp_path):
    from _trial_common import EXAMPLES_DIR
    trial_lineups.main(["--out", str(tmp_path)])
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
    assert [rows[i] for i in OBJECTIVE_IDS] == [
        title for _, title in trial_lineups.OBJECTIVE_TITLES
    ]


# --- Standing DoD item 12: failure paths asserted whole ------------------------

def test_live_without_a_token_exits_three_and_says_so_in_the_report(tmp_path, monkeypatch):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    code = trial_lineups.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert [(o["id"], o["status"], o["evidence"]) for o in payload["objectives"]] == [
        (objective_id, UNMET, "configuration incomplete; no request was issued")
        for objective_id in OBJECTIVE_IDS
    ]


def test_a_rejected_token_exits_three_and_says_something_different(tmp_path, monkeypatch):
    build = trial_lineups.mock_transport
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(trial_lineups, "mock_transport", lambda **_: _with_401(build()))
    code = trial_lineups.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert [(o["id"], o["status"], o["evidence"]) for o in payload["objectives"]] == [
        (objective_id, UNMET, "authentication rejected by the provider")
        for objective_id in OBJECTIVE_IDS
    ]


def test_the_two_exit_three_reasons_are_not_interchangeable(tmp_path, monkeypatch):
    build = trial_lineups.mock_transport
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    trial_lineups.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path / "cfg")])
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(trial_lineups, "mock_transport", lambda **_: _with_401(build()))
    trial_lineups.main(["--out", str(tmp_path / "auth")])

    def _reason(where):
        payload = json.loads(
            (tmp_path / where / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
        return payload["objectives"][0]["evidence"]

    assert _reason("cfg") == "configuration incomplete; no request was issued"
    assert _reason("auth") == "authentication rejected by the provider"
    assert _reason("cfg") != _reason("auth")


# --- Standing DoD item 13: the taxonomy -----------------------------------------

def _with_401(transport):
    transport._by_endpoint[ENDPOINTS["lineups"][0]] = response({}, status=401)
    return transport


def test_a_rejected_token_is_never_reported_as_an_absent_grid(tmp_path, monkeypatch):
    """A 401 is a credential fact. Swallowed, it becomes "no lineup record" —
    which is §14.4's NO-GO condition verbatim, decided on trial day 2 by an
    expired token."""
    build = trial_lineups.mock_transport
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(trial_lineups, "mock_transport", lambda **_: _with_401(build()))
    code = trial_lineups.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert payload["observed_shapes"] == []
    assert "none found" not in json.dumps(payload)


# --- The three families ---------------------------------------------------------

def test_each_family_shape_reports_the_fields_that_arrived():
    report = _collect(
        lineups=_pool(_lineup()),
        formations=_pool({"id": 31, "fixture_id": 1001, "formation": "4-3-3"}),
        substitutions=_pool(_sub()),
    )
    shapes = _shapes(report)
    assert shapes["lineups"] == (
        "1 record(s); record{id,fixture_id,player_id,type_id,"
        "detailed_position_id,formation_field}"
    )
    assert shapes["formations"] == "1 record(s); record{id,fixture_id,formation}"
    assert shapes["substitutions"] == (
        "1 record(s); record{id,fixture_id,player_in_id,player_out_id,minute}"
    )
    assert len({shapes["lineups"], shapes["formations"], shapes["substitutions"]}) == 3


def test_an_absent_family_drops_its_shape_and_blocks_its_objectives():
    """Lineups carry 6, 8 and 9; formations carry 7; substitutions carry 10. An
    absent family must block only its own."""
    no_lineups = _collect(lineups={"data": []})
    assert "lineups" not in _shapes(no_lineups)
    assert _statuses(no_lineups) == {6: UNMET, 7: OBSERVED, 8: UNMET, 9: UNMET, 10: OBSERVED}

    no_subs = _collect(substitutions={"data": []})
    assert "substitutions" not in _shapes(no_subs)
    assert _statuses(no_subs)[10] == UNMET


def test_a_refusing_family_is_reported_as_a_failure_not_as_emptiness():
    report = _collect(
        formations=SportmonksRequestError("gone", endpoint="formations", status_code=404))
    assert _statuses(report)[7] == UNMET
    assert "formations request failed: SportmonksRequestError" in _evidence(report, 7)


# --- DoD 1 and 3: the grid is recorded, never asserted ----------------------------

def test_the_grid_entry_reports_the_shape_it_found():
    """Three payloads whose grid differs in *structure*, three different
    entries, asserted by `==`. A script that named the documented shape would
    produce one string for all three."""
    documented = _collect(lineups=_pool(_lineup(formation_field="1:4")))
    listed = _collect(lineups=_pool(_lineup(formation_field=[1, 4])))
    nested = _collect(lineups=_pool(_lineup(formation_field=[[1, 4], [2, 3]])))
    assert _shapes(documented)["formation_grid"] == \
        "field=formation_field; shape=str; documented=str; 1/1 record(s)"
    assert _shapes(listed)["formation_grid"] == \
        "field=formation_field; shape=list[int]; documented=str; 1/1 record(s)"
    assert _shapes(nested)["formation_grid"] == \
        "field=formation_field; shape=list[list[int]]; documented=str; 1/1 record(s)"
    assert len({_shapes(r)["formation_grid"] for r in (documented, listed, nested)}) == 3


def test_an_unexpected_grid_shape_degrades_and_is_recorded_not_rejected():
    """DoD 1: a payload whose grid differs from the documented shape exits 1 with
    the objective `degraded` and the shape recorded — not a crash, not a silent
    pass. Driven from the checked-in `edge_cases.json` entries this slice added,
    because a fixture written inside the test proves only that the test can
    construct one."""
    for name, expected in (
        ("lineup_grid_wrong_type", "list[int]"),
        ("lineup_grid_nested", "list[list[int]]"),
    ):
        report = _collect(lineups=load_fixture("edge_cases.json")[name])
        assert _statuses(report)[8] == DEGRADED, name
        assert expected in _shapes(report)["formation_grid"], name
        assert "recorded, not rejected" in _evidence(report, 8), name


def test_an_unexpected_grid_shape_exits_one(tmp_path, monkeypatch):
    build = trial_lineups.mock_transport
    monkeypatch.setattr(
        trial_lineups, "mock_transport",
        lambda **_: build(lineups=load_fixture("edge_cases.json")["lineup_grid_nested"]),
    )
    assert trial_lineups.main(["--out", str(tmp_path)]) == EXIT_UNMET


def test_the_grid_entry_is_emitted_when_the_grid_is_absent():
    """Second branch of standing DoD item 10. An absent grid is the NO-GO
    condition §14.4 names by name, and an entry that vanished on absence would
    report it by saying nothing."""
    for name in ("lineup_grid_missing", "lineup_grid_null"):
        report = _collect(lineups=load_fixture("edge_cases.json")[name])
        assert _shapes(report)["formation_grid"] == \
            "field=none found; shape=none; documented=str; 0/1 record(s)", name
        assert _statuses(report)[8] == UNMET, name


def test_a_formation_string_alone_does_not_carry_the_grid():
    """DoD 3, the reason 7 and 8 are separate: a formation string satisfies GO
    criterion (b) on a technicality while the grid is absent. Collapsing them
    would report that state as a pass."""
    report = _collect(lineups=load_fixture("edge_cases.json")["lineup_grid_missing"])
    assert _statuses(report)[7] == OBSERVED
    assert _statuses(report)[8] == UNMET


def test_seven_eight_and_nine_move_independently():
    """Three separately-observable facts, shown by moving each one alone."""
    baseline = _collect(lineups=_pool(_lineup()))
    assert _statuses(baseline)[7] == OBSERVED
    assert _statuses(baseline)[8] == OBSERVED
    assert _statuses(baseline)[9] == OBSERVED

    no_formation = _collect(lineups=_pool(_lineup()), formations={"data": []})
    no_grid = _collect(lineups=_pool(_lineup(formation_field=None)))
    no_position = _collect(lineups=_pool(_lineup(detailed_position_id=None)))
    assert (_statuses(no_formation)[7], _statuses(no_formation)[8],
            _statuses(no_formation)[9]) == (UNMET, OBSERVED, OBSERVED)
    assert (_statuses(no_grid)[7], _statuses(no_grid)[8],
            _statuses(no_grid)[9]) == (OBSERVED, UNMET, OBSERVED)
    assert (_statuses(no_position)[7], _statuses(no_position)[8],
            _statuses(no_position)[9]) == (OBSERVED, OBSERVED, UNMET)


def test_no_grid_semantics_are_decided():
    """DoD 5. `value_shape` reports structure and never reads a value, so two
    grids that mean opposite things under either reading of §14.3 question 13
    are reported identically — which is the correct behaviour for a script whose
    job is to describe."""
    assert trial_lineups.value_shape("1:4") == trial_lineups.value_shape("4:1") == "str"
    assert trial_lineups.value_shape([1, 4]) == "list[int]"
    assert trial_lineups.value_shape([[1, 4]]) == "list[list[int]]"
    assert trial_lineups.value_shape(None) == "null"
    assert trial_lineups.value_shape({"x": 1, "y": 2}) == "dict{x,y}"
    assert trial_lineups.value_shape([]) == "list[]"


# --- Objective 6: the partition, without naming a side ----------------------------

def test_the_starter_entry_reports_the_partition_without_naming_a_side():
    """Two lineups partitioned by different fields with different values, two
    different entries. The entry never says which value means "starter": that is
    a semantic decision and §14.3 has not asked the question yet."""
    by_type = _collect(lineups=_pool(
        _lineup(type_id=11), _lineup(id=22, player_id=102, type_id=12)))
    by_flag = _collect(lineups=_pool(
        _lineup(type_id=None, starting=True),
        _lineup(id=22, player_id=102, type_id=None, starting=False)))
    assert _shapes(by_type)["starter_marker"] == \
        "field=type_id; values{11:1,12:1}; 2/2 record(s)"
    assert _shapes(by_flag)["starter_marker"] == \
        "field=starting; values{False:1,True:1}; 2/2 record(s)"
    assert "starter" not in _shapes(by_type)["starter_marker"]


def test_the_starter_entry_is_emitted_when_no_field_partitions_the_lineup():
    """Second branch: "no field partitions the lineup" is what makes objective 6
    unanswerable, and GO criterion (b) turns on it."""
    report = _collect(lineups=_pool(_lineup(type_id=None)))
    assert _shapes(report)["starter_marker"] == \
        "field=none found; values{}; 0/1 record(s)"
    assert _statuses(report)[6] == UNMET


def test_one_value_across_every_record_does_not_partition_anything():
    """A field present on every record with a single value cannot separate
    starters from substitutes. Reporting it as observed would claim a partition
    that is not there."""
    report = _collect(lineups=_pool(
        _lineup(type_id=11), _lineup(id=22, player_id=102, type_id=11)))
    assert _statuses(report)[6] == DEGRADED
    assert "does not partition the lineup" in _evidence(report, 6)


# --- Objective 9 -------------------------------------------------------------------

def test_the_detailed_position_entry_names_the_field_that_supplied_it():
    """Two corpora using two different candidate names, two different entries."""
    first = _collect(lineups=_pool(_lineup(detailed_position_id=24)))
    second = _collect(lineups=_pool(_lineup(detailed_position_id=None, position_id=27)))
    assert _shapes(first)["detailed_position"] == \
        "field=detailed_position_id; 1/1 record(s); 1 distinct value(s)"
    assert _shapes(second)["detailed_position"] == \
        "field=position_id; 1/1 record(s); 1 distinct value(s)"


def test_the_detailed_position_entry_is_emitted_when_it_is_absent():
    """Second branch: "grid absent, detailed_position present" is the fallback
    §14.4's NO-GO clause describes, and it is only visible if both entries are
    always there to be compared."""
    report = _collect(lineups=_pool(_lineup(detailed_position_id=None)))
    assert _shapes(report)["detailed_position"] == \
        "field=none found; 0/1 record(s); 0 distinct value(s)"
    assert _statuses(report)[9] == UNMET


# --- Objective 10: direction is the invertible fact --------------------------------

def test_the_substitution_direction_is_not_invertible():
    """DoD 4. Two substitutions with the two ids swapped must produce two
    different triples, asserted by `==` in `(player_off, player_on, minute)`
    order. An implementation reading the fields backwards passes every count and
    fails exactly this."""
    forward = _collect(substitutions=_pool(_sub(player_out_id=101, player_in_id=102)))
    reverse = _collect(substitutions=_pool(_sub(player_out_id=102, player_in_id=101)))
    assert _shapes(forward)["substitution_direction"] == \
        "off=player_out_id; on=player_in_id; first=(101,102,70)"
    assert _shapes(reverse)["substitution_direction"] == \
        "off=player_out_id; on=player_in_id; first=(102,101,70)"
    assert _shapes(forward)["substitution_direction"] != \
        _shapes(reverse)["substitution_direction"]


def _entities(*payloads):
    """Parse raw payloads into provider entities without going through a report."""
    from sportmonks_client.models import Substitution as SubstitutionEntity, parse_entity
    return tuple(
        parse_entity(SubstitutionEntity, payload, "substitutions") for payload in payloads
    )


def test_the_triples_are_built_in_the_documented_order():
    """The order is the contract: `(player_off, player_on, minute)`. Asserted on
    the dataclass fields rather than only through the rendered string, so a
    renderer that reordered its inputs could not hide behind it."""
    triples = trial_lineups.substitution_triples(
        _entities(_sub(player_out_id=7, player_in_id=9, minute=64)))
    assert triples[0].player_off == 7
    assert triples[0].player_on == 9
    assert triples[0].minute == 64
    assert triples[0].render() == "(7,9,64)"


def test_the_direction_entry_is_emitted_when_a_side_is_missing():
    """Second branch: a substitution missing one side is the state that makes
    the direction unreadable, and the entry is how the report says so."""
    report = _collect(substitutions=_pool(_sub(player_in_id=None)))
    assert _shapes(report)["substitution_direction"] == \
        "off=player_out_id; on=none found; first=(101,None,70)"
    assert _statuses(report)[10] == DEGRADED
    assert "missing one of (player_off, player_on, minute)" in _evidence(report, 10)


def test_a_substitution_without_a_minute_degrades():
    report = _collect(substitutions=_pool(_sub(minute=None)))
    assert _statuses(report)[10] == DEGRADED


# --- Exit codes ---------------------------------------------------------------------

def test_an_empty_envelope_from_edge_cases_exits_one(tmp_path, monkeypatch):
    empty = load_fixture("edge_cases.json")["empty"]
    build = trial_lineups.mock_transport
    monkeypatch.setattr(trial_lineups, "mock_transport", lambda **_: build(lineups=empty))
    assert trial_lineups.main(["--out", str(tmp_path)]) == EXIT_UNMET


# --- The synthesized rehearsal --------------------------------------------------------

def test_the_synthesis_is_declared_in_the_report(tmp_path):
    trial_lineups.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert trial_lineups.SYNTHETIC_WARNING in payload["warnings"]


def test_the_synthesis_uses_candidate_names_the_script_would_actually_find():
    """A synthesis writing fields outside the search lists would rehearse
    nothing: the run would degrade in mock and the gap would look like a
    provider fact.

    Asserted as membership per field rather than as a subset of the union. A
    subset check against a non-empty allowlist is **satisfied by the empty
    set**, so a synthesis that added nothing at all would pass it — the one
    outcome this test exists to exclude. Same defect as the S5a assertion
    corrected in #122; it is written out here because the shape is what
    recurs, not the instance.
    """
    source = {"data": [{"id": 21, "fixture_id": 1001, "player_id": 101,
                        "formation_field": "1:4"}]}
    built = trial_lineups._synthesize_lineups(source)
    record = built["data"][0]
    added = set(record) - set(source["data"][0])
    assert len(added) == 2, "the synthesis must add a starter marker and a position"

    starter = added & set(trial_lineups.STARTER_FIELDS)
    position = added & set(trial_lineups.DETAILED_POSITION_FIELDS)
    assert len(starter) == 1 and len(position) == 1
    for field in (starter | position):
        assert record[field] is not None, (
            f"{field} was synthesized as None; `survey` skips null values, so "
            "the rehearsal would find nothing while looking like it had"
        )


def test_the_synthesis_produces_a_real_partition():
    """A rehearsal where every record carries the same starter value would
    degrade objective 6 correctly and rehearse nothing."""
    built = trial_lineups._synthesize_lineups(
        {"data": [{"id": 21, "fixture_id": 1001, "player_id": 101,
                   "formation_field": "1:4"}]})
    values = {record[trial_lineups.STARTER_FIELDS[0]] for record in built["data"]}
    assert len(values) == 2


# --- The declaration -------------------------------------------------------------

def test_every_entry_is_declared_and_names_a_test_that_exists():
    report = _collect()
    assert set(trial_lineups.DECLARED_SHAPES) == set(_shapes(report))
    for names in trial_lineups.DECLARED_SHAPES.values():
        for name in names:
            assert name in globals(), name

"""FI-8 S4a: teams, squads, and current player records.

Every reported value is pinned by at least two inputs with pairwise-distinct
expected values asserted by `==` (standing DoD item 11), every failure path is
asserted as a whole `(id, status, evidence)` tuple (item 12), and a rejected
token is pinned as never reportable as a missing family (item 13).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import trial_squads  # noqa: E402
from _trial_common import (  # noqa: E402
    DEGRADED, EXIT_CONFIG, EXIT_OK, EXIT_REFUSED, EXIT_UNMET, MODE_MOCK, OBSERVED,
    UNMET, make_client, response,
)
from sportmonks_client.client import ENDPOINTS  # noqa: E402
from sportmonks_client.errors import SportmonksRequestError  # noqa: E402

SCRIPT = trial_squads.SCRIPT
#: Both objectives this script owns, in emitted order.
OBJECTIVE_IDS = (4, 5)


def _collect(**overrides):
    transport = trial_squads.mock_transport(**overrides)
    return trial_squads.collect(make_client(MODE_MOCK, transport=transport), MODE_MOCK)


def _shapes(report):
    return {shape.name: shape.shape for shape in report.observed_shapes}


def _statuses(report):
    return {objective.id: objective.status for objective in report.objectives}


def _evidence(report, objective_id):
    return next(o.evidence for o in report.objectives if o.id == objective_id)


def _team(**fields):
    return {"id": 1, "name": "Example FC", "short_code": "EFC", **fields}


def _squad(**fields):
    return {"id": 11, "team_id": 1, "player_id": 101, "position_id": 27, **fields}


def _player(**fields):
    return {"id": 101, "name": "Example Player", "date_of_birth": "2000-01-01", **fields}


# --- End to end ----------------------------------------------------------------

def test_a_mock_run_exits_zero_and_writes_both_artifacts(tmp_path):
    assert trial_squads.main(["--out", str(tmp_path)]) == EXIT_OK
    assert sorted(p.name for p in (tmp_path / "reports").iterdir()) == [
        f"{SCRIPT}.json", f"{SCRIPT}.md",
    ]


def test_mock_is_the_default_mode(tmp_path):
    trial_squads.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert payload["mode"] == MODE_MOCK


def test_live_without_the_acknowledgement_refuses(tmp_path, capsys):
    assert trial_squads.main(["--live", "--out", str(tmp_path)]) == EXIT_REFUSED
    assert capsys.readouterr().out.startswith("REFUSED:")


def test_a_mock_run_is_byte_stable_across_repeats(tmp_path):
    trial_squads.main(["--out", str(tmp_path / "a")])
    trial_squads.main(["--out", str(tmp_path / "b")])
    for suffix in ("json", "md"):
        name = f"{SCRIPT}.{suffix}"
        assert (tmp_path / "a" / "reports" / name).read_bytes() == \
               (tmp_path / "b" / "reports" / name).read_bytes()


def test_the_committed_example_matches_a_fresh_mock_run(tmp_path):
    """The frozen contract commits one mock report per script so
    `TRIAL_STATUS.md`'s evidence pointer resolves to something. A committed copy
    nobody re-derives is a stale artifact wearing an evidence pointer's name."""
    from _trial_common import EXAMPLES_DIR
    trial_squads.main(["--out", str(tmp_path)])
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
    assert rows[4] == trial_squads.OBJECTIVE_4
    assert rows[5] == trial_squads.OBJECTIVE_5


# --- Standing DoD item 12: failure paths asserted whole ------------------------

def test_live_without_a_token_exits_three_and_says_so_in_the_report(tmp_path, monkeypatch):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    code = trial_squads.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert [(o["id"], o["status"], o["evidence"]) for o in payload["objectives"]] == [
        (objective_id, UNMET, "configuration incomplete; no request was issued")
        for objective_id in OBJECTIVE_IDS
    ]


def test_a_rejected_token_exits_three_and_says_something_different(tmp_path, monkeypatch):
    build = trial_squads.mock_transport
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(trial_squads, "mock_transport", lambda **_: _with_401(build()))
    code = trial_squads.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert [(o["id"], o["status"], o["evidence"]) for o in payload["objectives"]] == [
        (objective_id, UNMET, "authentication rejected by the provider")
        for objective_id in OBJECTIVE_IDS
    ]


def test_the_two_exit_three_reasons_are_not_interchangeable(tmp_path, monkeypatch):
    build = trial_squads.mock_transport
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    trial_squads.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path / "cfg")])
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(trial_squads, "mock_transport", lambda **_: _with_401(build()))
    trial_squads.main(["--out", str(tmp_path / "auth")])

    def _reason(where):
        payload = json.loads(
            (tmp_path / where / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
        return payload["objectives"][0]["evidence"]

    assert _reason("cfg") == "configuration incomplete; no request was issued"
    assert _reason("auth") == "authentication rejected by the provider"
    assert _reason("cfg") != _reason("auth")


# --- Standing DoD item 13: the taxonomy -----------------------------------------

def _with_401(transport):
    transport._by_endpoint[ENDPOINTS["teams"][0]] = response({}, status=401)
    return transport


def test_a_rejected_token_is_never_reported_as_a_missing_family(tmp_path, monkeypatch):
    """A 401 is a credential fact, not a fact about the teams endpoint. The
    broad `except SportmonksError` that would swallow it is the S3 defect
    (standing DoD item 13); here it would tell a trial-day-2 reader that the
    Starter plan carries no team data."""
    build = trial_squads.mock_transport
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(trial_squads, "mock_transport", lambda **_: _with_401(build()))
    code = trial_squads.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert payload["observed_shapes"] == []
    assert "no teams record returned" not in json.dumps(payload)


# --- The three families ---------------------------------------------------------

def test_each_family_shape_reports_the_fields_that_arrived():
    """Three families, three different payloads, three different entries —
    asserted by equality and by pairwise distinctness, so a renderer ignoring
    its input cannot pass."""
    report = _collect(
        teams={"data": [_team()]},
        squads={"data": [_squad()]},
        players={"data": [_player(display_name="EP")]},
    )
    shapes = _shapes(report)
    assert shapes["teams"] == (
        "1 record(s); record{id,name,short_code}; required[id 1/1,name 1/1,short_code 1/1]"
    )
    assert shapes["squads"] == (
        "1 record(s); record{id,team_id,player_id,position_id}; "
        "required[id 1/1,team_id 1/1,player_id 1/1,position_id 1/1]"
    )
    assert shapes["players"] == (
        "1 record(s); record{id,name,date_of_birth,display_name}; "
        "required[id 1/1,name 1/1,date_of_birth 1/1]"
    )
    assert len({shapes["teams"], shapes["squads"], shapes["players"]}) == 3


def test_partial_field_presence_is_counted_not_rounded():
    """The S4a DoD's own test: a field present on some records but not all, with
    the exact `k/n` asserted and `k ∉ {0, n}`. A count satisfiable only by `0/n`
    or `n/n` is satisfiable by a literal."""
    report = _collect(
        teams={"data": [_team(), _team(id=2, short_code=None), _team(id=3, short_code=None)]},
        players={"data": [
            _player(), _player(id=102, date_of_birth=None), _player(id=103), _player(id=104),
        ]},
        squads={"data": [_squad(), _squad(id=12, position_id=None)]},
    )
    shapes = _shapes(report)
    assert "short_code 1/3" in shapes["teams"]
    assert "date_of_birth 3/4" in shapes["players"]
    assert "position_id 1/2" in shapes["squads"]


def test_the_missing_fields_are_named_in_the_evidence():
    """Two different missing fields, two different evidence strings. Naming the
    field is the difference between "something is incomplete" and a report a
    trial reader can act on."""
    without_short_code = _collect(
        teams={"data": [_team(), _team(id=2, short_code=None)]})
    without_name = _collect(
        teams={"data": [_team(), _team(id=2, name=None)]})
    assert _evidence(without_short_code, 4).endswith(
        "— teams record(s) missing short_code [short_code 1/2]")
    assert _evidence(without_name, 4).endswith(
        "— teams record(s) missing name [name 1/2]")
    assert _evidence(without_short_code, 4) != _evidence(without_name, 4)


def test_a_null_field_value_counts_as_missing():
    """A provider shipping `date_of_birth: null` has not supplied a date of
    birth. Counting the key rather than the value would report completeness the
    §14.1 identity gate cannot use."""
    null_valued = _collect(players={"data": [_player(date_of_birth=None)]})
    absent_key = _collect(players={"data": [{"id": 101, "name": "Example Player"}]})
    assert "date_of_birth 0/1" in _shapes(null_valued)["players"]
    assert "date_of_birth 0/1" in _shapes(absent_key)["players"]
    assert _statuses(null_valued)[5] == DEGRADED


def test_an_absent_family_drops_its_shape_and_blocks_the_objective():
    report = _collect(squads={"data": []})
    assert "squads" not in _shapes(report)
    assert _statuses(report) == {4: UNMET, 5: OBSERVED}
    assert _evidence(report, 4).endswith("— no squads record returned")


def test_a_refusing_family_is_reported_as_a_failure_not_as_emptiness():
    report = _collect(
        players=SportmonksRequestError("gone", endpoint="players", status_code=404))
    assert _statuses(report) == {4: OBSERVED, 5: UNMET}
    assert "players request failed: SportmonksRequestError" in _evidence(report, 5)


# --- DoD item 2: the two objectives are separately statused ----------------------

def test_impoverished_player_records_degrade_five_and_leave_four_observed():
    """The S4a DoD's second requirement, verbatim: a complete squad list with
    impoverished player records must degrade 5 while leaving 4 observed."""
    report = _collect(players={"data": [_player(name=None, date_of_birth=None)]})
    assert _statuses(report) == {4: OBSERVED, 5: DEGRADED}


def test_incomplete_squad_fields_degrade_four_and_leave_five_observed():
    """The mirror of the DoD case. Both directions are asserted because a status
    computed from the union of all three families would pass one and fail the
    other, and only running both shows which."""
    report = _collect(squads={"data": [_squad(position_id=None)]})
    assert _statuses(report) == {4: DEGRADED, 5: OBSERVED}


def test_an_absent_family_is_unmet_where_an_incomplete_one_is_degraded():
    """`unmet` and `degraded` are different facts: a squad list nobody can fetch
    and a squad list missing one field are not the same problem."""
    incomplete = _collect(teams={"data": [_team(short_code=None)]})
    absent = _collect(teams={"data": []})
    assert (_statuses(incomplete)[4], _statuses(absent)[4]) == (DEGRADED, UNMET)


# --- Squad → player coverage ------------------------------------------------------

def test_the_coverage_entry_counts_the_squad_rows_that_resolve():
    """Two corpora, two different coverage counts, asserted by equality."""
    full = _collect(
        squads={"data": [_squad(), _squad(id=12, player_id=102)]},
        players={"data": [_player(), _player(id=102)]},
    )
    partial = _collect(
        squads={"data": [_squad(), _squad(id=12, player_id=102)]},
        players={"data": [_player()]},
    )
    assert _shapes(full)["squad_player_coverage"] == \
        "2/2 squad row(s) resolve; 2 player record(s) held"
    assert _shapes(partial)["squad_player_coverage"] == \
        "1/2 squad row(s) resolve; 1 player record(s) held"
    assert _statuses(partial)[5] == DEGRADED
    assert "1 of 2 squad row(s) reference a player with no record" in _evidence(partial, 5)


def test_the_coverage_entry_is_emitted_even_when_nothing_resolves():
    """Second branch of standing DoD item 10: the entry's existence is itself the
    observation. Squads referencing players we cannot fetch is the state
    objective 5 exists to catch, and an entry that vanished on absence could not
    report it — so the content is what moves, not the entry."""
    report = _collect(
        squads={"data": [_squad(player_id=999)]},
        players={"data": [_player()]},
    )
    assert _shapes(report)["squad_player_coverage"] == \
        "0/1 squad row(s) resolve; 1 player record(s) held"
    assert _statuses(report)[5] == DEGRADED


def test_duplicate_unresolvable_rows_are_counted_as_two_gaps():
    """Rows, not distinct players: two squad rows pointing at the same
    unfetchable player are two gaps in the squad, not one."""
    report = _collect(
        squads={"data": [_squad(player_id=999), _squad(id=12, player_id=999)]},
        players={"data": [_player()]},
    )
    assert _shapes(report)["squad_player_coverage"] == \
        "0/2 squad row(s) resolve; 1 player record(s) held"


# --- Exit codes -------------------------------------------------------------------

def test_a_degraded_objective_exits_one(tmp_path, monkeypatch):
    build = trial_squads.mock_transport
    monkeypatch.setattr(
        trial_squads, "mock_transport",
        lambda **_: build(players={"data": [_player(date_of_birth=None)]}),
    )
    assert trial_squads.main(["--out", str(tmp_path)]) == EXIT_UNMET


def test_an_empty_envelope_from_edge_cases_exits_one(tmp_path, monkeypatch):
    from _trial_common import load_fixture
    empty = load_fixture("edge_cases.json")["empty"]
    build = trial_squads.mock_transport
    monkeypatch.setattr(trial_squads, "mock_transport", lambda **_: build(squads=empty))
    assert trial_squads.main(["--out", str(tmp_path)]) == EXIT_UNMET


# --- The declaration -------------------------------------------------------------

def test_every_entry_is_declared_and_names_a_test_that_exists():
    report = _collect()
    assert set(trial_squads.DECLARED_SHAPES) == set(_shapes(report))
    for names in trial_squads.DECLARED_SHAPES.values():
        for name in names:
            assert name in globals(), name

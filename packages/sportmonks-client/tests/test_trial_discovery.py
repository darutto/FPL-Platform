"""FI-8 S3: entity discovery and fixtures — competitions, seasons, fixtures.

The discipline here is the one S2 was rejected three times for missing: every
reported value is fed at least two different payloads and asserted to differ,
by `==` rather than containment. A test that feeds one payload and checks a
substring cannot tell "reports what arrived" from "reports a constant".
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
    COMPETITION_NAME, EXAMPLES_DIR, EXIT_CONFIG, EXIT_OK, EXIT_REFUSED,
    EXIT_UNMET, MODE_MOCK, OBSERVED, PACKAGE_ROOT, UNMET,
    EndpointReplayTransport, make_client, match_by_name, response,
)
from sportmonks_client.client import ENDPOINTS  # noqa: E402
from sportmonks_client.errors import SportmonksRequestError  # noqa: E402

SCRIPTS = (trial_entities, trial_fixtures)


def _collect(module, transport):
    """Run a script's `collect` against an injected transport, no artifacts."""
    return module.collect(make_client(MODE_MOCK, transport=transport), MODE_MOCK)


def _shapes(report):
    return {shape.name: shape.shape for shape in report.observed_shapes}


def _statuses(report):
    return {objective.id: objective.status for objective in report.objectives}


def _evidence(report, objective_id):
    return next(o.evidence for o in report.objectives if o.id == objective_id)


def _league(provider_id, name):
    return {"id": provider_id, "name": name}


# --- Both scripts, end to end -------------------------------------------------

@pytest.mark.parametrize("module", SCRIPTS, ids=lambda m: m.SCRIPT)
def test_a_mock_run_exits_zero_and_writes_both_artifacts(module, tmp_path):
    assert module.main(["--out", str(tmp_path)]) == EXIT_OK
    reports = tmp_path / "reports"
    assert sorted(p.name for p in reports.iterdir()) == [
        f"{module.SCRIPT}.json", f"{module.SCRIPT}.md",
    ]


@pytest.mark.parametrize("module", SCRIPTS, ids=lambda m: m.SCRIPT)
def test_mock_is_the_default_mode(module, tmp_path):
    module.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / f"{module.SCRIPT}.json").read_text(encoding="utf-8"))
    assert payload["mode"] == MODE_MOCK


@pytest.mark.parametrize("module", SCRIPTS, ids=lambda m: m.SCRIPT)
def test_live_without_the_acknowledgement_refuses(module, tmp_path, capsys):
    assert module.main(["--live", "--out", str(tmp_path)]) == EXIT_REFUSED
    assert capsys.readouterr().out.startswith("REFUSED:")


@pytest.mark.parametrize("module", SCRIPTS, ids=lambda m: m.SCRIPT)
def test_live_without_a_token_exits_three_and_says_so_in_the_report(module, tmp_path, monkeypatch):
    """The exit code is not the observation; the report is.

    The first version of this test asserted only the exit code, and a
    falsifiability sweep found the consequence: the status and evidence in
    `_report_with` could both be replaced with plausible literals and every
    test stayed green. Six of S3's survivors were this one omission, three
    times over. The objective tuple is asserted whole, by `==`.
    """
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    code = module.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    payload = json.loads(
        (tmp_path / "reports" / f"{module.SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert [(o["id"], o["status"], o["evidence"]) for o in payload["objectives"]] == [
        (objective_id, UNMET, "configuration incomplete; no request was issued")
        for objective_id in _OBJECTIVE_IDS[module.SCRIPT]
    ]


#: The objectives each script owns, in emitted order. Written down so the
#: failure-path assertions below are exact rather than "whatever came out".
_OBJECTIVE_IDS = {"trial_entities": (1,), "trial_fixtures": (2, 3)}


@pytest.mark.parametrize("module", SCRIPTS, ids=lambda m: m.SCRIPT)
def test_a_rejected_token_exits_three_and_says_something_different(module, tmp_path, monkeypatch):
    """The two exit-3 reasons must not be interchangeable: "we never configured
    a token" and "the provider refused ours" are different trial-day facts and
    lead to different next actions."""
    build = module.mock_transport
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(module, "mock_transport", lambda **_: _with_401(build()))
    code = module.main(["--out", str(tmp_path)])
    payload = json.loads(
        (tmp_path / "reports" / f"{module.SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert [(o["id"], o["status"], o["evidence"]) for o in payload["objectives"]] == [
        (objective_id, UNMET, "authentication rejected by the provider")
        for objective_id in _OBJECTIVE_IDS[module.SCRIPT]
    ]


@pytest.mark.parametrize("module", SCRIPTS, ids=lambda m: m.SCRIPT)
def test_the_two_exit_three_reasons_are_not_interchangeable(module, tmp_path, monkeypatch):
    build = module.mock_transport
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    module.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path / "cfg")])
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(module, "mock_transport", lambda **_: _with_401(build()))
    module.main(["--out", str(tmp_path / "auth")])

    def _reason(where):
        payload = json.loads(
            (tmp_path / where / "reports" / f"{module.SCRIPT}.json").read_text(encoding="utf-8"))
        return payload["objectives"][0]["evidence"]

    assert _reason("cfg") == "configuration incomplete; no request was issued"
    assert _reason("auth") == "authentication rejected by the provider"
    assert _reason("cfg") != _reason("auth")


@pytest.mark.parametrize("module", SCRIPTS, ids=lambda m: m.SCRIPT)
def test_a_rejected_token_is_never_reported_as_a_missing_endpoint(module, tmp_path, monkeypatch):
    """The taxonomy regression, pinned.

    `SportmonksAuthenticationError` subclasses `SportmonksError`, so a broad
    `except SportmonksError` around a family call swallows it. Measured before
    the fix: a 401 on `leagues` made `trial_entities` exit **1** with the
    objective `unmet` and the family reported `unavailable`. With every family
    answering 401 the report would have read "15 families unavailable" — which
    on trial day 1 reads as *the Starter plan does not carry these endpoints*,
    the single question this script exists to answer. A rejected token must
    never be able to masquerade as a missing endpoint.
    """
    build = module.mock_transport
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TRIAL-TOKEN")
    monkeypatch.setattr(module, "mock_transport", lambda **_: _with_401(build()))
    code = module.main(["--out", str(tmp_path)])
    payload = json.loads(
        (tmp_path / "reports" / f"{module.SCRIPT}.json").read_text(encoding="utf-8"))
    assert code == EXIT_CONFIG
    assert payload["observed_shapes"] == []
    assert "unavailable" not in json.dumps(payload)


def _with_401(transport):
    """Serve a real 401 for `leagues`, through the client's own status handling
    rather than by raising the exception directly — the path FI-9 will take."""
    transport._by_endpoint[ENDPOINTS["leagues"][0]] = response({}, status=401)
    return transport


@pytest.mark.parametrize("module", SCRIPTS, ids=lambda m: m.SCRIPT)
def test_a_mock_run_is_byte_stable_across_repeats(module, tmp_path):
    module.main(["--out", str(tmp_path / "a")])
    module.main(["--out", str(tmp_path / "b")])
    for suffix in ("json", "md"):
        name = f"{module.SCRIPT}.{suffix}"
        assert (tmp_path / "a" / "reports" / name).read_bytes() == \
               (tmp_path / "b" / "reports" / name).read_bytes()


@pytest.mark.parametrize("module", SCRIPTS, ids=lambda m: m.SCRIPT)
def test_the_committed_example_matches_a_fresh_mock_run(module, tmp_path):
    """The frozen contract commits one mock report per script so
    `TRIAL_STATUS.md`'s evidence pointer resolves to something. A committed copy
    nobody re-derives is a stale artifact wearing an evidence pointer's name.

    These two examples were missing entirely until this change, and the copies
    on the unmerged `agent/fi8-s3-discovery` branch no longer match what `main`
    emits — which is why they were regenerated rather than copied across.
    """
    module.main(["--out", str(tmp_path)])
    for suffix in ("json", "md"):
        name = f"{module.SCRIPT}.{suffix}"
        assert (EXAMPLES_DIR / name).read_bytes() == \
               (tmp_path / "reports" / name).read_bytes()


def test_the_objective_titles_match_the_trial_dashboard():
    """The dashboard names an owning script per objective; if the script's title
    drifts from the row, a reader reconciling them has two different objectives
    and no way to tell which is current."""
    dashboard = (PACKAGE_ROOT / "TRIAL_STATUS.md").read_text(encoding="utf-8")
    rows = {
        int(cells[1]): cells[2].strip()
        for line in dashboard.splitlines()
        if (cells := line.split("|")) and len(cells) > 3 and cells[1].strip().isdigit()
    }
    assert rows[1] == trial_entities.OBJECTIVE_1
    assert rows[2] == trial_fixtures.OBJECTIVE_2
    assert rows[3] == trial_fixtures.OBJECTIVE_3


# --- The endpoint-keyed transport ---------------------------------------------

def test_the_longest_matching_endpoint_wins():
    """`.../statistics/fixtures/teams` also ends with `/teams`. A shortest-match
    would serve the teams payload under the statistics family's name — a
    misobservation that reads as data."""
    transport = EndpointReplayTransport({
        "teams": response({"data": [{"id": 1}]}),
        "statistics/fixtures/teams": response({"data": [{"id": 91}, {"id": 92}]}),
    })
    plain = transport.request("GET", "https://x/v3/football/teams", params={}, timeout=1)
    nested = transport.request(
        "GET", "https://x/v3/football/statistics/fixtures/teams", params={}, timeout=1)
    assert [record["id"] for record in plain.body["data"]] == [1]
    assert [record["id"] for record in nested.body["data"]] == [91, 92]


def test_an_unmapped_endpoint_raises_rather_than_answering_empty():
    """A mock that answered "nothing here" for a family nobody wrote a fixture
    for would report `empty` — a claim about the provider — when the truth is a
    gap in our own corpus."""
    transport = EndpointReplayTransport({"teams": response({"data": []})})
    with pytest.raises(KeyError):
        transport.request("GET", "https://x/v3/football/leagues", params={}, timeout=1)


def test_a_callable_answers_on_the_parameters_not_the_call_order():
    transport = EndpointReplayTransport({
        "fixtures": lambda params: response({"data": [{"id": 1 if "team_id" in params else 2}]}),
    })
    by_team = transport.request("GET", "https://x/fixtures", params={"team_id": 7}, timeout=1)
    by_league = transport.request("GET", "https://x/fixtures", params={"league_id": 8}, timeout=1)
    assert (by_team.body["data"][0]["id"], by_league.body["data"][0]["id"]) == (1, 2)


def test_a_list_value_is_served_in_order():
    transport = EndpointReplayTransport({
        "leagues": [response({"data": [{"id": 1}]}), response({"data": [{"id": 2}]})],
    })
    first = transport.request("GET", "https://x/leagues", params={}, timeout=1)
    second = transport.request("GET", "https://x/leagues", params={}, timeout=1)
    assert (first.body["data"][0]["id"], second.body["data"][0]["id"]) == (1, 2)


def test_a_mapped_exception_is_raised_so_an_unavailable_family_is_observable():
    transport = EndpointReplayTransport({
        "injuries": SportmonksRequestError("gone", endpoint="injuries", status_code=404),
    })
    with pytest.raises(SportmonksRequestError):
        transport.request("GET", "https://x/injuries", params={}, timeout=1)


# --- match_by_name ------------------------------------------------------------

class _Record:
    def __init__(self, provider_id, **raw):
        self.provider_id = provider_id
        self.raw_fields = raw


def test_matching_by_name_is_case_insensitive_and_returns_every_match():
    records = (
        _Record(1, name="Premier League"), _Record(2, name="premier league 2"),
        _Record(3, name="Championship"), _Record(4),
    )
    assert [r.provider_id for r in match_by_name(records, COMPETITION_NAME)] == [1, 2]
    assert [r.provider_id for r in match_by_name(records, "Championship")] == [3]


# --- trial_entities: the family sweep -----------------------------------------

def _entities_transport(**overrides):
    return trial_entities.mock_transport(families=overrides)


def test_the_sweep_covers_every_family_in_endpoints():
    report = _collect(trial_entities, _entities_transport())
    assert set(_shapes(report)) == {f"family:{family}" for family in ENDPOINTS}


def test_each_family_entry_reports_the_count_and_ids_that_family_returned():
    """Two families, two different payloads, two different rendered entries —
    asserted by equality. With one payload, a renderer that ignored its input
    entirely would pass."""
    report = _collect(trial_entities, _entities_transport(
        leagues={"data": [_league(8, "Premier League"), _league(9, "Championship")]},
        teams={"data": [{"id": 1, "name": "A"}]},
    ))
    shapes = _shapes(report)
    assert shapes["family:leagues"] == "reachable; 2 record(s); provider_ids={8,9}"
    assert shapes["family:teams"] == "reachable; 1 record(s); provider_ids={1}"
    assert shapes["family:leagues"] != shapes["family:teams"]


def test_the_three_family_states_are_not_interchangeable():
    """`empty` and `unavailable` are different facts about the trial: one says
    the provider answered with nothing, the other that our plan does not carry
    the endpoint. Collapsing them hides a plan gap behind "no data yet"."""
    report = _collect(trial_entities, _entities_transport(
        teams={"data": []},
        injuries=SportmonksRequestError("gone", endpoint="injuries", status_code=404),
    ))
    shapes = _shapes(report)
    rendered = (shapes["family:leagues"], shapes["family:teams"], shapes["family:injuries"])
    assert rendered == (
        "reachable; 1 record(s); provider_ids={8}",
        "empty; 0 record(s); provider_ids={}",
        "unavailable; 0 record(s); provider_ids={}; SportmonksRequestError",
    )
    assert len(set(rendered)) == 3


def test_an_unavailable_family_does_not_abort_the_sweep():
    report = _collect(trial_entities, _entities_transport(
        injuries=SportmonksRequestError("gone", endpoint="injuries", status_code=404),
    ))
    assert len(_shapes(report)) == len(ENDPOINTS)
    assert _statuses(report) == {1: OBSERVED}


def test_an_unavailable_family_is_named_in_a_warning():
    report = _collect(trial_entities, _entities_transport(
        injuries=SportmonksRequestError("gone", endpoint="injuries", status_code=404),
        coaches=SportmonksRequestError("gone", endpoint="coaches", status_code=404),
    ))
    assert "families that did not answer: coaches, injuries" in report.warnings


def test_the_evidence_tracks_the_payload_rather_than_the_search_term():
    """Two corpora, two different resolved ids, asserted by equality. The
    competition *name* is an input; the id is the observation."""
    one = _collect(trial_entities, _entities_transport(
        leagues={"data": [_league(8, "Premier League")]},
        seasons={"data": [{"id": 23614, "league_id": 8}]},
    ))
    two = _collect(trial_entities, _entities_transport(
        leagues={"data": [_league(271, "Premier League")]},
        seasons={"data": [{"id": 99, "league_id": 271}]},
    ))
    assert _evidence(one, 1) == (
        "Premier League resolved to league_ids=(8,); season_ids=(23614,); "
        "swept 15 families: 15 reachable, 0 empty, 0 unavailable"
    )
    assert _evidence(two, 1) == (
        "Premier League resolved to league_ids=(271,); season_ids=(99,); "
        "swept 15 families: 15 reachable, 0 empty, 0 unavailable"
    )


def test_no_matching_league_is_unmet_not_observed():
    report = _collect(trial_entities, _entities_transport(
        leagues={"data": [_league(9, "Championship")]},
    ))
    assert _statuses(report) == {1: UNMET}
    assert _evidence(report, 1).endswith(
        "— no league reported a name containing 'Premier League'"
    )


def test_two_leagues_matching_the_term_are_reported_rather_than_resolved():
    """Which of two same-named competitions is the intended one is a question
    for the provider (§17). Taking the first would answer it by assumption."""
    report = _collect(trial_entities, _entities_transport(
        leagues={"data": [_league(8, "Premier League"), _league(24, "Premier League 2")]},
    ))
    assert _statuses(report) == {1: UNMET}
    assert _evidence(report, 1).endswith(
        "— 2 leagues matched 'Premier League': (8, 24)"
    )


def test_a_league_with_no_season_is_unmet():
    report = _collect(trial_entities, _entities_transport(
        seasons={"data": [{"id": 1, "league_id": 999}]},
    ))
    assert _statuses(report) == {1: UNMET}
    assert _evidence(report, 1).endswith("— no season carried a league_id in (8,)")


def test_an_empty_leagues_envelope_from_edge_cases_exits_one(tmp_path, monkeypatch):
    """The frozen unmet path, proved with the checked-in empty envelope rather
    than a hand-written one — the fixture FI-9 will actually meet."""
    from _trial_common import load_fixture
    empty = load_fixture("edge_cases.json")["empty"]
    build = trial_entities.mock_transport  # bound before the patch replaces it
    monkeypatch.setattr(
        trial_entities, "mock_transport", lambda **_: build(families={"leagues": empty}),
    )
    assert trial_entities.main(["--out", str(tmp_path)]) == EXIT_UNMET


def test_every_entity_entry_is_declared_and_names_a_test_that_exists():
    report = _collect(trial_entities, _entities_transport())
    assert set(trial_entities.DECLARED_SHAPES) == {"family:*"}
    assert {name.split(":")[1] for name in _shapes(report)} == set(ENDPOINTS)
    for names in trial_entities.DECLARED_SHAPES.values():
        for name in names:
            assert name in globals(), name


# --- trial_fixtures: two objectives, two requests ------------------------------

def test_the_two_objectives_are_statused_separately():
    """DoD: objectives 2 and 3 are distinct observations. An input where one
    holds and the other does not must produce two different statuses — a script
    reporting them from one fetch could not."""
    report = _collect(trial_fixtures, trial_fixtures.mock_transport(
        cross_fixtures={"data": [
            {"id": 1001, "league_id": 8, "season_id": 23614, "starting_at": "x"},
        ]},
    ))
    assert _statuses(report) == {2: OBSERVED, 3: UNMET}
    assert _evidence(report, 3).endswith(
        "— every fixture returned sat inside the requested competition (8,)"
    )


def test_the_cross_competition_request_carries_no_competition_filter():
    """Objective 3 asks what a club plays *outside* the competition. Sending
    `league_id` would make the answer unobtainable while still returning rows."""
    transport = trial_fixtures.mock_transport()
    _collect(trial_fixtures, transport)
    fixture_calls = [
        params for _method, url, params, _timeout in transport.calls
        if url.endswith("/fixtures")
    ]
    by_team = [params for params in fixture_calls if "team_id" in params]
    assert by_team
    assert all("league_id" not in params for params in by_team)


def test_the_season_request_carries_both_filters():
    transport = trial_fixtures.mock_transport()
    _collect(trial_fixtures, transport)
    season_calls = [
        params for _method, url, params, _timeout in transport.calls
        if url.endswith("/fixtures") and "team_id" not in params
    ]
    assert [sorted(set(params) - {"page"}) for params in season_calls] == \
           [["league_id", "season_id"]]


def test_the_season_shape_records_the_envelope_that_arrived():
    """Two payloads with different record fields, two different entries."""
    one = _collect(trial_fixtures, trial_fixtures.mock_transport(
        season_fixtures={"data": [{"id": 1, "league_id": 8, "season_id": 23614}]},
    ))
    two = _collect(trial_fixtures, trial_fixtures.mock_transport(
        season_fixtures={"data": [
            {"id": 1, "league_id": 8, "season_id": 23614, "state": "NS"},
        ]},
    ))
    assert _shapes(one)["season_fixtures"] == "data; record{id,league_id,season_id}"
    assert _shapes(two)["season_fixtures"] == "data; record{id,league_id,season_id,state}"


def test_a_record_field_that_only_some_records_carry_is_reported_as_such():
    """Heterogeneous records within one payload is the kind of surprise FI-9
    needs told, not averaged away."""
    report = _collect(trial_fixtures, trial_fixtures.mock_transport(
        season_fixtures={"data": [
            {"id": 1, "league_id": 8, "season_id": 23614},
            {"id": 2, "league_id": 8, "season_id": 23614, "aggregate_id": 5},
        ]},
    ))
    assert _shapes(report)["season_fixtures"] == \
        "data; record{id,league_id,season_id+aggregate_id}"


def test_the_cross_competition_shape_records_the_envelope_that_arrived():
    one = _collect(trial_fixtures, trial_fixtures.mock_transport(
        cross_fixtures={"data": [{"id": 1, "league_id": 99}]},
    ))
    two = _collect(trial_fixtures, trial_fixtures.mock_transport(
        cross_fixtures={"data": [{"id": 1, "league_id": 99, "round_id": 3}]},
    ))
    assert _shapes(one)["cross_competition_fixtures"] == "data; record{id,league_id}"
    assert _shapes(two)["cross_competition_fixtures"] == "data; record{id,league_id,round_id}"


def test_a_run_that_never_reached_the_fixtures_endpoint_emits_no_shape():
    report = _collect(trial_fixtures, trial_fixtures.mock_transport(
        leagues={"data": [_league(9, "Championship")]},
    ))
    assert _shapes(report) == {}
    assert _statuses(report) == {2: UNMET, 3: UNMET}


def test_no_team_to_sweep_drops_the_cross_competition_shape():
    report = _collect(trial_fixtures, trial_fixtures.mock_transport(teams={"data": []}))
    assert set(_shapes(report)) == {"season_fixtures"}
    assert _statuses(report) == {2: OBSERVED, 3: UNMET}
    assert _evidence(report, 3).endswith("— no team was resolved to sweep")


def test_an_empty_fixtures_envelope_from_edge_cases_exits_one(tmp_path, monkeypatch):
    from _trial_common import load_fixture
    empty = load_fixture("edge_cases.json")["empty"]
    build = trial_fixtures.mock_transport  # bound before the patch replaces it
    monkeypatch.setattr(
        trial_fixtures, "mock_transport", lambda **_: build(season_fixtures=empty),
    )
    assert trial_fixtures.main(["--out", str(tmp_path)]) == EXIT_UNMET


def test_the_fixtures_evidence_tracks_the_payload():
    one = _collect(trial_fixtures, trial_fixtures.mock_transport())
    two = _collect(trial_fixtures, trial_fixtures.mock_transport(
        cross_fixtures={"data": [
            {"id": 1, "league_id": 8, "season_id": 23614},
            {"id": 2, "league_id": 77, "season_id": 23614},
            {"id": 3, "league_id": 78, "season_id": 23614},
        ]},
    ))
    assert _evidence(one, 3) == (
        "swept 1 team(s) by team_id with no competition filter; 2 fixture(s); "
        "competitions inside=(8,), outside=(9,)"
    )
    assert _evidence(two, 3) == (
        "swept 1 team(s) by team_id with no competition filter; 3 fixture(s); "
        "competitions inside=(8,), outside=(77, 78)"
    )


def test_a_fixture_from_another_season_degrades_objective_two():
    report = _collect(trial_fixtures, trial_fixtures.mock_transport(
        season_fixtures={"data": [
            {"id": 1, "league_id": 8, "season_id": 23614},
            {"id": 2, "league_id": 8, "season_id": 99999},
        ]},
    ))
    assert _statuses(report)[2] == UNMET
    assert _evidence(report, 2).endswith("— 1 fixture(s) carried a different season_id: [2]")


def test_the_synthesized_rehearsal_is_declared_in_the_report(tmp_path):
    """Mock mode invents the cross-competition fixture the corpus lacks. A
    reader must not be able to mistake that rehearsal for evidence, so the
    admission travels in the artifact rather than in a docstring."""
    trial_fixtures.main(["--out", str(tmp_path)])
    payload = json.loads(
        (tmp_path / "reports" / "trial_fixtures.json").read_text(encoding="utf-8"))
    assert trial_fixtures.SYNTHETIC_WARNING in payload["warnings"]


def test_the_synthesized_competition_cannot_collide_with_a_real_one():
    base = {"data": [{"id": 1, "league_id": 8}, {"id": 2, "league_id": 12}]}
    synthesized = trial_fixtures._synthesize_cross_competition(base)
    assert [record["league_id"] for record in synthesized["data"]] == [8, 13]


def test_every_fixtures_entry_is_declared_and_names_a_test_that_exists():
    report = _collect(trial_fixtures, trial_fixtures.mock_transport())
    assert set(trial_fixtures.DECLARED_SHAPES) == set(_shapes(report))
    for names in trial_fixtures.DECLARED_SHAPES.values():
        for name in names:
            assert name in globals(), name

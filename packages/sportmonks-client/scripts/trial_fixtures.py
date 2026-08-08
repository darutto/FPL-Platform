"""FI-8 trial acceptance script: Premier League and cross-competition fixtures.

Covers brief §11.3 objective 2 (Premier League fixtures) and objective 3
(cross-competition fixtures for Premier League clubs) as two separately
observable facts, per S3's DoD 2: a script that only proved "some fixtures
came back" could not tell FI-9 whether cross-competition coverage exists at
all, so the two queries and the two objectives are kept apart end to end --
separate mock responses, separate classification functions, separate
`Objective` entries.

Objective 2's status is derived from whether the fixtures a "Premier League
season" query actually returned all carry the requested league and season id.
Objective 3's status is derived from whether the fixtures a "cross-competition"
query actually returned (a) include the requested club among participants and
(b) span at least one league other than the Premier League -- the second
condition is what makes the fact "cross-competition" rather than merely
"fixtures for a club"; without checking it, a mock that only ever returns
Premier League fixtures would still read as success.

Nothing here is a literal. `league_id`, `season_id`, and `participants` are
read from each fixture's own `raw_fields`, as parsed by the shared client from
the response the transport actually served this run.

`--mock` is the default and is the only mode that runs before FI-9.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    DEGRADED, EXIT_CONFIG, EXIT_REFUSED, MODE_MOCK, OBSERVED, UNMET, Objective,
    ObservedShape, ReplayTransport, TrialRefusal, TrialReport, build_parser,
    make_client, resolve_mode, response, write_report,
)
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
    SportmonksSchemaError,
)

SCRIPT = "trial_fixtures"
OBJECTIVE_2 = "Premier League fixtures"
OBJECTIVE_3 = "cross-competition fixtures for Premier League clubs"

#: Consistent with `trial_entities.py`'s `leagues`/`seasons` mock records, so a
#: reader cross-referencing both reports sees the same identifiers.
PL_LEAGUE_ID = 8
PL_SEASON_ID = 23614
PL_CLUB_ID = 1

#: A Premier League season's worth of fixtures -- objective 2's source data.
#: Documentation-derived, `unverified_against_live` until FI-9.
DEFAULT_SEASON_FIXTURES = {
    "data": [
        {
            "id": 2001, "league_id": PL_LEAGUE_ID, "season_id": PL_SEASON_ID,
            "starting_at": "2025-08-16 14:00:00",
            "participants": [{"id": PL_CLUB_ID, "name": "Team A"}, {"id": 2, "name": "Team B"}],
        },
        {
            "id": 2002, "league_id": PL_LEAGUE_ID, "season_id": PL_SEASON_ID,
            "starting_at": "2025-08-16 16:30:00",
            "participants": [{"id": 3, "name": "Team C"}, {"id": 4, "name": "Team D"}],
        },
    ],
}

#: The same club's fixtures in *other* competitions -- objective 3's source
#: data. League ids 24 (a domestic cup) and 2 (a continental competition) are
#: deliberately not `PL_LEAGUE_ID`, which is the fact objective 3 checks for.
DEFAULT_CROSS_COMPETITION_FIXTURES = {
    "data": [
        {
            "id": 3001, "league_id": 24, "season_id": 30001,
            "starting_at": "2025-09-24 19:45:00",
            "participants": [{"id": PL_CLUB_ID, "name": "Team A"}, {"id": 5, "name": "Team E"}],
        },
        {
            "id": 3002, "league_id": 2, "season_id": 30002,
            "starting_at": "2025-10-01 20:00:00",
            "participants": [{"id": PL_CLUB_ID, "name": "Team A"}, {"id": 6, "name": "Team F"}],
        },
    ],
}


def mock_transport(
    *,
    season_fixtures: dict | None = None,
    cross_competition_fixtures: dict | None = None,
) -> ReplayTransport:
    """Serve the season-fixtures response, then the cross-competition response.

    Overriding either keyword lets tests swap in an `edge_cases.json` fixture
    for exactly one of the two facts, proving each objective's unmet/degraded
    path is real and that the other objective is unaffected.
    """
    season = season_fixtures if season_fixtures is not None else DEFAULT_SEASON_FIXTURES
    cross = cross_competition_fixtures if cross_competition_fixtures is not None else DEFAULT_CROSS_COMPETITION_FIXTURES
    return ReplayTransport([response(season), response(cross)])


def _fetch(client, params: dict) -> tuple[tuple, str | None]:
    """One page of `fixtures`, catching a parser rejection rather than crashing.

    Mirrors `trial_auth.collect`'s handling of `SportmonksSchemaError`: the
    frozen contract requires a shape difference to degrade the objective, not
    abort the script.
    """
    try:
        records = client.fetch_page("fixtures", params=params)
        return records, None
    except SportmonksSchemaError as exc:
        return (), str(exc) or type(exc).__name__


def classify_season_fixtures(records: tuple, rejection: str | None) -> tuple[str, str]:
    """Objective 2: every returned fixture must carry the requested league and
    season id. Returns `(status, evidence)`."""
    if rejection is not None:
        return DEGRADED, f"payload rejected by the parser: {rejection}"
    if not records:
        return UNMET, "no fixtures returned for the Premier League season query"
    mismatched = [
        r.provider_id for r in records
        if r.raw_fields.get("league_id") != PL_LEAGUE_ID or r.raw_fields.get("season_id") != PL_SEASON_ID
    ]
    if mismatched:
        return DEGRADED, (
            f"{len(records)} fixture(s) returned; {len(mismatched)} did not carry "
            f"league_id={PL_LEAGUE_ID}/season_id={PL_SEASON_ID}: {mismatched}"
        )
    return OBSERVED, f"{len(records)} fixture(s), all league_id={PL_LEAGUE_ID} season_id={PL_SEASON_ID}"


def classify_cross_competition_fixtures(records: tuple, rejection: str | None) -> tuple[str, str]:
    """Objective 3: fixtures must (a) include the requested club and (b) span a
    league other than the Premier League -- otherwise the "cross-competition"
    fact has not actually been observed, even though fixtures came back.
    Returns `(status, evidence)`."""
    if rejection is not None:
        return DEGRADED, f"payload rejected by the parser: {rejection}"
    if not records:
        return UNMET, "no fixtures returned for the cross-competition query"
    leagues_seen = sorted({r.raw_fields.get("league_id") for r in records})
    missing_club = [
        r.provider_id for r in records
        if PL_CLUB_ID not in {
            p.get("id") for p in r.raw_fields.get("participants", []) if isinstance(p, dict)
        }
    ]
    other_leagues = [league for league in leagues_seen if league != PL_LEAGUE_ID]
    if missing_club:
        return DEGRADED, (
            f"{len(records)} fixture(s) returned across leagues {leagues_seen}; "
            f"{len(missing_club)} did not include club id {PL_CLUB_ID}: {missing_club}"
        )
    if not other_leagues:
        return DEGRADED, (
            f"{len(records)} fixture(s) returned for club id {PL_CLUB_ID}, but all were "
            f"league_id={PL_LEAGUE_ID} -- no competition outside the Premier League was observed"
        )
    return OBSERVED, (
        f"{len(records)} fixture(s) for club id {PL_CLUB_ID} across leagues {leagues_seen}"
    )


def collect(client, mode: str) -> TrialReport:
    """Build the report from what each of the two queries actually returned."""
    report = TrialReport(script=SCRIPT, mode=mode)

    season_records, season_rejection = _fetch(
        client, {"league_id": PL_LEAGUE_ID, "season_id": PL_SEASON_ID},
    )
    status, evidence = classify_season_fixtures(season_records, season_rejection)
    report.objectives.append(Objective(2, OBJECTIVE_2, status, evidence))
    if season_records:
        # Field names actually present across the returned records, not a
        # documented list -- a record missing a field shrinks this entry.
        keys = sorted({key for record in season_records for key in record.raw_fields})
        report.observed_shapes.append(ObservedShape("season_fixtures", f"fixture{{{','.join(keys)}}}"))

    cross_records, cross_rejection = _fetch(client, {"team_ids": [PL_CLUB_ID]})
    status, evidence = classify_cross_competition_fixtures(cross_records, cross_rejection)
    report.objectives.append(Objective(3, OBJECTIVE_3, status, evidence))
    if cross_records:
        leagues_seen = sorted({r.raw_fields.get("league_id") for r in cross_records})
        report.observed_shapes.append(ObservedShape(
            "cross_competition_leagues", ",".join(str(l) for l in leagues_seen),
        ))

    report.warnings.append(
        "mock mode: fixture payloads are documentation-derived and carry "
        '"status": "unverified_against_live" until FI-9'
        if mode == MODE_MOCK else
        "live mode: fixture payloads are as received from the provider"
    )
    return report


def _report_with(mode: str, status: str, reason: str) -> TrialReport:
    """A report is still written on the failure paths, matching `trial_auth`."""
    report = TrialReport(script=SCRIPT, mode=mode)
    report.objectives.append(Objective(2, OBJECTIVE_2, status, reason))
    report.objectives.append(Objective(3, OBJECTIVE_3, status, reason))
    report.warnings.append(reason)
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser(SCRIPT).parse_args(argv)
    try:
        mode = resolve_mode(args)
    except TrialRefusal as exc:
        print(f"REFUSED: {exc}")
        return EXIT_REFUSED

    transport = mock_transport() if mode == MODE_MOCK else None
    failure: str | None = None
    config_failure = False
    try:
        client = make_client(mode, transport=transport, out_dir=args.out)
        report = collect(client, mode)
    except SportmonksConfigurationError as exc:
        failure = f"CONFIG: {type(exc).__name__}"
        config_failure = True
        report = _report_with(mode, UNMET, "configuration incomplete; no request was issued")
    except SportmonksAuthenticationError as exc:
        failure = f"AUTH: {type(exc).__name__}"
        config_failure = True
        report = _report_with(mode, UNMET, "authentication rejected by the provider")
    except SportmonksError as exc:
        failure = f"PROVIDER: {type(exc).__name__}"
        report = _report_with(mode, DEGRADED, f"provider error: {type(exc).__name__}")

    json_path, md_path = write_report(report, args.out)
    if failure is not None:
        print(failure)
    print(f"{SCRIPT}: mode={report.mode} report={json_path} markdown={md_path}")
    return EXIT_CONFIG if config_failure else report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())

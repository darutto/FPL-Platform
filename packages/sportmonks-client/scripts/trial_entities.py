"""FI-8 trial acceptance script: entity discovery across every endpoint family.

Covers brief §11.3 objective 1 (competition and season identifiers).

`sportmonks_client.client.ENDPOINTS` lists 15 families. This script attempts
one page of each and classifies what actually came back -- `reachable` (a
non-empty `data` list), `empty` (a valid envelope with no records), or
`unavailable` (the request raised, most commonly a malformed envelope the
parser rejected). Every family is attempted and every family gets a report
entry, because "unavailable" is itself an observation the trial needs, not an
absence of one -- dropping the entry for a family that failed would hide
exactly the information DoD item 1 asks this script to produce.

Objective 1 itself is scoped narrower than the full sweep: it is literally
about competition (`leagues`) and season (`seasons`) identifiers, so its
status and evidence are derived only from those two families' classifications.
The other 13 are swept and reported as their own shape entries -- connectivity
context FI-9 needs on day one -- but do not themselves move objective 1's
status, per S3's non-goals ("no squad, lineup, injury, stat, or identity
work").

Nothing here is a literal. Every `status=`, `records=`, and `provider_ids=`
value is computed from the records `client.fetch_page` actually returned (or
the exception it actually raised) for that family, this run. Standing DoD item
10's deletion test swaps a single family's mock payload for
`edge_cases.json`'s `"empty"` (or a malformed envelope) and asserts only that
family's entry changes while the other 14 stay byte-identical.

`--mock` is the default and is the only mode that runs before FI-9.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    DEGRADED, EXIT_CONFIG, EXIT_REFUSED, MODE_MOCK, OBSERVED, Objective,
    ObservedShape, ReplayTransport, TrialRefusal, TrialReport, build_parser,
    make_client, resolve_mode, response, write_report,
)
from sportmonks_client.client import ENDPOINTS  # noqa: E402
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
)

SCRIPT = "trial_entities"
OBJECTIVE_1 = "competition and season identifiers"

STATUS_REACHABLE = "reachable"
STATUS_EMPTY = "empty"
STATUS_UNAVAILABLE = "unavailable"

#: One representative record per family, in `ENDPOINTS` order so re-runs are
#: deterministic. Documentation-derived, same status as every other FI-8 mock
#: fixture: unverified against live until FI-9.
DEFAULT_FAMILY_PAYLOADS: dict[str, dict] = {
    "leagues": {"data": [{"id": 8, "name": "Premier League"}]},
    "seasons": {"data": [{"id": 23614, "name": "2025/2026", "league_id": 8}]},
    "fixtures": {"data": [{"id": 1001, "league_id": 8, "season_id": 23614}]},
    "teams": {"data": [{"id": 1, "name": "Example FC"}]},
    "squads": {"data": [{"id": 11, "team_id": 1, "player_id": 101}]},
    "players": {"data": [{"id": 101, "name": "Example Player"}]},
    "lineups": {"data": [{"id": 21, "fixture_id": 1001, "player_id": 101}]},
    "formations": {"data": [{"id": 31, "fixture_id": 1001, "formation": "4-3-3"}]},
    "substitutions": {"data": [{"id": 41, "fixture_id": 1001, "player_in_id": 102}]},
    "injuries": {"data": [{"id": 51, "player_id": 101, "type_id": 1}]},
    "suspensions": {"data": [{"id": 61, "player_id": 101, "type_id": 2}]},
    "coaches": {"data": [{"id": 71, "name": "Example Coach", "team_id": 1}]},
    "referees": {"data": [{"id": 81, "name": "Example Referee"}]},
    "team_statistics": {"data": [{"id": 91, "fixture_id": 1001, "team_id": 1}]},
    "player_statistics": {"data": [{"id": 1011, "fixture_id": 1001, "player_id": 101}]},
}


def mock_transport(overrides: dict[str, dict] | None = None) -> ReplayTransport:
    """Serve one page per family, in `ENDPOINTS` order.

    `overrides` swaps a single family's payload -- the mechanism the DoD 3 exit
    proof and the item 10 deletion tests use, e.g. `{"leagues":
    load_fixture("edge_cases.json")["empty"]}` -- without touching the other 14.
    """
    payloads = dict(DEFAULT_FAMILY_PAYLOADS)
    if overrides:
        payloads.update(overrides)
    served = [response(payloads[family]) for family in ENDPOINTS]
    return ReplayTransport(served)


def classify_family(client, family: str) -> tuple[str, int, tuple[int, ...], str | None]:
    """Attempt one page of `family` and classify what was actually received.

    Returns `(status, record_count, provider_ids, reason)`. `reason` is
    populated only for `unavailable`, holding the exception the parser raised
    rather than discarding it.
    """
    try:
        records = client.fetch_page(family)
    except SportmonksError as exc:
        return STATUS_UNAVAILABLE, 0, (), f"{type(exc).__name__}: {exc}"
    if not records:
        return STATUS_EMPTY, 0, (), None
    ids = tuple(sorted(record.provider_id for record in records))
    return STATUS_REACHABLE, len(records), ids, None


def collect(client, mode: str) -> TrialReport:
    """Build the report from what each family's own response actually held."""
    report = TrialReport(script=SCRIPT, mode=mode)
    classifications: dict[str, tuple[str, int, tuple[int, ...], str | None]] = {}

    for family in ENDPOINTS:
        classification = classify_family(client, family)
        classifications[family] = classification
        status, count, ids, reason = classification
        ids_repr = ",".join(str(i) for i in ids) if ids else "none"
        detail = f"status={status} records={count} provider_ids={{{ids_repr}}}"
        if reason is not None:
            detail += f" reason={reason}"
        report.observed_shapes.append(ObservedShape(f"family:{family}", detail))

    leagues_status, leagues_count, leagues_ids, _ = classifications["leagues"]
    seasons_status, seasons_count, seasons_ids, _ = classifications["seasons"]

    missing = []
    if leagues_status != STATUS_REACHABLE:
        missing.append(f"leagues family {leagues_status}")
    if seasons_status != STATUS_REACHABLE:
        missing.append(f"seasons family {seasons_status}")

    evidence = (
        f"leagues: {leagues_status} ({leagues_count} records, "
        f"ids={{{','.join(str(i) for i in leagues_ids) or 'none'}}}); "
        f"seasons: {seasons_status} ({seasons_count} records, "
        f"ids={{{','.join(str(i) for i in seasons_ids) or 'none'}}})"
    )
    report.objectives.append(Objective(
        1, OBJECTIVE_1,
        OBSERVED if not missing else DEGRADED,
        evidence if not missing else f"{evidence} — {'; '.join(missing)}",
    ))

    unavailable = [f for f, c in classifications.items() if c[0] == STATUS_UNAVAILABLE]
    empty = [f for f, c in classifications.items() if c[0] == STATUS_EMPTY]
    if unavailable:
        report.warnings.append(f"unavailable families: {', '.join(unavailable)}")
    if empty:
        report.warnings.append(f"empty families: {', '.join(empty)}")
    report.warnings.append(
        "mock mode: family payloads are documentation-derived and carry "
        '"status": "unverified_against_live" until FI-9'
        if mode == MODE_MOCK else
        "live mode: family payloads are as received from the provider"
    )
    return report


def _report_with(mode: str, status: str, reason: str) -> TrialReport:
    """A report is still written on the failure paths, matching `trial_auth`."""
    report = TrialReport(script=SCRIPT, mode=mode)
    report.objectives.append(Objective(1, OBJECTIVE_1, status, reason))
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
        report = _report_with(mode, "unmet", "configuration incomplete; no request was issued")
    except SportmonksAuthenticationError as exc:
        failure = f"AUTH: {type(exc).__name__}"
        config_failure = True
        report = _report_with(mode, "unmet", "authentication rejected by the provider")
    except SportmonksError as exc:
        failure = f"PROVIDER: {type(exc).__name__}"
        report = _report_with(mode, "degraded", f"provider error: {type(exc).__name__}")

    json_path, md_path = write_report(report, args.out)
    if failure is not None:
        print(failure)
    print(f"{SCRIPT}: mode={report.mode} report={json_path} markdown={md_path}")
    return EXIT_CONFIG if config_failure else report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())

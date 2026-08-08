"""FI-8 trial acceptance script: injuries, suspensions, and coach/manager records.

Covers brief §11.3 objective 11 (injuries and suspensions) and objective 12
(coaches and manager records). S5 DoD 1 requires injuries, suspensions, and
coach/manager records to be reported as *three* separately-statused
objectives even though they collapse to two objective ids in the brief: this
script emits two `Objective(11, ...)` entries -- one titled "Injuries", one
titled "Suspensions" -- plus one `Objective(12, ...)`. Each is built only from
the records the transport actually returned; an empty family marks that
family's objective `unmet` -- nothing was observed, so it is not a partial
observation -- and drops that family's shape entry, leaving every other family
untouched (standing DoD item 10).

Existence-versus-content declaration (standing DoD item 10). Every shape entry
here is one whose **existence is the observation**'s subject, so each must
disappear when its family's data is absent, and each is covered by a test that
removes that family and asserts exactly that:

- `injury_record_fields`, `suspension_record_fields`, `coach_record_fields`
  -- content derived from the records received; entry disappears when empty.
- `injury_freshness_field` -- the entry's *existence* signals that at least one
  record carried a freshness timestamp, and it disappears when none did. Its
  value is the module constant `FRESHNESS_FIELD`, a declared and still
  unverified documentation assumption rather than a derived value; the failure
  mode is deliberately conservative, since an unexpected live field name yields
  "no timestamp" and therefore `degraded`, never a fabricated "fresh".

Every injury record's freshness is read from its own raw payload. A record
whose freshness field is absent, null, or empty is reported as carrying *no*
timestamp -- never defaulted to fresh (S5 DoD 2). This is the input the §12
degradation matrix will later consume to apply a confidence penalty; FI-8
only records the timestamp, it does not apply the penalty.

`--mock` is the default and is the only mode that runs before FI-9.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    DEGRADED, EXIT_CONFIG, EXIT_REFUSED, MODE_MOCK, OBSERVED, UNMET, Objective,
    ObservedShape, ReplayTransport, TrialRefusal, TrialReport, build_parser,
    make_client, resolve_mode, response, write_report,
)
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
)

SCRIPT = "trial_injuries"
OBJECTIVE_11 = 11
OBJECTIVE_12 = 12

#: The freshness field this script looks for on every injury record.
#: Sportmonks documentation is not authoritative on the live field name
#: (§17's top risk: docs != live payloads); FI-9 confirms or revises it.
#: Until then this is the one field treated as a freshness signal -- its
#: absence (missing key, null, or empty string) means the record is reported
#: as carrying no timestamp, never defaulted to fresh.
FRESHNESS_FIELD = "updated_at"

DEFAULT_INJURIES = [
    {"id": 51, "player_id": 101, "type_id": 1, "expected_return": None, "updated_at": "2026-08-01T09:00:00Z"},
    {"id": 52, "player_id": 102, "type_id": 1, "expected_return": "2026-08-15", "updated_at": "2026-08-02T08:30:00Z"},
]
DEFAULT_SUSPENSIONS = [
    {"id": 61, "player_id": 103, "type_id": 2, "games_remaining": 1},
]
DEFAULT_COACHES = [
    {"id": 71, "name": "Example Coach", "team_id": 1},
]


def mock_transport(*, injuries=None, suspensions=None, coaches=None) -> ReplayTransport:
    """Replay one page each of injuries, suspensions, coaches, in that order --
    the order `collect` requests them in.

    The keyword arguments exist for the tests that prove this script observes
    rather than asserts: passing an altered or empty list for one family must
    change only that family's objective and shape, never the others'.
    """
    served = [
        response({"data": DEFAULT_INJURIES if injuries is None else injuries}),
        response({"data": DEFAULT_SUSPENSIONS if suspensions is None else suspensions}),
        response({"data": DEFAULT_COACHES if coaches is None else coaches}),
    ]
    return ReplayTransport(served)


def _observed_fields(records: Sequence) -> tuple[str, ...]:
    """Field names actually present across these records -- key presence,
    union, first-seen order. Empty when there are no records. Mirrors
    `_trial_common.body_skeleton`'s "names only, never values" discipline."""
    seen: list[str] = []
    for record in records:
        for name in record.raw_fields:
            if name not in seen:
                seen.append(name)
    return tuple(seen)


def _has_freshness(record) -> bool:
    value = record.raw_fields.get(FRESHNESS_FIELD)
    return isinstance(value, str) and bool(value)


def _injuries_objective(records: Sequence) -> tuple[Objective, list[ObservedShape]]:
    shapes: list[ObservedShape] = []
    if not records:
        return Objective(OBJECTIVE_11, "Injuries", UNMET, "no injury records observed"), shapes

    with_ts = [r for r in records if _has_freshness(r)]
    without_ts = [r for r in records if not _has_freshness(r)]
    fields = _observed_fields(records)
    evidence = (
        f"{len(records)} injury record(s); fields observed: {', '.join(fields) or 'none'}; "
        f"{len(with_ts)} carry a '{FRESHNESS_FIELD}' freshness timestamp, "
        f"{len(without_ts)} do not (reported degraded, never defaulted to fresh)"
    )
    status = OBSERVED if not without_ts else DEGRADED
    if fields:
        shapes.append(ObservedShape("injury_record_fields", ", ".join(fields)))
    if with_ts:
        shapes.append(ObservedShape("injury_freshness_field", FRESHNESS_FIELD))
    return Objective(OBJECTIVE_11, "Injuries", status, evidence), shapes


def _suspensions_objective(records: Sequence) -> tuple[Objective, list[ObservedShape]]:
    shapes: list[ObservedShape] = []
    if not records:
        return Objective(OBJECTIVE_11, "Suspensions", UNMET, "no suspension records observed"), shapes

    fields = _observed_fields(records)
    evidence = f"{len(records)} suspension record(s); fields observed: {', '.join(fields) or 'none'}"
    if fields:
        shapes.append(ObservedShape("suspension_record_fields", ", ".join(fields)))
    return Objective(OBJECTIVE_11, "Suspensions", OBSERVED, evidence), shapes


def _coaches_objective(records: Sequence) -> tuple[Objective, list[ObservedShape]]:
    shapes: list[ObservedShape] = []
    if not records:
        return (
            Objective(OBJECTIVE_12, "Coaches and manager records", UNMET, "no coach records observed"),
            shapes,
        )

    fields = _observed_fields(records)
    evidence = f"{len(records)} coach/manager record(s); fields observed: {', '.join(fields) or 'none'}"
    if fields:
        shapes.append(ObservedShape("coach_record_fields", ", ".join(fields)))
    return Objective(OBJECTIVE_12, "Coaches and manager records", OBSERVED, evidence), shapes


def collect(client, mode: str) -> TrialReport:
    """Build the report from what the transport actually returned."""
    report = TrialReport(script=SCRIPT, mode=mode)

    injuries = tuple(client.injuries())
    suspensions = tuple(client.suspensions())
    coaches = tuple(client.coaches())

    injuries_objective, injuries_shapes = _injuries_objective(injuries)
    suspensions_objective, suspensions_shapes = _suspensions_objective(suspensions)
    coaches_objective, coaches_shapes = _coaches_objective(coaches)

    report.objectives.extend([injuries_objective, suspensions_objective, coaches_objective])
    report.observed_shapes.extend(injuries_shapes + suspensions_shapes + coaches_shapes)

    report.warnings.append(
        "mock mode: shapes are documentation-derived and carry "
        '"status": "unverified_against_live" until FI-9'
        if mode == MODE_MOCK else
        "live mode: shapes are as received from the provider"
    )
    return report


def _report_with(mode: str, status: str, reason: str) -> TrialReport:
    """A report is still written on the failure paths, mirroring trial_auth."""
    report = TrialReport(script=SCRIPT, mode=mode)
    report.objectives.append(Objective(OBJECTIVE_11, "Injuries", status, reason))
    report.objectives.append(Objective(OBJECTIVE_11, "Suspensions", status, reason))
    report.objectives.append(Objective(OBJECTIVE_12, "Coaches and manager records", status, reason))
    report.warnings.append(reason)
    return report


def _unmet_report(mode: str, reason: str) -> TrialReport:
    """The run never reached the provider, so nothing was observed at all."""
    return _report_with(mode, UNMET, reason)


def _degraded_report(mode: str, reason: str) -> TrialReport:
    """The provider was reached and misbehaved: a partial observation."""
    return _report_with(mode, DEGRADED, reason)


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
        report = _unmet_report(mode, "configuration incomplete; no request was issued")
    except SportmonksAuthenticationError as exc:
        failure = f"AUTH: {type(exc).__name__}"
        config_failure = True
        report = _unmet_report(mode, "authentication rejected by the provider")
    except SportmonksError as exc:
        # Only configuration/authentication map to exit 3. Any other provider
        # failure (schema mismatch, exhausted retries, pagination fault) is a
        # degraded observation with whatever was received recorded, not
        # discarded.
        failure = f"PROVIDER: {type(exc).__name__}"
        report = _degraded_report(mode, f"provider error: {type(exc).__name__}")

    json_path, md_path = write_report(report, args.out)
    if failure is not None:
        print(failure)
    print(f"{SCRIPT}: mode={report.mode} report={json_path} markdown={md_path}")
    return EXIT_CONFIG if config_failure else report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())

"""FI-8 trial acceptance script: fixture-level team and player match
statistics, plus the pre/during/post recording scaffold for update timing and
post-match corrections.

Covers brief §11.3 objective 13 (fixture-level team statistics) and objective
14 (player match statistics), each reported separately with per-field
presence counts derived from the records actually received (S5 DoD 3).

Existence-versus-content declaration (standing DoD item 10). Both shape
entries -- `team_stat_fields` and `player_stat_fields` -- are ones whose
**existence is the observation**'s subject: each disappears when its family
returns no records, and each is covered by a test that empties that family and
asserts the entry is gone while the sibling family's entry survives. Their
content is the per-field presence counts read from the records received.
Objectives 15 and 16 carry no shape entry at all; see below for why their
status is deliberately not derived from any payload.

Objectives 15 (data update timing) and 16 (post-match corrections) are
structurally different from the rest of FI-8 (S5 DoD 4): they can only be
measured by repeated live observation of a real match across pre/during/post
phases. A single `--mock` run has no second sample of the same fixture to
compare against, so this script marks both `not_applicable (requires FI-9
live observation)` unconditionally -- that status is not derived from the
mock payload because there is nothing in mock mode that could ever change it.
What S5 ships instead is the *recording scaffold*: the `StatSample` schema
below and `diff_samples`, which the tests in
`tests/test_trial_health_stats.py` exercise against two hand-written
`StatSample` instances. Two mock runs of this script can never stand in for
that: `MOCK_CLOCK` (`_trial_common.py`) makes repeated mock runs overwrite the
same snapshot filename, so there is no way to generate two independent mock
samples of one fixture by running the script twice.

`--mock` is the default and is the only mode that runs before FI-9.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    DEGRADED, EXIT_CONFIG, EXIT_REFUSED, MODE_MOCK, NOT_APPLICABLE, OBSERVED,
    UNMET, Objective, ObservedShape, ReplayTransport, TrialRefusal, TrialReport,
    build_parser, make_client, resolve_mode, response, write_report,
)
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
)

SCRIPT = "trial_stats"
OBJECTIVE_13 = 13
OBJECTIVE_14 = 14
OBJECTIVE_15 = 15
OBJECTIVE_16 = 16
OBJECTIVE_15_TITLE = "Data update timing before, during, and after matches"
OBJECTIVE_16_TITLE = "Post-match corrections"
NOT_APPLICABLE_REASON = "requires FI-9 live observation"

TEAM_STAT_FIELDS = ("fixture_id", "team_id", "type_id", "value")
PLAYER_STAT_FIELDS = ("fixture_id", "player_id", "type_id", "value")

DEFAULT_TEAM_STATS = [
    {"id": 91, "fixture_id": 1001, "team_id": 1, "type_id": 42, "value": 55},
    {"id": 92, "fixture_id": 1001, "team_id": 2, "type_id": 42, "value": 45},
]
DEFAULT_PLAYER_STATS = [
    {"id": 1011, "fixture_id": 1001, "player_id": 101, "type_id": 52, "value": 3},
    {"id": 1012, "fixture_id": 1001, "player_id": 102, "type_id": 52, "value": 1},
]


def mock_transport(*, team_stats=None, player_stats=None) -> ReplayTransport:
    """Replay one page of team statistics, then one page of player
    statistics -- the order `collect` requests them in."""
    served = [
        response({"data": DEFAULT_TEAM_STATS if team_stats is None else team_stats}),
        response({"data": DEFAULT_PLAYER_STATS if player_stats is None else player_stats}),
    ]
    return ReplayTransport(served)


def _field_presence(records: Sequence, fields: Sequence[str]) -> dict[str, int]:
    """How many of these records actually carry each field -- key presence,
    never a fixed list. A field absent from every record counts 0."""
    return {name: sum(1 for r in records if name in r.raw_fields) for name in fields}


def _stat_objective(
    objective_id: int, title: str, shape_name: str, records: Sequence, fields: Sequence[str],
) -> tuple[Objective, list[ObservedShape]]:
    shapes: list[ObservedShape] = []
    if not records:
        return Objective(objective_id, title, UNMET, f"no {title.lower()} records observed"), shapes

    presence = _field_presence(records, fields)
    missing = [name for name in fields if presence[name] == 0]
    counts_text = ", ".join(f"{name}={presence[name]}/{len(records)}" for name in fields)
    evidence = f"{len(records)} record(s); field presence: {counts_text}"
    status = OBSERVED
    if missing:
        status = DEGRADED
        evidence += f"; missing entirely: {', '.join(missing)}"

    present_fields = tuple(name for name in fields if presence[name] > 0)
    if present_fields:
        shapes.append(ObservedShape(shape_name, ", ".join(present_fields)))
    return Objective(objective_id, title, status, evidence), shapes


# --- S5 DoD 4: the recording scaffold for objectives 15 and 16 ---------------

@dataclass(frozen=True)
class StatSample:
    """One capture of a fixture's statistics at a point in the match
    lifecycle. Recording scaffold only: the schema a live `trial_stats.py`
    run will populate once FI-9 can observe a real match pre/during/post
    kickoff. `team_stats`/`player_stats` are keyed `(entity_id, type_id) ->
    value`, matching the flat `(id, fixture_id, team_id|player_id, type_id,
    value)` shape the checked-in fixtures already show for
    `team_statistics`/`player_statistics`.
    """

    fixture_id: int
    phase: str  # "pre" | "during" | "post"
    captured_at: str
    team_stats: Mapping[tuple[int, int], int] = field(default_factory=dict)
    player_stats: Mapping[tuple[int, int], int] = field(default_factory=dict)


@dataclass(frozen=True)
class SampleDiff:
    """What changed between two `StatSample`s of the same fixture."""

    fixture_id: int
    from_phase: str
    to_phase: str
    changed_team_stats: tuple[tuple[tuple[int, int], int, int], ...]
    added_team_stats: tuple[tuple[int, int], ...]
    removed_team_stats: tuple[tuple[int, int], ...]
    changed_player_stats: tuple[tuple[tuple[int, int], int, int], ...]
    added_player_stats: tuple[tuple[int, int], ...]
    removed_player_stats: tuple[tuple[int, int], ...]


def _diff_stats(before: Mapping, after: Mapping):
    changed = tuple(
        (key, before[key], after[key])
        for key in sorted(set(before) & set(after))
        if before[key] != after[key]
    )
    added = tuple(sorted(set(after) - set(before)))
    removed = tuple(sorted(set(before) - set(after)))
    return changed, added, removed


def diff_samples(before: StatSample, after: StatSample) -> SampleDiff:
    """Diff two samples of the *same* fixture.

    Objective 16 (post-match corrections) is exactly a value that changed
    between two samples of a settled fixture; objective 15 (update timing) is
    exactly the gap between `captured_at` on samples whose values changed.
    Both require a live fixture observed more than once -- this function only
    diffs whatever two samples it is given; it does not itself decide whether
    a real correction or a real timing gap occurred.
    """
    if before.fixture_id != after.fixture_id:
        raise ValueError("diff_samples requires two samples of the same fixture")

    changed_team, added_team, removed_team = _diff_stats(before.team_stats, after.team_stats)
    changed_player, added_player, removed_player = _diff_stats(before.player_stats, after.player_stats)
    return SampleDiff(
        before.fixture_id, before.phase, after.phase,
        changed_team, added_team, removed_team,
        changed_player, added_player, removed_player,
    )


def collect(client, mode: str) -> TrialReport:
    """Build the report from what the transport actually returned."""
    report = TrialReport(script=SCRIPT, mode=mode)

    team_stats = tuple(client.team_fixture_statistics())
    player_stats = tuple(client.player_fixture_statistics())

    team_objective, team_shapes = _stat_objective(
        OBJECTIVE_13, "Fixture-level team statistics", "team_statistics_fields",
        team_stats, TEAM_STAT_FIELDS,
    )
    player_objective, player_shapes = _stat_objective(
        OBJECTIVE_14, "Player match statistics", "player_statistics_fields",
        player_stats, PLAYER_STAT_FIELDS,
    )
    report.objectives.extend([team_objective, player_objective])
    report.observed_shapes.extend(team_shapes + player_shapes)

    # Objectives 15 and 16 cannot be measured in mock mode at all -- both
    # require repeated observation of a real fixture across pre/during/post
    # kickoff (S5 DoD 4). This is a modal statement about mock mode, not a
    # fact read from a payload, so it is deliberately unconditional. The
    # scaffold that will produce a real status once FI-9 supplies two live
    # samples (`StatSample`/`diff_samples` above) is exercised by
    # tests/test_trial_health_stats.py against two hand-written samples.
    report.objectives.append(Objective(OBJECTIVE_15, OBJECTIVE_15_TITLE, NOT_APPLICABLE, NOT_APPLICABLE_REASON))
    report.objectives.append(Objective(OBJECTIVE_16, OBJECTIVE_16_TITLE, NOT_APPLICABLE, NOT_APPLICABLE_REASON))

    report.warnings.append(
        "mock mode: shapes are documentation-derived and carry "
        '"status": "unverified_against_live" until FI-9'
        if mode == MODE_MOCK else
        "live mode: shapes are as received from the provider"
    )
    report.warnings.append(
        "objectives 15 and 16 are a recording scaffold only in FI-8; see "
        "StatSample/diff_samples and tests/test_trial_health_stats.py"
    )
    return report


def _report_with(mode: str, status: str, reason: str) -> TrialReport:
    """A report is still written on the failure paths, mirroring trial_auth."""
    report = TrialReport(script=SCRIPT, mode=mode)
    report.objectives.append(Objective(OBJECTIVE_13, "Fixture-level team statistics", status, reason))
    report.objectives.append(Objective(OBJECTIVE_14, "Player match statistics", status, reason))
    report.objectives.append(Objective(OBJECTIVE_15, OBJECTIVE_15_TITLE, NOT_APPLICABLE, NOT_APPLICABLE_REASON))
    report.objectives.append(Objective(OBJECTIVE_16, OBJECTIVE_16_TITLE, NOT_APPLICABLE, NOT_APPLICABLE_REASON))
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
        # failure is a degraded observation with whatever was received
        # recorded, not discarded.
        failure = f"PROVIDER: {type(exc).__name__}"
        report = _degraded_report(mode, f"provider error: {type(exc).__name__}")

    json_path, md_path = write_report(report, args.out)
    if failure is not None:
        print(failure)
    print(f"{SCRIPT}: mode={report.mode} report={json_path} markdown={md_path}")
    return EXIT_CONFIG if config_failure else report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())

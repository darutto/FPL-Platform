"""FI-8 trial acceptance script: teams, squads, and current player records.

Covers brief §11.3 objectives 4 (team and squad completeness) and 5 (current
player records).

COMPLETENESS IS A COUNT PER FIELD, NEVER A BOOLEAN
--------------------------------------------------
The S4a DoD is explicit that completeness is reported as counts with named
missing fields. The reason is falsifiability: a boolean `complete: true` is
satisfiable by the literal `True`, and so is a count that can only ever read
`0/n` or `n/n`. Every family here reports `field k/n` for each required field,
so a record set where *some* records carry a field produces a number no literal
survives — which is what `test_partial_field_presence_is_counted_not_rounded`
pins.

A field present with a `null` value counts as **missing**. A provider that
ships `date_of_birth: null` has not supplied a date of birth, and counting the
key rather than the value would report completeness the identity work
(§14.1's ≥95% gate, which consumes birth dates) cannot use.

WHY THE REQUIRED SETS ARE INPUTS
--------------------------------
`REQUIRED_FIELDS` is an **input**, the same way an endpoint path is: it says
which fields this platform needs, not which fields Sportmonks documents. What
gets *observed* is how many records actually carried each one. FI-9 may find a
provider field named differently; that is a plan-revision request (§17), not a
value to guess at here.

OBJECTIVES 4 AND 5 ARE SEPARATELY STATUSED
------------------------------------------
DoD item 2: a complete squad list with impoverished player records must degrade
5 while leaving 4 observed. They are computed from disjoint inputs — 4 from the
`teams` and `squads` families, 5 from `players` plus the squad→player coverage
that says whether the player records we hold actually cover the squads we were
given.

`--mock` is the default and is the only mode that runs before FI-9.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    DEGRADED, EXIT_CONFIG, EXIT_REFUSED, MODE_MOCK, OBSERVED, UNMET,
    EndpointReplayTransport, Objective, ObservedShape, TrialRefusal, TrialReport,
    build_parser, load_fixture, make_client, resolve_mode, response, write_report,
)
from sportmonks_client.client import ENDPOINTS  # noqa: E402
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
)

SCRIPT = "trial_squads"
OBJECTIVE_4 = "Team and squad completeness"
OBJECTIVE_5 = "Current player records"

#: Fields this platform needs from each family, per family. An **input**: the
#: observation is the per-field count of records that actually carried one.
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "teams": ("id", "name", "short_code"),
    "squads": ("id", "team_id", "player_id", "position_id"),
    "players": ("id", "name", "date_of_birth"),
}

#: Standing DoD items 10 and 11, per entry.
#:
#: `teams`, `squads` and `players` are under item 10's **first** branch: each
#: exists only when that family returned records, so an absent family is visible
#: as a missing entry *and* a non-`observed` objective.
#:
#: `squad_player_coverage` is under the **second** branch — existence is the
#: observation. It is emitted whenever squad records arrived, including when not
#: one of them resolves to a player record, because "we hold squads referencing
#: players we cannot fetch" is precisely the state objective 5 exists to catch,
#: and an entry that vanished on absence could not report it.
DECLARED_SHAPES = {
    "teams": (
        "test_each_family_shape_reports_the_fields_that_arrived",
        "test_partial_field_presence_is_counted_not_rounded",
        "test_an_absent_family_drops_its_shape_and_blocks_the_objective",
    ),
    "squads": (
        "test_each_family_shape_reports_the_fields_that_arrived",
        "test_partial_field_presence_is_counted_not_rounded",
        "test_an_absent_family_drops_its_shape_and_blocks_the_objective",
    ),
    "players": (
        "test_each_family_shape_reports_the_fields_that_arrived",
        "test_partial_field_presence_is_counted_not_rounded",
        "test_an_absent_family_drops_its_shape_and_blocks_the_objective",
    ),
    "squad_player_coverage": (
        "test_the_coverage_entry_counts_the_squad_rows_that_resolve",
        "test_the_coverage_entry_is_emitted_even_when_nothing_resolves",
    ),
}


@dataclass(frozen=True)
class FieldCount:
    """How many of `total` records carried `name` with a non-null value."""

    name: str
    present: int
    total: int

    @property
    def complete(self) -> bool:
        return self.present == self.total

    def render(self) -> str:
        return f"{self.name} {self.present}/{self.total}"


@dataclass(frozen=True)
class FamilyResult:
    family: str
    records: tuple[Any, ...]
    failure: str = ""

    @property
    def present(self) -> bool:
        return bool(self.records) and not self.failure

    @property
    def counts(self) -> tuple[FieldCount, ...]:
        """Per-required-field presence over the records actually returned."""
        total = len(self.records)
        return tuple(
            FieldCount(
                name,
                sum(1 for r in self.records if r.raw_fields.get(name) is not None),
                total,
            )
            for name in REQUIRED_FIELDS[self.family]
        )

    @property
    def missing(self) -> tuple[str, ...]:
        """Required fields not carried by every record, named."""
        return tuple(count.name for count in self.counts if not count.complete)

    def render(self) -> str:
        """Field names as the provider sent them, plus the per-field counts.

        The names answer "what shape is this?"; the counts answer "how much of
        it arrived?". Reporting only the first would let a family whose records
        each carry a different half of the schema read as complete.
        """
        if not self.records:
            return f"none; {self.failure}" if self.failure else "none"
        first = tuple(self.records[0].raw_fields)
        extra = sorted({key for r in self.records for key in r.raw_fields} - set(first))
        rendered = ",".join(first)
        body = f"{rendered}+{','.join(extra)}" if extra else rendered
        counts = ",".join(count.render() for count in self.counts)
        return f"{len(self.records)} record(s); record{{{body}}}; required[{counts}]"

    def shortfall(self) -> str:
        """Why this family is not fully observed, or empty when it is."""
        if self.failure:
            return f"{self.family} request failed: {self.failure}"
        if not self.records:
            return f"no {self.family} record returned"
        if self.missing:
            return (
                f"{self.family} record(s) missing {','.join(self.missing)} "
                f"[{','.join(c.render() for c in self.counts if not c.complete)}]"
            )
        return ""

    def summary(self) -> str:
        return (
            f"{self.family}: {len(self.records)} record(s) "
            f"[{','.join(count.render() for count in self.counts)}]"
        )


def resolved_squad_rows(squads: FamilyResult, players: FamilyResult) -> int:
    """Squad rows whose `player_id` matches a player record we actually hold.

    Counts rows, not distinct players: two squad rows pointing at the same
    unfetchable player are two gaps in the squad, not one.
    """
    known = {player.provider_id for player in players.records}
    return sum(1 for row in squads.records if row.raw_fields.get("player_id") in known)


def mock_transport(
    *,
    teams: Any | None = None,
    squads: Any | None = None,
    players: Any | None = None,
) -> EndpointReplayTransport:
    """Replay the checked-in payloads for the three families this script reads.

    Each override takes a payload or an `Exception`, so the tests can prove an
    absent, impoverished, or refusing family changes the objective rather than
    only a count.
    """
    payloads = load_fixture("endpoint_payloads.json")["families"]
    chosen = {
        "teams": payloads["teams"] if teams is None else teams,
        "squads": payloads["squads"] if squads is None else squads,
        "players": payloads["players"] if players is None else players,
    }
    return EndpointReplayTransport({
        ENDPOINTS[family][0]: item if isinstance(item, Exception) else response(item)
        for family, item in chosen.items()
    })


def _fetch(client, family: str) -> FamilyResult:
    try:
        return FamilyResult(family, tuple(client.iter_entities(family)))
    except (SportmonksConfigurationError, SportmonksAuthenticationError):
        # Standing DoD item 13: both subclass SportmonksError, and a broad catch
        # here would report a rejected token as "this family has no records" —
        # on trial day 2 that reads as "the Starter plan carries no squads".
        raise
    except SportmonksError as exc:
        return FamilyResult(family, (), type(exc).__name__)


def _status(results: Sequence[FamilyResult], shortfalls: Sequence[str]) -> str:
    """`unmet` when a family produced nothing, `degraded` when it produced less
    than a whole record.

    The two are different facts and collapsing them would tell a reader that a
    squad list nobody can fetch and a squad list missing one field are the same
    problem. Absence dominates: a run with one absent family and one incomplete
    family is `unmet`.
    """
    if not shortfalls:
        return OBSERVED
    return UNMET if any(not result.present for result in results) else DEGRADED


def collect(client, mode: str) -> TrialReport:
    report = TrialReport(script=SCRIPT, mode=mode)
    teams = _fetch(client, "teams")
    squads = _fetch(client, "squads")
    players = _fetch(client, "players")

    resolved = resolved_squad_rows(squads, players)

    # --- Objective 4: team and squad completeness -----------------------------
    shortfalls_4 = [text for text in (teams.shortfall(), squads.shortfall()) if text]
    evidence_4 = f"{teams.summary()}; {squads.summary()}"
    report.objectives.append(Objective(
        4, OBJECTIVE_4,
        _status((teams, squads), shortfalls_4),
        evidence_4 if not shortfalls_4 else f"{evidence_4} — {'; '.join(shortfalls_4)}",
    ))

    # --- Objective 5: current player records ----------------------------------
    # Coverage belongs to 5, not 4: a squad list can be complete in its own
    # right while the player records behind it are absent, and that is exactly
    # the split DoD item 2 asks for.
    shortfalls_5 = [text for text in (players.shortfall(),) if text]
    if squads.present and resolved != len(squads.records):
        shortfalls_5.append(
            f"{len(squads.records) - resolved} of {len(squads.records)} squad row(s) "
            "reference a player with no record"
        )
    evidence_5 = (
        f"{players.summary()}; "
        f"{resolved}/{len(squads.records)} squad row(s) resolve to a player record"
    )
    report.objectives.append(Objective(
        5, OBJECTIVE_5,
        _status((players,), shortfalls_5),
        evidence_5 if not shortfalls_5 else f"{evidence_5} — {'; '.join(shortfalls_5)}",
    ))

    for result in (teams, squads, players):
        if result.records:
            report.observed_shapes.append(ObservedShape(result.family, result.render()))

    if squads.records:
        # Second branch: emitted even when nothing resolves, because "these
        # squads reference players we cannot fetch" is the observation that
        # decides whether objective 5's record set is usable at all.
        report.observed_shapes.append(ObservedShape(
            "squad_player_coverage",
            f"{resolved}/{len(squads.records)} squad row(s) resolve; "
            f"{len(players.records)} player record(s) held",
        ))

    report.warnings.append(
        "mock mode: shapes are documentation-derived and carry "
        '"status": "unverified_against_live" until FI-9'
        if mode == MODE_MOCK else
        "live mode: shapes are as received from the provider"
    )
    return report


def _report_with(mode: str, status: str, reason: str) -> TrialReport:
    report = TrialReport(script=SCRIPT, mode=mode)
    report.objectives.append(Objective(4, OBJECTIVE_4, status, reason))
    report.objectives.append(Objective(5, OBJECTIVE_5, status, reason))
    report.warnings.append(reason)
    return report


def _unmet_report(mode: str, reason: str) -> TrialReport:
    """Nothing was reached, so nothing was observed."""
    return _report_with(mode, UNMET, reason)


# No `_degraded_report`: `_fetch` turns every family-scoped provider error into
# that family's observation and re-raises the two that are not, so no generic
# provider branch is enterable. Same reasoning as `trial_entities` and
# `trial_injuries`.


def main(argv: Sequence[str] | None = None) -> int:
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

    json_path, md_path = write_report(report, args.out)
    if failure is not None:
        print(failure)
    print(f"{SCRIPT}: mode={report.mode} report={json_path} markdown={md_path}")
    return EXIT_CONFIG if config_failure else report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())

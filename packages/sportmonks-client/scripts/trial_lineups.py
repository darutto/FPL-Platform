"""FI-8 trial acceptance script: lineups, formations, grid, and substitutions.

Covers brief §11.3 objectives 6 (confirmed starters and substitutes), 7
(formation strings), 8 (formation-grid or lineup-position fields), 9 (detailed
position identifiers), and 10 (substitution relationships and minutes).

THE SCRIPTS DESCRIBE; FI-9 DECIDES
----------------------------------
This is the slice §14.4's GO criterion (b) and its *"M2 collapses to
detailed_position only"* NO-GO both hinge on, and §14.3 question 13 exists
precisely because the grid semantics are **undocumented**. So nothing here
decides what a grid value *means*. It reports the field that carried it and the
**structure** of the value — `str`, `list[int]`, `list[list[int]]`, absent — and
stops. Whether `"1:4"` is a row-and-slot index or a pitch coordinate is a
question for the provider, and encoding a guess would be a *stop and ask* per
§17.

The same restraint applies to objective 6, which is easier to get wrong because
a plausible answer is available: Sportmonks is widely said to mark a starter
with one `type_id` and a bench player with another. This script does not adopt
that. It reports **which field partitions the lineup and what values it took** —
`field=type_id; values{11:11,12:7}` — which is the observation. Naming 11 as
"starter" would be a semantic decision wearing a count's clothes, and it would
be reported with exactly the same confidence whether or not it were true.

WHAT IS AN INPUT AND WHAT IS AN OBSERVATION
-------------------------------------------
The candidate field lists below are **inputs**, like an endpoint path: they say
which names to look for. Which one the provider actually uses is the
observation, and the report names it. `DOCUMENTED_GRID_SHAPE` is an input of the
same kind — it is what the documentation gives us about the value's *type*, not
about its meaning — and a payload that differs from it is recorded and
`degraded`, never a crash and never a silent pass. Per the frozen contract:
shape reporting over shape assertion.

SEVEN, EIGHT AND NINE ARE THREE FACTS, NOT ONE
----------------------------------------------
Collapsing them would hide the NO-GO condition §14.4 watches for: a formation
string alone satisfies criterion (b) on a technicality while the grid is absent.
They are computed from different fields on different families and statused
independently, and `test_a_formation_string_alone_does_not_carry_the_grid`
drives exactly that payload.

`--mock` is the default and is the only mode that runs before FI-9.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

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

SCRIPT = "trial_lineups"
OBJECTIVE_6 = "Confirmed starters and substitutes"
OBJECTIVE_7 = "Formation strings"
OBJECTIVE_8 = "Formation-grid or lineup-position fields"
OBJECTIVE_9 = "Detailed position identifiers"
OBJECTIVE_10 = "Substitution relationships and minutes"

#: Candidate fields, searched in order. **Inputs.** Which name the provider uses
#: is unverified until FI-9, and a script that hardcoded one would report
#: `degraded` on live data for the wrong reason -- the S5a lesson, applied to
#: three more fields whose names are just as unverified.
STARTER_FIELDS: tuple[str, ...] = (
    "type_id", "starting", "is_starter", "position_type",
)
GRID_FIELDS: tuple[str, ...] = (
    "formation_field", "formation_position", "grid", "lineup_position",
)
DETAILED_POSITION_FIELDS: tuple[str, ...] = (
    "detailed_position_id", "detailed_position", "position_id",
)
FORMATION_FIELDS: tuple[str, ...] = ("formation", "formation_string", "name")

#: The **type** the documentation gives for a grid value. Not its meaning:
#: §14.3 question 13 is open precisely because the meaning is undocumented, and
#: nothing here reads the value. A payload whose grid is shaped otherwise is
#: recorded with the shape it had and degrades -- it does not fail, and it does
#: not pass silently.
DOCUMENTED_GRID_SHAPE = "str"

#: The two fields a substitution's direction rests on. Which is which is the
#: single most invertible fact in this slice: an implementation that swapped
#: them would report every substitution backwards with complete confidence, and
#: no count would look wrong. Pinned by `test_the_substitution_direction_is_not_
#: invertible`.
SUBSTITUTION_OUT_FIELDS: tuple[str, ...] = ("player_out_id", "player_off_id")
SUBSTITUTION_IN_FIELDS: tuple[str, ...] = ("player_in_id", "player_on_id")
SUBSTITUTION_MINUTE_FIELDS: tuple[str, ...] = ("minute", "minutes")

#: Emitted whenever mock mode supplied a field the corpus lacks. The corpus
#: carries no starter marker and no detailed position at all, so a faithful mock
#: run would degrade two objectives against standing DoD 2's exit-0 requirement.
#: Synthesized and declared, the way S3 declared its cross-competition fixture
#: and S5a its freshness stamps -- and the synthesis uses a *candidate* name so
#: the rehearsal exercises the search rather than bypassing it.
SYNTHETIC_WARNING = (
    "the mock lineup records carry a synthesized starter marker and detailed "
    "position; the checked-in corpus has neither, and which fields Sportmonks "
    "actually uses is unverified until FI-9"
)

#: Standing DoD items 10 and 11, per entry.
#:
#: `lineups`, `formations` and `substitutions` are under item 10's **first**
#: branch: each exists only when that family returned records.
#:
#: `starter_marker`, `formation_grid`, `detailed_position` and
#: `substitution_direction` are under the **second** branch — existence is the
#: observation, and each is emitted whenever its family returned records
#: including when the thing was not found:
#:  - `starter_marker` because "no field partitions the lineup" is the state
#:    that makes objective 6 unanswerable, and GO criterion (b) turns on it.
#:  - `formation_grid` because an absent grid is the NO-GO condition §14.4
#:    names by name — an entry that vanished would report it by saying nothing.
#:  - `detailed_position` because "grid absent, detailed_position present" is
#:    the exact fallback the NO-GO clause describes, and it is only visible if
#:    both entries are always present to be compared.
#:  - `substitution_direction` because it names which field supplied `on` and
#:    which supplied `off`; that naming is the only thing standing between a
#:    correct report and a confidently inverted one.
DECLARED_SHAPES = {
    "lineups": (
        "test_each_family_shape_reports_the_fields_that_arrived",
        "test_an_absent_family_drops_its_shape_and_blocks_its_objectives",
    ),
    "formations": (
        "test_each_family_shape_reports_the_fields_that_arrived",
        "test_an_absent_family_drops_its_shape_and_blocks_its_objectives",
    ),
    "substitutions": (
        "test_each_family_shape_reports_the_fields_that_arrived",
        "test_an_absent_family_drops_its_shape_and_blocks_its_objectives",
    ),
    "starter_marker": (
        "test_the_starter_entry_reports_the_partition_without_naming_a_side",
        "test_the_starter_entry_is_emitted_when_no_field_partitions_the_lineup",
    ),
    "formation_grid": (
        "test_the_grid_entry_reports_the_shape_it_found",
        "test_the_grid_entry_is_emitted_when_the_grid_is_absent",
    ),
    "detailed_position": (
        "test_the_detailed_position_entry_names_the_field_that_supplied_it",
        "test_the_detailed_position_entry_is_emitted_when_it_is_absent",
    ),
    "substitution_direction": (
        "test_the_substitution_direction_is_not_invertible",
        "test_the_direction_entry_is_emitted_when_a_side_is_missing",
    ),
}


def value_shape(value: Any) -> str:
    """Structure of a value, never its meaning.

    `"1:4"` renders `str` whether it is a row-and-slot pair or a pitch
    coordinate, which is the point: this function cannot accidentally decide
    §14.3 question 13 because it never looks inside.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return type(value).__name__
    if isinstance(value, str):
        return "str"
    if isinstance(value, Mapping):
        return f"dict{{{','.join(sorted(str(key) for key in value))}}}"
    if isinstance(value, Sequence):
        if not value:
            return "list[]"
        inner = sorted({value_shape(item) for item in value})
        return f"list[{'|'.join(inner)}]"
    return type(value).__name__


def first_present(record: Any, names: Sequence[str]) -> tuple[str, Any] | None:
    """The first candidate field this record carries with a non-null value."""
    for name in names:
        value = record.raw_fields.get(name)
        if value is not None:
            return name, value
    return None


@dataclass(frozen=True)
class FamilyResult:
    family: str
    records: tuple[Any, ...]
    failure: str = ""

    @property
    def present(self) -> bool:
        return bool(self.records) and not self.failure

    def render(self) -> str:
        if not self.records:
            return f"none; {self.failure}" if self.failure else "none"
        first = tuple(self.records[0].raw_fields)
        extra = sorted({key for r in self.records for key in r.raw_fields} - set(first))
        rendered = ",".join(first)
        body = f"{rendered}+{','.join(extra)}" if extra else rendered
        return f"{len(self.records)} record(s); record{{{body}}}"


@dataclass(frozen=True)
class FieldSurvey:
    """Which candidate field supplied a value, on how many records, and how the
    values were distributed. No candidate is preferred and no value is named."""

    field: str
    covered: int
    total: int
    shapes: tuple[str, ...]
    values: tuple[tuple[str, int], ...]

    @property
    def found(self) -> bool:
        return bool(self.field)

    @property
    def complete(self) -> bool:
        return self.found and self.covered == self.total


def survey(records: Sequence[Any], names: Sequence[str]) -> FieldSurvey:
    """Search the candidate list across a record set and describe what it found.

    The field reported is the first candidate any record carried, so a corpus
    using a name outside the list surveys as not-found rather than as an
    unexplained gap — which is the difference between "Sportmonks does not ship
    this" and "we looked for the wrong key".
    """
    field = ""
    for name in names:
        if any(record.raw_fields.get(name) is not None for record in records):
            field = name
            break
    if not field:
        return FieldSurvey("", 0, len(records), (), ())
    values = [record.raw_fields.get(field) for record in records]
    carried = [value for value in values if value is not None]
    counts: dict[str, int] = {}
    for value in carried:
        key = str(value) if not isinstance(value, (list, dict)) else value_shape(value)
        counts[key] = counts.get(key, 0) + 1
    return FieldSurvey(
        field, len(carried), len(records),
        tuple(sorted({value_shape(value) for value in carried})),
        tuple(sorted(counts.items())),
    )


@dataclass(frozen=True)
class Substitution:
    """One substitution as the provider reported it, direction named."""

    player_off: Any
    player_on: Any
    minute: Any

    @property
    def complete(self) -> bool:
        return all(part is not None for part in (self.player_off, self.player_on, self.minute))

    def render(self) -> str:
        return f"({self.player_off},{self.player_on},{self.minute})"


def substitution_triples(records: Sequence[Any]) -> tuple[Substitution, ...]:
    """`(player_off, player_on, minute)` per record, in that order.

    The order is the contract and the direction is read from the field name, not
    from position in the payload: `player_out_id` supplies `player_off` and
    `player_in_id` supplies `player_on`. An implementation that swapped them
    would produce a report that is wrong in every row and looks right in all of
    them.
    """
    return tuple(
        Substitution(
            (first_present(record, SUBSTITUTION_OUT_FIELDS) or ("", None))[1],
            (first_present(record, SUBSTITUTION_IN_FIELDS) or ("", None))[1],
            (first_present(record, SUBSTITUTION_MINUTE_FIELDS) or ("", None))[1],
        )
        for record in records
    )


def _synthesize_lineups(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Give mock lineup records the two fields the corpus does not ship.

    Uses the **first** candidate name in each list, so the rehearsal exercises
    the search rather than stepping around it, and gives the records two
    different starter values so objective 6's partition is a real partition
    rather than a single group.
    """
    starter, position = STARTER_FIELDS[0], DETAILED_POSITION_FIELDS[0]
    rows = list(payload["data"])
    if not rows:
        return {"data": []}
    stamped = [
        {**record, starter: 11, position: 24 + index}
        for index, record in enumerate(rows)
    ]
    # A second record carrying the *other* starter value, so the partition the
    # rehearsal exercises is a real partition. One value across every record
    # cannot separate two groups, and objective 6 would degrade -- correctly,
    # which is exactly why the mock must not be built that way.
    stamped.append({**rows[0], "id": 22, "player_id": 102, starter: 12, position: 27})
    return {"data": stamped}


def mock_transport(
    *,
    lineups: Any | None = None,
    formations: Any | None = None,
    substitutions: Any | None = None,
) -> EndpointReplayTransport:
    """Replay the checked-in payloads for the three families this script reads."""
    payloads = load_fixture("endpoint_payloads.json")["families"]
    chosen = {
        "lineups": _synthesize_lineups(payloads["lineups"]) if lineups is None else lineups,
        "formations": payloads["formations"] if formations is None else formations,
        "substitutions": payloads["substitutions"] if substitutions is None else substitutions,
    }
    return EndpointReplayTransport({
        ENDPOINTS[family][0]: item if isinstance(item, Exception) else response(item)
        for family, item in chosen.items()
    })


def _fetch(client, family: str) -> FamilyResult:
    try:
        return FamilyResult(family, tuple(client.iter_entities(family)))
    except (SportmonksConfigurationError, SportmonksAuthenticationError):
        # Standing DoD item 13: both subclass SportmonksError. A broad catch
        # here would report a rejected token as "the Starter plan carries no
        # lineups", which is the NO-GO condition §14.4 names.
        raise
    except SportmonksError as exc:
        return FamilyResult(family, (), type(exc).__name__)


def _family_shortfall(result: FamilyResult) -> str:
    if result.failure:
        return f"{result.family} request failed: {result.failure}"
    if not result.records:
        return f"no {result.family} record returned"
    return ""


def collect(client, mode: str) -> TrialReport:
    report = TrialReport(script=SCRIPT, mode=mode)
    lineups = _fetch(client, "lineups")
    formations = _fetch(client, "formations")
    substitutions = _fetch(client, "substitutions")

    starters = survey(lineups.records, STARTER_FIELDS)
    grid = survey(lineups.records, GRID_FIELDS)
    positions = survey(lineups.records, DETAILED_POSITION_FIELDS)
    formation_names = survey(formations.records, FORMATION_FIELDS)
    triples = substitution_triples(substitutions.records)

    # --- Objective 6: starters and substitutes -------------------------------
    shortfall_6 = _family_shortfall(lineups)
    reasons_6: list[str] = [shortfall_6] if shortfall_6 else []
    if lineups.present:
        if not starters.found:
            reasons_6.append(
                f"no lineup record carries any of the candidate starter fields "
                f"{STARTER_FIELDS}")
        elif len(starters.values) < 2:
            # One value across every record cannot separate two groups. Saying
            # so is the observation; guessing which group it is would not be.
            reasons_6.append(
                f"{starters.field} took one value across every record, so it "
                "does not partition the lineup")
        elif not starters.complete:
            reasons_6.append(
                f"{starters.covered}/{starters.total} record(s) carry {starters.field}")
    evidence_6 = (
        f"lineups: {len(lineups.records)} record(s); "
        f"partition field {starters.field or 'none found'} with "
        f"{len(starters.values)} distinct value(s)"
    )
    report.objectives.append(Objective(
        6, OBJECTIVE_6,
        OBSERVED if not reasons_6
        else (UNMET if not lineups.present or not starters.found else DEGRADED),
        evidence_6 if not reasons_6 else f"{evidence_6} — {'; '.join(reasons_6)}",
    ))

    # --- Objective 7: formation strings --------------------------------------
    shortfall_7 = _family_shortfall(formations)
    reasons_7: list[str] = [shortfall_7] if shortfall_7 else []
    if formations.present and not formation_names.found:
        reasons_7.append(
            f"no formation record carries any of {FORMATION_FIELDS}")
    elif formations.present and not formation_names.complete:
        reasons_7.append(
            f"{formation_names.covered}/{formation_names.total} record(s) carry "
            f"{formation_names.field}")
    evidence_7 = (
        f"formations: {len(formations.records)} record(s); "
        f"field {formation_names.field or 'none found'}; "
        f"{len(formation_names.values)} distinct value(s)"
    )
    report.objectives.append(Objective(
        7, OBJECTIVE_7,
        OBSERVED if not reasons_7
        else (UNMET if not formations.present or not formation_names.found else DEGRADED),
        evidence_7 if not reasons_7 else f"{evidence_7} — {'; '.join(reasons_7)}",
    ))

    # --- Objective 8: the formation grid -------------------------------------
    # The slice's whole risk. Reported, never asserted: a shape differing from
    # the documented one degrades with the shape recorded.
    reasons_8: list[str] = [shortfall_6] if shortfall_6 else []
    if lineups.present:
        if not grid.found:
            reasons_8.append(
                f"no lineup record carries any of the candidate grid fields "
                f"{GRID_FIELDS}")
        else:
            if not grid.complete:
                reasons_8.append(
                    f"{grid.covered}/{grid.total} record(s) carry {grid.field}")
            unexpected = tuple(s for s in grid.shapes if s != DOCUMENTED_GRID_SHAPE)
            if unexpected:
                reasons_8.append(
                    f"{grid.field} arrived as {','.join(unexpected)} where the "
                    f"documentation gives {DOCUMENTED_GRID_SHAPE}; recorded, not rejected")
    evidence_8 = (
        f"grid field {grid.field or 'none found'}; "
        f"shape(s) {','.join(grid.shapes) if grid.shapes else 'none'}; "
        f"{grid.covered}/{grid.total} record(s)"
    )
    report.objectives.append(Objective(
        8, OBJECTIVE_8,
        OBSERVED if not reasons_8
        else (UNMET if not lineups.present or not grid.found else DEGRADED),
        evidence_8 if not reasons_8 else f"{evidence_8} — {'; '.join(reasons_8)}",
    ))

    # --- Objective 9: detailed position identifiers --------------------------
    reasons_9: list[str] = [shortfall_6] if shortfall_6 else []
    if lineups.present:
        if not positions.found:
            reasons_9.append(
                f"no lineup record carries any of the candidate detailed-position "
                f"fields {DETAILED_POSITION_FIELDS}")
        elif not positions.complete:
            reasons_9.append(
                f"{positions.covered}/{positions.total} record(s) carry {positions.field}")
    evidence_9 = (
        f"detailed-position field {positions.field or 'none found'}; "
        f"{positions.covered}/{positions.total} record(s); "
        f"{len(positions.values)} distinct value(s)"
    )
    report.objectives.append(Objective(
        9, OBJECTIVE_9,
        OBSERVED if not reasons_9
        else (UNMET if not lineups.present or not positions.found else DEGRADED),
        evidence_9 if not reasons_9 else f"{evidence_9} — {'; '.join(reasons_9)}",
    ))

    # --- Objective 10: substitution relationships and minutes ----------------
    shortfall_10 = _family_shortfall(substitutions)
    reasons_10: list[str] = [shortfall_10] if shortfall_10 else []
    incomplete = tuple(triple for triple in triples if not triple.complete)
    if substitutions.present and incomplete:
        reasons_10.append(
            f"{len(incomplete)} of {len(triples)} substitution(s) are missing one "
            "of (player_off, player_on, minute)")
    evidence_10 = (
        f"substitutions: {len(triples)} triple(s) "
        f"(player_off, player_on, minute); "
        f"{len(triples) - len(incomplete)} complete"
    )
    report.objectives.append(Objective(
        10, OBJECTIVE_10,
        OBSERVED if not reasons_10
        else (UNMET if not substitutions.present else DEGRADED),
        evidence_10 if not reasons_10 else f"{evidence_10} — {'; '.join(reasons_10)}",
    ))

    for result in (lineups, formations, substitutions):
        if result.records:
            report.observed_shapes.append(ObservedShape(result.family, result.render()))

    if lineups.records:
        # Second branch, all three: see DECLARED_SHAPES. Each reports the field
        # and the distribution; none names what a value means.
        report.observed_shapes.append(ObservedShape(
            "starter_marker",
            f"field={starters.field or 'none found'}; "
            f"values{{{','.join(f'{value}:{count}' for value, count in starters.values)}}}; "
            f"{starters.covered}/{starters.total} record(s)",
        ))
        report.observed_shapes.append(ObservedShape(
            "formation_grid",
            f"field={grid.field or 'none found'}; "
            f"shape={'|'.join(grid.shapes) if grid.shapes else 'none'}; "
            f"documented={DOCUMENTED_GRID_SHAPE}; "
            f"{grid.covered}/{grid.total} record(s)",
        ))
        report.observed_shapes.append(ObservedShape(
            "detailed_position",
            f"field={positions.field or 'none found'}; "
            f"{positions.covered}/{positions.total} record(s); "
            f"{len(positions.values)} distinct value(s)",
        ))

    if substitutions.records:
        out_field = first_present(substitutions.records[0], SUBSTITUTION_OUT_FIELDS)
        in_field = first_present(substitutions.records[0], SUBSTITUTION_IN_FIELDS)
        report.observed_shapes.append(ObservedShape(
            "substitution_direction",
            f"off={out_field[0] if out_field else 'none found'}; "
            f"on={in_field[0] if in_field else 'none found'}; "
            f"first={triples[0].render() if triples else 'none'}",
        ))

    if mode == MODE_MOCK:
        report.warnings.append(SYNTHETIC_WARNING)
    report.warnings.append(
        "mock mode: shapes are documentation-derived and carry "
        '"status": "unverified_against_live" until FI-9'
        if mode == MODE_MOCK else
        "live mode: shapes are as received from the provider"
    )
    report.warnings.append(
        "grid semantics are not decided here: §14.3 question 13 is open, and "
        "this report describes the value's structure only"
    )
    return report


OBJECTIVE_TITLES = (
    (6, OBJECTIVE_6), (7, OBJECTIVE_7), (8, OBJECTIVE_8),
    (9, OBJECTIVE_9), (10, OBJECTIVE_10),
)


def _report_with(mode: str, status: str, reason: str) -> TrialReport:
    report = TrialReport(script=SCRIPT, mode=mode)
    for objective_id, title in OBJECTIVE_TITLES:
        report.objectives.append(Objective(objective_id, title, status, reason))
    report.warnings.append(reason)
    return report


def _unmet_report(mode: str, reason: str) -> TrialReport:
    """Nothing was reached, so nothing was observed."""
    return _report_with(mode, UNMET, reason)


# No `_degraded_report`: `_fetch` turns every family-scoped provider error into
# that family's observation and re-raises the two that are not, so no generic
# provider branch is enterable. Same reasoning as `trial_entities`,
# `trial_injuries`, `trial_squads`, and `trial_mapping`.


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

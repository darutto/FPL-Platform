"""FI-8 trial acceptance script: injuries, suspensions, and coach records.

Covers brief §11.3 objectives 11 (injuries and suspensions) and 12 (coaches and
manager records).

TWO PLAN CONFLICTS, RESOLVED HERE AND RECORDED
----------------------------------------------
1. **"Three separately-statused objectives" vs. two objective ids.** The S5 DoD
   asks for injuries, suspensions, and coaches to be *separately statused*; the
   brief gives injuries-and-suspensions a single id (11) and coaches another
   (12), and `TRIAL_STATUS.md` has two rows. Minting an id 11b would break the
   20-objective map the dashboard and the coverage table both key on.

   Resolved by satisfying the DoD's *purpose* at the observation level: injuries
   and suspensions are observed, shaped, and evidenced **separately**, and
   objective 11 takes the **worse** of the two statuses. The failure the DoD
   guards against — suspensions absent, hidden behind injuries present — cannot
   occur: objective 11 cannot read `observed` unless both did, and the evidence
   names which one fell short.

2. **Freshness timestamps are not in the corpus.** DoD item 2 requires every
   injury record to carry a freshness timestamp and a record without one to be
   reported `degraded` — but `endpoint_payloads.json`'s injury record has no
   time field at all, so a faithful mock run would degrade, against standing DoD
   item 2's requirement that every script exits 0 on `--mock`.

   Resolved the way S3 resolved its cross-competition gap: mock mode synthesizes
   the field and **says so in a warning that travels with the report**. What is
   emphatically *not* done is assuming which field the provider uses — that is
   an open trial question (§17), so the script **searches a candidate list and
   reports which name actually supplied the value**. The candidate list is an
   input, like an endpoint path. Which one FI-9 finds is the observation.

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

SCRIPT = "trial_injuries"
OBJECTIVE_11 = "Injuries and suspensions"
OBJECTIVE_12 = "Coaches and manager records"

#: Field names searched, in order, for an injury record's freshness stamp. An
#: **input**, not a claim about the provider: §12's degradation matrix needs a
#: timestamp and the documentation does not say which field carries one, so the
#: script reports the name it found rather than asserting the name it expected.
#: A record matching none of these is stale-unknown and degrades — never
#: defaulted to fresh, which is the reading that would silently grant full
#: confidence to an injury record of unknown age.
FRESHNESS_FIELDS: tuple[str, ...] = (
    "updated_at", "last_updated", "modified_at", "timestamp",
)

#: Emitted whenever mock mode supplied a freshness field the corpus lacks.
SYNTHETIC_WARNING = (
    "injury freshness timestamps were synthesized for the rehearsal; "
    "the field name the provider actually uses is unverified until FI-9"
)

#: Standing DoD items 10 and 11, per entry.
#:
#: `injuries`, `suspensions` and `coaches` are under item 10's **first** branch:
#: each exists only when that family returned records, so an absent family is
#: visible as a missing entry *and* a non-`observed` objective.
#:
#: `injury_freshness` is under the **second** branch — existence is the
#: observation. It is emitted whenever injury records arrived, including when no
#: candidate field was found, because "these records carry no freshness field"
#: is the single most decision-relevant thing this script can report: §12 would
#: otherwise apply a confidence penalty against a timestamp nobody checked for.
DECLARED_SHAPES = {
    "injuries": (
        "test_each_family_shape_reports_the_fields_that_arrived",
        "test_an_absent_family_drops_its_shape_and_blocks_the_objective",
    ),
    "suspensions": (
        "test_each_family_shape_reports_the_fields_that_arrived",
        "test_an_absent_family_drops_its_shape_and_blocks_the_objective",
    ),
    "coaches": (
        "test_each_family_shape_reports_the_fields_that_arrived",
        "test_an_absent_family_drops_its_shape_and_blocks_the_objective",
    ),
    "injury_freshness": (
        "test_the_freshness_entry_names_the_field_that_supplied_the_value",
        "test_records_with_no_freshness_field_are_reported_not_defaulted_to_fresh",
    ),
}


@dataclass(frozen=True)
class FamilyResult:
    family: str
    records: tuple[Any, ...]
    failure: str = ""

    @property
    def present(self) -> bool:
        return bool(self.records) and not self.failure

    def render(self) -> str:
        """Record field names as the provider sent them, first record's order
        kept; fields only some records carry appended after `+`."""
        if not self.records:
            return f"none; {self.failure}" if self.failure else "none"
        first = tuple(self.records[0].raw_fields)
        extra = sorted({key for r in self.records for key in r.raw_fields} - set(first))
        rendered = ",".join(first)
        body = f"{rendered}+{','.join(extra)}" if extra else rendered
        return f"{len(self.records)} record(s); record{{{body}}}"


def freshness_of(record: Any) -> tuple[str, Any] | None:
    """The first candidate field this record actually carries, with its value.

    `None` — not a default timestamp — when the record carries no candidate.
    """
    for name in FRESHNESS_FIELDS:
        value = record.raw_fields.get(name)
        if value is not None:
            return name, value
    return None


def _with_synthetic_freshness(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Give each injury record a freshness field the corpus does not ship.

    Uses the **first** candidate name, and the report says which name it found —
    so if this synthesis is ever mistaken for evidence, the warning and the
    reported field name are both there to contradict it.
    """
    field = FRESHNESS_FIELDS[0]
    return {"data": [
        {**record, field: "2026-08-09T12:00:00Z"} for record in payload["data"]
    ]}


def mock_transport(
    *,
    injuries: Any | None = None,
    suspensions: Any | None = None,
    coaches: Any | None = None,
) -> EndpointReplayTransport:
    """Replay the checked-in payloads for the three families this script reads.

    Each override takes a payload or an `Exception`, so the tests can prove an
    absent or refusing family changes the objective rather than only a count.
    """
    payloads = load_fixture("endpoint_payloads.json")["families"]
    chosen = {
        "injuries": _with_synthetic_freshness(payloads["injuries"])
        if injuries is None else injuries,
        "suspensions": payloads["suspensions"] if suspensions is None else suspensions,
        "coaches": payloads["coaches"] if coaches is None else coaches,
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
        # here would report a rejected token as "this family has no records".
        raise
    except SportmonksError as exc:
        return FamilyResult(family, (), type(exc).__name__)


def collect(client, mode: str) -> TrialReport:
    report = TrialReport(script=SCRIPT, mode=mode)
    injuries = _fetch(client, "injuries")
    suspensions = _fetch(client, "suspensions")
    coaches = _fetch(client, "coaches")

    stamped = tuple(r for r in injuries.records if freshness_of(r) is not None)
    unstamped = len(injuries.records) - len(stamped)
    fields_used = tuple(sorted({freshness_of(r)[0] for r in stamped}))

    # --- Objective 11: injuries and suspensions, observed separately ---------
    missing_11: list[str] = []
    for result in (injuries, suspensions):
        if result.failure:
            missing_11.append(f"{result.family} request failed: {result.failure}")
        elif not result.records:
            missing_11.append(f"no {result.family} record returned")
    if injuries.present and unstamped:
        missing_11.append(
            f"{unstamped} of {len(injuries.records)} injury record(s) carry none of "
            f"the candidate freshness fields {FRESHNESS_FIELDS}"
        )

    # `degraded` and `unmet` are different facts: records that arrived without a
    # usable timestamp are a partial observation, a family that returned nothing
    # is not an observation at all. Collapsing them would let a §12 reader treat
    # "we have no injuries data" and "we have injuries of unknown age" alike.
    absent = any(not result.present for result in (injuries, suspensions))
    evidence_11 = (
        f"injuries: {len(injuries.records)} record(s), "
        f"{len(stamped)} with a freshness field "
        f"[{','.join(fields_used) if fields_used else 'none found'}]; "
        f"suspensions: {len(suspensions.records)} record(s)"
    )
    report.objectives.append(Objective(
        11, OBJECTIVE_11,
        OBSERVED if not missing_11 else (UNMET if absent else DEGRADED),
        evidence_11 if not missing_11 else f"{evidence_11} — {'; '.join(missing_11)}",
    ))

    # --- Objective 12: coaches and manager records ---------------------------
    missing_12: list[str] = []
    if coaches.failure:
        missing_12.append(f"coaches request failed: {coaches.failure}")
    elif not coaches.records:
        missing_12.append("no coach record returned")
    evidence_12 = f"coaches: {len(coaches.records)} record(s)"
    report.objectives.append(Objective(
        12, OBJECTIVE_12,
        OBSERVED if not missing_12 else UNMET,
        evidence_12 if not missing_12 else f"{evidence_12} — {'; '.join(missing_12)}",
    ))

    for result in (injuries, suspensions, coaches):
        if result.records:
            report.observed_shapes.append(ObservedShape(result.family, result.render()))

    if injuries.records:
        # Second branch: emitted even when nothing was found, because "no
        # freshness field on any record" is the observation §12 most needs.
        report.observed_shapes.append(ObservedShape(
            "injury_freshness",
            f"field={','.join(fields_used) if fields_used else 'none found'}; "
            f"{len(stamped)}/{len(injuries.records)} record(s) stamped",
        ))

    if mode == MODE_MOCK:
        report.warnings.append(SYNTHETIC_WARNING)
    report.warnings.append(
        "mock mode: shapes are documentation-derived and carry "
        '"status": "unverified_against_live" until FI-9'
        if mode == MODE_MOCK else
        "live mode: shapes are as received from the provider"
    )
    return report


def _report_with(mode: str, status: str, reason: str) -> TrialReport:
    report = TrialReport(script=SCRIPT, mode=mode)
    report.objectives.append(Objective(11, OBJECTIVE_11, status, reason))
    report.objectives.append(Objective(12, OBJECTIVE_12, status, reason))
    report.warnings.append(reason)
    return report


def _unmet_report(mode: str, reason: str) -> TrialReport:
    """Nothing was reached, so nothing was observed."""
    return _report_with(mode, UNMET, reason)


# No `_degraded_report`: `_fetch` turns every family-scoped provider error into
# that family's observation and re-raises the two that are not, so no generic
# provider branch is enterable. Same reasoning as `trial_entities`.


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

"""FI-8 trial acceptance script: entity discovery across all endpoint families.

Covers brief §11.3 objective 1 (competition and season identifiers) and sweeps
every family in `ENDPOINTS` so FI-9 day 1 has a single artifact saying which
parts of the API answered at all.

The sweep is deliberately wider than the objective. Objective 1 needs `leagues`
and `seasons`; the other thirteen families are swept because the cheapest thing
to learn on trial day 1 is *which endpoints exist for us* — a family that is
unavailable on the Starter plan is a plan-revision input (§17), and finding it
on day 1 is worth far more than finding it in S5.

WHAT IS AN INPUT AND WHAT IS AN OBSERVATION
-------------------------------------------
`COMPETITION_NAME` is an input: it is the term the sweep searches by, the same
way an endpoint path is an input. The provider's **id** for it is the
observation, which is why no league id appears anywhere in this file. A script
that hardcoded `8` would report "Premier League resolved to 8" from a payload
that said nothing of the kind — the defect S2 was rejected for three times.

`--mock` is the default and is the only mode that runs before FI-9.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    COMPETITION_NAME, EXIT_CONFIG, EXIT_REFUSED, MODE_MOCK, OBSERVED,
    UNMET, EndpointReplayTransport, Objective, ObservedShape, TrialRefusal,
    TrialReport, build_parser, load_fixture, make_client, match_by_name,
    resolve_mode, response, write_report,
)
from sportmonks_client.client import ENDPOINTS  # noqa: E402
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
)

SCRIPT = "trial_entities"
OBJECTIVE_1 = "Competition and season identifiers"

#: Per-family outcomes. Three values, not two: `empty` (the provider answered
#: and had nothing) and `unavailable` (the provider did not answer) are
#: different facts about the trial, and collapsing them would hide a plan
#: unavailable to us behind "no data yet".
REACHABLE = "reachable"
EMPTY = "empty"
UNAVAILABLE = "unavailable"

#: Standing DoD items 10 and 11, per entry.
#:
#: Every entry here is under item 10's **second** branch —
#: existence-is-the-observation. One entry is emitted per family swept,
#: including families that failed, because "this family did not answer" is the
#: observation FI-9 most needs and an omitted entry is indistinguishable from a
#: family nobody swept. The falsifiability obligation therefore falls entirely
#: on the entry's *content*: the named tests feed families with different data
#: and assert the rendered entries are pairwise different, by `==`.
DECLARED_SHAPES = {
    "family:*": (
        "test_each_family_entry_reports_the_count_and_ids_that_family_returned",
        "test_the_three_family_states_are_not_interchangeable",
    ),
}


@dataclass(frozen=True)
class FamilyResult:
    """One family as actually swept. `records` stays out of the report."""

    family: str
    state: str
    count: int
    provider_ids: tuple[int, ...]
    failure: str = ""
    records: tuple[Any, ...] = field(default=(), repr=False)

    def render(self) -> str:
        """The reported line. Derived from what came back, never from the
        family name — two families with different payloads must render
        differently or the entry is decoration (standing DoD item 11)."""
        ids = ",".join(str(value) for value in self.provider_ids)
        line = f"{self.state}; {self.count} record(s); provider_ids={{{ids}}}"
        return f"{line}; {self.failure}" if self.failure else line


def mock_transport(*, families: Mapping[str, Any] | None = None) -> EndpointReplayTransport:
    """Replay the checked-in per-family payloads.

    `families` overrides individual families, which is how the tests swap in
    `edge_cases.json`'s empty envelope or a provider error and prove the sweep
    reports what it met rather than what the corpus usually contains.
    """
    payloads = load_fixture("endpoint_payloads.json")["families"]
    overrides = dict(families or {})
    mapping: dict[str, Any] = {}
    for family, (endpoint, _model) in ENDPOINTS.items():
        if family in overrides:
            item = overrides[family]
            mapping[endpoint] = item if isinstance(item, Exception) else response(item)
        else:
            mapping[endpoint] = response(payloads[family])
    return EndpointReplayTransport(mapping)


def sweep(client) -> dict[str, FamilyResult]:
    """Walk every family in `ENDPOINTS` and record what each one did."""
    results: dict[str, FamilyResult] = {}
    for family in ENDPOINTS:
        try:
            records = tuple(client.iter_entities(family))
        except (SportmonksConfigurationError, SportmonksAuthenticationError):
            # NOT an observation about this family. Both are subclasses of
            # SportmonksError, so the broad catch below swallowed them: a 401 on
            # the first call was reported as "leagues unavailable" and the run
            # exited 1. With every family 401ing, the report would have read
            # "15 families unavailable" — indistinguishable from a Starter plan
            # that carries none of these endpoints, on the day that question is
            # being answered. Measured, not reasoned: seeded a 401 and got
            # exit 1 where the frozen contract requires exit 3.
            raise
        except SportmonksError as exc:
            # An unavailable family is an observation, not a crash. The sweep
            # continues: learning that fourteen families answer and one does not
            # is the artifact; aborting on the first failure yields nothing.
            results[family] = FamilyResult(family, UNAVAILABLE, 0, (), type(exc).__name__)
            continue
        ids = tuple(sorted({record.provider_id for record in records}))
        results[family] = FamilyResult(
            family, REACHABLE if records else EMPTY, len(records), ids, records=records,
        )
    return results


def collect(client, mode: str) -> TrialReport:
    report = TrialReport(script=SCRIPT, mode=mode)
    results = sweep(client)

    matched = match_by_name(results["leagues"].records, COMPETITION_NAME)
    league_ids = tuple(sorted({record.provider_id for record in matched}))
    seasons = tuple(
        record for record in results["seasons"].records
        if record.raw_fields.get("league_id") in league_ids
    )
    season_ids = tuple(sorted({record.provider_id for record in seasons}))

    missing: list[str] = []
    if not matched:
        missing.append(f"no league reported a name containing {COMPETITION_NAME!r}")
    elif len(matched) > 1:
        # Reported, never resolved by picking one. Which of two same-named
        # competitions is the right one is a question for the provider (§17),
        # not something a script may decide by taking the first.
        missing.append(f"{len(matched)} leagues matched {COMPETITION_NAME!r}: {league_ids}")
    if matched and not seasons:
        missing.append(f"no season carried a league_id in {league_ids}")

    states = {state: sorted(r.family for r in results.values() if r.state == state)
              for state in (REACHABLE, EMPTY, UNAVAILABLE)}
    evidence = (
        f"{COMPETITION_NAME} resolved to league_ids={league_ids or '()'}; "
        f"season_ids={season_ids or '()'}; "
        f"swept {len(results)} families: "
        f"{len(states[REACHABLE])} reachable, {len(states[EMPTY])} empty, "
        f"{len(states[UNAVAILABLE])} unavailable"
    )
    report.objectives.append(Objective(
        1, OBJECTIVE_1,
        OBSERVED if not missing else UNMET,
        evidence if not missing else f"{evidence} — {'; '.join(missing)}",
    ))

    for family, result in results.items():
        report.observed_shapes.append(ObservedShape(f"family:{family}", result.render()))

    if states[UNAVAILABLE]:
        # A warning, not an objective failure: objective 1 is about competition
        # and season identifiers, and a squad endpoint that refuses says nothing
        # about those. It is the loudest thing in the report all the same.
        report.warnings.append(
            f"families that did not answer: {', '.join(states[UNAVAILABLE])}"
        )
    if states[EMPTY]:
        report.warnings.append(
            f"families that answered with no records: {', '.join(states[EMPTY])}"
        )

    report.warnings.append(
        "mock mode: shapes are documentation-derived and carry "
        '"status": "unverified_against_live" until FI-9'
        if mode == MODE_MOCK else
        "live mode: shapes are as received from the provider"
    )
    return report


def _report_with(mode: str, status: str, reason: str) -> TrialReport:
    report = TrialReport(script=SCRIPT, mode=mode)
    report.objectives.append(Objective(1, OBJECTIVE_1, status, reason))
    report.warnings.append(reason)
    return report


def _unmet_report(mode: str, reason: str) -> TrialReport:
    """Nothing was reached, so nothing was observed."""
    return _report_with(mode, UNMET, reason)


# There is deliberately no `_degraded_report` here, unlike `trial_auth.py`.
# `sweep` turns every provider error that is *about a family* into that family's
# observation, and re-raises the two that are not, which `main` handles
# explicitly. Nothing can therefore reach a generic provider branch. A handler
# no input can enter would need a test no input can write — which is how
# unfalsifiable assertions get authored in the first place.


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

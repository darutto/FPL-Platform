"""FI-8 trial acceptance script: fixtures, in-competition and cross-competition.

Covers brief §11.3 objectives 2 (Premier League fixtures for a season) and 3
(fixtures for Premier League clubs in other competitions).

WHY THE TWO OBJECTIVES ARE NEVER MERGED
---------------------------------------
They are answered by two different requests with two different parameter shapes:
objective 2 filters by competition and season, objective 3 filters by team and
deliberately does *not* filter by competition. A script that fetched once and
reported both from the same records would report objective 3 as observed on the
strength of a payload that could not contain a cross-competition fixture at all.
They are therefore statused separately, and the report records the parameters
each observation came from.

WHAT MOCK MODE CAN AND CANNOT REHEARSE
--------------------------------------
The checked-in corpus contains a single fixture in a single competition, so the
cross-competition case has no fixture to rehearse against. Mock mode synthesizes
one — derived from the checked-in record, with a competition id chosen to be
distinct from every id the corpus contains — and says so in a warning that
travels with the report. That is the honest shape: a rehearsal of the reporting
path, not evidence about the provider. Objective 3 is answered for real in FI-9.

`--mock` is the default and is the only mode that runs before FI-9.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    COMPETITION_NAME, DEGRADED, EXIT_CONFIG, EXIT_REFUSED, MODE_MOCK, OBSERVED,
    UNMET, EndpointReplayTransport, Objective, ObservedShape, TrialRefusal,
    TrialReport, build_parser, load_fixture, make_client, match_by_name,
    render_skeleton, resolve_mode, response, write_report,
)
from sportmonks_client.client import ENDPOINTS  # noqa: E402
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
)

SCRIPT = "trial_fixtures"
OBJECTIVE_2 = "Premier League fixtures"
OBJECTIVE_3 = "Cross-competition fixtures for Premier League clubs"

#: Warning emitted whenever the cross-competition observation came from a
#: synthesized payload rather than the provider. Named so a test can assert the
#: report carries it, and so a reader cannot mistake the rehearsal for evidence.
SYNTHETIC_WARNING = (
    "cross-competition fixtures were synthesized for the rehearsal; "
    "objective 3 is unverified against live until FI-9"
)

#: Standing DoD items 10 and 11, per entry.
#:
#: Both entries are under item 10's **first** branch: the entry exists only when
#: the corresponding request produced a response, so a run that never reached
#: the fixtures endpoint emits neither. Each named pair is one test proving the
#: content tracks the payload (two inputs, different expectations, `==`) and one
#: proving the entry disappears when the data is absent.
DECLARED_SHAPES = {
    "season_fixtures": (
        "test_the_season_shape_records_the_envelope_that_arrived",
        "test_a_run_that_never_reached_the_fixtures_endpoint_emits_no_shape",
    ),
    "cross_competition_fixtures": (
        "test_the_cross_competition_shape_records_the_envelope_that_arrived",
        "test_no_team_to_sweep_drops_the_cross_competition_shape",
    ),
}


@dataclass(frozen=True)
class FixtureSweep:
    """One fixtures request and what came back, with the parameters that
    produced it — an observation is not interpretable without them."""

    params: dict[str, Any]
    records: tuple[Any, ...]
    envelope: str
    failure: str = ""

    def league_ids(self) -> tuple[int, ...]:
        return tuple(sorted({
            record.raw_fields["league_id"] for record in self.records
            if record.raw_fields.get("league_id") is not None
        }))

    def season_ids(self) -> tuple[int, ...]:
        return tuple(sorted({
            record.raw_fields["season_id"] for record in self.records
            if record.raw_fields.get("season_id") is not None
        }))


def _record_shape(records: Sequence[Any]) -> str:
    """Field names as the provider actually sent them.

    The envelope skeleton alone renders `data` for every fixtures payload ever
    sent — true, and useless: `body_skeleton` does not descend into lists (#85,
    #92), so the record fields, which are the entire point of a fixtures
    observation, are dropped. They survive on the parsed records' `raw_fields`,
    which preserves the provider's keys, so that is what is reported.

    The first record's key order is kept as-is rather than sorted; the order a
    provider serialises in is itself an observation. Fields that appear on later
    records but not the first are appended after a `+`, because heterogeneous
    records within one payload is exactly the kind of surprise FI-9 needs told.
    """
    if not records:
        return ""
    first = tuple(records[0].raw_fields)
    extra = sorted({key for record in records for key in record.raw_fields} - set(first))
    rendered = ",".join(first)
    return f"{rendered}+{','.join(extra)}" if extra else rendered


def _synthesize_cross_competition(base: Mapping[str, Any]) -> dict[str, Any]:
    """A second fixture for the same club in a competition the corpus does not
    contain. The new competition id is derived as one past the largest id
    present, so it cannot silently collide with the resolved competition."""
    template = dict(base["data"][0])
    known = [
        record.get("league_id") for record in base["data"]
        if isinstance(record.get("league_id"), int)
    ]
    other = max(known) + 1 if known else 1
    return {"data": [template, {**template, "id": template["id"] + 1, "league_id": other}]}


def mock_transport(
    *,
    season_fixtures: Any | None = None,
    cross_fixtures: Any | None = None,
    teams: Any | None = None,
    leagues: Any | None = None,
) -> EndpointReplayTransport:
    """Replay the checked-in payloads, dispatching the two fixtures requests on
    their parameters rather than on call order.

    The overrides exist for the tests that prove this script observes: an empty
    envelope from `edge_cases.json` in either position must change the reported
    objective, not just a count.
    """
    payloads = load_fixture("endpoint_payloads.json")["families"]
    base = payloads["fixtures"]
    season_body = base if season_fixtures is None else season_fixtures
    cross_body = _synthesize_cross_competition(base) if cross_fixtures is None else cross_fixtures

    def _fixtures(params: Mapping[str, Any]):
        # `team_id` present and no `league_id` is objective 3's request; anything
        # else is objective 2's. Dispatching on the parameters is what lets the
        # script's call order change without silently re-labelling the results.
        if "team_id" in params and "league_id" not in params:
            return response(cross_body)
        return response(season_body)

    mapping: dict[str, Any] = {
        ENDPOINTS["fixtures"][0]: _fixtures,
        ENDPOINTS["leagues"][0]: response(payloads["leagues"] if leagues is None else leagues),
        ENDPOINTS["seasons"][0]: response(payloads["seasons"]),
        ENDPOINTS["teams"][0]: response(payloads["teams"] if teams is None else teams),
    }
    return EndpointReplayTransport(mapping)


def _fetch(client, params: Mapping[str, Any]) -> FixtureSweep:
    """One fixtures request, with the envelope it produced.

    The exchange slice is taken around this call rather than read from the end
    of the list, so the recorded envelope belongs to *this* request no matter
    what the script does before or after it.
    """
    before = len(client.transport.exchanges)
    try:
        records = tuple(client.iter_entities("fixtures", params=dict(params)))
        failure = ""
    except (SportmonksConfigurationError, SportmonksAuthenticationError):
        # Not a fact about this request. Both subclass SportmonksError, so the
        # broad catch below would report a rejected token as "this fixtures
        # query returned nothing" and exit 1 rather than 3. See the same
        # correction in `trial_entities.sweep`.
        raise
    except SportmonksError as exc:
        records = ()
        failure = type(exc).__name__
    exchanges = client.transport.exchanges[before:]
    envelope = render_skeleton(exchanges[-1].body_keys) if exchanges else ""
    if envelope and records:
        envelope = f"{envelope}; record{{{_record_shape(records)}}}"
    return FixtureSweep(dict(params), records, envelope, failure)


def collect(client, mode: str) -> TrialReport:
    report = TrialReport(script=SCRIPT, mode=mode)

    leagues = tuple(client.iter_entities("leagues"))
    matched = match_by_name(leagues, COMPETITION_NAME)
    league_ids = tuple(sorted({record.provider_id for record in matched}))
    seasons = tuple(
        record for record in client.iter_entities("seasons")
        if record.raw_fields.get("league_id") in league_ids
    )
    season_ids = tuple(sorted({record.provider_id for record in seasons}))

    # --- Objective 2: fixtures inside the competition, for one season ---------
    season_sweep: FixtureSweep | None = None
    missing_2: list[str] = []
    if not league_ids:
        missing_2.append(f"no league reported a name containing {COMPETITION_NAME!r}")
    elif not season_ids:
        missing_2.append(f"no season carried a league_id in {league_ids}")
    else:
        season_sweep = _fetch(
            client, {"league_id": league_ids[0], "season_id": season_ids[0]},
        )
        if season_sweep.failure:
            missing_2.append(f"fixtures request failed: {season_sweep.failure}")
        elif not season_sweep.records:
            missing_2.append("no fixture returned for the requested league and season")
        else:
            off_season = [
                record.provider_id for record in season_sweep.records
                if record.raw_fields.get("season_id") != season_ids[0]
            ]
            if off_season:
                missing_2.append(
                    f"{len(off_season)} fixture(s) carried a different season_id: {off_season}"
                )

    evidence_2 = (
        f"requested league_id={league_ids[0] if league_ids else 'none'}, "
        f"season_id={season_ids[0] if season_ids else 'none'}; "
        f"{len(season_sweep.records) if season_sweep else 0} fixture(s); "
        f"season_ids returned={season_sweep.season_ids() if season_sweep else ()}; "
        f"league_ids returned={season_sweep.league_ids() if season_sweep else ()}"
    )
    report.objectives.append(Objective(
        2, OBJECTIVE_2,
        OBSERVED if not missing_2 else UNMET,
        evidence_2 if not missing_2 else f"{evidence_2} — {'; '.join(missing_2)}",
    ))

    # --- Objective 3: fixtures for those clubs *outside* the competition ------
    teams = tuple(client.iter_entities("teams")) if league_ids else ()
    team_sweeps: list[FixtureSweep] = [
        _fetch(client, {"team_id": team.provider_id}) for team in teams
    ]
    outside = tuple(sorted({
        league_id for sweep in team_sweeps for league_id in sweep.league_ids()
        if league_id not in league_ids
    }))
    inside = tuple(sorted({
        league_id for sweep in team_sweeps for league_id in sweep.league_ids()
        if league_id in league_ids
    }))
    fetched = sum(len(sweep.records) for sweep in team_sweeps)

    missing_3: list[str] = []
    if not teams:
        missing_3.append("no team was resolved to sweep")
    elif any(sweep.failure for sweep in team_sweeps):
        failed = [sweep.failure for sweep in team_sweeps if sweep.failure]
        missing_3.append(f"{len(failed)} team fixture request(s) failed: {sorted(set(failed))}")
    elif not fetched:
        missing_3.append("no fixture returned for any swept team")
    elif not outside:
        missing_3.append(
            f"every fixture returned sat inside the requested competition {league_ids}"
        )

    evidence_3 = (
        f"swept {len(team_sweeps)} team(s) by team_id with no competition filter; "
        f"{fetched} fixture(s); competitions inside={inside}, outside={outside}"
    )
    report.objectives.append(Objective(
        3, OBJECTIVE_3,
        OBSERVED if not missing_3 else UNMET,
        evidence_3 if not missing_3 else f"{evidence_3} — {'; '.join(missing_3)}",
    ))

    # --- Shapes: only what a response actually produced -----------------------
    if season_sweep is not None and season_sweep.envelope:
        report.observed_shapes.append(
            ObservedShape("season_fixtures", season_sweep.envelope)
        )
    cross_envelopes = [sweep.envelope for sweep in team_sweeps if sweep.envelope]
    if cross_envelopes:
        report.observed_shapes.append(
            ObservedShape("cross_competition_fixtures", cross_envelopes[0])
        )

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
    report.objectives.append(Objective(2, OBJECTIVE_2, status, reason))
    report.objectives.append(Objective(3, OBJECTIVE_3, status, reason))
    report.warnings.append(reason)
    return report


def _unmet_report(mode: str, reason: str) -> TrialReport:
    """Nothing was reached, so neither objective was observed."""
    return _report_with(mode, UNMET, reason)


def _degraded_report(mode: str, reason: str) -> TrialReport:
    """The provider was reached and misbehaved: a partial observation."""
    return _report_with(mode, DEGRADED, reason)


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
    except SportmonksError as exc:
        failure = f"PROVIDER: {type(exc).__name__}"
        report = _degraded_report(mode, f"provider error: {type(exc).__name__}")

    json_path, md_path = write_report(report, args.out)
    if failure is not None:
        print(failure)
    print(f"{SCRIPT}: mode={report.mode} report={json_path} markdown={md_path}")
    return EXIT_CONFIG if config_failure else report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())

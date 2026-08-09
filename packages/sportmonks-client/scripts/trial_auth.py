"""FI-8 trial acceptance script: authentication, rate limits, and pagination.

Covers brief §11.3 objective 17 (API rate limits and pagination) and proves the
`SPORTMONKS_API_TOKEN` wiring required by plan §14.1 -- token absent degrades
cleanly, dummy token surfaces the auth-failure path, and neither leaks the token
into the report.

Everything this script reports is read from the responses it actually received,
via `ObservingTransport`. Nothing about the provider is stated as a literal: if
the rate-limit headers are absent, the objective degrades and the shape entry
does not appear. That is standing DoD item 10, and it exists because the first
version of this file claimed "rate-limit headers observed" from a hardcoded
string that survived deleting every header from the payload.

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
    load_fixture, make_client, observed_pagination, observed_rate_limit_fields,
    observed_retry_after, observed_throttles, render_skeleton, resolve_mode,
    response, write_report,
)
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
    SportmonksSchemaError,
)

SCRIPT = "trial_auth"
OBJECTIVE_17 = "API rate limits and pagination"


#: The full documented rate-limit header set. Tests select subsets of it to
#: prove the reported fields track the payload rather than this constant:
#: an all-or-nothing switch cannot distinguish "reports what arrived" from
#: "reports the canonical set whenever anything arrived" (standing DoD item 11).
RATE_LIMIT_HEADERS = {
    "X-RateLimit-Limit": "3000",
    "X-RateLimit-Remaining": "2997",
    "X-RateLimit-Reset": "3600",
}


def mock_transport(
    *,
    rate_limit_headers: bool | Sequence[str] = True,
    throttle: bool | int = True,
    retry_after: bool | str = True,
    pagination: bool = True,
) -> ReplayTransport:
    """Replay the checked-in multi-page fixture.

    The keyword arguments exist for the tests that prove this script observes
    rather than asserts: with `rate_limit_headers=False` the objective must
    degrade and the shape entry must disappear, and with a *subset* of header
    names the entry must name that subset and nothing more.

    `rate_limit_headers` takes `True` (all), `False` (none), or the header
    names to serve. `retry_after` takes `True` (the default `2`), `False`
    (header omitted), or the literal value to send. `throttle` takes `True`
    (one 429), `False` (none), or how many to serve -- a count above one is
    what distinguishes a derived throttle tally from `1 if any else 0`, which
    survived a seeding probe of the two-input version.
    """
    pages = load_fixture("multi_page.json")["pages"]
    if rate_limit_headers is True:
        headers = dict(RATE_LIMIT_HEADERS)
    elif rate_limit_headers is False:
        headers = {}
    else:
        headers = {name: RATE_LIMIT_HEADERS[name] for name in rate_limit_headers}
    if not pagination:
        pages = [{"data": page["data"]} for page in pages[:1]]
    served: list[object] = []
    if throttle is not False:
        # Synthetic 429s, ahead of page one. The client retries them; the
        # observation is of the real header the provider would send. `retry_after`
        # can be turned off to prove a throttle with no header is still counted.
        throttle_headers = dict(headers)
        if retry_after is not False:
            throttle_headers["Retry-After"] = "2" if retry_after is True else retry_after
        count = 1 if throttle is True else throttle
        served += [response({}, status=429, headers=throttle_headers) for _ in range(count)]
    served += [response(page, headers=headers if index == 0 else {}) for index, page in enumerate(pages)]
    return ReplayTransport(served)


def collect(client, mode: str) -> TrialReport:
    """Build the report from what the transport actually saw."""
    report = TrialReport(script=SCRIPT, mode=mode)
    rejection: str | None = None
    try:
        records = tuple(client.iter_entities("leagues"))
    except SportmonksSchemaError as exc:
        # A payload that differs from the documented shape is the single thing
        # FI-8 exists to rehearse (§17's top risk: "Sportmonks docs != live
        # payloads"). The frozen contract is explicit that a script "must not
        # fail merely because a payload differs from the documented shape; it
        # records the difference and marks the objective degraded". The response
        # is already in `exchanges`, so the skeleton survives the rejection.
        rejection = str(exc) or type(exc).__name__
        records = ()
    exchanges = client.transport.exchanges

    pages_walked = sum(1 for exchange in exchanges if exchange.status == 200)
    rate_fields = observed_rate_limit_fields(exchanges)
    page_location, page_fields = observed_pagination(exchanges)
    throttles = observed_throttles(exchanges)
    retry_afters = observed_retry_after(exchanges)

    missing = []
    if rejection is not None:
        missing.append(f"payload rejected by the parser: {rejection}")
    if pages_walked <= 1:
        missing.append(f"pagination did not advance beyond {pages_walked} page(s)")
    if page_location is None:
        missing.append("no pagination metadata on any response")
    elif not page_fields:
        missing.append(f"{page_location} block present but carried no field names")
    if not rate_fields:
        missing.append("no rate-limit headers present on any response")
    if throttles and not retry_afters:
        missing.append(f"{len(throttles)} throttled response(s) carried no Retry-After")

    evidence = (
        f"walked {pages_walked} pages, {len(records)} records; "
        f"pagination at: {page_location or 'none'}; "
        f"rate-limit fields seen: {', '.join(rate_fields) if rate_fields else 'none'}; "
        f"throttled responses: {len(throttles)} (with Retry-After: {len(retry_afters)})"
    )
    report.objectives.append(Objective(
        17, OBJECTIVE_17,
        OBSERVED if not missing else DEGRADED,
        evidence if not missing else f"{evidence} — {'; '.join(missing)}",
    ))

    # Shapes are recorded only when found, and describe what was found -- the
    # block's actual location and the fields it actually carried. An
    # unconditional entry is an assertion wearing an observation's name
    # (standing DoD item 10).
    if page_location is not None:
        report.observed_shapes.append(ObservedShape(
            "pagination", f"envelope.{page_location}{{{','.join(page_fields)}}}",
        ))
    if rejection is not None and exchanges:
        # The payload the parser refused, recorded rather than discarded. This is
        # the observation FI-9 most needs on day one.
        report.observed_shapes.append(ObservedShape(
            "rejected_envelope", render_skeleton(exchanges[-1].body_keys),
        ))
    if rate_fields:
        report.observed_shapes.append(ObservedShape("rate_limit_headers", ", ".join(rate_fields)))
    if retry_afters:
        report.observed_shapes.append(ObservedShape(
            "retry_after",
            "; ".join(f"HTTP {status} retry-after={value}" for status, value in retry_afters),
        ))
    elif not throttles:
        report.warnings.append("no throttled response observed; retry pacing is unmeasured")

    report.warnings.append(
        "mock mode: shapes are documentation-derived and carry "
        '"status": "unverified_against_live" until FI-9'
        if mode == MODE_MOCK else
        "live mode: shapes are as received from the provider"
    )
    return report


def _report_with(mode: str, status: str, reason: str) -> TrialReport:
    """A report is still written on the failure paths, so the token-leak check
    has real bytes to assert against and the run leaves an evidence pointer."""
    report = TrialReport(script=SCRIPT, mode=mode)
    report.objectives.append(Objective(17, OBJECTIVE_17, status, reason))
    report.warnings.append(reason)
    return report


def _unmet_report(mode: str, reason: str) -> TrialReport:
    """The run never reached the provider, so nothing was observed at all --
    `unmet`, not partially observed. This keeps the frozen status S3 depends on
    exercised rather than merely declared."""
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
        # Token absent. Degrade cleanly -- never a traceback, never a partial fetch.
        failure = f"CONFIG: {type(exc).__name__}"
        config_failure = True
        report = _unmet_report(mode, "configuration incomplete; no request was issued")
    except SportmonksAuthenticationError as exc:
        # Dummy or rejected token. The error is already secret-safe.
        failure = f"AUTH: {type(exc).__name__}"
        config_failure = True
        report = _unmet_report(mode, "authentication rejected by the provider")
    except SportmonksError as exc:
        # Exit 3 is defined as *configuration or authentication* failure. A
        # provider that paginated badly, throttled us out, or returned an
        # unparseable body is none of those -- it is a degraded observation, and
        # collapsing it into the config bucket misreports what happened. Only
        # the two branches above are exit 3.
        failure = f"PROVIDER: {type(exc).__name__}"
        report = _degraded_report(mode, f"provider error: {type(exc).__name__}")

    json_path, md_path = write_report(report, args.out)
    if failure is not None:
        print(failure)
    print(f"{SCRIPT}: mode={report.mode} report={json_path} markdown={md_path}")
    return EXIT_CONFIG if config_failure else report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())

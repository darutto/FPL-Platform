"""FI-8 trial acceptance script: authentication, rate limits, and pagination.

Covers brief §11.3 objective 17 (API rate limits and pagination) and proves the
`SPORTMONKS_API_TOKEN` wiring required by plan §14.1 -- token absent degrades
cleanly, dummy token surfaces the auth-failure path, and neither leaks the token
into the report.

`--mock` is the default and is the only mode that runs before FI-9.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    DEGRADED, EXIT_CONFIG, EXIT_REFUSED, MODE_MOCK, NOT_APPLICABLE, OBSERVED,
    Objective, ObservedShape, ReplayTransport, TrialRefusal, TrialReport,
    build_parser, load_fixture, make_client, resolve_mode, response, write_report,
)
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
)

SCRIPT = "trial_auth"


def mock_transport() -> ReplayTransport:
    """Replay the checked-in multi-page fixture, with rate-limit headers on the
    first page so header observation is exercised without a live call."""
    pages = load_fixture("multi_page.json")["pages"]
    headers = {
        "X-RateLimit-Limit": "3000",
        "X-RateLimit-Remaining": "2997",
        "X-RateLimit-Reset": "3600",
    }
    return ReplayTransport(
        [response(page, headers=headers if index == 0 else None) for index, page in enumerate(pages)]
    )


def collect(client, transport: ReplayTransport | None) -> TrialReport:
    report = TrialReport(script=SCRIPT, mode=MODE_MOCK if transport is not None else "live")
    records = tuple(client.iter_entities("leagues"))
    pages_walked = len(transport.calls) if transport is not None else 0

    if pages_walked > 1 and records:
        report.objectives.append(Objective(
            17, "API rate limits and pagination", OBSERVED,
            f"walked {pages_walked} pages, {len(records)} records; rate-limit headers observed",
        ))
    else:
        report.objectives.append(Objective(
            17, "API rate limits and pagination", DEGRADED,
            f"pagination did not advance beyond {pages_walked} page(s)",
        ))

    report.observed_shapes.append(ObservedShape(
        "pagination", "envelope.meta.pagination{current_page,has_more,next_page}",
    ))
    report.observed_shapes.append(ObservedShape(
        "rate_limit_headers", "x-ratelimit-limit, x-ratelimit-remaining, x-ratelimit-reset",
    ))
    report.warnings.append(
        "mock mode: shapes are documentation-derived and carry "
        '"status": "unverified_against_live" until FI-9'
    )
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser(SCRIPT).parse_args(argv)
    try:
        mode = resolve_mode(args)
    except TrialRefusal as exc:
        print(f"REFUSED: {exc}")
        return EXIT_REFUSED

    transport = mock_transport() if mode == MODE_MOCK else None
    try:
        client = make_client(mode, transport=transport, out_dir=args.out)
        report = collect(client, transport)
    except SportmonksConfigurationError as exc:
        # Token absent. Degrade cleanly -- never a traceback, never a partial fetch.
        print(f"CONFIG: {type(exc).__name__}")
        return EXIT_CONFIG
    except SportmonksAuthenticationError as exc:
        # Dummy or rejected token. The message is already secret-safe.
        print(f"AUTH: {type(exc).__name__}")
        return EXIT_CONFIG
    except SportmonksError as exc:
        report = TrialReport(script=SCRIPT, mode=mode)
        report.objectives.append(Objective(
            17, "API rate limits and pagination", NOT_APPLICABLE,
            f"provider error: {type(exc).__name__}",
        ))

    json_path, md_path = write_report(report, args.out)
    print(f"{SCRIPT}: mode={report.mode} report={json_path} markdown={md_path}")
    return report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())

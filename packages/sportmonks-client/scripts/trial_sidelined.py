"""FI-9 trial script: current sidelined list, polled and diffed (objective 11, criterion c).

`teams/{id}?include=sidelined` is a club's open list of absences, independent of
any match (21 requests per pass with the scope bootstrap, 20 without). The
fixtures include in `trial_injuries` is the per-match audit trail; this is the
source of *current* bajas, and the one whose latency against public news can be
measured: criterion (c) asks whether a new absence shows up within 48 hours.

The provider stamps no `updated_at` on these rows, so latency is observable only
one way: run this script every 6-12 hours, keep the previous pass, and record
when each absence **first appeared**. State and the event log live under
`--out` (gitignored, local); the committed report carries counts only, never
rows, never timestamps (byte-stable reports, see `_trial_common`).

First pass: every row is a baseline, nothing is "new". From the second pass on,
each id the previous pass did not have is an `appeared` event with the pass time
and the row's own `start_date`; ids that left are `gone`; a changed `end_date`
or `completed` is `changed`.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    EXIT_CONFIG, EXIT_REFUSED, MODE_MOCK, OBSERVED, UNMET, Objective, ObservedShape,
    TrialRefusal, TrialReport, build_parser, fetch_family, make_client, resolve_mode,
    routes_transport, load_fixture, scope_for, write_report,
)
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
)

SCRIPT = "trial_sidelined"
OBJECTIVE_11 = "Injuries and suspensions"
TRACKED = ("player_id", "team_id", "type_id", "category", "start_date", "end_date",
           "games_missed", "completed")
CHANGE_WATCH = ("end_date", "completed")

DECLARED_SHAPES = {
    "current_sidelined": (
        "test_the_shape_entry_reports_the_fields_that_arrived",
        "test_a_missing_family_is_unmet_and_drops_its_shape",
    ),
    "poll_pass": (
        "test_the_first_pass_is_a_baseline_and_reports_no_new_absences",
        "test_a_second_pass_reports_what_appeared_left_and_changed",
    ),
}


def mock_transport(*, current_sidelined: Any | None = None) -> Any:
    payloads = load_fixture("endpoint_payloads.json")["families"]
    item = payloads["current_sidelined"] if current_sidelined is None else current_sidelined
    return routes_transport({"current_sidelined": item})


def _row(record: Any) -> dict[str, Any]:
    return {name: record.raw_fields.get(name) for name in TRACKED}


def diff_pass(previous: Mapping[str, Mapping[str, Any]] | None,
              current: Mapping[str, Mapping[str, Any]], now: str) -> list[dict[str, Any]]:
    """Events between two passes. ``previous is None`` means baseline: no events."""
    if previous is None:
        return []
    events: list[dict[str, Any]] = []
    for key, row in current.items():
        if key not in previous:
            events.append({"event": "appeared", "id": key, "seen_at": now,
                           "start_date": row.get("start_date"), "category": row.get("category"),
                           "team_id": row.get("team_id"), "player_id": row.get("player_id")})
        else:
            for name in CHANGE_WATCH:
                if previous[key].get(name) != row.get(name):
                    events.append({"event": "changed", "id": key, "seen_at": now, "field": name,
                                   "before": previous[key].get(name), "after": row.get(name)})
    for key, row in previous.items():
        if key not in current:
            events.append({"event": "gone", "id": key, "seen_at": now,
                           "team_id": row.get("team_id"), "player_id": row.get("player_id")})
    return events


def _load_state(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def collect(client, mode: str, state_dir: Path, *, now: str | None = None) -> TrialReport:
    report = TrialReport(script=SCRIPT, mode=mode)
    stamp = now or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    scope = scope_for(client, mode)
    failure = ""
    try:
        records, _ = fetch_family(client, "current_sidelined", scope)
    except (SportmonksConfigurationError, SportmonksAuthenticationError):
        raise
    except SportmonksError as exc:
        records, failure = (), type(exc).__name__

    if failure or not records:
        reason = f"current_sidelined request failed: {failure}" if failure else "no sidelined row returned"
        report.objectives.append(Objective(11, OBJECTIVE_11, UNMET, reason))
        report.warnings.append("no pass was recorded; the previous state is untouched")
        return report

    current = {str(r.provider_id): _row(r) for r in records}
    state_path = state_dir / "state.json"
    prior = _load_state(state_path)
    previous = prior["rows"] if prior else None
    events = diff_pass(previous, current, stamp)
    pass_no = (prior["pass"] if prior else 0) + 1

    state_dir.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"pass": pass_no, "at": stamp, "rows": current}, sort_keys=True),
                          encoding="utf-8", newline="\n")
    if events:
        with (state_dir / "events.ndjson").open("a", encoding="utf-8", newline="\n") as handle:
            for event in events:
                handle.write(json.dumps(event, sort_keys=True) + "\n")

    clubs = len({row["team_id"] for row in current.values()})
    categories: dict[str, int] = {}
    for row in current.values():
        categories[str(row["category"])] = categories.get(str(row["category"]), 0) + 1
    counts = {name: sum(1 for e in events if e["event"] == name) for name in ("appeared", "gone", "changed")}
    evidence = (
        f"current_sidelined: {len(current)} open row(s) over {clubs} club(s); "
        + ", ".join(f"{k} {v}" for k, v in sorted(categories.items()))
    )
    report.objectives.append(Objective(11, OBJECTIVE_11, OBSERVED, evidence))

    first = next(iter(records))
    report.observed_shapes.append(ObservedShape(
        "current_sidelined",
        f"{len(records)} record(s); record{{{','.join(first.raw_fields)}}}",
    ))
    if previous is None:
        report.observed_shapes.append(ObservedShape(
            "poll_pass", f"pass {pass_no}: baseline of {len(current)} row(s); no earlier pass to diff"))
    else:
        report.observed_shapes.append(ObservedShape(
            "poll_pass",
            f"pass {pass_no}: {counts['appeared']} appeared, {counts['gone']} gone, "
            f"{counts['changed']} changed since pass {prior['pass']}",
        ))
    report.warnings.append(
        "the rows carry no updated_at: first-seen is the earliest pass that contained the id, "
        "so latency has a resolution of one polling interval"
    )
    report.warnings.append(
        "mock mode: shapes are documentation-derived and carry "
        '"status": "unverified_against_live" until FI-9'
        if mode == MODE_MOCK else
        "live mode: shapes are as received from the provider"
    )
    return report


def _unmet_report(mode: str, reason: str) -> TrialReport:
    report = TrialReport(script=SCRIPT, mode=mode)
    report.objectives.append(Objective(11, OBJECTIVE_11, UNMET, reason))
    report.warnings.append(reason)
    return report


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
        report = collect(client, mode, args.out / "sidelined")
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

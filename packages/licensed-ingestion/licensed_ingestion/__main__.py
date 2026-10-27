"""``python -m licensed_ingestion --pass {daily,matchday,deadline} [--dry-run | --smoke | --publish]``

* ``--dry-run`` (default): prints the calls a live pass would make and their number, then replays the
  synthetic recording through the whole pass. No token is read, no network, nothing is published.
* ``--smoke``: needs ``SPORTMONKS_API_TOKEN``. Reads the provider for real, builds locally, reports counts and
  publishes nothing.
* ``--publish``: a smoke that also publishes the build to the private bucket. The previous build comes from the
  bucket (a CI runner starts empty).

``--pass backfill`` is a manual, one-off history fill (the workflow's schedule never runs it): it reads the finished
PL lineups from the season's first kickoff to yesterday in 14-day windows and appends them to the store. It needs a
published daily build to take the crosswalk from, and ``--since YYYY-MM-DD`` narrows it.

Every mode takes ``--max-calls``, hard-capped per pass (daily 120, backfill 40, matchday and deadline 10): a counter
on the client's ``Transport`` raises before call N+1.

The repository is public and so are its CI logs: stdout is ONE JSON line of counts, and a failure prints only
the exception's type. No name, id or row is ever printed, on any path.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence

PREFIX = "football-licensed"
DEFAULT_ALIASES = Path(__file__).resolve().parent.parent / "manual_aliases.json"
EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_BUDGET = 0, 1, 2, 3
#: The hard per-pass ceiling for --max-calls (also its default).
MAX_CALLS = {"daily": 120, "matchday": 10, "deadline": 10, "backfill": 40}


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="licensed_ingestion")
    parser.add_argument("--pass", dest="kind", required=True, choices=tuple(MAX_CALLS))
    modes = parser.add_mutually_exclusive_group()
    for name, help_ in (("dry-run", "print the planned calls and replay the synthetic recording (default)"),
                        ("smoke", "read the provider for real, build locally, publish nothing"),
                        ("publish", "read the provider for real and publish the build to the private bucket")):
        modes.add_argument(f"--{name}", dest="mode", action="store_const", const=name, help=help_)
    parser.add_argument("--max-calls", type=int, help="hard Sportmonks call cap (default and ceiling: daily 120, "
                                                       "matchday 10, deadline 10)")
    parser.add_argument("--work-dir", type=Path, help="where builds are written (default: a temp dir, removed after)")
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES, help="optional manual alias file")
    parser.add_argument("--now", help="dry-run only: UTC time to run at (YYYY-MM-DDTHH:MM:SSZ)")
    parser.add_argument("--since", help="backfill only: first day to read (YYYY-MM-DD), never earlier than the season's start")
    args = parser.parse_args(argv)
    args.mode = args.mode or "dry-run"
    return args


def _emit(summary: dict[str, Any]) -> None:
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))


def _refuse(reason: str) -> int:
    _emit({"status": "refused", "reason": reason})
    return EXIT_REFUSED


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    cap = MAX_CALLS[args.kind] if args.max_calls is None else args.max_calls
    if not 1 <= cap <= MAX_CALLS[args.kind]:
        return _refuse("max_calls_out_of_range")
    if args.now and args.mode != "dry-run":
        return _refuse("now_is_dry_run_only")
    if args.since and args.kind != "backfill":
        return _refuse("since_is_backfill_only")
    try:
        args.since_day = date.fromisoformat(args.since) if args.since else None
    except ValueError:
        return _refuse("since_is_not_a_date")
    started = time.monotonic()
    counted: list[Any] = []
    try:
        summary = _run(args, cap, counted)
    except Exception as exc:  # noqa: BLE001 -- the type only: messages may carry what the logs must not
        from .budget import BudgetExceeded
        print(f"FAILED {type(exc).__name__}", file=sys.stderr)
        if isinstance(exc, BudgetExceeded):
            _emit({"status": "budget_exceeded", "mode": args.mode, "pass": args.kind, "cap": cap,
                   "calls": counted[0].calls if counted else None})
            return EXIT_BUDGET
        return EXIT_FAILED
    if "refused" in summary:
        return _refuse(summary["refused"])
    summary.update(mode=args.mode, cap=cap, duration_seconds=round(time.monotonic() - started, 1))
    _emit(summary)
    return EXIT_OK


def _plan(kind: str, windows: int = 1) -> dict[str, Any]:
    from .fetch import planned_calls, planned_count
    return {"planned_calls": planned_count(kind, windows=windows), "planned_requests": planned_calls(kind)}


def _backfill_windows(feed: Any, now: datetime, since: date | None) -> int:
    from datetime import timedelta
    from .fetch import backfill_windows
    from .run import season_first_day
    first = max(filter(None, (season_first_day(feed), since)), default=None)
    return len(backfill_windows(first, now.date() - timedelta(days=1))) if first else 0


def _run(args: argparse.Namespace, cap: int, counted: list[Any]) -> dict[str, Any]:
    if args.work_dir:
        return _run_in(args, cap, counted, args.work_dir)
    with tempfile.TemporaryDirectory(prefix="licensed-ingestion-", ignore_cleanup_errors=True) as tmp:
        return _run_in(args, cap, counted, Path(tmp))


def _run_in(args: argparse.Namespace, cap: int, counted: list[Any], work: Path) -> dict[str, Any]:
    from football_intelligence.distribution.keys import pointer_key
    from football_intelligence.distribution.service import publish_build, sync_build
    from football_intelligence.ingestion.licensed.crosswalk import load_aliases
    from football_intelligence.ingestion.licensed.store import LICENSED_V1, POINTER_NAME
    from sportmonks_client.client import SportmonksClient
    from sportmonks_client.config import SportmonksConfig

    from . import fpl
    from .budget import CountingTransport
    from .run import latest_build, run_pass

    store = None
    dry = args.mode == "dry-run"
    if dry:
        from .recording import BACKFILL_FEED, BACKFILL_PROVIDER, FEED, NOW, RecordedTransport
        now = datetime.strptime(args.now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if args.now else NOW
        backfill = args.kind == "backfill"
        feed, config = (BACKFILL_FEED if backfill else FEED), SportmonksConfig()
        inner = RecordedTransport(BACKFILL_PROVIDER) if backfill else RecordedTransport()
    else:
        from football_intelligence.distribution.config import RemoteStoreConfig
        from football_intelligence.distribution.store import S3ArtifactStore
        from sportmonks_client.transport import RequestsTransport
        now = datetime.now(timezone.utc).replace(microsecond=0)
        config = SportmonksConfig.from_env()
        config.require_token()  # before any network read, FPL's included
        remote = RemoteStoreConfig.from_env()
        store = S3ArtifactStore(replace(remote, prefix=PREFIX)) if remote else None
        if args.mode == "publish" and store is None:
            return {"refused": "publish_needs_remote_config"}
        feed, inner = fpl.load_feed(), RequestsTransport(max_response_bytes=config.max_response_bytes)

    windows = _backfill_windows(feed, now, args.since_day) if args.kind == "backfill" else 1
    plan = _plan(args.kind, windows) if dry else {}
    if not fpl.due(args.kind, feed, now) or (args.kind == "backfill" and windows == 0):
        return {**plan, "status": "skipped", "pass": args.kind, "calls": 0}
    transport = CountingTransport(inner, cap)
    counted.append(transport)
    client = SportmonksClient.offline(transport, config=config) if dry else SportmonksClient(config, transport=transport)
    aliases = load_aliases(args.aliases)
    if store is not None and store.head(pointer_key(PREFIX, POINTER_NAME)) is not None:
        previous = work / "builds" / sync_build(store, PREFIX, work, family=LICENSED_V1).build_id
    else:
        previous = latest_build(work)
    if dry and previous is None and args.kind != "daily":
        from .recording import FEED as SEED_FEED
        # A matchday or deadline pass builds on a daily one: seed it from the recording, outside the counted run.
        seed = SportmonksClient.offline(CountingTransport(RecordedTransport(), 1_000), config=config)
        previous, _ = run_pass("daily", seed, SEED_FEED, work, now=NOW, previous=None, aliases=aliases)
    build, summary = run_pass(args.kind, client, feed, work, now=now, previous=previous, aliases=aliases,
                              since=args.since_day)
    summary.update(plan, status="built", calls=transport.calls, published=False)
    if args.mode == "publish":
        publish_build(store, PREFIX, build, family=LICENSED_V1)
        summary["published"] = True
    return summary


if __name__ == "__main__":
    raise SystemExit(main())

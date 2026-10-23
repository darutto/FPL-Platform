"""Harvest of the "Pressure Index & xG" add-on (per-minute pressure, team xG) for the Premier League, to disk, local only.

Why it exists: the add-on is on the trial token only. Sportmonks confirmed in writing (2026-10-23) that data read while
subscribed may be kept and used internally for derived insights, never resold or redistributed raw. So this reads
``include=pressure`` and ``include=xGFixture`` on the full-season fixture listings of the last three Premier League seasons,
in the fewest requests (50 fixtures per page), and keeps them under ``trial-output/`` (gitignored). Nothing here is published.

Rules this script keeps, because earlier scripts broke them:

* It goes ONLY through ``sportmonks_client`` (``make_client``); there is no raw HTTP in this file.
* Live needs ``--live --i-understand-this-is-live``. ``--dry-run`` needs neither, makes no request and no token read.
* The token comes from the environment inside the client; it is never printed. Errors print only their type.
* It writes only under ``trial-output/`` (gitignored). The summary carries counts, no names and no provider ids.
* Hard request cap (``--max-requests``, default 60): when reached it stops and keeps what it read. Starter allows
  2,000 requests per entity per hour.

    python scripts/pressure_harvest.py --dry-run
    python scripts/pressure_harvest.py --live --i-understand-this-is-live [--years 2026,2025,2024]
"""
from __future__ import annotations

import dataclasses
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    DEFAULT_OUT, EXIT_CONFIG, EXIT_OK, EXIT_REFUSED, MODE_LIVE, TrialRefusal, build_parser, make_client, resolve_mode,
)
from euro_preload import FINISHED, _inside_trial_output, default_years, pick_season  # noqa: E402
from sportmonks_client.config import SportmonksConfig  # noqa: E402
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
)

SCRIPT = "pressure_harvest"
PREMIER_LEAGUE = 8
EXPECTED_GOALS_TYPE = 5304
FIXTURE_INCLUDES = "pressure;xGFixture;participants;state;round"
DEFAULT_MAX_REQUESTS = 60
FIXTURE_PAGE_SIZE = 50
FIXTURE_MAX_PAGES = 10      # 380 fixtures a season = 8 pages of 50
SEASON_MAX_PAGES = 3
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
OUT_SUBDIR = "pressure-harvest"


class BudgetReached(Exception):
    """The request cap was reached; what was read so far is kept."""


def plan(years: Sequence[int]) -> list[dict[str, Any]]:
    """The calls a run would make: ``min`` (one page each) and ``max`` (every page up to the bounds)."""
    steps: list[dict[str, Any]] = [
        {"step": "seasons", "what": f"Premier League (league {PREMIER_LEAGUE}): list of seasons", "min": 1,
         "max": SEASON_MAX_PAGES}]
    steps.extend({"step": "fixtures", "what": f"Premier League {year}-{str(year + 1)[2:]}: full list with pressure and xG",
                  "min": 1, "max": FIXTURE_MAX_PAGES} for year in years)
    return steps


def render_plan(steps: Sequence[Mapping[str, Any]], cap: int) -> str:
    lines = [f"{SCRIPT} dry run: no request is made and no token is read.", ""]
    for s in steps:
        lines.append(f"  {s['step']:<10} {s['what']}  ({s['min']}..{s['max']} requests)")
    low, high = sum(s["min"] for s in steps), sum(s["max"] for s in steps)
    expected = 1 + 8 * (len(steps) - 1)
    lines += ["", f"planned requests: minimum {low}, maximum {high}, hard cap {cap}; "
                  f"expected about {expected} (1 season list + 8 pages of 50 for each season)."]
    return "\n".join(lines)


def fixture_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregates of one season: nothing but counts."""
    finished = [r for r in rows if (r.get("state") or {}).get("developer_name") in FINISHED]
    with_pressure = [r for r in finished if r.get("pressure")]
    with_xg = [r for r in finished if any(x.get("type_id") == EXPECTED_GOALS_TYPE for x in (r.get("xgfixture") or r.get("xGFixture") or []))]
    two_per_minute = 0
    for r in with_pressure:
        per_minute = Counter(p.get("minute") for p in r["pressure"])
        if per_minute and all(n == 2 for n in per_minute.values()):
            two_per_minute += 1
    return {"fixtures": len(rows), "finished": len(finished), "finished_with_pressure": len(with_pressure),
            "finished_with_team_xg": len(with_xg), "pressure_two_rows_per_minute": two_per_minute,
            "pressure_rows": sum(len(r["pressure"]) for r in with_pressure)}


def run(client, out_dir: Path, *, years: Sequence[int], cap: int = DEFAULT_MAX_REQUESTS) -> dict[str, Any]:
    """Make the reads, write them under ``out_dir`` and return the aggregates (also written as summary.json)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    base = len(client.transport.exchanges)

    def spent() -> int:
        return len(client.transport.exchanges) - base

    summary: dict[str, Any] = {"started": _now(), "cap": cap, "units": [], "notes": []}
    try:
        if spent() + 1 > cap:
            raise BudgetReached(f"request cap {cap} reached after {spent()}")
        seasons = tuple(client.iter_entities(
            "seasons", params={"filters": f"seasonLeagues:{PREMIER_LEAGUE}", "per_page": 50}, max_pages=SEASON_MAX_PAGES))
        for year in years:
            season = pick_season(seasons, year)
            if not season:
                summary["notes"].append(f"Premier League {year}: no season found")
                continue
            remaining = cap - spent()
            if remaining < 2:
                raise BudgetReached(f"request cap {cap} reached after {spent()}")
            rows: list[dict[str, Any]] = []
            truncated, error, before = False, None, spent()
            try:
                for record in client.iter_entities("fixtures", params={
                        "filters": f"fixtureSeasons:{season['id']};fixtureLeagues:{PREMIER_LEAGUE}",
                        "include": FIXTURE_INCLUDES, "per_page": FIXTURE_PAGE_SIZE},
                        max_pages=min(FIXTURE_MAX_PAGES, remaining)):
                    rows.append(dict(record.raw_fields))
            except SportmonksError as exc:
                truncated, error = True, type(exc).__name__
            (out_dir / f"fixtures-{year}.json").write_text(
                json.dumps(rows, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            summary["units"].append({"year": year, "requests": spent() - before, **fixture_stats(rows),
                                     "truncated": truncated, "error": error})
    except BudgetReached as exc:
        summary["notes"].append(f"BUDGET: {exc}")
    finally:
        summary["requests"] = spent()
        summary["finished"] = _now()
        (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser(SCRIPT)
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="print the planned calls and their count; no request, no token read")
    parser.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS, help="hard cap on requests")
    parser.add_argument("--years", default=None, help="comma-separated season start years (default: current and two before)")
    args = parser.parse_args(argv)
    out_dir = args.out / OUT_SUBDIR
    if not _inside_trial_output(out_dir):
        print(f"REFUSED: output must be under {DEFAULT_OUT.name}/ (gitignored); got {args.out}")
        return EXIT_REFUSED
    try:
        years = tuple(int(y) for y in args.years.split(",")) if args.years else default_years()
    except ValueError:
        print("REFUSED: --years must be a comma-separated list of years")
        return EXIT_REFUSED
    if args.dry_run:
        print(render_plan(plan(years), args.max_requests))
        return EXIT_OK
    try:
        if resolve_mode(args) != MODE_LIVE:
            raise TrialRefusal("pressure_harvest is live-only; pass --live --i-understand-this-is-live (or --dry-run)")
    except TrialRefusal as exc:
        print(f"REFUSED: {exc}")
        return EXIT_REFUSED
    try:
        config = dataclasses.replace(SportmonksConfig.from_env(), max_response_bytes=MAX_RESPONSE_BYTES)
        client = make_client(MODE_LIVE, config=config)
        summary = run(client, out_dir, years=years, cap=args.max_requests)
    except (SportmonksConfigurationError, SportmonksAuthenticationError) as exc:
        print(f"CONFIG: {type(exc).__name__}")
        return EXIT_CONFIG
    except SportmonksError as exc:
        print(f"FAILED: {type(exc).__name__}")
        return 1
    for unit in summary["units"]:
        print(f"{unit['year']}: fixtures {unit['fixtures']}, finished {unit['finished']}, "
              f"pressure {unit['finished_with_pressure']}, team xG {unit['finished_with_team_xg']}, "
              f"requests {unit['requests']}" + (f" TRUNCATED ({unit['error']})" if unit["truncated"] else ""))
    for note in summary["notes"]:
        print(f"note: {note}")
    print(f"{SCRIPT}: wrote {out_dir} ({summary['requests']} Sportmonks requests)")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

"""Pre-load of the European competitions (and the clubs' season calendars), to disk, local only.

Why it exists: Euro Club Tournaments is not part of the Starter plan (Premier League only). While a token that
includes it is available, this reads what the product would otherwise lose: every fixture of the Champions League,
Europa League, Conference League and the UEFA Super Cup for the last three seasons, with lineups (formation, grid,
detailed position, minutes) for every finished match, plus every fixture of the current clubs in every competition.
First run: 2026-10-22, 87 requests (trial-reports/live/decision-draft.md).

Rules this script keeps, because earlier scripts broke them:

* It goes ONLY through ``sportmonks_client`` (``make_client``); there is no raw HTTP in this file.
* Live needs ``--live --i-understand-this-is-live``. ``--dry-run`` needs neither, makes no request and no token read.
* The token comes from the environment inside the client; it is never printed. Errors print only their type.
* It writes only under ``trial-output/`` (gitignored). The data is local: Sportmonks confirmed retention only for data
  obtained while subscribed, so trial data is not for production until they confirm otherwise in writing.
* Hard request cap (``--max-requests``, default 180): when reached it stops and keeps what it read. Starter allows
  2,000 requests per entity per hour.

    python scripts/euro_preload.py --dry-run
    python scripts/euro_preload.py --live --i-understand-this-is-live [--years 2026,2025,2024] [--capture PATH]

Team ids for the clubs' calendars come from an earlier ``live_capture`` file (``--capture``, default
``<out>/capture/capture.json``); without it that step is skipped, never guessed.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    DEFAULT_OUT, EXIT_CONFIG, EXIT_OK, EXIT_REFUSED, MODE_LIVE, TrialRefusal, build_parser, make_client, resolve_mode,
)
from sportmonks_client.config import SportmonksConfig  # noqa: E402
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
)

SCRIPT = "euro_preload"
#: Sportmonks league id -> the badge the calendar uses (see football_intelligence.live_trial_calendar.BADGES).
LEAGUES = {2: "UCL", 5: "UEL", 2286: "UECL", 1328: "UEFA-SC"}
MINUTES_DETAIL_TYPE = 119
FIXTURE_INCLUDES = "lineups.detailedPosition;lineups.details;formations;participants;round;stage;state;league"
TEAM_FIXTURE_INCLUDES = "participants;stage;round;state;league;scores"
FINISHED = frozenset({"FT", "AET", "FT_PEN"})
STARTER_TYPE = 11
DEFAULT_MAX_REQUESTS = 180
FIXTURE_PAGE_SIZE = 50
FIXTURE_MAX_PAGES = 10
SEASON_MAX_PAGES = 3
TEAM_MAX_PAGES = 3
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
OUT_SUBDIR = "euro-preload"


class BudgetReached(Exception):
    """The request cap was reached; what was read so far is kept."""


def default_years(today: date | None = None) -> tuple[int, ...]:
    """Start years of the current and the two previous seasons (a season starts in the summer)."""
    today = today or date.today()
    current = today.year if today.month >= 6 else today.year - 1
    return (current, current - 1, current - 2)


def pick_season(seasons: Sequence[Any], year: int) -> Mapping[str, Any] | None:
    """The season starting from June to December of ``year`` (qualifying rounds begin in the summer)."""
    hits = []
    for season in seasons:
        raw = season.raw_fields
        start = str(raw.get("starting_at") or "")[:10]
        if f"{year}-06-01" <= start <= f"{year}-12-31":
            hits.append((start, raw))
    hits.sort(key=lambda hit: hit[0])
    return hits[-1][1] if hits else None


def load_team_ids(capture: Path) -> list[int] | None:
    """The club ids of an earlier ``live_capture`` file, or None when there is no such file."""
    if not capture.is_file():
        return None
    ids = json.loads(capture.read_text(encoding="utf-8")).get("scope", {}).get("team_ids")
    return [int(i) for i in ids] if ids else None


def plan(years: Sequence[int], team_ids: Sequence[int] | None) -> list[dict[str, Any]]:
    """The calls a run would make: ``min`` (one page each) and ``max`` (every page up to the bounds)."""
    steps: list[dict[str, Any]] = [
        {"step": "seasons", "what": f"{badge} (league {lid}): list of seasons", "min": 1, "max": SEASON_MAX_PAGES}
        for lid, badge in LEAGUES.items()]
    for year in years:
        for lid, badge in LEAGUES.items():
            steps.append({"step": "fixtures", "what": f"{badge} {year}-{str(year + 1)[2:]}: full list with lineups",
                          "min": 1, "max": FIXTURE_MAX_PAGES})
    if team_ids:
        steps.extend({"step": "team_fixtures", "what": f"club {tid}: every competition {years[0]}-{str(years[0] + 1)[2:]}",
                      "min": 1, "max": TEAM_MAX_PAGES} for tid in team_ids)
    return steps


def render_plan(steps: Sequence[Mapping[str, Any]], cap: int, team_ids: Sequence[int] | None) -> str:
    lines = [f"{SCRIPT} dry run: no request is made and no token is read.", ""]
    for s in steps:
        lines.append(f"  {s['step']:<14} {s['what']}  ({s['min']}..{s['max']} requests)")
    low, high = sum(s["min"] for s in steps), sum(s["max"] for s in steps)
    lines += ["", f"planned requests: minimum {low}, maximum {high}, hard cap {cap} "
                  f"(a run stops at the cap and keeps what it read; the last live run used 87)."]
    if not team_ids:
        lines.append("club calendars: skipped (no capture file with team ids; pass --capture)")
    return "\n".join(lines)


def _starters(fixture: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [row for row in (fixture.get("lineups") or []) if row.get("type_id") == STARTER_TYPE]


def fixture_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Aggregates of one competition-season: nothing but counts."""
    finished = [r for r in rows if (r.get("state") or {}).get("developer_name") in FINISHED]
    full_xi = [r for r in finished if len(_starters(r)) >= 22]
    with_grid = [r for r in full_xi if all(row.get("formation_field") for row in _starters(r))]
    with_formation = [r for r in finished if r.get("formations")]
    return {"fixtures": len(rows), "finished": len(finished), "finished_with_full_xi": len(full_xi),
            "finished_with_grid_on_all_starters": len(with_grid), "finished_with_formation": len(with_formation)}


def run(client, out_dir: Path, *, years: Sequence[int], team_ids: Sequence[int] | None,
        cap: int = DEFAULT_MAX_REQUESTS) -> dict[str, Any]:
    """Make the reads, write them under ``out_dir`` and return the aggregates (also written as summary.json)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    base = len(client.transport.exchanges)

    def spent() -> int:
        return len(client.transport.exchanges) - base

    summary: dict[str, Any] = {"started": _now(), "cap": cap, "units": [], "notes": []}
    try:
        season_by: dict[tuple[int, int], Mapping[str, Any] | None] = {}
        for lid, badge in LEAGUES.items():
            if spent() + 1 > cap:
                raise BudgetReached(f"request cap {cap} reached after {spent()}")
            seasons = tuple(client.iter_entities(
                "seasons", params={"filters": f"seasonLeagues:{lid}", "per_page": 50}, max_pages=SEASON_MAX_PAGES))
            for year in years:
                season_by[(lid, year)] = pick_season(seasons, year)
        (out_dir / "seasons.json").write_text(json.dumps(
            {f"{lid}-{year}": s for (lid, year), s in season_by.items()}, ensure_ascii=False), encoding="utf-8")

        for year in years:
            for lid, badge in LEAGUES.items():
                season = season_by.get((lid, year))
                if not season:
                    summary["notes"].append(f"{badge} {year}: no season found")
                    continue
                remaining = cap - spent()
                if remaining < 2:
                    raise BudgetReached(f"request cap {cap} reached after {spent()}")
                rows: list[dict[str, Any]] = []
                truncated, error, before = False, None, spent()
                try:
                    for record in client.iter_entities("fixtures", params={
                            "filters": f"fixtureSeasons:{season['id']};fixtureLeagues:{lid};lineupDetailTypes:{MINUTES_DETAIL_TYPE}",
                            "include": FIXTURE_INCLUDES, "per_page": FIXTURE_PAGE_SIZE},
                            max_pages=min(FIXTURE_MAX_PAGES, remaining)):
                        rows.append(dict(record.raw_fields))
                except SportmonksError as exc:
                    truncated, error = True, type(exc).__name__
                (out_dir / f"fixtures-{year}-{badge}.json").write_text(
                    json.dumps(rows, ensure_ascii=False, sort_keys=True), encoding="utf-8")
                summary["units"].append({"kind": "fixtures", "league": badge, "year": year, "requests": spent() - before,
                                         **fixture_stats(rows), "truncated": truncated, "error": error})

        if team_ids:
            team_fixtures: dict[int, dict[str, Any]] = {}
            before = spent()
            start, end = f"{years[0]}-07-01", f"{years[0] + 1}-06-30"
            for team_id in team_ids:
                if spent() + 1 > cap:
                    raise BudgetReached(f"request cap {cap} reached after {spent()}")
                for record in client.iter_entities(
                        "team_fixtures", scope={"start": start, "end": end, "team_id": team_id},
                        params={"include": TEAM_FIXTURE_INCLUDES, "per_page": FIXTURE_PAGE_SIZE}, max_pages=TEAM_MAX_PAGES):
                    team_fixtures[record.provider_id] = dict(record.raw_fields)
            (out_dir / f"team_fixtures-{years[0]}.json").write_text(
                json.dumps(list(team_fixtures.values()), ensure_ascii=False, sort_keys=True), encoding="utf-8")
            by: dict[str, int] = {}
            for fixture in team_fixtures.values():
                name = str((fixture.get("league") or {}).get("name") or fixture.get("league_id"))
                by[name] = by.get(name, 0) + 1
            summary["units"].append({"kind": "team_fixtures", "year": years[0], "requests": spent() - before,
                                     "fixtures_by_competition": by})
        else:
            summary["notes"].append("club calendars skipped: no capture file with team ids")
    except BudgetReached as exc:
        summary["notes"].append(f"BUDGET: {exc}")
    finally:
        summary["requests"] = spent()
        summary["finished"] = _now()
        (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _inside_trial_output(path: Path) -> bool:
    try:
        path.resolve().relative_to(DEFAULT_OUT.resolve())
    except ValueError:
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser(SCRIPT)
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="print the planned calls and their count; no request, no token read")
    parser.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS, help="hard cap on requests")
    parser.add_argument("--years", default=None, help="comma-separated season start years (default: current and two before)")
    parser.add_argument("--capture", type=Path, default=None, help="live_capture file with the clubs' team ids")
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
    capture = args.capture or (args.out / "capture" / "capture.json")
    team_ids = load_team_ids(capture)
    if args.dry_run:
        print(render_plan(plan(years, team_ids), args.max_requests, team_ids))
        return EXIT_OK
    try:
        if resolve_mode(args) != MODE_LIVE:
            raise TrialRefusal("euro_preload is live-only; pass --live --i-understand-this-is-live (or --dry-run)")
    except TrialRefusal as exc:
        print(f"REFUSED: {exc}")
        return EXIT_REFUSED
    try:
        config = dataclasses.replace(SportmonksConfig.from_env(), max_response_bytes=MAX_RESPONSE_BYTES)
        client = make_client(MODE_LIVE, config=config)
        summary = run(client, out_dir, years=years, team_ids=team_ids, cap=args.max_requests)
    except (SportmonksConfigurationError, SportmonksAuthenticationError) as exc:
        print(f"CONFIG: {type(exc).__name__}")
        return EXIT_CONFIG
    except SportmonksError as exc:
        print(f"FAILED: {type(exc).__name__}")
        return 1
    for unit in summary["units"]:
        if unit["kind"] == "fixtures":
            print(f"{unit['league']} {unit['year']}: fixtures {unit['fixtures']}, finished {unit['finished']}, "
                  f"full XI {unit['finished_with_full_xi']}, requests {unit['requests']}"
                  + (f" TRUNCATED ({unit['error']})" if unit["truncated"] else ""))
    for note in summary["notes"]:
        print(f"note: {note}")
    print(f"{SCRIPT}: wrote {out_dir} ({summary['requests']} Sportmonks requests)")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

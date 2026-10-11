"""FI-9 local capture: one read of everything the M1-M3 analysis needs, written to a local file.

Not an acceptance script. It exists so the canonical-ingestion adapter (in
`football-intelligence`) can be run, re-run and tested against one frozen set of
live reads instead of the provider. The output is **local only**: it lives under
`--out` (gitignored), it is never committed, and the licensing questions on raw
storage (Q2/Q3/Q8) are unanswered, so it is not copied anywhere either.

Live only. There is no mock mode: a mock capture would be a document of the
fixtures, and the adapter has its own checked-in fixtures.

What it reads (about 85 Sportmonks requests, one FPL bootstrap read):

- the 20 clubs' squads with their player records (`squads/teams/{id}?include=player`);
- every fixture of the 20 clubs in every competition the plan covers
  (`fixtures/between/{season start}/{season end}/{team}` with participants,
  stage, round, state, league and scores);
- for the Premier League's own fixtures, lineups with the detailed position and
  the provider's minutes-played detail (type 119), formations and events;
- the country names for the clubs' countries (core API);
- the FPL bootstrap (public, read-only) and the identity pairs the mapping run
  left in `--out` (`trial_mapping_pairs.json`), so identity is the mapping's
  result and not a second opinion.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trial_common import (  # noqa: E402
    EXIT_CONFIG, EXIT_OK, EXIT_REFUSED, MODE_LIVE, TrialRefusal, build_parser, fetch_family, live_scope,
    make_client, resolve_mode,
)
from sportmonks_client.client import SportmonksClient  # noqa: E402
from sportmonks_client.config import SportmonksConfig  # noqa: E402
from sportmonks_client.errors import (  # noqa: E402
    SportmonksAuthenticationError, SportmonksConfigurationError, SportmonksError,
)

SCRIPT = "live_capture"
SCHEMA_VERSION = 1
#: Large enough for a page of lineups with details; the client default is 4 MiB.
CAPTURE_MAX_RESPONSE_BYTES = 32 * 1024 * 1024
#: Covers the qualifying rounds in July to the last fixture of the season.
TEAM_FIXTURES_START = "2026-07-01"
TEAM_FIXTURES_END = "2027-06-30"
TEAM_FIXTURE_INCLUDES = "participants;stage;round;state;league;scores"
MATCH_DETAIL_INCLUDES = "lineups.detailedPosition;lineups.details;formations;events;participants;round;stage;state"
#: Sportmonks lineup-detail type for minutes played, the only detail the adapter reads.
MINUTES_DETAIL_TYPE = 119
FPL_ELEMENT_FIELDS = ("id", "code", "first_name", "second_name", "web_name", "team", "element_type",
                      "birth_date", "status", "news", "chance_of_playing_next_round",
                      "chance_of_playing_this_round", "minutes")
FPL_TEAM_FIELDS = ("id", "code", "name", "short_name")


def _rows(records) -> list[dict[str, Any]]:
    return [dict(r.raw_fields) for r in records]


def assemble(*, scope, teams, squads, players, team_fixtures, match_detail, countries,
             fpl_elements, fpl_teams, pairs) -> dict[str, Any]:
    """The capture document, from reads already made. Pure: nothing here touches the network."""
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": dataclasses.asdict(scope) if dataclasses.is_dataclass(scope) else dict(scope),
        "teams": list(teams),
        "squads": list(squads),
        "players": list(players),
        "team_fixtures": list(team_fixtures),
        "match_detail": list(match_detail),
        "countries": dict(countries),
        "fpl": {
            "elements": [{k: e.get(k) for k in FPL_ELEMENT_FIELDS} for e in fpl_elements],
            "teams": [{k: t.get(k) for k in FPL_TEAM_FIELDS} for t in fpl_teams],
        },
        "identity_pairs": [{"sportmonks_id": str(a), "fpl_id": int(b), "method": str(m)} for a, b, m in pairs],
    }


def load_pairs(out_dir: Path) -> list[tuple[str, int, str]]:
    path = out_dir / "reports" / "trial_mapping_pairs.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8"))["items"]
    except (OSError, ValueError, KeyError) as exc:
        raise TrialRefusal(
            f"identity pairs not found at {path}: run trial_mapping --live first, in the same --out") from exc
    return [(i["sportmonks_id"], i["fpl_id"], i["method"]) for i in items]


def read_countries(config: SportmonksConfig) -> dict[int, str]:
    core = SportmonksClient(dataclasses.replace(config, base_url="https://api.sportmonks.com/v3/core"))
    out: dict[int, str] = {}
    page = 1
    while page <= 10:
        body = core._request("countries", {"per_page": 50, "page": page}).body
        for row in body.get("data", []):
            out[int(row["id"])] = str(row["name"])
        pagination = body.get("pagination") or {}
        if not pagination.get("has_more"):
            break
        page += 1
    return out


def collect_live(client: SportmonksClient, out_dir: Path) -> tuple[dict[str, Any], int]:
    """Make the reads and return (capture, number of Sportmonks requests)."""
    pairs = load_pairs(out_dir)
    from trial_mapping import load_fpl_bootstrap  # lazy: loads the sibling FPL client

    before = len(client.transport.exchanges)
    scope = live_scope(client)
    teams, _ = fetch_family(client, "teams", scope)
    squads, _ = fetch_family(client, "squads", scope)
    players, _ = fetch_family(client, "players", scope)

    team_fixtures: dict[int, dict[str, Any]] = {}
    for team_id in scope.team_ids:
        for record in client.iter_entities(
                "team_fixtures", scope={"start": TEAM_FIXTURES_START, "end": TEAM_FIXTURES_END, "team_id": team_id},
                params={"include": TEAM_FIXTURE_INCLUDES, "per_page": 50}, max_pages=6):
            team_fixtures[record.provider_id] = dict(record.raw_fields)

    detail = [dict(r.raw_fields) for r in client.iter_entities(
        "fixtures", params={
            "filters": f"fixtureSeasons:{scope.season_id};fixtureLeagues:{scope.league_id};"
                       f"lineupDetailTypes:{MINUTES_DETAIL_TYPE}",
            "include": MATCH_DETAIL_INCLUDES, "per_page": 50}, max_pages=10)]

    countries = read_countries(client.config)
    bootstrap = load_fpl_bootstrap()
    requests_made = len(client.transport.exchanges) - before
    capture = assemble(
        scope=scope, teams=_rows(teams), squads=_rows(squads), players=_rows(players),
        team_fixtures=list(team_fixtures.values()), match_detail=detail, countries=countries,
        fpl_elements=bootstrap.get("elements", []), fpl_teams=bootstrap.get("teams", []), pairs=pairs)
    return capture, requests_made


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser(SCRIPT).parse_args(argv)
    try:
        mode = resolve_mode(args)
        if mode != MODE_LIVE:
            raise TrialRefusal("live_capture is live-only; pass --live --i-understand-this-is-live")
    except TrialRefusal as exc:
        print(f"REFUSED: {exc}")
        return EXIT_REFUSED
    try:
        config = dataclasses.replace(SportmonksConfig.from_env(), max_response_bytes=CAPTURE_MAX_RESPONSE_BYTES)
        client = make_client(MODE_LIVE, config=config)
        capture, requests_made = collect_live(client, args.out)
    except TrialRefusal as exc:
        print(f"REFUSED: {exc}")
        return EXIT_REFUSED
    except (SportmonksConfigurationError, SportmonksAuthenticationError) as exc:
        print(f"CONFIG: {type(exc).__name__}")
        return EXIT_CONFIG
    except SportmonksError as exc:
        print(f"FAILED: {type(exc).__name__} {exc}")
        return 1
    target = args.out / "capture"
    target.mkdir(parents=True, exist_ok=True)
    path = target / "capture.json"
    path.write_text(json.dumps(capture, ensure_ascii=False, sort_keys=True), encoding="utf-8", newline="\n")
    counts = {k: len(v) for k, v in capture.items() if isinstance(v, (list, dict)) and k != "scope"}
    print(f"{SCRIPT}: wrote {path} ({requests_made} Sportmonks requests); " + ", ".join(f"{k} {n}" for k, n in counts.items()))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

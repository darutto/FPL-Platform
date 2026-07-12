#!/usr/bin/env python3
"""
publish_stats.py — publish a static team attack/defense stats snapshot for the
Bendito Fantasy editorial site to consume.

Deterministic, no LLM, no secrets. Fetches the official FPL bootstrap + all
fixtures via ``fpl_api_client``, aggregates goals-for / goals-against per team
from FINISHED fixtures, and writes ``data/stats.json`` at the repo root.

The editorial site (benditofantasy-web) fetches the committed file via its raw
GitHub URL and renders it as a chart tile — see that repo's
``scripts/sync-fpl-stats.mjs``. Publishing a plain file (not an endpoint) keeps
this decoupled from the gated Railway assistant service.

Run:  python scripts/publish_stats.py [--out data/stats.json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
# fpl_api_client is a PYTHONPATH package (no pyproject in this monorepo); add its
# dir to sys.path so this script runs both locally and in CI with no install step.
sys.path.insert(0, str(REPO_ROOT / "packages" / "fpl-api-client"))

from fpl_api_client.fpl_client import (  # noqa: E402
    get_all_fixtures,
    get_bootstrap,
    get_current_gameweek,
    get_teams,
)


def derive_season(bootstrap: dict) -> str:
    """Season label like ``"2025/26"``, derived from data — never hardcoded — so
    it rolls to the next season automatically when the live API does.

    Uses the earliest event ``deadline_time`` year (the season's opening GW). In
    a deep off-season where no deadlines are set yet, infers from today (the PL
    season opens in August, so month >= 7 belongs to ``{year}/{year+1}``).
    """
    years = [
        int(e["deadline_time"][:4])
        for e in bootstrap.get("events", [])
        if e.get("deadline_time")
    ]
    if years:
        start = min(years)
    else:
        today = dt.date.today()
        start = today.year if today.month >= 7 else today.year - 1
    return f"{start}/{str(start + 1)[-2:]}"


def last_finished_gameweek(bootstrap: dict) -> int | None:
    """The highest event id with ``finished: true`` — the GW the aggregation is
    current through (used for labels both in- and off-season, so a run through
    GW13's results is never mislabelled GW14)."""
    finished = [int(e["id"]) for e in bootstrap.get("events", []) if e.get("finished")]
    return max(finished) if finished else None


def aggregate_team_goals(teams: list[dict], fixtures: list[dict]) -> dict[int, dict]:
    """``{team_id: {goalsFor, goalsAgainst, played}}`` over FINISHED fixtures only."""
    stats = {t["id"]: {"goalsFor": 0, "goalsAgainst": 0, "played": 0} for t in teams}
    for fx in fixtures:
        if not fx.get("finished"):
            continue
        home, away = fx.get("team_h"), fx.get("team_a")
        home_score, away_score = fx.get("team_h_score"), fx.get("team_a_score")
        if home not in stats or away not in stats:
            continue
        if home_score is None or away_score is None:
            continue
        stats[home]["goalsFor"] += home_score
        stats[home]["goalsAgainst"] += away_score
        stats[home]["played"] += 1
        stats[away]["goalsFor"] += away_score
        stats[away]["goalsAgainst"] += home_score
        stats[away]["played"] += 1
    return stats


def build_payload() -> dict:
    bootstrap = get_bootstrap()
    teams = get_teams(bootstrap)
    fixtures = get_all_fixtures()

    # Broken-source guard (parity with the site's sync): a bootstrap with no
    # teams means the FPL API changed shape or returned garbage — fail loudly so
    # CI goes red and the alert issue opens, rather than publishing nonsense.
    if not teams:
        raise SystemExit("FPL bootstrap returned no teams — treating as a broken source.")

    agg = aggregate_team_goals(teams, fixtures)
    team_rows = [
        {
            "name": t["name"],
            "short": t["short_name"],
            "goalsFor": agg[t["id"]]["goalsFor"],
            "goalsAgainst": agg[t["id"]]["goalsAgainst"],
            "played": agg[t["id"]]["played"],
        }
        for t in teams
    ]

    current = get_current_gameweek(bootstrap)
    return {
        "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": derive_season(bootstrap),
        "seasonStatus": "in_season" if current is not None else "offseason",
        "gameweek": last_finished_gameweek(bootstrap),
        "teams": team_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish team stats snapshot JSON.")
    parser.add_argument("--out", default=str(REPO_ROOT / "data" / "stats.json"))
    args = parser.parse_args()

    payload = build_payload()

    total_played = sum(t["played"] for t in payload["teams"])
    # An all-zero table is never worth publishing — it means either an in-season
    # break, or a pre-season where the API already rolled to a not-yet-played
    # season. Fail loudly instead of shipping an empty chart. (Today, off-season,
    # the API still serves the just-finished season, so this passes.)
    if total_played == 0:
        raise SystemExit(
            "No finished fixtures aggregated — nothing meaningful to publish "
            f"(season {payload['season']}, {payload['seasonStatus']}). Aborting."
        )

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {out_path} — season {payload['season']} ({payload['seasonStatus']}), "
        f"gw {payload['gameweek']}, {len(payload['teams'])} teams, "
        f"{total_played} team-fixtures."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

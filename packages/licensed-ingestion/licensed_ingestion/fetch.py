"""Provider reads for one pass, through ``sportmonks_client`` routes only (no URL is built here).

A daily pass reads the season's clubs, their squads (with players), their open absences, their fixtures in
every competition the plan returns, and two PL lineup windows. A matchday pass reads one narrow PL window and a
deadline pass one 14-day window. The records come
back as plain dicts for ``football_intelligence.ingestion.licensed``; nothing is written to disk here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sportmonks_client.client import SportmonksClient

from .fpl import POLL_AFTER, POLL_BEFORE

PL_LEAGUE_ID = 8
#: The provider caps ``fixtures/between`` (a season-long window answers 422); the trial used 14 days.
WINDOW_DAYS = 14
#: Explicit page bound on every list walk; hitting it raises (never a silent truncation).
MAX_PAGES = 4
PER_PAGE = 50


class FetchError(RuntimeError):
    """The provider's answer does not let the pass continue (e.g. not exactly one current season)."""


@dataclass
class ProviderReads:
    teams: list[dict[str, Any]] = field(default_factory=list)
    pl_fixtures: list[dict[str, Any]] = field(default_factory=list)
    squads: list[dict[str, Any]] = field(default_factory=list)
    players: list[dict[str, Any]] = field(default_factory=list)
    sidelined: list[dict[str, Any]] = field(default_factory=list)
    team_fixtures: list[dict[str, Any]] = field(default_factory=list)


def _window(client: SportmonksClient, start: date, end: date) -> list[dict[str, Any]]:
    return [dict(r.raw_fields) for r in client.iter_entities(
        "licensed_pl_fixtures", scope={"start": start.isoformat(), "end": end.isoformat()},
        params={"filters": f"fixtureLeagues:{PL_LEAGUE_ID}", "per_page": PER_PAGE}, max_pages=MAX_PAGES)]


def season_teams(client: SportmonksClient) -> list[dict[str, Any]]:
    """The current PL season's clubs: 2 calls (seasons filtered by league, then its teams)."""
    seasons = [r for r in client.iter_entities("seasons", params={"filters": f"seasonLeagues:{PL_LEAGUE_ID}"},
                                               max_pages=MAX_PAGES) if r.raw_fields.get("is_current") is True]
    if len(seasons) != 1:
        raise FetchError("expected exactly one current Premier League season")
    return [dict(r.raw_fields) for r in client.iter_entities(
        "teams", scope={"season_id": seasons[0].provider_id}, max_pages=MAX_PAGES)]


def daily(client: SportmonksClient, today: date) -> ProviderReads:
    reads = ProviderReads(teams=season_teams(client))
    ahead = (today, today + timedelta(days=WINDOW_DAYS - 1))
    for team in reads.teams:
        team_id = int(team["id"])
        for row in client.iter_entities("licensed_squads", scope={"team_id": team_id}, max_pages=MAX_PAGES):
            raw = dict(row.raw_fields)
            player = raw.pop("player", None)
            reads.squads.append({**raw, "team_id": raw.get("team_id", team_id)})
            if isinstance(player, dict):
                reads.players.append({**player, "squad_team_id": team_id})
        for row in client.fetch_page("current_sidelined", scope={"team_id": team_id}):
            reads.sidelined.append({**row.raw_fields, "team_id": row.raw_fields.get("team_id", team_id)})
        reads.team_fixtures += [dict(r.raw_fields) for r in client.iter_entities(
            "licensed_team_fixtures", scope={"start": ahead[0].isoformat(), "end": ahead[1].isoformat(), "team_id": team_id},
            params={"per_page": PER_PAGE}, max_pages=MAX_PAGES)]
    reads.pl_fixtures = _window(client, *ahead) + _window(client, today - timedelta(days=7), today - timedelta(days=1))
    return reads


def matchday(client: SportmonksClient, now: datetime) -> ProviderReads:
    """One call: the PL fixtures that can be active now, i.e. kicking off in [now - 30 min, now + 3 h]. The
    window's dates are UTC, so a late kickoff that crosses midnight is still read."""
    start, end = (now - POLL_AFTER).date(), (now + POLL_BEFORE).date()
    return ProviderReads(pl_fixtures=_window(client, start, end))


def deadline(client: SportmonksClient, today: date) -> ProviderReads:
    """One call: the next 14 days of PL fixtures, i.e. the freshest predicted XIs for the deadline's gameweek."""
    return ProviderReads(pl_fixtures=_window(client, today, today + timedelta(days=WINDOW_DAYS - 1)))


def backfill_windows(first: date, last: date) -> list[tuple[date, date]]:
    """Consecutive WINDOW_DAYS windows covering ``first``..``last`` inclusive (the last one clipped); none when the
    range is empty, which is a normal answer (a season that starts today has nothing to fill)."""
    windows: list[tuple[date, date]] = []
    start = first
    while start <= last:
        end = min(start + timedelta(days=WINDOW_DAYS - 1), last)
        windows.append((start, end))
        start = end + timedelta(days=1)
    return windows


def backfill(client: SportmonksClient, windows: list[tuple[date, date]]) -> ProviderReads:
    """One ``licensed_pl_fixtures`` read per window, the same route and includes as the daily pass. Disjoint windows
    cannot repeat a fixture, but the ids are de-duplicated anyway so a provider quirk cannot double a match."""
    seen: set[Any] = set()
    reads = ProviderReads()
    for start, end in windows:
        for fixture in _window(client, start, end):
            if fixture.get("id") not in seen:
                seen.add(fixture.get("id"))
                reads.pl_fixtures.append(fixture)
    return reads


def planned_calls(kind: str, clubs: int = 20) -> list[str]:
    """What a live pass would request, assuming one page per walk (the cap still applies to the real count)."""
    if kind == "daily":
        return (["seasons (PL, current)", "teams (season)"]
                + [f"{family} x{clubs}" for family in ("licensed_squads", "current_sidelined", "licensed_team_fixtures")]
                + ["licensed_pl_fixtures (next 14 days)", "licensed_pl_fixtures (last 7 days)"])
    if kind == "deadline":
        return ["licensed_pl_fixtures (next 14 days)"]
    if kind == "backfill":
        return ["licensed_pl_fixtures (one per 14-day window, season start to yesterday)"]
    return ["licensed_pl_fixtures (kickoffs in [-30 min, +3 h])"]


def planned_count(kind: str, clubs: int = 20, windows: int = 1) -> int:
    """``windows`` only matters to a backfill, whose call count is its number of 14-day windows."""
    if kind == "backfill":
        return windows
    return 2 + 3 * clubs + 2 if kind == "daily" else 1

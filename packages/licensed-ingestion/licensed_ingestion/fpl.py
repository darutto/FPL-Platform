"""The free FPL feed: elements for identity, fixtures for the FPL keys, kickoffs and deadlines for the gate.

Read before any Sportmonks call, so a poll that has nothing to do costs zero provider calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from football_intelligence.ingestion.licensed.derive import FplFixture

#: Poll window around each PL kickoff (lineups are confirmed ~60 minutes before kickoff, Q16).
POLL_BEFORE = timedelta(hours=3)
POLL_AFTER = timedelta(minutes=30)
#: A deadline pass runs 3 h and 30 min before each FPL deadline. The workflow ticks every 15 minutes and
#: GitHub may start a tick late, so each target is a 20-minute window: never missed, at worst read twice.
DEADLINE_TARGETS = (timedelta(hours=3), timedelta(minutes=30))
DEADLINE_SLACK = timedelta(minutes=20)


@dataclass(frozen=True)
class FplFeed:
    bootstrap: dict[str, Any]
    fixtures: list[dict[str, Any]]

    @property
    def elements(self) -> list[dict[str, Any]]:
        return list(self.bootstrap.get("elements", []))

    def fpl_fixtures(self) -> list[FplFixture]:
        codes = {int(t["id"]): str(t["short_name"]) for t in self.bootstrap.get("teams", [])}
        return [FplFixture(int(f["id"]), codes[int(f["team_h"])], codes[int(f["team_a"])])
                for f in self.fixtures if int(f["team_h"]) in codes and int(f["team_a"]) in codes]

    def kickoffs(self) -> list[datetime]:
        return [_utc(f["kickoff_time"]) for f in self.fixtures if f.get("kickoff_time")]

    def deadlines(self) -> list[datetime]:
        return [_utc(e["deadline_time"]) for e in self.bootstrap.get("events", []) if e.get("deadline_time")]


def _utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def load_feed(fetch_json: Callable[[str], Any] | None = None) -> FplFeed:
    """Live: the public FPL API through ``fpl_api_client`` (no token, no Sportmonks budget)."""
    from fpl_api_client import fpl_client
    get = fetch_json or fpl_client.fetch_json
    return FplFeed(get(fpl_client.BOOTSTRAP_URL), list(get(fpl_client.ALL_FIXTURES_URL)))


def due(kind: str, feed: FplFeed, now: datetime) -> bool:
    """Whether a pass of this kind has anything to read now. A daily pass always runs."""
    if kind == "matchday":
        return any(k - POLL_BEFORE <= now <= k + POLL_AFTER for k in feed.kickoffs())
    if kind == "deadline":
        return any(target <= d - now < target + DEADLINE_SLACK for d in feed.deadlines() for target in DEADLINE_TARGETS)
    return True

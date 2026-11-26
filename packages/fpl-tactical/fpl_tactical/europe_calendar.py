"""The European calendar job: StrikerAPI ``list_games`` for UCL, UEL and UECL -> one private R2 object.

    raw page (kept on R2 before parsing) -> football_intelligence.strikerapi_calendar -> europe.json

One run asks for each competition's pages (2 credits each, 6 on a normal run), under the run's own ceiling
and the shared credit check (``strikerapi_budget``). A page already bought today is read from the raw cache
and costs nothing. A competition whose reply is rejected, unreachable or unaffordable KEEPS its previous
snapshot, with its old ``fetched_at`` (so it goes stale by itself); the run reports it and exits non-zero.
When nothing was updated, nothing is written.

The object holds only converted rows for the Premier League clubs; the raw replies stay in the private raw
cache. Nothing here runs unless someone starts it: publishing to R2 is the operator's decision.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from football_intelligence.strikerapi_calendar import (
    LEAGUES,
    PROVENANCE,
    SCHEMA_VERSION,
    SourceRejected,
    convert_competition,
    snapshot_to_dict,
)

from fpl_tactical.paths import SOURCE_STRIKERAPI, source_dir
from fpl_tactical.strikerapi_budget import affordable, within_ceiling
from fpl_tactical.strikerapi_client import (
    COST_LIST_GAMES,
    StrikerApiClient,
    StrikerApiError,
    games_page,
    parse_data,
)
from fpl_tactical.strikerapi_raw import RawCache, raw_name

#: The most one run may spend (a normal run is 3 pages = 6 credits).
RUN_CEILING = 20
#: 200 games per page; a competition has at most a few hundred.
MAX_PAGES = 5
FILE_NAME = "europe.json"


class BudgetStop(RuntimeError):
    """The next page would break the run's ceiling or the source's remaining credits."""


def local_path(season: str) -> Path:
    return source_dir(season, SOURCE_STRIKERAPI) / "calendar" / FILE_NAME


def r2_key(prefix: str, season: str) -> str:
    """Private; neither the tactical publish nor the tactical sync touches ``calendar/``."""
    return f"{prefix}calendar/{season}/{FILE_NAME}"


@dataclass
class CalendarReport:
    updated: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    credits_spent: int = 0
    credits_remaining: int | None = None
    #: Per competition, from what was just built: bound, number of rows, unmapped opponent count. No rows.
    competitions: dict = field(default_factory=dict)


class _Buyer:
    """Pages of one run: cache first, then the budget checks, then one paid request."""

    def __init__(self, client: StrikerApiClient, cache: RawCache, now: datetime, max_credits: int):
        self.client, self.cache, self.now, self.max_credits = client, cache, now, max_credits
        self.bought = 0          # our own count: the ceiling must hold even if the source sends no usage header
        self._writable = False

    def page(self, league: str, season: int, offset: int) -> tuple[list[dict], object]:
        request = {"league": league, "offset": offset}
        kept = self.cache.get(raw_name("list_games", request, self.now.strftime("%Y%m%d")))
        if kept is not None:
            return games_page(parse_data("list_games", kept["body"]))
        spent = max(self.bought, self.client.credits_spent)
        if not within_ceiling(spent, COST_LIST_GAMES, self.max_credits):
            raise BudgetStop(f"the run ceiling of {self.max_credits} credits is reached")
        if not affordable(COST_LIST_GAMES, self.client.credits_remaining):
            raise BudgetStop(f"the source reports {self.client.credits_remaining} credits remaining")
        if not self._writable:
            self.cache.check_writable()                                  # never buy what cannot be kept
            self.client.on_response = lambda tool, body, text: self.cache.put(tool, body, text, self.now)
            self._writable = True
        self.bought += COST_LIST_GAMES
        return self.client.competition_games_page(league, season, offset)

    def games(self, league: str, season: int) -> tuple[list[dict], bool]:
        games: list[dict] = []
        offset = 0
        for _ in range(MAX_PAGES):
            page, following = self.page(league, season, offset)
            games.extend(page)
            if not following:
                return games, True
            offset = int(following)  # type: ignore[arg-type]
        return games, False


def build(
    season: str,
    client: StrikerApiClient,
    cache: RawCache,
    now: datetime,
    previous: dict | None = None,
    max_credits: int = RUN_CEILING,
) -> tuple[dict | None, CalendarReport]:
    """(the new file's payload, or None when nothing was updated; the report)."""
    now = now.astimezone(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    report = CalendarReport()
    usable = isinstance(previous, dict) and previous.get("season") == season and previous.get("provenance") == PROVENANCE
    competitions: dict = dict(previous.get("competitions") or {}) if usable else {}  # type: ignore[union-attr]
    buyer = _Buyer(client, cache, now, max_credits)
    stopped: str | None = None
    for league, competition in LEAGUES.items():
        if stopped is None:
            try:
                games, whole = buyer.games(league, int(season[:4]))
                snapshot = convert_competition(
                    games, competition=competition, season=season, fetched_at=stamp, paged_to_end=whole,
                )
                competitions[competition] = snapshot_to_dict(snapshot)
                report.updated.append(competition)
                report.competitions[competition] = {
                    "complete_as_of": snapshot.complete_as_of, "rows": len(snapshot.records),
                    "unmapped": len(snapshot.unmapped), "postponed": snapshot.postponed,
                }
                continue
            except BudgetStop as exc:
                stopped = str(exc)
                report.alerts.append(f"{competition}: not fetched, {stopped}")
            except (SourceRejected, StrikerApiError) as exc:
                report.alerts.append(f"{competition}: rejected ({exc})")
        else:
            report.alerts.append(f"{competition}: not fetched, {stopped}")
        report.kept.append(competition)
    report.credits_spent = max(buyer.bought, client.credits_spent)
    report.credits_remaining = client.credits_remaining
    if not report.updated:
        return None, report
    return {
        "schema_version": SCHEMA_VERSION, "provenance": PROVENANCE, "season": season, "built_at": stamp,
        "competitions": competitions,
    }, report


def read_previous(season: str, r2: object | None = None, bucket: str = "", prefix: str = "") -> dict | None:
    """The file now being served: from R2 when configured, else this machine's. None when there is none.

    An R2 error other than "not there" is raised: guessing "no previous file" would drop the competitions
    this run cannot refresh.
    """
    path = local_path(season)
    if r2 is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".json.part")
        try:
            r2.download_file(bucket, r2_key(prefix, season), str(part))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            code = str((getattr(exc, "response", None) or {}).get("Error", {}).get("Code", ""))
            if isinstance(exc, FileNotFoundError) or code in ("404", "NoSuchKey", "NotFound"):
                return None
            raise RuntimeError(f"could not read the served calendar from R2: {type(exc).__name__}") from None
        os.replace(str(part), str(path))
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write(payload: dict, season: str, r2: object | None = None, bucket: str = "", prefix: str = "") -> Path:
    """Local file (atomic), then the R2 object when a client is given."""
    path = local_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))
    if r2 is not None:
        r2.upload_file(str(path), bucket, r2_key(prefix, season))  # type: ignore[attr-defined]
    return path

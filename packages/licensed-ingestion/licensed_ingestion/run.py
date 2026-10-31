"""One ingestion pass: provider reads -> crosswalk -> derived tables -> an immutable licensed build.

A daily pass rebuilds the crosswalk from its own squad reads. A matchday or deadline pass reads one PL window and
no squads, so it reuses the previous build's crosswalk (and the store carries the cup tables forward):
rebuilding from an empty squad read would wipe the crosswalk and drop every lineup row as unmatched.
"""
from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from football_intelligence.ingestion.licensed.crosswalk import build_crosswalk
from football_intelligence.ingestion.licensed.derive import (
    LINEUP_CONFIRMED_TYPE_ID, DeriveReport, DerivedTables, derive, team_codes_from,
)
from football_intelligence.ingestion.licensed.player_stats import unresolved_columns
from football_intelligence.ingestion.licensed.store import read_table, write_build
from football_intelligence.ingestion.live_trial import fixture_status
from sportmonks_client.client import SportmonksClient

from . import fetch
from .fpl import FplFeed

PASSES = ("daily", "matchday", "deadline", "backfill")


class NoBaseline(RuntimeError):
    """A matchday or deadline pass needs a previous build to take the crosswalk from; run a daily pass first."""


def season_of(day: date) -> str:
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def previous_crosswalk(build: Path) -> dict[int, int]:
    frame = pd.read_parquet(build / "datasets/crosswalk.parquet")
    return {int(k): int(v) for k, v in zip(frame.sportmonks_player_id, frame.element)}


def previous_stat_types(build: Path | None) -> dict[int, str]:
    """The statistic names the last build learned (empty for a first build or one that predates the table)."""
    if build is None:
        return {}
    frame = read_table(build, "stat_types")
    return {int(k): str(v) for k, v in zip(frame.type_id, frame.name)}


def resolve_stat_types(client: SportmonksClient, fixtures: Sequence[Mapping[str, Any]], known: dict[int, str],
                       summary: dict[str, Any]) -> tuple[dict[int, str], dict[int, str]]:
    """The type map to derive with, and the names learned this pass. The provider is asked ONLY when a finished
    fixture carries a type id the map does not know (this includes an empty map), once per pass, from the finished
    fixture whose details carry the most unknown ids (so later passes keep learning instead of re-reading one match).
    An id still unknown after that is left out of the statistics and counted. ``summary`` gets counts, plus the
    curated statistic names still unknown (written as ``None``, never zero): names of measures, no player data."""
    carrying = [f for f in fixtures if fixture_status(f) == "completed"
                and any(r.get("details") for r in f.get("lineups") or [])]
    seen = {i for f in carrying for i in _type_ids(f)}
    learned: dict[int, str] = {}
    called = bool(seen - set(known))
    if called:
        best = max(carrying, key=lambda f: len(_type_ids(f) - set(known)))   # first on a tie: deterministic
        learned = fetch.stat_types(client, int(best["id"]))
    names = {**known, **learned}
    summary["stat_types"] = {"known": len(names), "learned": len(set(learned) - set(known)), "provider_calls": int(called),
                             "unknown_after": len(seen - set(names)),
                             "columns_unresolved": unresolved_columns(names) if carrying else []}
    return names, learned


def _type_ids(fixture: Mapping[str, Any]) -> set[int]:
    return {d.get("type_id") for r in fixture.get("lineups") or [] for d in r.get("details") or []
            if isinstance(d.get("type_id"), int)}


def latest_build(root: Path) -> Path | None:
    """The newest build under ``root/builds`` by its manifest's ``built_at`` (local runs only)."""
    builds = [p for p in (root / "builds").glob("*") if (p / "manifest.json").is_file()] if (root / "builds").is_dir() else []
    if not builds:
        return None
    return max(builds, key=lambda p: (json.loads((p / "manifest.json").read_text(encoding="utf-8"))["built_at"], p.name))


def season_first_day(feed: FplFeed) -> date | None:
    """The day of the season's first kickoff, from the free FPL fixture list (None when it has no kickoffs)."""
    kickoffs = feed.kickoffs()
    return min(kickoffs).date() if kickoffs else None


def _as_final(fixture: Mapping[str, Any]) -> dict[str, Any]:
    """A completed match's stored lineup is the XI that was played, so it is a confirmed lineup whatever the provider's
    flag still says after full time (the flag describes the announcement, and a finished match has none pending)."""
    metadata = [m for m in fixture.get("metadata") or [] if m.get("type_id") != LINEUP_CONFIRMED_TYPE_ID]
    metadata.append({"type_id": LINEUP_CONFIRMED_TYPE_ID, "values": {"confirmed": True}})
    return {**fixture, "metadata": metadata}


def _merge(parts: Sequence[DerivedTables]) -> DerivedTables:
    report = DeriveReport()
    for part in parts:
        for name, value in asdict(part.report).items():
            if isinstance(value, int):
                setattr(report, name, getattr(report, name) + value)
    return DerivedTables(
        lineup_snapshots=tuple(r for p in parts for r in p.lineup_snapshots),
        lineup_slots=tuple(r for p in parts for r in p.lineup_slots),
        sidelined=(), squad_membership=(), cup_snapshots=(), report=report,
        player_match_stats=tuple(r for p in parts for r in p.player_match_stats))


def _backfill_tables(reads: fetch.ProviderReads, feed: FplFeed, crosswalk: dict[int, int],
                     summary: dict[str, Any], names: Mapping[int, str]) -> DerivedTables:
    """Derive the finished matches of the windows, one kickoff day at a time.

    ``observed_at`` is the MORNING AFTER the kickoff day (00:00:00Z), not the time of the read. Two consequences, both
    on purpose: re-running the backfill, today or next week, produces the same keys, so the store's de-duplication on
    the full key makes it idempotent; and a backfilled row can never read as knowledge from before the match. Only
    completed matches are kept: a postponed or unfinished fixture would otherwise enter history as a provisional XI
    under a stamp that a later, real observation of the same match could never replace.
    """
    finished = [f for f in reads.pl_fixtures if fixture_status(f) == "completed"]
    summary["backfill"] = {"fixtures_read": len(reads.pl_fixtures), "fixtures_completed": len(finished),
                           "fixtures_skipped_not_completed": len(reads.pl_fixtures) - len(finished)}
    by_day: dict[str, list[dict[str, Any]]] = {}
    for fixture in finished:
        by_day.setdefault(str(fixture["starting_at"])[:10], []).append(_as_final(fixture))
    parts = []
    for day in sorted(by_day):
        observed = (date.fromisoformat(day) + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
        parts.append(derive(observed_at=observed, season=season_of(date.fromisoformat(day)), pl_fixtures=by_day[day],
                            squads=[], sidelined=[], team_fixtures=[], fpl_fixtures=feed.fpl_fixtures(),
                            team_codes={}, crosswalk=crosswalk, stat_type_names=names))
    return _merge(parts)


def run_pass(kind: str, client: SportmonksClient, feed: FplFeed, root: Path, *, now: datetime,
             previous: Path | None, aliases: Sequence[dict[str, Any]] = (),
             since: date | None = None) -> tuple[Path, dict[str, Any]]:
    """Build one pass under ``root``. Returns the build and a summary of COUNTS only (it is logged publicly).

    ``since`` narrows a backfill to start later than the season's first kickoff; other passes ignore it."""
    if kind not in PASSES:
        raise ValueError("unknown pass")
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    summary: dict[str, Any] = {"pass": kind}
    if kind == "backfill":
        if previous is None:
            raise NoBaseline("no previous licensed build")
        first = max(filter(None, (season_first_day(feed), since)), default=None)
        windows = fetch.backfill_windows(first, now.date() - timedelta(days=1)) if first else []
        summary["windows"] = len(windows)
        crosswalk = previous_crosswalk(previous)
        reads = fetch.backfill(client, windows)
        names, learned = resolve_stat_types(client, reads.pl_fixtures, previous_stat_types(previous), summary)
        tables = replace(_backfill_tables(reads, feed, crosswalk, summary, names), stat_types=learned)
        build = write_build(tables, crosswalk, root, build_id=f"backfill-{now:%Y%m%dt%H%M%S}", built_at=stamp,
                            previous=previous, carry_state=True)
        summary["derive"] = {k: v for k, v in asdict(tables.report).items() if k != "rows"}
        summary["rows"] = json.loads((build / "manifest.json").read_text(encoding="utf-8"))["row_counts"]
        return build, summary
    if kind == "daily":
        reads = fetch.daily(client, now.date())
        summary["cup_window"] = reads.cup_window_summary()
        cross = build_crosswalk(reads.players, feed.elements, aliases)
        crosswalk = dict(cross.pairs)
        codes = team_codes_from(reads.teams)
        report = asdict(cross.report)
        summary["crosswalk"] = {**{k: report[k] for k in ("pool", "pool_resolved", "elements_with_minutes",
                                                          "with_minutes_resolved", "by_method", "aliases_accepted",
                                                          "aliases_rejected")},
                                "rate_with_minutes_percent": cross.report.rate_with_minutes_percent}
    else:
        if previous is None:
            raise NoBaseline("no previous licensed build")
        reads = fetch.deadline(client, now.date()) if kind == "deadline" else fetch.matchday(client, now)
        crosswalk = previous_crosswalk(previous)
        codes = {}
    names, learned = resolve_stat_types(client, reads.pl_fixtures, previous_stat_types(previous), summary)
    tables = derive(observed_at=stamp, season=season_of(now.date()), pl_fixtures=reads.pl_fixtures,
                    squads=reads.squads, sidelined=reads.sidelined, team_fixtures=reads.team_fixtures,
                    fpl_fixtures=feed.fpl_fixtures(), team_codes=codes, crosswalk=crosswalk,
                    stat_type_names=names)
    tables = replace(tables, stat_types=learned)
    build = write_build(tables, crosswalk, root, build_id=f"{kind}-{now:%Y%m%dt%H%M%S}", built_at=stamp,
                        previous=previous, carry_state=kind != "daily")
    derived = asdict(tables.report)
    summary["derive"] = {k: v for k, v in derived.items() if k != "rows"}
    summary["rows"] = json.loads((build / "manifest.json").read_text(encoding="utf-8"))["row_counts"]
    return build, summary

"""One ingestion pass: provider reads -> crosswalk -> derived tables -> an immutable licensed build.

A daily pass rebuilds the crosswalk from its own squad reads. A matchday or deadline pass reads one PL window and
no squads, so it reuses the previous build's crosswalk (and the store carries the cup tables forward):
rebuilding from an empty squad read would wipe the crosswalk and drop every lineup row as unmatched.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from football_intelligence.ingestion.licensed.crosswalk import build_crosswalk
from football_intelligence.ingestion.licensed.derive import derive, team_codes_from
from football_intelligence.ingestion.licensed.store import write_build
from sportmonks_client.client import SportmonksClient

from . import fetch
from .fpl import FplFeed

PASSES = ("daily", "matchday", "deadline")


class NoBaseline(RuntimeError):
    """A matchday or deadline pass needs a previous build to take the crosswalk from; run a daily pass first."""


def season_of(day: date) -> str:
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def previous_crosswalk(build: Path) -> dict[int, int]:
    frame = pd.read_parquet(build / "datasets/crosswalk.parquet")
    return {int(k): int(v) for k, v in zip(frame.sportmonks_player_id, frame.element)}


def latest_build(root: Path) -> Path | None:
    """The newest build under ``root/builds`` by its manifest's ``built_at`` (local runs only)."""
    builds = [p for p in (root / "builds").glob("*") if (p / "manifest.json").is_file()] if (root / "builds").is_dir() else []
    if not builds:
        return None
    return max(builds, key=lambda p: (json.loads((p / "manifest.json").read_text(encoding="utf-8"))["built_at"], p.name))


def run_pass(kind: str, client: SportmonksClient, feed: FplFeed, root: Path, *, now: datetime,
             previous: Path | None, aliases: Sequence[dict[str, Any]] = ()) -> tuple[Path, dict[str, Any]]:
    """Build one pass under ``root``. Returns the build and a summary of COUNTS only (it is logged publicly)."""
    if kind not in PASSES:
        raise ValueError("unknown pass")
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    summary: dict[str, Any] = {"pass": kind}
    if kind == "daily":
        reads = fetch.daily(client, now.date())
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
    tables = derive(observed_at=stamp, season=season_of(now.date()), pl_fixtures=reads.pl_fixtures,
                    squads=reads.squads, sidelined=reads.sidelined, team_fixtures=reads.team_fixtures,
                    fpl_fixtures=feed.fpl_fixtures(), team_codes=codes, crosswalk=crosswalk)
    build = write_build(tables, crosswalk, root, build_id=f"{kind}-{now:%Y%m%dt%H%M%S}", built_at=stamp,
                        previous=previous, carry_state=kind != "daily")
    derived = asdict(tables.report)
    summary["derive"] = {k: v for k, v in derived.items() if k != "rows"}
    summary["rows"] = json.loads((build / "manifest.json").read_text(encoding="utf-8"))["row_counts"]
    return build, summary

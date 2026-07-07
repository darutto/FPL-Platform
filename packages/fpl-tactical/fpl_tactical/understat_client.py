"""
fpl_tactical.understat_client
=============================
Thin wrapper around ``soccerdata.Understat`` (T1a decision — DECISIONS.md).

soccerdata is imported lazily inside :meth:`UnderstatClient.fetch_raw` so that
importing ``fpl_tactical`` never pulls it in: soccerdata is a weekly-workflow
(build-time) dependency only — the serving deployment reads the parquet store
and must never receive soccerdata as a runtime dependency.

This module is the ONLY network touchpoint in the package. It returns the two
raw soccerdata frames (shots + schedule) with their MultiIndex reset;
normalization into the owned schema is a pure function in ``ingest.py`` so
tests can exercise it against canned frames with no network.
"""

from __future__ import annotations

from typing import Tuple

import pandas as pd

# soccerdata league key for the English Premier League
DEFAULT_LEAGUE: str = "ENG-Premier League"

SOURCE_NAME: str = "understat via soccerdata"


class UnderstatClient:
    """Fetch Understat shot events + schedule for one league via soccerdata."""

    def __init__(self, league: str = DEFAULT_LEAGUE) -> None:
        self.league = league

    def fetch_raw(self, season: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Return ``(shots, schedule)`` for *season* (key style "2025-2026").

        Both frames come back ``reset_index()``-ed, exactly as soccerdata
        produced them otherwise. Network + local soccerdata cache
        (``~/soccerdata/data/Understat``) are touched here and only here.
        """
        import soccerdata as sd  # lazy: weekly-workflow dependency only

        understat = sd.Understat(leagues=self.league, seasons=season)
        shots = understat.read_shot_events().reset_index()
        schedule = understat.read_schedule().reset_index()
        return shots, schedule

    @staticmethod
    def source_version() -> str:
        """Return the installed soccerdata version for provenance."""
        import soccerdata as sd  # lazy: weekly-workflow dependency only

        return getattr(sd, "__version__", "unknown")

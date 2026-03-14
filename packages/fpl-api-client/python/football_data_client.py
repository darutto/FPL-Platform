"""
fpl-api-client · packages/fpl-api-client/python/football_data_client.py
========================================================================
HTTP client for the football-data.org API (v4).

SOURCE:  Extracted and generalised from:
  - FPL-team-stats/app.py                            (FOOTBALL_DATA_BASE_URL,
                                                      get_competition_data, get_matches_data)
  - FPL-team-stats/football-proxy-server/src/routes/api.js  (same logic, Node.js port)

REPLACES (do NOT delete originals until migration is approved):
  - FPL-team-stats/app.py                → import from this module instead of inline requests
  - FPL-team-stats/football-proxy-server → can be retired once apps call this directly

CONSUMERS AFTER MIGRATION:
  - FPL-team-stats/app.py (slim Flask wrapper that uses this client)
  - fpl-platform/apps/team-stats-explorer backend
"""

from __future__ import annotations

import os
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://api.football-data.org/v4/"
PREMIER_LEAGUE_ID = 2021  # Competition ID for the English Premier League

# Auth header name required by football-data.org
_AUTH_HEADER = "X-Auth-Token"


class FootballDataClient:
    """Simple client for football-data.org API v4.

    Usage:
        client = FootballDataClient(api_key=os.environ["FOOTBALL_DATA_API_KEY"])
        competition = client.get_competition()
        matches = client.get_matches()

    SOURCE: FPL-team-stats/app.py — routes get_competition_data, get_matches_data (lines 17-51)
    """

    def __init__(self, api_key: str | None = None, competition_id: int = PREMIER_LEAGUE_ID):
        """
        Args:
            api_key:        football-data.org API key. Falls back to
                            FOOTBALL_DATA_API_KEY env variable.
            competition_id: Defaults to Premier League (2021).
        """
        self.api_key = api_key or os.environ.get("FOOTBALL_DATA_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "football-data.org API key required. "
                "Pass api_key= or set FOOTBALL_DATA_API_KEY env variable."
            )
        self.competition_id = competition_id
        self._headers = {_AUTH_HEADER: self.api_key}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Make a GET request and return parsed JSON.

        Raises:
            requests.HTTPError on non-2xx status
        """
        url = f"{BASE_URL}{path}"
        resp = requests.get(url, headers=self._headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Competition
    # ------------------------------------------------------------------

    def get_competition(self) -> dict[str, Any]:
        """Return competition metadata including the current matchday.

        SOURCE: FPL-team-stats/app.py::get_competition_data (lines 17-32)
        SOURCE: FPL-team-stats/football-proxy-server/routes/api.js::router.get('/matchday') (lines 10-29)
        """
        return self._get(f"competitions/{self.competition_id}")

    def get_current_matchday(self) -> int:
        """Return the current matchday number.

        SOURCE: FPL-team-stats/football-proxy-server/routes/api.js (line 24: data.currentSeason.currentMatchday)
        """
        data = self.get_competition()
        return data["currentSeason"]["currentMatchday"]

    # ------------------------------------------------------------------
    # Matches
    # ------------------------------------------------------------------

    def get_matches(self, matchday: int | None = None) -> list[dict[str, Any]]:
        """Return all matches for the season, optionally filtered to a matchday.

        SOURCE: FPL-team-stats/app.py::get_matches_data (lines 34-51)

        Args:
            matchday: If provided, return only this matchday's matches.
        """
        params = {}
        if matchday is not None:
            params["matchday"] = matchday
        data = self._get(f"competitions/{self.competition_id}/matches", params=params)
        return data.get("matches", [])

    def get_finished_matches(
        self,
        from_matchday: int = 1,
        to_matchday: int = 38,
    ) -> list[dict[str, Any]]:
        """Return FINISHED matches within a matchday range.

        SOURCE: FPL-team-stats/script.js::calculateTeamStats filter logic (lines 129-140)

        Args:
            from_matchday: First matchday to include (inclusive).
            to_matchday:   Last matchday to include (inclusive).
        """
        all_matches = self.get_matches()
        return [
            m for m in all_matches
            if m.get("status") == "FINISHED"
            and from_matchday <= m.get("matchday", 0) <= to_matchday
        ]



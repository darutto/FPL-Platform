"""
fpl-api-client · packages/fpl-api-client/python/fpl_client.py
==============================================================
Unified HTTP client for the official Fantasy Premier League API.

SOURCE:  Extracted and generalised from:
  - fpl-video-repurposer/build_fpl_kb.py  (fetch_json, BOOTSTRAP_URL, FIXTURES_URL,
                                           build_master_squad, build_next_fixture_map)

REPLACES (do NOT delete originals until migration is approved):
  - fpl-video-repurposer/build_fpl_kb.py  → import from this module instead

CONSUMERS AFTER MIGRATION:
  - fpl-video-repurposer/build_fpl_kb.py
  - captaincy-ml pipelines that need live FPL data
  - fpl-platform/pipelines/build_player_registry.py
"""

from __future__ import annotations

import time
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Endpoint constants
# ---------------------------------------------------------------------------

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/?event={gameweek}"
ELEMENT_SUMMARY_URL = "https://fantasy.premierleague.com/api/element-summary/{player_id}/"

# Default HTTP settings
_DEFAULT_TIMEOUT = 30
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = 2.0  # seconds, doubles each attempt


# ---------------------------------------------------------------------------
# Low-level fetch helper
# ---------------------------------------------------------------------------

def fetch_json(url: str, timeout: int = _DEFAULT_TIMEOUT) -> Any:
    """Fetch a URL and return parsed JSON.

    Raises:
        requests.HTTPError: on non-2xx responses after retries
        requests.ConnectionError: on network failure after retries

    SOURCE: fpl-video-repurposer/build_fpl_kb.py::fetch_json (lines 22-26)
    """
    last_exc: Exception | None = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except (requests.HTTPError, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt < _RETRY_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF * attempt)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Bootstrap data (players + teams + gameweek events)
# ---------------------------------------------------------------------------

def get_bootstrap() -> dict[str, Any]:
    """Return the full FPL bootstrap-static response.

    Contains:
      - elements      → all players with stats, status, ownership, xG/xA
      - teams         → team names, codes, strengths, fixtures difficulty
      - events        → gameweek events (deadline, is_finished, etc.)
      - element_types → position definitions (1=GKP, 2=DEF, 3=MID, 4=FWD)

    SOURCE: fpl-video-repurposer/build_fpl_kb.py::main (line 104)
    """
    return fetch_json(BOOTSTRAP_URL)


def get_players(bootstrap: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return a lightweight player list from bootstrap.

    Each entry contains:
        id, first_name, second_name, web_name, team_id,
        element_type (position), status, now_cost, selected_by_percent,
        form, expected_goals, expected_assists, expected_goal_involvements

    SOURCE: fpl-video-repurposer/build_fpl_kb.py::build_master_squad (lines 38-50)
    """
    if bootstrap is None:
        bootstrap = get_bootstrap()
    return [
        {
            "id":           e["id"],
            "first_name":   e["first_name"],
            "second_name":  e["second_name"],
            "web_name":     e["web_name"],
            "team_id":      e["team"],
            "team_code":    e.get("team_code"),
            "element_type": e["element_type"],
            "status":       e["status"],
            "now_cost":     e.get("now_cost"),
            "selected_by_percent": e.get("selected_by_percent"),
            "form":         e.get("form"),
            "expected_goals":           e.get("expected_goals"),
            "expected_assists":         e.get("expected_assists"),
            "expected_goal_involvements": e.get("expected_goal_involvements"),
        }
        for e in bootstrap["elements"]
    ]


def get_teams(bootstrap: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return team list from bootstrap.

    SOURCE: fpl-video-repurposer/build_fpl_kb.py::build_master_squad (lines 51-56)
    """
    if bootstrap is None:
        bootstrap = get_bootstrap()
    return [
        {
            "id":         t["id"],
            "name":       t["name"],
            "short_name": t["short_name"],
            "code":       t.get("code"),
            "strength":   t.get("strength"),
        }
        for t in bootstrap["teams"]
    ]


def get_current_gameweek(bootstrap: dict[str, Any] | None = None) -> int | None:
    """Return the current (next unfinished) gameweek number, or None if season over.

    SOURCE: New helper based on bootstrap events array.
    """
    if bootstrap is None:
        bootstrap = get_bootstrap()
    for event in bootstrap.get("events", []):
        if event.get("is_current"):
            return event["id"]
    for event in bootstrap.get("events", []):
        if event.get("is_next"):
            return event["id"]
    return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def get_fixtures(gameweek: int) -> list[dict[str, Any]]:
    """Return fixture list for a specific gameweek.

    SOURCE: fpl-video-repurposer/build_fpl_kb.py::build_next_fixture_map
    """
    return fetch_json(FIXTURES_URL.format(gameweek=gameweek))


def get_fixture_difficulty_map(
    gameweek: int,
    teams: list[dict[str, Any]] | None = None,
    bootstrap: dict[str, Any] | None = None,
) -> dict[int, int]:
    """Return {team_id: fixture_difficulty} for a given gameweek.

    Difficulty is opponent strength (2-5 scale). Returns 3 (neutral) for
    double gameweeks or blank gameweeks.

    SOURCE: captaincy-showdown/src/services/captaincyDataService.ts::getFixtureDifficulty
    """
    if teams is None:
        teams = get_teams(bootstrap)

    team_strength: dict[int, int] = {t["id"]: t.get("strength", 3) for t in teams}
    fixtures = get_fixtures(gameweek)

    difficulty_map: dict[int, int] = {}
    for fix in fixtures:
        home_id = fix["team_h"]
        away_id = fix["team_a"]
        difficulty_map[home_id] = team_strength.get(away_id, 3)
        difficulty_map[away_id] = team_strength.get(home_id, 3)

    return difficulty_map


# ---------------------------------------------------------------------------
# Player element summary (match-by-match history)
# ---------------------------------------------------------------------------

def get_player_history(player_id: int) -> dict[str, Any]:
    """Return a player's element summary (history, fixtures, history_past).

    SOURCE: New helper; not yet used by any project but needed for chat interface.
    """
    return fetch_json(ELEMENT_SUMMARY_URL.format(player_id=player_id))



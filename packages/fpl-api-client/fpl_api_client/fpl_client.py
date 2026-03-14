"""
fpl_api_client.fpl_client
==========================
Bootstrap-only HTTP client for the official FPL API.

Phase 1c surface — bootstrap only:
    fetch_json()             Low-level fetch with retry
    get_bootstrap()          Full bootstrap-static response
    get_players(bootstrap)   Lightweight player list derived from bootstrap
    get_teams(bootstrap)     Team list derived from bootstrap
    get_current_gameweek()   Current / next gameweek number

Excluded from this slice (Phase 2+):
    get_fixtures, get_fixture_difficulty_map, get_player_history

Reference: fpl-api-client/python/fpl_client.py (audit copy — do not modify)
Sources:   fpl-video-repurposer/build_fpl_kb.py (fetch_json, build_master_squad)
           captaincy-showdown/src/services/captaincyDataService.ts (gameweek logic)
"""

from __future__ import annotations

import time
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Endpoint constants  (bootstrap slice only)
# ---------------------------------------------------------------------------

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"

# Default HTTP settings
_DEFAULT_TIMEOUT: int = 30
_RETRY_ATTEMPTS: int = 3
_RETRY_BACKOFF: float = 2.0  # seconds; multiplied by attempt number


# ---------------------------------------------------------------------------
# Low-level fetch helper
# ---------------------------------------------------------------------------

def fetch_json(url: str, timeout: int = _DEFAULT_TIMEOUT) -> Any:
    """Fetch *url* and return parsed JSON.

    Retries up to ``_RETRY_ATTEMPTS`` times with linear back-off on
    ``HTTPError`` or ``ConnectionError``.

    Raises:
        requests.HTTPError:      on non-2xx response after all retries
        requests.ConnectionError: on network failure after all retries

    Source: fpl-video-repurposer/build_fpl_kb.py::fetch_json (adapted — retry
            loop added; original had a single bare requests.get call)
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
# Bootstrap data
# ---------------------------------------------------------------------------

def get_bootstrap() -> dict[str, Any]:
    """Return the full FPL bootstrap-static response.

    The bootstrap payload contains:
      - ``elements``      — all players (stats, status, ownership, xG/xA)
      - ``teams``         — team names, codes, strengths
      - ``events``        — gameweek events (deadline, is_current, is_next, …)
      - ``element_types`` — position definitions (1=GKP 2=DEF 3=MID 4=FWD)

    Callers should store the result and pass it to ``get_players()``,
    ``get_teams()``, and ``get_current_gameweek()`` to avoid redundant
    network calls.

    Source: fpl-video-repurposer/build_fpl_kb.py::main (line 104)
    """
    return fetch_json(BOOTSTRAP_URL)


def get_players(bootstrap: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return a lightweight player list derived from *bootstrap*.

    If *bootstrap* is ``None``, ``get_bootstrap()`` is called automatically.

    Each entry contains:
        ``id``, ``first_name``, ``second_name``, ``web_name``,
        ``team_id``, ``team_code``, ``element_type``, ``status``,
        ``now_cost``, ``selected_by_percent``, ``form``,
        ``expected_goals``, ``expected_assists``,
        ``expected_goal_involvements``

    Source: fpl-video-repurposer/build_fpl_kb.py::build_master_squad (lines 38–50)
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
            "expected_goals":             e.get("expected_goals"),
            "expected_assists":           e.get("expected_assists"),
            "expected_goal_involvements": e.get("expected_goal_involvements"),
        }
        for e in bootstrap["elements"]
    ]


def get_teams(bootstrap: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return team list derived from *bootstrap*.

    If *bootstrap* is ``None``, ``get_bootstrap()`` is called automatically.

    Each entry contains:
        ``id``, ``name``, ``short_name``, ``code``, ``strength``

    Source: fpl-video-repurposer/build_fpl_kb.py::build_master_squad (lines 51–56)
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
    """Return the current (or next) gameweek number from *bootstrap*.

    Resolution order:
    1. First event where ``is_current`` is truthy → current live GW
    2. First event where ``is_next`` is truthy    → upcoming GW (between GWs)
    3. ``None``                                   → season not started / over

    If *bootstrap* is ``None``, ``get_bootstrap()`` is called automatically.

    Source: new helper; logic derived from bootstrap ``events`` array shape
            confirmed in FPL-Elo-Insights data (2025–26 season).
    """
    if bootstrap is None:
        bootstrap = get_bootstrap()
    events: list[dict[str, Any]] = bootstrap.get("events", [])
    for event in events:
        if event.get("is_current"):
            return int(event["id"])
    for event in events:
        if event.get("is_next"):
            return int(event["id"])
    return None



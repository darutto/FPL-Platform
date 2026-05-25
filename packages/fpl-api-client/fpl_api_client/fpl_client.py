"""
fpl_api_client.fpl_client
==========================
HTTP client for the official FPL API.

Phase 1c surface — bootstrap only:
    fetch_json()             Low-level fetch with retry
    get_bootstrap()          Full bootstrap-static response
    get_players(bootstrap)   Lightweight player list derived from bootstrap
    get_teams(bootstrap)     Team list derived from bootstrap
    get_current_gameweek()   Current / next gameweek number

Phase 4a additions — fixtures:
    get_fixtures(gameweek)                       GW fixture list (live)
    get_fixture_difficulty_map(fixtures, bootstrap)  {team_id: fdr} map

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

BOOTSTRAP_URL       = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_URL        = "https://fantasy.premierleague.com/api/fixtures/?event={gameweek}"
ALL_FIXTURES_URL    = "https://fantasy.premierleague.com/api/fixtures/"
ELEMENT_SUMMARY_URL = "https://fantasy.premierleague.com/api/element-summary/{element_id}/"
EVENT_LIVE_URL      = "https://fantasy.premierleague.com/api/event/{gameweek}/live/"

# Default HTTP settings
_DEFAULT_TIMEOUT: int = 30
_RETRY_ATTEMPTS: int = 3
_RETRY_BACKOFF: float = 2.0  # seconds; multiplied by attempt number

# Per-request timeout for element-summary calls.
# Tighter than _DEFAULT_TIMEOUT because element-summary is a lightweight
# per-player endpoint; 4 s is generous for a single JSON payload.
# The player_form handler enforces a stricter *total* latency budget on top of
# this via its own ThreadPoolExecutor gate.
ELEMENT_SUMMARY_TIMEOUT_S: int = 4


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


# ---------------------------------------------------------------------------
# Fixtures  (Phase 4a)
# ---------------------------------------------------------------------------

def get_element_summary(element_id: int) -> dict[str, Any]:
    """Return the per-player element summary from the FPL API.

    The response contains a ``history`` array with one entry per gameweek
    played, and a ``fixtures`` array with upcoming fixtures.  Each ``history``
    entry includes: ``round`` (GW number), ``minutes``, ``goals_scored``,
    ``assists``, ``bonus``, ``total_points``, ``was_home``, etc.

    Uses ``ELEMENT_SUMMARY_TIMEOUT_S`` (4 s) per request, tighter than the
    default 30 s bootstrap timeout.  The player_form handler wraps this call
    inside a separate total-latency budget gate.

    Parameters
    ----------
    element_id:
        The FPL element (player) integer id.

    Source: FPL API — element-summary/{id}/ endpoint
    """
    return fetch_json(
        ELEMENT_SUMMARY_URL.format(element_id=element_id),
        timeout=ELEMENT_SUMMARY_TIMEOUT_S,
    )


def get_fixtures(gameweek: int) -> list[dict[str, Any]]:
    """Return the fixture list for *gameweek* from the FPL API.

    Each fixture dict contains at minimum ``team_h`` (home team id),
    ``team_a`` (away team id), and ``event`` (gameweek number).

    Source: fpl-api-client/python/fpl_client.py::get_fixtures
    """
    return fetch_json(FIXTURES_URL.format(gameweek=gameweek))


def get_all_fixtures() -> list[dict[str, Any]]:
    """Return all fixtures for the current season from the FPL API.

    Unlike ``get_fixtures(gameweek)``, this call fetches every fixture
    across all gameweeks in one request (no ``?event=`` filter applied).
    Each fixture dict contains at minimum ``id``, ``team_h`` (home team
    id), ``team_a`` (away team id), and ``event`` (gameweek number).

    Source: fpl-api-client — ALL_FIXTURES_URL (Track A H1 historical pipeline)
    """
    return fetch_json(ALL_FIXTURES_URL)


def get_event_live(gameweek: int) -> dict[str, Any]:
    """Return the live event data for *gameweek* from the FPL API.

    The response is a JSON object with a top-level ``elements`` key
    containing a list of per-player entries for the given gameweek.
    Each entry has the following shape::

        {
            "id":       <int>,          # FPL element (player) id
            "stats":    { ... },        # live cumulative stats for the GW
            "explain":  [ ... ],        # bonus point breakdown per fixture
            "modified": <bool>          # True when stats were last updated live
        }

    Parameters
    ----------
    gameweek:
        The gameweek number (1–38).

    Source: FPL API — event/{gameweek}/live/ endpoint
            (Track A H2a incremental GW puller)
    """
    return fetch_json(EVENT_LIVE_URL.format(gameweek=gameweek))


def get_fixture_difficulty_map(
    fixtures: list[dict[str, Any]],
    bootstrap: dict[str, Any],
) -> dict[int, int]:
    """Return ``{team_id: fdr}`` for every team appearing in *fixtures*.

    FDR (fixture difficulty rating) = opponent team's ``strength`` from the
    bootstrap teams array (1–5 scale).  Teams absent from *fixtures* (blank
    gameweek) are absent from the returned dict.

    Parameters
    ----------
    fixtures:
        Fixture list for a single gameweek (e.g. from ``get_fixtures()``).
    bootstrap:
        FPL bootstrap dict containing a ``teams`` array with ``strength``
        values.

    Source: captaincy-showdown/src/services/captaincyDataService.ts::getFixtureDifficulty
    """
    strength_by_id: dict[int, int] = {
        t["id"]: t.get("strength", 3)
        for t in bootstrap.get("teams", [])
    }
    fdr_map: dict[int, int] = {}
    for fix in fixtures:
        home_id = fix["team_h"]
        away_id = fix["team_a"]
        fdr_map[home_id] = strength_by_id.get(away_id, 3)
        fdr_map[away_id] = strength_by_id.get(home_id, 3)
    return fdr_map



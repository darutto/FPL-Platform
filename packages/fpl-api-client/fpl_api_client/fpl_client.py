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

Reference: fpl-api-client/audit-reference/fpl_client.py (audit copy — do not modify)
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
ENTRY_PICKS_URL      = "https://fantasy.premierleague.com/api/entry/{team_id}/event/{gameweek}/picks/"

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

# Per-request timeout for entry-picks calls.
# Same rationale as ELEMENT_SUMMARY_TIMEOUT_S: a single small per-team JSON
# payload, called on-demand only when a squad-related question needs it.
ENTRY_PICKS_TIMEOUT_S: int = 6


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


FORM_INFORMATIVE_THRESHOLD = 0.05  # ≥5% of elements carrying real form


def is_form_informative(bootstrap: dict[str, Any]) -> bool:
    """Return False while ``form`` is still empty for ~everyone in *bootstrap*
    — preseason, or the narrow post-kickoff window before GW1 results are
    processed.

    Deliberately checks ``form`` itself, population-wide, rather than
    ``is_current``/``get_current_gameweek``: ``minutes``/``starts`` reset to
    0 at season rollover around the same moment a gameweek turns
    ``is_current``, so gating on that flag instead of on ``form`` would
    switch consumers off a preseason-aware code path right as ``form`` is
    still 0 but ``minutes``-derived rates have just collapsed too — a worse
    window than the one being fixed. ``form`` and ``minutes`` are expected to
    become meaningful together, since both come from the same GW1 results.

    Must be evaluated over the whole population, never per-player — one
    legitimately out-of-form player having ``form == 0`` mid-season must not
    read as "the season hasn't started".
    """
    elements: list[dict[str, Any]] = bootstrap.get("elements", [])
    if not elements:
        return True  # missing/incomplete data: don't guess, assume normal
    non_zero = sum(1 for e in elements if float(e.get("form") or 0) > 0)
    return (non_zero / len(elements)) >= FORM_INFORMATIVE_THRESHOLD


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

    Source: fpl-api-client/audit-reference/fpl_client.py::get_fixtures
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


def get_entry_picks(team_id: int, gameweek: int) -> dict[str, Any]:
    """Return one manager's squad picks for *gameweek* from the FPL API.

    The response contains a ``picks`` array (15 entries, ``element`` id +
    ``position`` 1-15, ``is_captain``, ``is_vice_captain``, ``multiplier``)
    and an ``entry_history`` object (``points``, ``total_points``, ``bank``,
    ``event_transfers``, ``event_transfers_cost``). ``active_chip`` is
    ``None`` or one of the FPL chip codes (``"wildcard"``, ``"3xc"``,
    ``"bboost"``, ``"freehit"``) when a chip was played that gameweek.

    Raises the same ``requests.HTTPError`` / ``requests.ConnectionError`` as
    ``fetch_json`` on failure — including a 404 for an unknown ``team_id`` or
    a ``gameweek`` the manager has no picks for (e.g. before their team was
    created). Callers must catch these; this function does not degrade them
    to a status dict itself.

    Parameters
    ----------
    team_id:
        The FPL manager (entry) integer id.
    gameweek:
        The gameweek number (1-38) to fetch picks for.

    Source: FPL API — entry/{id}/event/{gw}/picks/ endpoint
            (packages/fpl-ui/app/api/fpl-squad/[teamId]/route.ts uses the
            same endpoint for the U2 pitch view)
    """
    return fetch_json(
        ENTRY_PICKS_URL.format(team_id=team_id, gameweek=gameweek),
        timeout=ENTRY_PICKS_TIMEOUT_S,
    )


def get_fixture_difficulty_map(
    fixtures: list[dict[str, Any]],
    bootstrap: dict[str, Any],
) -> dict[int, int]:
    """Return ``{team_id: fdr}`` for every team appearing in *fixtures*.

    FDR (fixture difficulty rating) is taken from the fixture's own
    ``team_h_difficulty`` / ``team_a_difficulty`` fields — the canonical FPL
    per-fixture difficulty (1–5), the same source the fixtures calendar uses.
    These are populated from GW1 onward, unlike the aggregate team ``strength``
    field which the API leaves null pre-season.

    When a fixture is missing those fields, we fall back to the opponent team's
    ``strength`` (with a neutral 3 default when that too is null/absent), so the
    map always yields a usable integer.  Teams absent from *fixtures* (blank
    gameweek) are absent from the returned dict.

    Parameters
    ----------
    fixtures:
        Fixture list for a single gameweek (e.g. from ``get_fixtures()``).
    bootstrap:
        FPL bootstrap dict containing a ``teams`` array (used for the
        strength fallback only).

    Source: captaincy-showdown/src/services/captaincyDataService.ts::getFixtureDifficulty
    """
    # `strength` (and per-fixture difficulty) can be present-but-null pre-season
    # — the FPL API ships teams/fixtures before ratings are published, so a
    # plain `.get(key, default)` won't fire (the key exists with value null) and
    # int(None) raises. `_coerce` guards None/invalid to a neutral default and is
    # reused below for the per-fixture difficulty preference.
    def _coerce(value: Any, default: int = 3) -> int:
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    strength_by_id: dict[int, int] = {
        t["id"]: _coerce(t.get("strength"))
        for t in bootstrap.get("teams", [])
    }
    fdr_map: dict[int, int] = {}
    for fix in fixtures:
        home_id = fix["team_h"]
        away_id = fix["team_a"]
        # Prefer the fixture's own difficulty; fall back to opponent strength.
        fdr_map[home_id] = _coerce(
            fix.get("team_h_difficulty"), strength_by_id.get(away_id, 3)
        )
        fdr_map[away_id] = _coerce(
            fix.get("team_a_difficulty"), strength_by_id.get(home_id, 3)
        )
    return fdr_map



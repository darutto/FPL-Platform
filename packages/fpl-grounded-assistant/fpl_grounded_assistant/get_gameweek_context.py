"""
fpl_grounded_assistant.get_gameweek_context
============================================
P2.5: Atomic get_gameweek_context tool — current/next GW with deadlines
and blank/double indicators for the next 5 upcoming gameweeks.

Addresses the failed query class: "Bench Boost en la GW que viene" /
"what gameweek are we in" / "next gameweek fixtures" — the LLM needed
temporal grounding before reasoning about "la jornada que viene" vs
"this week".

Bootstrap source
----------------
All data is read from ``bootstrap["events"]`` — the FPL API's gameweek
event list.  Each event has:
    id, name, deadline_time, finished, is_current, is_next, is_previous

No player or team data is required.  Blank/double indicators do require
team fixture data, fetched via the P2.4 helper.

Test-injection path
-------------------
Supply a pre-fetched bootstrap with custom events:

    bootstrap["events"] = [...]

For blank/double indicators, supply all-GW fixtures via the same
``_gw_fixtures`` injection key used by P2.4:

    bootstrap["_gw_fixtures"] = {
        "28": [...],   # GW 28 fixtures
        "29": [...],   # GW 29 fixtures
        ...
    }

Pass ``fixtures`` directly to override all fixture fetching for the
alert window (useful for unit tests covering blank/double logic).

Blank/double detection
----------------------
Reuses ``_fetch_fixtures_for_gw``, ``_build_short_map``, and
``_compute_team_fixture_counts`` from P2.4 (``get_fixtures_for_gw``).
This avoids any fixture-parsing logic duplication.

For each of the next 5 GWs (starting from next_gw):
- Teams with 0 fixtures → blank for that GW.
- Teams with 2+ fixtures → double for that GW.

Caching
-------
An in-process dict keyed by (current_gw, season_total_gws) stores the
full result for ~10 minutes.  Bootstrap changes only at GW deadlines so
this is safe.

Registration
------------
Registers ``get_gameweek_context`` in ``TOOL_REGISTRY`` as a side-effect
of import.  ``__init__.py`` imports this module so
``run_tool("get_gameweek_context", ...)`` works.
"""
from __future__ import annotations

import time
from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .get_fixtures_for_gw import (
    _build_short_map,
    _build_all_team_ids,
    _compute_team_fixture_counts,
    _fetch_fixtures_for_gw,
    _extract_fixture,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Number of upcoming GWs to scan for blank/double alerts.
_ALERT_HORIZON: int = 5

#: Cache TTL in seconds (~10 minutes).
_CACHE_TTL_SECONDS: int = 600


# ---------------------------------------------------------------------------
# In-process result cache
# ---------------------------------------------------------------------------

#: {(current_gw, season_total_gws): (result_dict, expiry_timestamp)}
_context_cache: dict[tuple[int, int], tuple[dict[str, Any], float]] = {}


def _clear_context_cache() -> None:
    """Clear the in-process context cache (test helper)."""
    _context_cache.clear()


# ---------------------------------------------------------------------------
# Bootstrap parsing helpers
# ---------------------------------------------------------------------------

def _find_current_event(events: list[dict[str, Any]]) -> "dict[str, Any] | None":
    """Return the event with ``is_current=True``, or the most recent finished one."""
    # Primary: explicit is_current flag.
    for ev in events:
        if ev.get("is_current"):
            return ev
    # Fallback: most recently finished event.
    finished = [ev for ev in events if ev.get("finished")]
    if finished:
        return max(finished, key=lambda e: int(e.get("id", 0)))
    return None


def _find_next_event(events: list[dict[str, Any]], current_id: int) -> "dict[str, Any] | None":
    """Return the event with ``is_next=True``, or current_id+1 if it exists."""
    for ev in events:
        if ev.get("is_next"):
            return ev
    # Fallback: the event whose id == current_id + 1.
    for ev in events:
        if int(ev.get("id", 0)) == current_id + 1:
            return ev
    return None


def _event_status(event: "dict[str, Any]") -> str:
    """Return 'finished' | 'in_progress' | 'pending' for a GW event dict."""
    if event.get("finished"):
        return "finished"
    if event.get("is_current"):
        # is_current but not finished means it's in progress.
        return "in_progress"
    return "pending"


# ---------------------------------------------------------------------------
# Blank/double detection over alert horizon
# ---------------------------------------------------------------------------

def _build_blank_double_alerts(
    bootstrap: "dict[str, Any]",
    next_gw: int,
    season_total: int,
    fixtures_override: "dict[int, list[dict[str, Any]]] | None",
) -> "tuple[list[dict[str, Any]], list[dict[str, Any]]]":
    """Build blank and double GW alert lists for next ``_ALERT_HORIZON`` GWs.

    Parameters
    ----------
    bootstrap:
        FPL bootstrap (for team name data and optional ``_gw_fixtures`` injection).
    next_gw:
        First GW to scan (inclusive).
    season_total:
        Last valid GW number.
    fixtures_override:
        Optional per-GW fixture override map ``{gw: list[fixture_dict]}``.
        When supplied, takes precedence over bootstrap injection and live API.

    Returns
    -------
    (blank_alerts, double_alerts)
        Each element is ``{"gw": int, "blank_teams": list[str], "count": int}``
        or ``{"gw": int, "double_teams": list[str], "count": int}``.
        Only GWs with at least one affected team are included.
    """
    short_map       = _build_short_map(bootstrap)
    all_team_ids    = _build_all_team_ids(bootstrap)
    all_team_shorts = {short_map[tid] for tid in all_team_ids if tid in short_map}

    blank_alerts:  list[dict[str, Any]] = []
    double_alerts: list[dict[str, Any]] = []

    for gw_offset in range(_ALERT_HORIZON):
        gw = next_gw + gw_offset
        if gw > season_total:
            break

        # Resolve fixtures for this GW.
        if fixtures_override and gw in fixtures_override:
            raw = list(fixtures_override[gw])
        else:
            raw = _fetch_fixtures_for_gw(gw, bootstrap, None)

        if raw is None:
            # API failure for this GW — skip silently.
            continue

        extracted = [_extract_fixture(f, short_map) for f in raw]
        counts    = _compute_team_fixture_counts(extracted)
        playing   = set(counts.keys())

        blank_teams  = sorted(all_team_shorts - playing)
        double_teams = sorted(t for t, c in counts.items() if c > 1)

        if blank_teams:
            blank_alerts.append({
                "gw":          gw,
                "blank_teams": blank_teams,
                "count":       len(blank_teams),
            })
        if double_teams:
            double_alerts.append({
                "gw":           gw,
                "double_teams": double_teams,
                "count":        len(double_teams),
            })

    return blank_alerts, double_alerts


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def get_gameweek_context(
    bootstrap: "dict | None" = None,
    fixtures: "dict[int, list] | None" = None,
) -> dict[str, Any]:
    """Current/next gameweek context with blank/double indicators.

    Takes NO positional arguments from the LLM — pure read of bootstrap
    state.  Returns the temporal grounding info the LLM needs before
    reasoning about "next GW", "la jornada que viene", "fecha 38", etc.

    Args:
        bootstrap: live FPL bootstrap; must be provided (not fetched here).
        fixtures:  optional per-GW fixture override ``{gw_number: [...]}``.
                   Used in tests to avoid HTTP calls for blank/double logic.

    Returns:
        {
            "status": "ok",
            "current_gw": <int>,
            "next_gw": <int | None>,
            "current_gw_deadline": <str | None>,
            "next_gw_deadline": <str | None>,
            "season_total_gws": <int>,
            "is_season_over": <bool>,
            "is_pre_season": <bool>,
            "current_gw_status": <str>,          # "pending"|"in_progress"|"finished"
            "blank_gw_alerts": [
                {"gw": int, "blank_teams": [str,...], "count": int},
                ...
            ],
            "double_gw_alerts": [
                {"gw": int, "double_teams": [str,...], "count": int},
                ...
            ]
        }

    On invalid bootstrap:
        {"status": "error", "code": "bootstrap_invalid", "message": "..."}
    """
    # ------------------------------------------------------------------
    # 0. Bootstrap guard
    # ------------------------------------------------------------------
    if bootstrap is None:
        bootstrap = {}

    events: list[dict[str, Any]] = bootstrap.get("events", [])
    if not isinstance(events, list) or len(events) == 0:
        return {
            "status":  "error",
            "code":    "bootstrap_invalid",
            "message": "bootstrap['events'] is empty or missing; cannot determine gameweek context.",
        }

    # Validate each event has at least an 'id' field.
    for ev in events:
        if not isinstance(ev, dict) or "id" not in ev:
            return {
                "status":  "error",
                "code":    "bootstrap_invalid",
                "message": "One or more events are malformed (missing 'id').",
            }

    season_total = max(int(ev["id"]) for ev in events)

    # ------------------------------------------------------------------
    # 1. Find current / next GW event
    # ------------------------------------------------------------------
    current_event = _find_current_event(events)

    if current_event is None:
        # No finished events and no is_current → pre-season.
        # Use GW 1 as current placeholder.
        first_event = min(events, key=lambda e: int(e.get("id", 0)))
        current_gw          = int(first_event.get("id", 1))
        current_gw_deadline = first_event.get("deadline_time")
        current_gw_status   = "pending"
        is_pre_season       = True
    else:
        current_gw          = int(current_event["id"])
        current_gw_deadline = current_event.get("deadline_time")
        current_gw_status   = _event_status(current_event)
        is_pre_season       = False

    # Cache key — check before computing blank/double (expensive).
    cache_key = (current_gw, season_total)
    now       = time.monotonic()
    if cache_key in _context_cache:
        cached_result, expiry = _context_cache[cache_key]
        if now < expiry:
            return cached_result

    next_event = _find_next_event(events, current_gw)

    if next_event is not None:
        next_gw          = int(next_event["id"])
        next_gw_deadline = next_event.get("deadline_time")
    else:
        next_gw          = None
        next_gw_deadline = None

    is_season_over = (
        current_gw == season_total
        and current_gw_status == "finished"
        and next_gw is None
    )

    # ------------------------------------------------------------------
    # 2. Blank/double alerts for next _ALERT_HORIZON GWs
    # ------------------------------------------------------------------
    alert_start = next_gw if next_gw is not None else (current_gw + 1)

    blank_alerts: list[dict[str, Any]] = []
    double_alerts: list[dict[str, Any]] = []

    if not is_season_over and alert_start <= season_total:
        blank_alerts, double_alerts = _build_blank_double_alerts(
            bootstrap      = bootstrap,
            next_gw        = alert_start,
            season_total   = season_total,
            fixtures_override = fixtures,
        )

    # ------------------------------------------------------------------
    # 3. Build and cache result
    # ------------------------------------------------------------------
    result: dict[str, Any] = {
        "status":               "ok",
        "current_gw":           current_gw,
        "next_gw":              next_gw,
        "current_gw_deadline":  current_gw_deadline,
        "next_gw_deadline":     next_gw_deadline,
        "season_total_gws":     season_total,
        "is_season_over":       is_season_over,
        "is_pre_season":        is_pre_season,
        "current_gw_status":    current_gw_status,
        "blank_gw_alerts":      blank_alerts,
        "double_gw_alerts":     double_alerts,
    }

    _context_cache[cache_key] = (result, now + _CACHE_TTL_SECONDS)
    return result


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

GET_GAMEWEEK_CONTEXT_SPEC = ToolSpec(
    name="get_gameweek_context",
    description=(
        "Current/next GW with deadlines + blank/double alerts for next 5 GWs. "
        "Returns current_gw, next_gw, season status, blank_gw_alerts, "
        "double_gw_alerts. No args. Use before reasoning about next GW."
    ),
    parameters={
        "type":                 "object",
        "properties":           {},
        "required":             [],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":              {"type": "string"},
            "current_gw":         {"type": "integer"},
            "next_gw":            {"type": ["integer", "null"]},
            "current_gw_deadline": {"type": ["string", "null"]},
            "next_gw_deadline":   {"type": ["string", "null"]},
            "season_total_gws":   {"type": "integer"},
            "is_season_over":     {"type": "boolean"},
            "is_pre_season":      {"type": "boolean"},
            "current_gw_status":  {"type": "string"},
            "blank_gw_alerts":    {"type": "array"},
            "double_gw_alerts":   {"type": "array"},
        },
    },
)


def _get_gameweek_context_handler(
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``get_gameweek_context()``.

    Note: no-parameter tools are called as ``handler(bootstrap)`` by the
    runner (see fpl_tool_runner runner.py line ~173).
    """
    try:
        return get_gameweek_context(bootstrap=bootstrap)
    except Exception as exc:  # noqa: BLE001
        return {
            "status":  "error",
            "code":    "tool_exception",
            "message": f"get_gameweek_context raised an unexpected error: {exc}",
        }


# Register with the shared tool registry so run_tool("get_gameweek_context", ...) works.
TOOL_REGISTRY.register(GET_GAMEWEEK_CONTEXT_SPEC, _get_gameweek_context_handler)

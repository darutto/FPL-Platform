"""
fpl_grounded_assistant.get_team_snapshot
=========================================
P2.6: Atomic get_team_snapshot tool — single-team snapshot with form,
upcoming fixtures with FDR, and top players with full grounding payload.

Addresses the failing query class: "quien es el mejor jugador de wolves?"
and "contra quien juega aston villa esta semana" — the LLM gets a one-shot
team overview combining identity, fixture run, and top players.

Team resolution algorithm
--------------------------
Three-tier matching, accent+case insensitive:

    Tier 0 — exact match on normalized ``short_name`` OR ``name``.
              1 match → ok. >1 match → ambiguous (rare but handled).
    Tier 1 — prefix match on either field.
              1 match → ok. >1 match → ambiguous.
    Tier 2 — substring match.
              >0 matches → ambiguous (too loose to auto-resolve).
    None   → not_found.

Examples::

    "wolves"         → WOL  (substring on "Wolverhampton")
    "wolverhampton"  → WOL  (exact on name)
    "WOL"            → WOL  (exact on short_name)
    "manchester"     → ambiguous (MUN + MCI)
    "aston villa"    → AVL  (exact on name)
    "villa"          → AVL  (substring)

Reuse
-----
*  ``_normalize`` from ``find_players`` for accent/case stripping.
*  ``_build_match_dict`` from ``find_players`` for the full 20-field
   grounding payload (``match_rank`` stripped since it is a single-team
   context).
*  ``_fetch_fixtures_for_gw``, ``_extract_fixture`` from
   ``get_fixtures_for_gw`` for upcoming fixture resolution.

Upcoming-fixtures strategy
---------------------------
Starting from ``current_gw + 1`` (resolved from ``bootstrap["events"]``),
scan each GW in order.  For each GW fetch raw fixtures and check if the
target team plays.  Stop when we have ``fixture_horizon`` entries or run
out of GWs.

FDR for this team:
*  ``team_h_difficulty`` when team is home.
*  ``team_a_difficulty`` when team is away.

Caching
-------
Per-process dict keyed by ``(team_id, current_gw)`` with 1-hour TTL.
Fixture data re-uses the P2.4 in-process cache automatically.

Registration
------------
Registers ``get_team_snapshot`` in ``TOOL_REGISTRY`` as a side-effect of
import.  ``__init__.py`` imports this module so
``run_tool("get_team_snapshot", ...)`` works.
"""
from __future__ import annotations

import time
from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .find_players import (
    _normalize,
    _build_match_dict,
    _safe_float,
    _safe_int,
)
from .get_fixtures_for_gw import (
    _fetch_fixtures_for_gw,
    _build_short_map,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_TOP_N:           int = 10
_MAX_FIXTURE_HORIZON: int = 10
_GW_MIN:              int = 1
_GW_MAX:              int = 38

#: Cache TTL in seconds (1 hour).
_CACHE_TTL_SECONDS: int = 3600

#: {(team_id, current_gw): (result_dict, expiry_timestamp)}
_snapshot_cache: dict[tuple[int, int], tuple[dict[str, Any], float]] = {}


def _clear_snapshot_cache() -> None:
    """Clear the in-process snapshot cache (test helper)."""
    _snapshot_cache.clear()


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------

def _current_gw_from_events(events: list[dict[str, Any]]) -> int:
    """Return the current GW id from a bootstrap events list.

    Falls back to the first finished event, then to 1 for pre-season.
    """
    for ev in events:
        if ev.get("is_current"):
            return int(ev["id"])
    finished = [ev for ev in events if ev.get("finished")]
    if finished:
        return int(max(finished, key=lambda e: int(e.get("id", 0)))["id"])
    if events:
        return int(min(events, key=lambda e: int(e.get("id", 0)))["id"])
    return 1


def _season_total_from_events(events: list[dict[str, Any]]) -> int:
    """Return the highest GW id in the events list (season total)."""
    if not events:
        return _GW_MAX
    return max(int(ev.get("id", 1)) for ev in events)


# ---------------------------------------------------------------------------
# Team resolution
# ---------------------------------------------------------------------------

def _resolve_team(
    team_name: str,
    teams: list[dict[str, Any]],
) -> dict[str, Any]:
    """Match team_name against bootstrap teams.

    Returns
    -------
    dict with one of:
        {"status": "ok",        "team_data": <team dict>}
        {"status": "ambiguous", "candidates": [...]}
        {"status": "not_found"}
    """
    normalized_query = _normalize(team_name.strip())

    # Pre-normalize all team fields
    team_norms: list[tuple[dict[str, Any], str, str]] = []
    for t in teams:
        norm_short = _normalize(str(t.get("short_name", "") or ""))
        norm_name  = _normalize(str(t.get("name", "") or ""))
        team_norms.append((t, norm_short, norm_name))

    # Tier 0: exact match on short_name or full name
    exact: list[dict[str, Any]] = [
        t for t, ns, nn in team_norms
        if normalized_query in (ns, nn)
    ]
    if len(exact) == 1:
        return {"status": "ok", "team_data": exact[0]}
    if len(exact) > 1:
        return {
            "status":     "ambiguous",
            "candidates": [
                {"short_name": t.get("short_name", ""), "name": t.get("name", "")}
                for t in exact
            ],
        }

    # Tier 1: prefix match on short_name or full name
    prefix: list[dict[str, Any]] = [
        t for t, ns, nn in team_norms
        if ns.startswith(normalized_query) or nn.startswith(normalized_query)
    ]
    if len(prefix) == 1:
        return {"status": "ok", "team_data": prefix[0]}
    if len(prefix) > 1:
        return {
            "status":     "ambiguous",
            "candidates": [
                {"short_name": t.get("short_name", ""), "name": t.get("name", "")}
                for t in prefix
            ],
        }

    # Tier 2: substring match (always ambiguous or not_found — never auto-resolve)
    substring: list[dict[str, Any]] = [
        t for t, ns, nn in team_norms
        if normalized_query in ns or normalized_query in nn
    ]
    if len(substring) == 1:
        # Even substring of 1 → ok (e.g. "villa" → only AVL)
        return {"status": "ok", "team_data": substring[0]}
    if len(substring) > 1:
        return {
            "status":     "ambiguous",
            "candidates": [
                {"short_name": t.get("short_name", ""), "name": t.get("name", "")}
                for t in substring
            ],
        }

    return {"status": "not_found"}


# ---------------------------------------------------------------------------
# Team dict builder
# ---------------------------------------------------------------------------

def _build_team_block(team: dict[str, Any]) -> dict[str, Any]:
    """Extract public-facing team identity fields."""
    return {
        "id":                      int(team.get("id", 0)),
        "short_name":              str(team.get("short_name", "") or ""),
        "name":                    str(team.get("name", "") or ""),
        "strength":                int(team.get("strength", 3) or 3),
        "strength_overall_home":   int(team.get("strength_overall_home", 0) or 0),
        "strength_overall_away":   int(team.get("strength_overall_away", 0) or 0),
        "form":                    team.get("form"),         # str or None
        "position":                team.get("position"),     # int or None
        "played":                  team.get("played"),       # int or None
        "win":                     team.get("win"),          # int or None
        "draw":                    team.get("draw"),         # int or None
        "loss":                    team.get("loss"),         # int or None
        "points":                  team.get("points"),       # int or None
    }


# ---------------------------------------------------------------------------
# Top-players builder
# ---------------------------------------------------------------------------

def _build_top_players(
    team_id: int,
    top_n: int,
    bootstrap: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return top ``top_n`` players for ``team_id``, sorted by total_points desc.

    Each entry is the full 20-field grounding payload (match_rank omitted).
    """
    elements:      list[dict[str, Any]] = bootstrap.get("elements", []) or []
    teams:         list[dict[str, Any]] = bootstrap.get("teams", []) or []
    element_types: list[dict[str, Any]] = bootstrap.get("element_types", []) or []

    team_players = [el for el in elements if el.get("team") == team_id]
    team_players.sort(key=lambda el: -_safe_int(el.get("total_points"), 0))
    team_players = team_players[:top_n]

    result: list[dict[str, Any]] = []
    for el in team_players:
        payload = _build_match_dict(el, teams, element_types, match_rank=0)
        # Strip match_rank — it's a single-team context.
        payload.pop("match_rank", None)
        result.append(payload)
    return result


# ---------------------------------------------------------------------------
# Upcoming-fixtures builder
# ---------------------------------------------------------------------------

def _build_upcoming_fixtures(
    team_id:          int,
    team_short_name:  str,
    current_gw:       int,
    season_total:     int,
    fixture_horizon:  int,
    bootstrap:        dict[str, Any],
    fixtures_override: "list[dict[str, Any]] | None",
) -> list[dict[str, Any]]:
    """Return up to ``fixture_horizon`` upcoming fixtures for ``team_id``.

    Scans GWs from current_gw+1 onwards.  For each GW, fetches raw fixtures
    and checks if the team plays (home or away).

    ``fixtures_override`` is injected raw fixtures for the *first* future GW
    (test path only); pass ``None`` for live operation.
    """
    short_map = _build_short_map(bootstrap)
    upcoming: list[dict[str, Any]] = []

    for gw in range(current_gw + 1, season_total + 1):
        if len(upcoming) >= fixture_horizon:
            break

        # Use override only when explicitly supplied (single-GW test injection)
        raw = _fetch_fixtures_for_gw(gw, bootstrap, fixtures_override)
        if raw is None:
            continue

        for fix in raw:
            home_id = int(fix.get("team_h", 0))
            away_id = int(fix.get("team_a", 0))
            is_home = home_id == team_id
            is_away = away_id == team_id

            if not is_home and not is_away:
                continue

            if is_home:
                opp_id  = away_id
                fdr     = int(fix.get("team_h_difficulty") or 3)
            else:
                opp_id  = home_id
                fdr     = int(fix.get("team_a_difficulty") or 3)

            opp_short = short_map.get(opp_id, f"T{opp_id}")
            opp_name  = ""
            for t in bootstrap.get("teams", []):
                if int(t.get("id", 0)) == opp_id:
                    opp_name = str(t.get("name", "") or "")
                    break

            upcoming.append({
                "gw":            gw,
                "opponent_short": opp_short,
                "opponent_name":  opp_name,
                "is_home":       is_home,
                "fdr":           fdr,
                "kickoff_time":  fix.get("kickoff_time"),
            })

            if len(upcoming) >= fixture_horizon:
                break

    return upcoming


# ---------------------------------------------------------------------------
# Summary block
# ---------------------------------------------------------------------------

def _build_summary(
    upcoming_fixtures: list[dict[str, Any]],
    top_players:       list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the 5-key summary block."""
    # avg_fdr using top-5 fixtures (or fewer if not available)
    fdr_values = [f["fdr"] for f in upcoming_fixtures[:5]]
    avg_fdr    = round(sum(fdr_values) / len(fdr_values), 2) if fdr_values else 0.0

    is_easy_run = avg_fdr <= 2.5
    is_hard_run = avg_fdr >= 3.5

    # top scorer: already sorted by total_points
    top_scorer_web_name = top_players[0]["web_name"] if top_players else ""

    # top form player: sort by form desc
    sorted_by_form = sorted(top_players, key=lambda p: -_safe_float(p.get("form"), 0.0))
    top_form_web_name = sorted_by_form[0]["web_name"] if sorted_by_form else ""

    return {
        "avg_fdr_next_5":    avg_fdr,
        "is_easy_run":       is_easy_run,
        "is_hard_run":       is_hard_run,
        "top_scorer_web_name": top_scorer_web_name,
        "top_form_web_name":   top_form_web_name,
    }


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def get_team_snapshot(
    team_name:        str,
    top_n_players:    int = 5,
    fixture_horizon:  int = 5,
    bootstrap:        "dict | None" = None,
    fixtures:         "list | None" = None,
) -> dict[str, Any]:
    """Single team snapshot: form, next N fixtures with FDR, top players.

    Args:
        team_name: team short code (e.g. "WOL"), full name (e.g. "Wolves" /
                   "Wolverhampton"), or substring. Case + accent insensitive.
        top_n_players: how many top players to return per team. Capped at 10.
        fixture_horizon: how many upcoming fixtures to include. Capped at 10.
        bootstrap: live FPL bootstrap; injected by dispatcher in normal
                   operation.
        fixtures: pre-fetched fixtures list for the first upcoming GW (test
                  injection only). Supply via bootstrap["_gw_fixtures"] for
                  multi-GW test coverage.

    Returns one of:

        # Single unambiguous match:
        {
            "status": "ok",
            "team": {
                "id", "short_name", "name", "strength",
                "strength_overall_home", "strength_overall_away",
                "form", "position", "played", "win", "draw", "loss", "points"
            },
            "upcoming_fixtures": [
                {"gw", "opponent_short", "opponent_name",
                 "is_home", "fdr", "kickoff_time"},
                ...
            ],
            "top_players": [
                {<full 20-field grounding payload — no match_rank>},
                ...
            ],
            "summary": {
                "avg_fdr_next_5", "is_easy_run", "is_hard_run",
                "top_scorer_web_name", "top_form_web_name"
            }
        }

        # Ambiguous:
        {
            "status": "ambiguous",
            "query": <str>,
            "candidates": [{"short_name": ..., "name": ...}, ...],
            "message": "Multiple teams match ..."
        }

        # Not found:
        {
            "status": "not_found",
            "query": <str>,
            "message": "No team matching ..."
        }
    """
    # ------------------------------------------------------------------
    # 0. Validate inputs
    # ------------------------------------------------------------------
    if not isinstance(team_name, str) or not team_name.strip():
        return {
            "status":  "error",
            "code":    "invalid_argument",
            "message": "team_name must be a non-empty string.",
        }

    top_n_players   = max(1, min(_safe_int(top_n_players, 5), _MAX_TOP_N))
    fixture_horizon = max(1, min(_safe_int(fixture_horizon, 5), _MAX_FIXTURE_HORIZON))

    normalized_query = _normalize(team_name.strip())

    # ------------------------------------------------------------------
    # 1. Bootstrap guard
    # ------------------------------------------------------------------
    if bootstrap is None:
        return {
            "status":  "not_found",
            "query":   normalized_query,
            "message": f"No team matching '{normalized_query}'.",
        }

    teams:         list[dict[str, Any]] = bootstrap.get("teams", []) or []
    events:        list[dict[str, Any]] = bootstrap.get("events", []) or []
    element_types: list[dict[str, Any]] = bootstrap.get("element_types", []) or []

    # ------------------------------------------------------------------
    # 2. Resolve team
    # ------------------------------------------------------------------
    resolution = _resolve_team(team_name, teams)

    if resolution["status"] == "not_found":
        return {
            "status":  "not_found",
            "query":   normalized_query,
            "message": f"No team matching '{normalized_query}'.",
        }

    if resolution["status"] == "ambiguous":
        candidates = resolution["candidates"]
        return {
            "status":     "ambiguous",
            "query":      normalized_query,
            "candidates": candidates,
            "message":    (
                f"Multiple teams match '{normalized_query}'. Please specify. "
                f"Candidates: {', '.join(c['short_name'] for c in candidates)}"
            ),
        }

    # status == "ok"
    team_data = resolution["team_data"]
    team_id   = int(team_data.get("id", 0))

    # ------------------------------------------------------------------
    # 3. Check cache
    # ------------------------------------------------------------------
    current_gw   = _current_gw_from_events(events)
    season_total = _season_total_from_events(events)
    cache_key    = (team_id, current_gw)
    now          = time.monotonic()

    if cache_key in _snapshot_cache and fixtures is None:
        cached_result, expiry = _snapshot_cache[cache_key]
        if now < expiry:
            # Return cached but with the requested top_n / horizon sliced.
            # For simplicity, skip cache if params differ — just re-compute.
            cached_top_n = len(cached_result.get("top_players", []))
            cached_hz    = len(cached_result.get("upcoming_fixtures", []))
            if cached_top_n >= top_n_players and cached_hz >= fixture_horizon:
                sliced = dict(cached_result)
                sliced["top_players"]       = cached_result["top_players"][:top_n_players]
                sliced["upcoming_fixtures"] = cached_result["upcoming_fixtures"][:fixture_horizon]
                sliced["summary"]           = _build_summary(
                    sliced["upcoming_fixtures"], sliced["top_players"]
                )
                return sliced

    # ------------------------------------------------------------------
    # 4. Build top players (sorted by total_points desc)
    # ------------------------------------------------------------------
    top_players = _build_top_players(team_id, top_n_players, bootstrap)

    # ------------------------------------------------------------------
    # 5. Build upcoming fixtures
    # ------------------------------------------------------------------
    team_short_name = str(team_data.get("short_name", "") or "")
    upcoming_fixtures = _build_upcoming_fixtures(
        team_id          = team_id,
        team_short_name  = team_short_name,
        current_gw       = current_gw,
        season_total     = season_total,
        fixture_horizon  = fixture_horizon,
        bootstrap        = bootstrap,
        fixtures_override = fixtures,
    )

    # ------------------------------------------------------------------
    # 6. Build summary
    # ------------------------------------------------------------------
    summary = _build_summary(upcoming_fixtures, top_players)

    # ------------------------------------------------------------------
    # 7. Assemble result
    # ------------------------------------------------------------------
    result: dict[str, Any] = {
        "status":            "ok",
        "team":              _build_team_block(team_data),
        "upcoming_fixtures": upcoming_fixtures,
        "top_players":       top_players,
        "summary":           summary,
    }

    # Cache the full result (max top_n + horizon for later slicing).
    _snapshot_cache[cache_key] = (result, now + _CACHE_TTL_SECONDS)
    return result


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

GET_TEAM_SNAPSHOT_SPEC = ToolSpec(
    name="get_team_snapshot",
    description=(
        "Single team snapshot: form, next N fixtures+FDR, top N players (full grounding payload), "
        "summary (avg FDR, easy/hard run, top scorer). "
        "status=ambiguous on multi-match (e.g. 'manchester')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "team_name": {
                "type":        "string",
                "description": (
                    "Team name, short code, or substring (case+accent insensitive). "
                    "E.g. 'wolves', 'WOL', 'Wolverhampton', 'aston villa', 'AVL'."
                ),
            },
            "top_n_players": {
                "type":        "integer",
                "description": "Max top players to return (1-10, default 5)",
                "minimum":     1,
                "maximum":     10,
            },
            "fixture_horizon": {
                "type":        "integer",
                "description": "Number of upcoming fixtures to include (1-10, default 5)",
                "minimum":     1,
                "maximum":     10,
            },
        },
        "required":             ["team_name"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":            {"type": "string"},
            "team":              {"type": "object"},
            "upcoming_fixtures": {"type": "array"},
            "top_players":       {"type": "array"},
            "summary":           {"type": "object"},
        },
    },
)


def _get_team_snapshot_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``get_team_snapshot()``."""
    try:
        team_name = args.get("team_name")
        if not team_name:
            return {
                "status":  "error",
                "code":    "missing_team_name",
                "message": "team_name is required.",
            }
        return get_team_snapshot(
            team_name       = team_name,
            top_n_players   = args.get("top_n_players", 5),
            fixture_horizon = args.get("fixture_horizon", 5),
            bootstrap       = bootstrap,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status":  "error",
            "code":    "tool_exception",
            "message": f"get_team_snapshot raised an unexpected error: {exc}",
        }


# Register with the shared tool registry so run_tool("get_team_snapshot", ...) works.
TOOL_REGISTRY.register(GET_TEAM_SNAPSHOT_SPEC, _get_team_snapshot_handler)

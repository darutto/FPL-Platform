"""
fpl_grounded_assistant.team_fixture_calendar
============================================
Phase 2.6e.1: Deterministic team fixture calendar ranking.
Phase 2.6e.2: Explicit DGW/BGW labeling per team entry.

Ranks all teams in the bootstrap by upcoming fixture difficulty over a
bounded GW horizon.  Returns a structured, ordered list sorted either
ascending (easiest = lowest avg FDR) or descending (hardest = highest).

Supported prompt families
--------------------------
* "que equipos tienen el mejor calendario las proximas 5 jornadas"
* "best fixtures next 4 gameweeks"
* "worst upcoming fixtures"
* "which teams have the easiest run from now"
* "hardest fixture run next 3 GWs"

Scoring formula
---------------
For each team with at least one fixture in the horizon:

    fixtures_in_window = [f for f in team_fixtures[team]
                          if current_gw <= f.gameweek < current_gw + horizon]
    total_fdr     = sum(f.difficulty for f in fixtures_in_window)
    fixture_count = len(fixtures_in_window)
    avg_fdr       = total_fdr / fixture_count   (2 d.p.)

Teams with *zero* fixtures in the horizon (blank GW across whole window)
are excluded from the ranked output.

Ranking:
* ``mode="easiest"`` → sort by ``avg_fdr`` ascending (lowest avg = easiest)
* ``mode="hardest"`` → sort by ``avg_fdr`` descending (highest avg = hardest)

Design rules
------------
* Pure deterministic — no LLM, no live API calls beyond bootstrap.
* Reuses ``bootstrap["team_fixtures"]`` already populated by the
  player-fixture-run path (Phase 7h).
* Missing ``team_fixtures`` in bootstrap → ``status="missing_context"``.
* No transfer / buy / avoid language — schedule ranking only.
* Bounded top-N output (default 5) to keep responses scannable.
* DGW (two fixtures in one GW) handled naturally: both fixtures counted.

DGW / BGW labeling  (Phase 2.6e.2)
------------------------------------
Each team entry now carries four additional fields:

``has_dgw``        True when the team has ≥2 fixtures in any GW in the horizon.
``has_bgw``        True when the team has 0 fixtures in a GW that other teams play.
``dgw_gameweeks``  Sorted list of GW numbers where this team has a double fixture.
``bgw_gameweeks``  Sorted list of GW numbers where this team blanks while others play.

A GW is considered "active" (and therefore a potential BGW) when at least one team
in ``team_fixtures`` has a fixture in that GW.  If ALL teams are blank in a GW (e.g.
fixture data simply ends), that GW is not flagged as a BGW for any team.

The scoring formula and sort order are unchanged from Phase 2.6e.1.

Phase 2.6e.3: Single-team calendar lookup
------------------------------------------
Intent ``team_schedule`` returns one club's next N fixtures + DGW/BGW labels.
The team is resolved from bootstrap by name / short_name / common alias.
Uses the same scoring helpers and DGW/BGW classification logic as Phase 2.6e.1.

Intentionally deferred
-----------------------
* Position-filtered calendar
"""
from __future__ import annotations

from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Default GW lookahead window.
DEFAULT_HORIZON: int = 5

#: Maximum allowed horizon (bounds the output list).
_MAX_HORIZON: int = 10

#: Default number of teams to return in the ranked output.
DEFAULT_TOP_N: int = 5

#: Maximum top-N result count.
_MAX_TOP_N: int = 20


# ---------------------------------------------------------------------------
# Bootstrap helpers  (shared pattern with player_fixture_run)
# ---------------------------------------------------------------------------

def _get_current_gameweek(bootstrap: dict[str, Any]) -> int | None:
    for ev in bootstrap.get("events", []):
        if ev.get("is_current"):
            return int(ev["id"])
    return None


def _team_short_map(bootstrap: dict[str, Any]) -> dict[int, str]:
    return {
        int(t["id"]): str(t.get("short_name", f"T{t['id']}"))
        for t in bootstrap.get("teams", [])
    }


def _team_name_map(bootstrap: dict[str, Any]) -> dict[int, str]:
    return {
        int(t["id"]): str(t.get("name", f"Team {t['id']}"))
        for t in bootstrap.get("teams", [])
    }


# ---------------------------------------------------------------------------
# DGW / BGW classification helpers  (Phase 2.6e.2)
# ---------------------------------------------------------------------------

def _get_active_gws(
    team_fixtures: dict,
    current_gw: int,
    horizon: int,
) -> frozenset[int]:
    """Return the set of GWs in ``[current_gw, current_gw+horizon)`` that have
    at least one fixture from any team.

    A GW absent from this set means no team data covers it — not treated as a BGW.
    """
    gw_end  = current_gw + horizon
    active: set[int] = set()
    for raw_fixtures in team_fixtures.values():
        for f in raw_fixtures:
            gw = int(f.get("gameweek", 0))
            if current_gw <= gw < gw_end:
                active.add(gw)
    return frozenset(active)


def _classify_team_gws(
    team_id: int,
    team_fixtures: dict,
    current_gw: int,
    horizon: int,
    active_gws: frozenset[int],
) -> tuple[list[int], list[int]]:
    """Return ``(dgw_gameweeks, bgw_gameweeks)`` for *team_id* within the horizon.

    Parameters
    ----------
    team_id:      The team's numeric id.
    team_fixtures: Full team_fixtures dict from bootstrap.
    current_gw:   First GW of the horizon window.
    horizon:      Number of GWs to scan.
    active_gws:   Set of GWs in the window that have ≥1 fixture from any team.
                  Built once by ``_get_active_gws()`` and shared across all teams.

    Returns
    -------
    dgw_gameweeks:
        Sorted list of GW numbers where this team has ≥2 fixtures (DGW).
    bgw_gameweeks:
        Sorted list of GW numbers where this team has 0 fixtures while the GW
        is active (BGW — other teams play but this team blanks).
    """
    gw_end = current_gw + horizon
    raw    = team_fixtures.get(team_id) or team_fixtures.get(str(team_id)) or []

    gw_count: dict[int, int] = {}
    for f in raw:
        gw = int(f.get("gameweek", 0))
        if current_gw <= gw < gw_end:
            gw_count[gw] = gw_count.get(gw, 0) + 1

    dgw_gws: list[int] = []
    bgw_gws: list[int] = []
    for gw in range(current_gw, gw_end):
        count = gw_count.get(gw, 0)
        if count >= 2:
            dgw_gws.append(gw)
        elif count == 0 and gw in active_gws:
            bgw_gws.append(gw)

    return dgw_gws, bgw_gws


# ---------------------------------------------------------------------------
# Core scorer
# ---------------------------------------------------------------------------

def _score_team(
    team_id: int,
    team_fixtures: dict,
    current_gw: int | None,
    horizon: int,
    short_map: dict[int, str],
) -> dict[str, Any] | None:
    """Compute avg_fdr for one team over the next ``horizon`` GWs.

    Returns a scoring dict or ``None`` when no fixtures fall in the window.
    """
    raw: list[dict] | None = (
        team_fixtures.get(team_id) or team_fixtures.get(str(team_id))
    )
    if not raw:
        return None

    if current_gw is None:
        # No current GW determinable — use the first ``horizon`` entries
        upcoming = sorted(raw, key=lambda f: int(f["gameweek"]))[:horizon]
    else:
        gw_end   = current_gw + horizon
        upcoming = [
            f for f in raw
            if current_gw <= int(f["gameweek"]) < gw_end
        ]
        upcoming.sort(key=lambda f: int(f["gameweek"]))

    if not upcoming:
        return None

    total_fdr = sum(int(f["difficulty"]) for f in upcoming)
    avg_fdr   = round(total_fdr / len(upcoming), 2)

    fixtures_out = [
        {
            "gameweek":       int(f["gameweek"]),
            "opponent_short": short_map.get(int(f.get("opponent_team", 0)),
                                            f"T{f.get('opponent_team', '?')}"),
            "is_home":        bool(f.get("is_home", False)),
            "difficulty":     int(f["difficulty"]),
        }
        for f in upcoming
    ]

    return {
        "fixture_count": len(upcoming),
        "total_fdr":     total_fdr,
        "avg_fdr":       avg_fdr,
        "fixtures":      fixtures_out,
    }


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------

def get_team_fixture_calendar(
    bootstrap: dict[str, Any],
    mode: str = "easiest",
    horizon: int = DEFAULT_HORIZON,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any]:
    """Rank teams by upcoming fixture difficulty over a bounded GW horizon.

    Parameters
    ----------
    bootstrap:
        FPL bootstrap dict.  Must contain ``team_fixtures`` for a non-error
        response.  Falls back to ``status="missing_context"`` when absent.
    mode:
        ``"easiest"`` (default) — ascending by ``avg_fdr`` (lowest = easiest).
        ``"hardest"``           — descending by ``avg_fdr`` (highest = hardest).
    horizon:
        Number of upcoming GWs to include (default 5, clamped 1–10).
    top_n:
        Maximum number of teams to return (default 5, clamped 1–20).

    Returns — status "ok"
    ----------------------
    ``status``           "ok"
    ``mode``             "easiest" | "hardest"
    ``horizon``          GW window used
    ``current_gameweek`` current GW number (None if not determinable)
    ``top_n``            number of teams actually returned
    ``teams``            ordered list of team entries (see below)

    Each team entry:
    ``rank``           1-based rank in the sorted output
    ``team_short``     3-char abbreviation
    ``team_name``      full team name
    ``fixture_count``  fixtures in the horizon (> horizon possible for DGWs)
    ``avg_fdr``        average FDR across all fixtures in horizon (float)
    ``total_fdr``      sum of FDR values
    ``fixtures``       per-fixture list (gameweek, opponent_short, is_home, difficulty)
    ``has_dgw``        True if the team has ≥2 fixtures in any GW in the horizon
    ``has_bgw``        True if the team blanks in a GW other teams play
    ``dgw_gameweeks``  sorted list of GW numbers with double fixtures for this team
    ``bgw_gameweeks``  sorted list of GW numbers where this team has a blank

    Returns — status "missing_context"
    ------------------------------------
    When ``team_fixtures`` is absent from bootstrap.
    """
    horizon = max(1, min(int(horizon), _MAX_HORIZON))
    top_n   = max(1, min(int(top_n),   _MAX_TOP_N))
    mode    = "hardest" if str(mode).lower() == "hardest" else "easiest"

    team_fixtures: dict = bootstrap.get("team_fixtures", {})
    if not team_fixtures:
        return {
            "status":  "missing_context",
            "message": (
                "No team fixture schedule available "
                "(team_fixtures not in bootstrap)."
            ),
        }

    current_gw = _get_current_gameweek(bootstrap)
    short_map  = _team_short_map(bootstrap)
    name_map   = _team_name_map(bootstrap)

    # Pre-compute active GWs once (shared by all per-team BGW checks)
    active_gws: frozenset[int] = (
        _get_active_gws(team_fixtures, current_gw, horizon)
        if current_gw is not None
        else frozenset()
    )

    # Score every team that has fixtures in the window; attach DGW/BGW labels
    scored: list[dict[str, Any]] = []
    for raw_key in team_fixtures:
        team_id = int(raw_key)
        entry   = _score_team(team_id, team_fixtures, current_gw, horizon, short_map)
        if entry is None:
            continue

        # DGW/BGW classification  (Phase 2.6e.2)
        if current_gw is not None:
            dgw_gws, bgw_gws = _classify_team_gws(
                team_id, team_fixtures, current_gw, horizon, active_gws
            )
        else:
            dgw_gws, bgw_gws = [], []

        scored.append({
            "team_id":       team_id,
            "team_short":    short_map.get(team_id, f"T{team_id}"),
            "team_name":     name_map.get(team_id, f"Team {team_id}"),
            "fixture_count": entry["fixture_count"],
            "avg_fdr":       entry["avg_fdr"],
            "total_fdr":     entry["total_fdr"],
            "fixtures":      entry["fixtures"],
            # Phase 2.6e.2: explicit DGW/BGW labels
            "has_dgw":       bool(dgw_gws),
            "has_bgw":       bool(bgw_gws),
            "dgw_gameweeks": dgw_gws,
            "bgw_gameweeks": bgw_gws,
        })

    if not scored:
        return {
            "status":  "missing_context",
            "message": (
                "No upcoming fixtures found in the current horizon "
                f"(horizon={horizon} GWs from GW{current_gw})."
            ),
        }

    # Sort: easiest = ascending avg_fdr, hardest = descending
    scored.sort(
        key=lambda t: (t["avg_fdr"], t["team_short"]),
        reverse=(mode == "hardest"),
    )

    # Build ranked output (bounded by top_n)
    teams_out = [
        {
            "rank":           rank,
            "team_short":     t["team_short"],
            "team_name":      t["team_name"],
            "fixture_count":  t["fixture_count"],
            "avg_fdr":        t["avg_fdr"],
            "total_fdr":      t["total_fdr"],
            "fixtures":       t["fixtures"],
            # Phase 2.6e.2: DGW/BGW labels
            "has_dgw":        t["has_dgw"],
            "has_bgw":        t["has_bgw"],
            "dgw_gameweeks":  t["dgw_gameweeks"],
            "bgw_gameweeks":  t["bgw_gameweeks"],
        }
        for rank, t in enumerate(scored[:top_n], start=1)
    ]

    return {
        "status":           "ok",
        "mode":             mode,
        "horizon":          horizon,
        "current_gameweek": current_gw,
        "top_n":            len(teams_out),
        "teams":            teams_out,
    }


# ---------------------------------------------------------------------------
# Tool contract
# ---------------------------------------------------------------------------

TEAM_FIXTURE_CALENDAR_SPEC = ToolSpec(
    name="get_team_fixture_calendar",
    description=(
        "Rank all teams by upcoming fixture difficulty over a bounded GW horizon. "
        "Use mode='easiest' for teams with the easiest upcoming schedules, "
        "'hardest' for the toughest. "
        "Returns a top-N list with avg FDR, fixture count, and per-GW detail. "
        "Returns status='missing_context' if fixture data is absent from bootstrap."
    ),
    parameters={
        "type": "object",
        "properties": {
            "mode": {
                "type":        "string",
                "enum":        ["easiest", "hardest"],
                "description": "Sort order: 'easiest' or 'hardest'.",
            },
            "horizon": {
                "type":        "integer",
                "description": "GW lookahead window (default 5, max 10).",
            },
        },
        # mode is always supplied by the router; listing it as required
        # ensures the runner calls handler(args, bootstrap) so both mode
        # and horizon are available to the handler.
        "required": ["mode"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":           {"type": "string"},
            "mode":             {"type": "string"},
            "horizon":          {"type": "integer"},
            "current_gameweek": {"type": ["integer", "null"]},
            "top_n":            {"type": "integer"},
            "teams":            {"type": "array"},
        },
    },
)


def _get_team_fixture_calendar_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``get_team_fixture_calendar()``."""
    mode    = args.get("mode", "easiest")
    horizon = int(args.get("horizon", DEFAULT_HORIZON))
    return get_team_fixture_calendar(bootstrap, mode=mode, horizon=horizon)


TOOL_REGISTRY.register(TEAM_FIXTURE_CALENDAR_SPEC, _get_team_fixture_calendar_handler)


# ===========================================================================
# Phase 2.6e.3 — Single-team fixture schedule
# ===========================================================================

# Common team-name aliases not captured by bootstrap name / short_name alone.
# Maps lowercase variant → lowercase target that matches a bootstrap team name
# or short_name substring.
_TEAM_RESOLVE_ALIASES: dict[str, str] = {
    "spurs":                "tottenham",
    "man city":             "manchester city",
    "man utd":              "manchester utd",
    "man united":           "manchester utd",
    "manchester united":    "manchester utd",
    "wolves":               "wolverhampton",
    "palace":               "crystal palace",
    "villa":                "aston villa",
    "forest":               "nottingham",
    "saints":               "southampton",
    "toffees":              "everton",
    "hammers":              "west ham",
}


def _resolve_team(team_query: str, bootstrap: "dict[str, Any]") -> "dict | None":
    """Resolve a free-text team name to a bootstrap team dict.

    Resolution order:
    1. Static alias map (common nicknames / abbreviations).
    2. Exact match on ``short_name`` (case-insensitive).
    3. Exact match on ``name`` (case-insensitive).
    4. Substring match on ``name`` (returns first match).

    Returns the first matching bootstrap team dict, or ``None``.
    """
    q = team_query.lower().strip()
    # Apply alias map before any bootstrap lookup
    q = _TEAM_RESOLVE_ALIASES.get(q, q)

    teams = bootstrap.get("teams", [])
    # 1. Exact short_name
    for t in teams:
        if t.get("short_name", "").lower() == q:
            return t
    # 2. Exact name
    for t in teams:
        if t.get("name", "").lower() == q:
            return t
    # 3. Substring on name
    for t in teams:
        if q in t.get("name", "").lower():
            return t
    return None


def get_team_schedule(
    args:      "dict[str, Any]",
    bootstrap: "dict[str, Any]",
) -> "dict[str, Any]":
    """Return one team's upcoming fixtures with DGW/BGW labels.

    Parameters
    ----------
    args:
        ``team_query`` (str)  — team name / short_name / common alias.
        ``horizon``    (int)  — GW lookahead window (default 5, clamped 1–10).
    bootstrap:
        FPL bootstrap dict with ``team_fixtures`` and ``teams`` keys.

    Returns — status "ok"
    ----------------------
    ``team_short``        3-char abbreviation
    ``team_name``         full team name
    ``horizon``           GW window used
    ``current_gameweek``  current GW (None if not determinable)
    ``fixture_count``     fixtures in window
    ``avg_fdr``           average FDR across fixtures (2 d.p.)
    ``total_fdr``         sum of FDR values
    ``fixtures``          per-fixture list (gameweek, opponent_short, is_home, difficulty)
    ``has_dgw``           True when team has ≥2 fixtures in any GW in horizon
    ``has_bgw``           True when team blanks in a GW other teams play
    ``dgw_gameweeks``     sorted GW numbers with double fixtures
    ``bgw_gameweeks``     sorted GW numbers where this team has a blank

    Returns — status "not_found"
    ----------------------------
    When no team matches ``team_query`` in bootstrap.

    Returns — status "missing_context"
    ------------------------------------
    When ``team_fixtures`` is absent, or the matched team has no fixtures.
    """
    team_query = str(args.get("team_query", "")).strip()
    horizon    = max(1, min(int(args.get("horizon", DEFAULT_HORIZON)), _MAX_HORIZON))

    team_fixtures: dict = bootstrap.get("team_fixtures", {})
    if not team_fixtures:
        return {
            "status":  "missing_context",
            "message": "No team fixture schedule available (team_fixtures not in bootstrap).",
        }

    team = _resolve_team(team_query, bootstrap)
    if team is None:
        return {
            "status":     "not_found",
            "team_query": team_query,
            "message":    f"No team found matching '{team_query}'.",
        }

    team_id   = int(team["id"])
    short     = team.get("short_name", f"T{team_id}")
    name      = team.get("name",       f"Team {team_id}")
    current_gw = _get_current_gameweek(bootstrap)
    short_map  = _team_short_map(bootstrap)

    entry = _score_team(team_id, team_fixtures, current_gw, horizon, short_map)
    if entry is None:
        return {
            "status":     "missing_context",
            "team_short": short,
            "team_name":  name,
            "message":    (
                f"No upcoming fixtures for {name} "
                f"in the next {horizon} GWs."
            ),
        }

    if current_gw is not None:
        active_gws          = _get_active_gws(team_fixtures, current_gw, horizon)
        dgw_gws, bgw_gws    = _classify_team_gws(
            team_id, team_fixtures, current_gw, horizon, active_gws
        )
    else:
        dgw_gws = bgw_gws = []

    return {
        "status":           "ok",
        "team_short":       short,
        "team_name":        name,
        "horizon":          horizon,
        "current_gameweek": current_gw,
        "fixture_count":    entry["fixture_count"],
        "avg_fdr":          entry["avg_fdr"],
        "total_fdr":        entry["total_fdr"],
        "fixtures":         entry["fixtures"],
        "has_dgw":          bool(dgw_gws),
        "has_bgw":          bool(bgw_gws),
        "dgw_gameweeks":    dgw_gws,
        "bgw_gameweeks":    bgw_gws,
    }


# ---------------------------------------------------------------------------
# Tool contract
# ---------------------------------------------------------------------------

TEAM_SCHEDULE_SPEC = ToolSpec(
    name="get_team_schedule",
    description=(
        "Return one club's upcoming fixtures with DGW/BGW labels. "
        "Resolves the team by name, short_name, or common alias from bootstrap. "
        "Returns status='not_found' when no team matches the query, "
        "status='missing_context' when fixture data is absent."
    ),
    parameters={
        "type": "object",
        "properties": {
            "team_query": {
                "type":        "string",
                "description": "Team name, short_name (e.g. 'ARS'), or alias (e.g. 'Spurs').",
            },
            "horizon": {
                "type":        "integer",
                "description": "GW lookahead window (default 5, max 10).",
            },
        },
        "required": ["team_query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":           {"type": "string"},
            "team_short":       {"type": "string"},
            "team_name":        {"type": "string"},
            "horizon":          {"type": "integer"},
            "current_gameweek": {"type": ["integer", "null"]},
            "fixture_count":    {"type": "integer"},
            "avg_fdr":          {"type": "number"},
            "fixtures":         {"type": "array"},
        },
    },
)

TOOL_REGISTRY.register(TEAM_SCHEDULE_SPEC, get_team_schedule)

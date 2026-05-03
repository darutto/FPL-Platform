"""
fpl_grounded_assistant.team_fixture_calendar
============================================
Phase 2.6e.1: Deterministic team fixture calendar ranking.

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

Intentionally deferred
-----------------------
* DGW / BGW explicit labeling (to 2.6e.2+)
* Single-team calendar lookup (to 2.6e.3)
* Position-filtered calendar (to 2.6e.3)
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
    ``rank``          1-based rank in the sorted output
    ``team_short``    3-char abbreviation
    ``team_name``     full team name
    ``fixture_count`` fixtures in the horizon (> horizon possible for DGWs)
    ``avg_fdr``       average FDR across all fixtures in horizon (float)
    ``total_fdr``     sum of FDR values
    ``fixtures``      per-fixture list (gameweek, opponent_short, is_home, difficulty)

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

    # Score every team that has fixtures in the window
    scored: list[dict[str, Any]] = []
    for raw_key in team_fixtures:
        team_id = int(raw_key)
        entry   = _score_team(team_id, team_fixtures, current_gw, horizon, short_map)
        if entry is None:
            continue
        scored.append({
            "team_id":      team_id,
            "team_short":   short_map.get(team_id, f"T{team_id}"),
            "team_name":    name_map.get(team_id, f"Team {team_id}"),
            "fixture_count": entry["fixture_count"],
            "avg_fdr":      entry["avg_fdr"],
            "total_fdr":    entry["total_fdr"],
            "fixtures":     entry["fixtures"],
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
            "rank":          rank,
            "team_short":    t["team_short"],
            "team_name":     t["team_name"],
            "fixture_count": t["fixture_count"],
            "avg_fdr":       t["avg_fdr"],
            "total_fdr":     t["total_fdr"],
            "fixtures":      t["fixtures"],
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

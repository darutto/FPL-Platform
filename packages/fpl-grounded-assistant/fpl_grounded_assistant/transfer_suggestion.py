"""
fpl_grounded_assistant.transfer_suggestion
==========================================
Phase 2.6h: Deterministic transfer target suggestions by position and price.

Provides ranked transfer target recommendations for prompts like:
  "best midfielders to buy"
  "best forwards under 8.0"
  "cheap defenders to transfer in"
  "a quién fichar para el mediocampo"
  "mejores delanteros para fichar bajo 7.5 millones"

Design rules
------------
* Pure deterministic logic — no LLM calls.
* Players filtered to status="a" (available only).
* Position filter: if specified, only players of that FPL position.
* Price ceiling: if max_price given, only players with now_cost ≤ max_price*10
  (FPL stores cost in tenths of £, e.g. now_cost=75 → £7.5m).
* Ranking composite_score = form / avg_fdr (higher is better).
  - form: float from element "form" field (string → float cast).
  - avg_fdr: average FDR over next ``horizon`` GWs from team_fixtures.
  - Fallback when team_fixtures absent: avg_fdr treated as 1.0 (neutral).
* Players with composite_score ≤ 0 (zero form) are excluded.
* Returns at most top_n results (default 5).

Output shape — status "ok"
---------------------------
  status           "ok"
  position         canonical FPL code or "ALL" when no filter applied
  position_label   human-readable or "all positions"
  team_short       3-char team abbreviation (e.g. "LIV") — None when no team filter
  team_name        full team name (e.g. "Liverpool")       — None when no team filter
  max_price        float or None
  horizon          GW lookahead used for FDR
  top_n            number of picks returned
  picks            list of pick dicts (see below)

Each pick dict:
  rank             1-based rank by composite_score descending
  web_name         display name (e.g. "Palmer")
  team_short       3-char team abbreviation (e.g. "CHE")
  position         FPL position string
  now_cost         int  — price in tenths of £ (FPL format)
  now_cost_m       float — price in millions (now_cost / 10)
  form             float — recent form score
  avg_fdr          float — average FDR over horizon (2 d.p.)
  difficulty_label "easy" | "moderate" | "hard"
  composite_score  float — form / avg_fdr ranking key (2 d.p.)
  ownership        float — selected_by_percent as float

Output shape — status "empty"
-------------------------------
  When no players survive the filters.

Output shape — status "not_found"  (Phase 2.6i)
-------------------------------------------------
  When team_query is provided but no team matches it in bootstrap.
  team_query  the unresolved query string
  message     descriptive message

Output shape — status "missing_context"
-----------------------------------------
  When no element data is present in bootstrap.
"""
from __future__ import annotations

import re as _re
from typing import Any

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .team_fixture_calendar import _resolve_team  # reuse existing team resolver


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HORIZON: int = 5
DEFAULT_TOP_N:   int = 5
_MAX_HORIZON:    int = 10

# FDR thresholds (shared with player_fixture_run.py)
_EASY_THRESHOLD: float = 3.0
_HARD_THRESHOLD: float = 3.5

# Position code → display label
_POSITION_LABELS: dict[str, str] = {
    "GKP": "goalkeepers",
    "DEF": "defenders",
    "MID": "midfielders",
    "FWD": "forwards",
    "ALL": "all positions",
}

# Position alias map: lowercase alias → canonical FPL code
_POSITION_ALIASES: dict[str, str] = {
    "gkp":              "GKP",
    "goalkeeper":       "GKP",
    "goalkeepers":      "GKP",
    "portero":          "GKP",
    "porteros":         "GKP",
    "def":              "DEF",
    "defender":         "DEF",
    "defenders":        "DEF",
    "defensa":          "DEF",
    "defensas":         "DEF",
    "defensor":         "DEF",
    "defensores":       "DEF",
    "mid":              "MID",
    "midfielder":       "MID",
    "midfielders":      "MID",
    "centrocampista":   "MID",
    "centrocampistas":  "MID",
    "mediocampista":    "MID",
    "mediocampistas":   "MID",
    "medio":            "MID",
    "medios":           "MID",
    "fwd":              "FWD",
    "forward":          "FWD",
    "forwards":         "FWD",
    "striker":          "FWD",
    "strikers":         "FWD",
    "delantero":        "FWD",
    "delanteros":       "FWD",
    "atacante":         "FWD",
    "atacantes":        "FWD",
    "punta":            "FWD",
    "puntas":           "FWD",
}


def _resolve_position(query: str) -> str | None:
    """Map a free-text position alias to canonical FPL code, or None."""
    return _POSITION_ALIASES.get(query.lower().strip())


def _position_label(element_type: int) -> str:
    return {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}.get(element_type, "UNK")


# ---------------------------------------------------------------------------
# Bootstrap helpers
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


def _team_avg_fdr(
    team_id: int,
    team_fixtures: dict,
    current_gw: int | None,
    horizon: int,
) -> float:
    """Compute avg FDR for a team over the horizon from current_gw.

    Returns 3.0 (neutral) when data is unavailable.
    """
    if not team_fixtures or current_gw is None:
        return 3.0
    raw = team_fixtures.get(team_id) or team_fixtures.get(str(team_id)) or []
    gw_end = current_gw + horizon
    upcoming = [
        int(f["difficulty"])
        for f in raw
        if current_gw <= int(f.get("gameweek", 0)) < gw_end
    ]
    if not upcoming:
        return 3.0
    return round(sum(upcoming) / len(upcoming), 2)


def _difficulty_label(avg_fdr: float) -> str:
    if avg_fdr < _EASY_THRESHOLD:
        return "easy"
    if avg_fdr < _HARD_THRESHOLD:
        return "moderate"
    return "hard"


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------

def get_transfer_suggestion(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Return ranked transfer targets filtered by position, club, and price ceiling.

    Parameters
    ----------
    args:
        position_query : str | None   — position alias ("midfielders") or absent
        team_query     : str | None   — club name/alias ("Arsenal", "liverpool") or absent
        max_price      : float | None — price ceiling in millions (e.g. 8.0)
        horizon        : int          — GW lookahead for FDR (default 5)
        top_n          : int          — max results (default 5)
    bootstrap:
        FPL bootstrap dict.
    """
    position_query = args.get("position_query") or None
    team_query_raw = args.get("team_query") or None
    max_price_raw  = args.get("max_price")
    horizon        = max(1, min(int(args.get("horizon", DEFAULT_HORIZON)), _MAX_HORIZON))
    top_n          = max(1, min(int(args.get("top_n", DEFAULT_TOP_N)), 20))

    # Resolve position
    position_code: str = "ALL"
    if position_query:
        resolved = _resolve_position(str(position_query))
        if resolved:
            position_code = resolved

    # Resolve club filter (Phase 2.6i)
    filter_team_id: int | None = None
    filter_team_short: str | None = None
    filter_team_name:  str | None = None
    if team_query_raw:
        team_dict = _resolve_team(str(team_query_raw), bootstrap)
        if team_dict is None:
            return {
                "status":     "not_found",
                "team_query": team_query_raw,
                "message":    f"No team found matching '{team_query_raw}'.",
            }
        filter_team_id    = int(team_dict["id"])
        filter_team_short = team_dict.get("short_name")
        filter_team_name  = team_dict.get("name")

    # Resolve max price (convert £m to FPL cost units; None = no ceiling)
    max_cost: int | None = None
    if max_price_raw is not None:
        try:
            max_cost = int(round(float(max_price_raw) * 10))
        except (TypeError, ValueError):
            pass

    elements = bootstrap.get("elements", [])
    if not elements:
        return {
            "status":  "missing_context",
            "message": "No player data available in bootstrap (elements absent).",
        }

    team_fixtures = bootstrap.get("team_fixtures") or {}
    current_gw    = _get_current_gameweek(bootstrap)
    short_map     = _team_short_map(bootstrap)

    scored: list[dict[str, Any]] = []

    for el in elements:
        # Availability
        if el.get("status") != "a":
            continue

        # Position filter
        pos_code = _position_label(int(el.get("element_type", 0)))
        if position_code != "ALL" and pos_code != position_code:
            continue

        # Club filter (Phase 2.6i)
        team_id = int(el.get("team", 0))
        if filter_team_id is not None and team_id != filter_team_id:
            continue

        # Price filter
        now_cost = int(el.get("now_cost", 0))
        if max_cost is not None and now_cost > max_cost:
            continue

        # Form
        try:
            form = float(el.get("form", 0) or 0)
        except (TypeError, ValueError):
            form = 0.0

        avg_fdr  = _team_avg_fdr(team_id, team_fixtures, current_gw, horizon)
        # Guard against division by zero (avg_fdr=0 should not occur in practice)
        denom = avg_fdr if avg_fdr > 0 else 1.0
        composite = round(form / denom, 4)

        # Exclude zero-form players (no useful signal)
        if composite <= 0:
            continue

        try:
            ownership = float(el.get("selected_by_percent", 0) or 0)
        except (TypeError, ValueError):
            ownership = 0.0

        scored.append({
            "web_name":        str(el.get("web_name", "")),
            "team_short":      short_map.get(team_id, f"T{team_id}"),
            "position":        pos_code,
            "now_cost":        now_cost,
            "now_cost_m":      round(now_cost / 10, 1),
            "form":            round(form, 1),
            "avg_fdr":         avg_fdr,
            "difficulty_label": _difficulty_label(avg_fdr),
            "composite_score": composite,
            "ownership":       round(ownership, 1),
        })

    if not scored:
        pos_label    = _POSITION_LABELS.get(position_code, position_code.lower())
        price_clause = f" under £{max_price_raw}m" if max_price_raw is not None else ""
        team_clause  = f" from {filter_team_short}" if filter_team_short else ""
        return {
            "status":     "empty",
            "position":   position_code,
            "team_short": filter_team_short,
            "team_name":  filter_team_name,
            "max_price":  max_price_raw,
            "horizon":    horizon,
            "top_n":      top_n,
            "message": (
                f"No available {pos_label}{team_clause}{price_clause} found "
                "with positive form in the current bootstrap."
            ),
        }

    # Sort by composite_score descending, then by form descending as tiebreaker
    scored.sort(key=lambda p: (p["composite_score"], p["form"]), reverse=True)
    top = scored[:top_n]

    picks = [
        {
            "rank":             i + 1,
            "web_name":         p["web_name"],
            "team_short":       p["team_short"],
            "position":         p["position"],
            "now_cost":         p["now_cost"],
            "now_cost_m":       p["now_cost_m"],
            "form":             p["form"],
            "avg_fdr":          p["avg_fdr"],
            "difficulty_label": p["difficulty_label"],
            "composite_score":  p["composite_score"],
            "ownership":        p["ownership"],
        }
        for i, p in enumerate(top)
    ]

    return {
        "status":         "ok",
        "position":       position_code,
        "position_label": _POSITION_LABELS.get(position_code, position_code.lower()),
        "team_short":     filter_team_short,   # None when no club filter
        "team_name":      filter_team_name,    # None when no club filter
        "max_price":      max_price_raw,
        "horizon":        horizon,
        "top_n":          len(picks),
        "picks":          picks,
    }


# ---------------------------------------------------------------------------
# Tool contract
# ---------------------------------------------------------------------------

TRANSFER_SUGGESTION_SPEC = ToolSpec(
    name="get_transfer_suggestion",
    description=(
        "Return ranked transfer targets for a given position and optional price ceiling. "
        "Filters available players by position and max_price, then ranks by "
        "form / avg_fdr composite score (higher = better). "
        "Returns status='empty' when no players survive filters. "
        "Returns status='missing_context' when no element data is in bootstrap."
    ),
    parameters={
        "type": "object",
        "properties": {
            "position_query": {
                "type":        "string",
                "description": "Position alias e.g. 'midfielders', 'delanteros'. Omit for all positions.",
            },
            "team_query": {
                "type":        "string",
                "description": "Club name or alias e.g. 'Arsenal', 'Liverpool'. Omit for all clubs.",
            },
            "max_price": {
                "type":        "number",
                "description": "Price ceiling in millions (e.g. 8.0 = £8.0m). Omit for no ceiling.",
            },
            "horizon": {
                "type":        "integer",
                "description": "GW lookahead for FDR computation (default 5, max 10).",
            },
        },
        # horizon is always provided by the router; listing it as required
        # ensures the tool runner calls handler(args, bootstrap) so all
        # route-injected parameters (position_query, max_price, horizon) are passed.
        "required": ["horizon"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":         {"type": "string"},
            "position":       {"type": "string"},
            "position_label": {"type": "string"},
            "max_price":      {"type": ["number", "null"]},
            "horizon":        {"type": "integer"},
            "top_n":          {"type": "integer"},
            "picks":          {"type": "array"},
        },
    },
)


def _get_transfer_suggestion_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``get_transfer_suggestion()``."""
    return get_transfer_suggestion(args, bootstrap)


TOOL_REGISTRY.register(TRANSFER_SUGGESTION_SPEC, _get_transfer_suggestion_handler)

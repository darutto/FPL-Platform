"""
fpl_grounded_assistant.differential_picks
==========================================
Phase 7g: Deterministic differential picks retrieval.

Provides grounded low-ownership player recommendations for prompts like:
  "good differentials"
  "differential options"
  "low ownership picks"
  "best differentials this week"
  "differentials"
  "show me differentials"

Design rules
------------
* Pure deterministic logic -- no LLM calls, no external API calls.
* Players are filtered to ``status == "a"`` (available) and
  ``selected_by_percent < OWNERSHIP_THRESHOLD`` (default 15.0%).
* Players whose team has no fixture in the current GW (blank GW) are
  excluded when ``team_fixtures`` data is available.  If fixture data
  is absent the filter is skipped (safe fallback — no players dropped).
* Ranking uses the canonical ``calculate_captain_score`` formula from
  ``fpl_captain_engine`` -- the same engine used by captain scoring,
  comparison, transfer, and chip advice.
* Scoring inputs are derived from bootstrap element data (form,
  xgi_per_90, minutes_risk, fixture_difficulty) using the shared
  ``_derive_scoring_inputs`` helper from ``transfer_advisor``.
* Players with ``position_score <= 0`` are excluded (insufficient data).
* Results are bounded to ``top_n`` entries (default 5).
* Default ownership threshold: 15.0 (%).
* Default top_n: 5.

Output shape -- status "ok"
---------------------------
    status              "ok"
    ownership_threshold float -- threshold used for filtering
    top_n               int   -- number of results returned
    picks               list of pick dicts (see below)

Each pick dict:
    rank            1-based rank by captain_score descending
    web_name        display name (e.g. "Palmer")
    team_short      3-char team abbreviation (e.g. "CHE")
    position        FPL position string (FWD/MID/DEF/GKP)
    captain_score   float -- deterministic captain score
    ownership       float -- selected_by_percent as float
    now_cost        int   -- current price in tenths of £ (e.g. 75 = £7.5m)

Output shape -- status "empty"
-------------------------------
    status              "empty"
    ownership_threshold float
    top_n               int
    message             descriptive message explaining why no picks were found

Deferred
--------
* Positional filtering (FWD/MID/DEF only — GKP currently included at
  low captaincy score but filtered by score_floor in practice)
* Ownership threshold configurability via prompt (currently fixed at 15%)
* top_n configurability via prompt (currently fixed at 5)
* DGW/fixture-run overlay per pick
* Price ceiling filter
"""
from __future__ import annotations

from typing import Any

from fpl_captain_engine import calculate_captain_score
from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .transfer_advisor import _derive_scoring_inputs
from .position_score import compute_position_score


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Ownership percentage ceiling for differential classification.
OWNERSHIP_THRESHOLD: float = 15.0

#: Number of top differentials to return.
TOP_N: int = 5

#: Minimum captain score for a pick to be included.
_SCORE_FLOOR: float = 0.0


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------

def _get_current_gw(bootstrap: dict[str, Any]) -> int | None:
    """Return the current GW id from bootstrap events, or None."""
    for event in bootstrap.get("events", []):
        if event.get("is_current"):
            return event.get("id")
    return None


def _has_current_gw_fixture(
    team_id: int,
    team_fixtures: dict | None,
    current_gw: int | None,
) -> bool | None:
    """Return whether the team has a fixture in the current GW.

    Returns
    -------
    True
        Team has at least one fixture in ``current_gw``.
    False
        Team has fixture data available but no entry for ``current_gw``
        (blank gameweek for this team).
    None
        Fixture data is unavailable (``team_fixtures`` is None,
        ``current_gw`` is None, or the team has no entry in
        ``team_fixtures``).  The player is *not* filtered when None.
    """
    if team_fixtures is None or current_gw is None:
        return None
    fixtures = team_fixtures.get(team_id)
    if fixtures is None:
        return None
    return any(fix.get("gameweek") == current_gw for fix in fixtures)


def _position_label(element_type: int) -> str:
    """Map FPL element_type int (1-4) to a position string."""
    return {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}.get(element_type, "UNK")


def _team_short_map(bootstrap: dict[str, Any]) -> dict[int, str]:
    """Build a team_id → short_name lookup from bootstrap["teams"]."""
    return {
        int(t["id"]): str(t.get("short_name", f"T{t['id']}"))
        for t in bootstrap.get("teams", [])
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_differential_picks(
    bootstrap: dict[str, Any],
    ownership_threshold: float = OWNERSHIP_THRESHOLD,
    top_n: int = TOP_N,
) -> dict[str, Any]:
    """Return the top differential picks from bootstrap data.

    Filters available players below the ownership threshold and ranks
    them by deterministic captain score (descending).  Returns at most
    ``top_n`` results.

    Parameters
    ----------
    bootstrap:
        Raw FPL bootstrap dict.  Must contain ``elements``, ``teams``,
        and ``fixture_difficulty_map``.
    ownership_threshold:
        Ownership percentage ceiling (default 15.0).  Players with
        ``selected_by_percent >= ownership_threshold`` are excluded.
    top_n:
        Maximum number of picks to return (default 5).

    Returns
    -------
    dict
        Always returned -- never raises.  Inspect ``"status"`` to detect
        empty or error outcomes.

    Examples
    --------
    >>> from fpl_grounded_assistant import STANDARD_BOOTSTRAP
    >>> result = get_differential_picks(STANDARD_BOOTSTRAP)
    >>> result["status"]
    'ok'
    >>> result["ownership_threshold"]
    15.0
    """
    ownership_threshold = max(0.1, min(ownership_threshold, 100.0))
    top_n = max(1, min(top_n, 20))

    fdr_map: dict = bootstrap.get("fixture_difficulty_map", {})
    team_fixtures  = bootstrap.get("team_fixtures")
    current_gw     = _get_current_gw(bootstrap)
    short_map = _team_short_map(bootstrap)

    scored: list[dict[str, Any]] = []

    for element in bootstrap.get("elements", []):
        # Availability filter — only fully available players
        if element.get("status") != "a":
            continue

        # Ownership filter
        try:
            ownership = float(element.get("selected_by_percent", 100))
        except (TypeError, ValueError):
            ownership = 100.0
        if ownership >= ownership_threshold:
            continue

        # Blank-GW filter: exclude players whose team has no current-GW fixture.
        # When team_fixtures data is absent the filter is skipped (safe default).
        team_id = int(element.get("team", 0))
        if _has_current_gw_fixture(team_id, team_fixtures, current_gw) is False:
            continue

        # Score derivation
        inputs = _derive_scoring_inputs(element, fdr_map, team_fixtures, current_gw)
        try:
            # Layer 1: canonical captain_score uses raw fixture_difficulty
            score = float(calculate_captain_score(
                inputs["form"],
                inputs["fixture_difficulty"],
                inputs["xgi_per_90"],
                inputs["minutes_risk"],
            ))
        except Exception:
            continue

        # Phase 8a1/8b: position-aware heuristic evaluation (Layer 2)
        # Uses effective_fdr (home/away adjusted) for fixture component
        position = _position_label(int(element.get("element_type", 0)))
        saves_per_90 = float(element.get("saves_per_90", 0) or 0)
        cs_per_90    = float(element.get("clean_sheets_per_90", 0) or 0)
        dc_per_90    = float(element.get("defensive_contribution_per_90", 0) or 0)

        ps_result = compute_position_score(
            position=position,
            form=inputs["form"],
            fixture_difficulty=inputs["effective_fdr"],
            xgi_per_90=inputs["xgi_per_90"],
            minutes_risk=inputs["minutes_risk"],
            saves_per_90=saves_per_90,
            clean_sheets_per_90=cs_per_90,
            dc_per_90=dc_per_90,
        )

        if ps_result.position_score <= _SCORE_FLOOR:
            continue

        scored.append({
            "web_name":        str(element.get("web_name", "")),
            "team_short":      short_map.get(team_id, f"T{team_id}"),
            "position":        position,
            "captain_score":   round(score, 2),
            "position_score":  ps_result.position_score,
            "ownership":       round(ownership, 1),
            "now_cost":        int(element.get("now_cost", 0)),
            "is_home":         inputs["is_home"],
        })

    if not scored:
        return {
            "status":              "empty",
            "ownership_threshold": ownership_threshold,
            "top_n":               top_n,
            "message": (
                f"No available players found with ownership < {ownership_threshold}% "
                "and a positive captain score."
            ),
        }

    # Phase 8a1: rank by position_score descending (Layer 2)
    scored.sort(key=lambda p: p["position_score"], reverse=True)
    top = scored[:top_n]

    picks = [
        {
            "rank":           i + 1,
            "web_name":       p["web_name"],
            "team_short":     p["team_short"],
            "position":       p["position"],
            "captain_score":  p["captain_score"],
            "position_score": p["position_score"],
            "ownership":      p["ownership"],
            "now_cost":       p["now_cost"],
            "is_home":        p.get("is_home"),
        }
        for i, p in enumerate(top)
    ]

    return {
        "status":              "ok",
        "ownership_threshold": ownership_threshold,
        "top_n":               len(picks),
        "picks":               picks,
    }


# ---------------------------------------------------------------------------
# Tool contract
# ---------------------------------------------------------------------------

DIFFERENTIAL_PICKS_SPEC = ToolSpec(
    name="get_differential_picks",
    description=(
        "Return the top differential FPL picks from bootstrap data. "
        "Filters available players below the ownership threshold (default 15%) "
        "and ranks them by deterministic captain score (descending). "
        "Returns at most top_n results (default 5). "
        "Returns status='empty' when no eligible players are found."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    output_schema={
        "oneOf": [
            {
                "title": "ok",
                "type":  "object",
                "required": ["status", "ownership_threshold", "top_n", "picks"],
                "properties": {
                    "status": {"type": "string", "enum": ["ok"]},
                    "ownership_threshold": {"type": "number"},
                    "top_n": {"type": "integer"},
                    "picks": {
                        "type":  "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "rank":          {"type": "integer"},
                                "web_name":      {"type": "string"},
                                "team_short":    {"type": "string"},
                                "position":      {"type": "string"},
                                "captain_score": {"type": "number"},
                                "ownership":     {"type": "number"},
                                "now_cost":      {"type": "integer"},
                            },
                        },
                    },
                },
            },
            {
                "title": "empty",
                "type":  "object",
                "required": ["status", "ownership_threshold", "top_n", "message"],
                "properties": {
                    "status":  {"type": "string", "enum": ["empty"]},
                    "ownership_threshold": {"type": "number"},
                    "top_n":   {"type": "integer"},
                    "message": {"type": "string"},
                },
            },
        ],
    },
)


def _get_differential_picks_handler(bootstrap: dict[str, Any]) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``get_differential_picks()``.

    No required parameters, so the runner calls this with only ``bootstrap``.
    """
    return get_differential_picks(bootstrap)


# Register with the shared tool registry so run_tool("get_differential_picks", ...) works.
TOOL_REGISTRY.register(DIFFERENTIAL_PICKS_SPEC, _get_differential_picks_handler)

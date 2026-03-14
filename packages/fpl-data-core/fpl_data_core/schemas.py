"""
fpl_data_core.schemas
======================
Canonical column schemas and stat definitions. Tier B upstream contract adapter.

Reference: fpl-data-core/python/schemas.py (audit copy — do not modify)
Source:    FPL-Elo-Insights/scripts/export_data.py (CUMULATIVE_COLS, ID_COLS,
           SNAPSHOT_COLS, TOURNAMENT_NAME_MAP)

# aligned-with: <add upstream commit SHA before first production adoption>
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Player identity columns
# ---------------------------------------------------------------------------

ID_COLS: list[str] = [
    "id",
    "first_name",
    "second_name",
    "web_name",
]

# ---------------------------------------------------------------------------
# Stats that accumulate across the season (26 columns)
# ---------------------------------------------------------------------------

CUMULATIVE_COLS: list[str] = [
    "total_points",
    "minutes",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "own_goals",
    "penalties_saved",
    "penalties_missed",
    "yellow_cards",
    "red_cards",
    "saves",
    "starts",
    "bonus",
    "bps",
    "transfers_in",
    "transfers_out",
    "dreamteam_count",
    "expected_goals",
    "expected_assists",
    "expected_goal_involvements",
    "expected_goals_conceded",
    "influence",
    "creativity",
    "threat",
    "ict_index",
]

# ---------------------------------------------------------------------------
# Snapshot columns — point-in-time values, NOT cumulative
# ---------------------------------------------------------------------------

SNAPSHOT_COLS: list[str] = [
    "status",
    "news",
    "now_cost",
    "selected_by_percent",
    "form",
    "event_points",
    "cost_change_event",
    "transfers_in_event",
    "transfers_out_event",
    "value_form",
    "value_season",
    "ep_next",
    "ep_this",
]

# ---------------------------------------------------------------------------
# Tournament name normalisation
# ---------------------------------------------------------------------------

TOURNAMENT_NAME_MAP: dict[str, str] = {
    "friendly":          "Friendlies",
    "premier-league":    "Premier League",
    "prem":              "Premier League",
    "champions-league":  "Champions League",
    "europa-league":     "Europa League",
    "conference-league": "Conference League",
    "fa-cup":            "FA Cup",
    "efl-cup":           "EFL Cup",
    "community-shield":  "Community Shield",
    "uefa-super-cup":    "Uefa Super Cup",
}

EXCLUDED_TOURNAMENTS: set[str] = {"friendly"}
EXCLUDED_GAMEWEEKS: set[int] = {0}

# ---------------------------------------------------------------------------
# Position mapping  (FPL element_type → string code)
# ---------------------------------------------------------------------------

POSITION_MAP: dict[int, str] = {
    1: "GKP",
    2: "DEF",
    3: "MID",
    4: "FWD",
}


def normalise_position(element_type: int | str) -> str:
    """Return position abbreviation for a numeric or string element_type.

    Source: captaincy-showdown/src/utils/candidateMapper.ts::normalizePosition

    Examples:
        normalise_position(3)            → "MID"
        normalise_position("MID")        → "MID"
        normalise_position("Midfielder") → "MID"
        normalise_position(99)           → "Unknown"
    """
    aliases: dict[str, str] = {
        "GKP": "GKP", "GK": "GKP", "GOALKEEPER": "GKP",
        "DEF": "DEF", "DEFENDER": "DEF",
        "MID": "MID", "MIDFIELDER": "MID",
        "FWD": "FWD", "FORWARD": "FWD", "ST": "FWD", "STRIKER": "FWD",
    }
    s = str(element_type).strip().upper()
    if s in aliases:
        return aliases[s]
    try:
        return POSITION_MAP.get(int(s), "Unknown")
    except (ValueError, TypeError):
        return "Unknown"



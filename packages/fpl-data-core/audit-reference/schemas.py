"""
fpl-data-core · packages/fpl-data-core/python/schemas.py
=========================================================
Canonical column schemas and stat definitions.

SOURCE:  Promoted from:
  - FPL-Elo-Insights/scripts/export_data.py
    • CUMULATIVE_COLS  (lines 30-37)  — the canonical stat column list
    • ID_COLS          (line 38)
    • SNAPSHOT_COLS    (lines 39-43)
    • TOURNAMENT_NAME_MAP (lines 12-23)

REPLACES (do NOT delete originals until migration is approved):
  - FPL-Elo-Insights/scripts/export_data.py  CUMULATIVE_COLS / ID_COLS / SNAPSHOT_COLS

CONSUMERS AFTER MIGRATION:
  - FPL-Elo-Insights/scripts/export_data.py
  - fpl-elo-insights-clean/scripts/export_data.py  (the diverged fork)
  - fpl-platform/pipelines/sync_from_supabase.py
  - captaincy-ml (any script that references these column lists)
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
"""Columns that uniquely identify a player row.

SOURCE: FPL-Elo-Insights/scripts/export_data.py line 38
"""

# ---------------------------------------------------------------------------
# Stats that accumulate across the season
# Used by calculate_discrete_gameweek_stats() to produce per-GW deltas
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
    # 2025-26 additions — confirmed present in bootstrap-static elements
    "defensive_contribution",           # tackles_won + interceptions + blocks + clearances
    "clearances_blocks_interceptions",  # FPL's broader defensive actions count
    "tackles",                          # tackles won (season total)
    "recoveries",                       # ball recoveries (season total)
]
"""Columns whose season values are cumulative (not discrete).

To obtain per-gameweek values subtract the previous GW's value from the
current GW's value. See stat_calculator.py::calculate_discrete_gameweek_stats.

SOURCE: FPL-Elo-Insights/scripts/export_data.py lines 30-37
Updated: 2026-03-23 — added 2025-26 defensive contribution fields confirmed
via live bootstrap-static API inspection (105 element keys total).
"""

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
"""Columns that are point-in-time snapshots (use as-is, no subtraction needed).

SOURCE: FPL-Elo-Insights/scripts/export_data.py lines 39-43
"""

# ---------------------------------------------------------------------------
# Per-90 columns — pre-computed by FPL from season cumulative totals
# These are ratio snapshots; do NOT subtract to get per-GW values.
# Confirmed present in bootstrap-static elements (2025-26 season).
# ---------------------------------------------------------------------------

PER_90_COLS: list[str] = [
    "defensive_contribution_per_90",      # dc season total / (minutes / 90)
    "clean_sheets_per_90",                # clean_sheets / (minutes / 90)
    "goals_conceded_per_90",              # goals_conceded / (minutes / 90)
    "saves_per_90",                       # saves / (minutes / 90) — GKP only non-zero
    "expected_goals_conceded_per_90",     # xGC / (minutes / 90)
    "expected_goals_per_90",              # xG / (minutes / 90)
    "expected_assists_per_90",            # xA / (minutes / 90)
    "expected_goal_involvements_per_90",  # xGI / (minutes / 90) — FPL pre-computed
    "starts_per_90",                      # starts / (minutes / 90)
]
"""Pre-computed per-90 ratio fields provided directly by the FPL bootstrap API.

Key scoring observations (live data, GW28 2025-26, players with >450 min):
    GKP  defensive_contribution_per_90: median=0.0, max=0.0  (always zero — GKPs excluded)
    DEF  defensive_contribution_per_90: median=7.5, max=13.8
    MID  defensive_contribution_per_90: median=8.3, max=14.9  (higher than DEF — DMs dominate)
    FWD  defensive_contribution_per_90: median=4.4, max=7.5

    saves_per_90: GKP range 1.6–3.6, all outfield = 0.0  (GKP-exclusive signal)
    clean_sheets_per_90: uniform across outfield positions (~0.27–0.34 median)
                         — useful as player-level history, not position differentiator

These observations inform Phase 8a position-aware scoring:
    - dc_per_90 is NOT a DEF advantage over MID (MIDs score higher)
    - dc_per_90 IS a GKP disqualifier (GKPs = 0 always)
    - saves_per_90 is the primary GKP-specific signal
    - clean_sheets_per_90 is a player-level historical signal for DEF/GKP bias

Updated: 2026-03-23 via live bootstrap-static API inspection.
"""

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
"""Mapping from tournament slugs (as stored in match_id) to display names.

SOURCE: FPL-Elo-Insights/scripts/export_data.py lines 12-23
"""

EXCLUDED_TOURNAMENTS: set[str] = {"friendly"}
"""Tournaments to exclude from all FPL-relevant stat calculations."""

EXCLUDED_GAMEWEEKS: set[int] = {0}
"""Gameweek numbers that are not real FPL gameweeks (e.g. pre-season)."""


# ---------------------------------------------------------------------------
# Position mapping  (FPL element_type → string code)
# ---------------------------------------------------------------------------

POSITION_MAP: dict[int, str] = {
    1: "GKP",
    2: "DEF",
    3: "MID",
    4: "FWD",
}
"""Maps FPL numeric element_type to the standard position abbreviation.

SOURCE: captaincy-showdown/src/utils/candidateMapper.ts::normalizePosition (lines 1-17)
"""

def normalise_position(element_type: int | str) -> str:
    """Return position abbreviation for a numeric or string element_type.

    SOURCE: captaincy-showdown/src/utils/candidateMapper.ts::normalizePosition

    Examples:
        normalise_position(3)     → "MID"
        normalise_position("MID") → "MID"
        normalise_position("Midfielder") → "MID"
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



"""fpl-data-core — Phase 1a public package surface.

Exports for Phase 1a (season_registry + schemas + analytics).
stat_calculator (make_discrete, calculate_discrete_gameweek_stats) is NOT
exported here — those functions are Tier C duplications scheduled for retirement.

Usage:
    from fpl_data_core.season_registry import get_season_layout, SeasonLayout
    from fpl_data_core.schemas import CUMULATIVE_COLS, normalise_position
    from fpl_data_core.analytics import compute_rolling_xgi_per_90
"""

from .season_registry import (
    SeasonLayout,
    SEASON_REGISTRY,
    get_season_layout,
    list_available_seasons,
    register_season,
    load_registry_from_yaml,
)
from .schemas import (
    ID_COLS,
    CUMULATIVE_COLS,
    SNAPSHOT_COLS,
    TOURNAMENT_NAME_MAP,
    EXCLUDED_TOURNAMENTS,
    EXCLUDED_GAMEWEEKS,
    POSITION_MAP,
    normalise_position,
)
from .analytics import compute_rolling_xgi_per_90

__all__ = [
    # season_registry
    "SeasonLayout", "SEASON_REGISTRY", "get_season_layout",
    "list_available_seasons", "register_season", "load_registry_from_yaml",
    # schemas
    "ID_COLS", "CUMULATIVE_COLS", "SNAPSHOT_COLS",
    "TOURNAMENT_NAME_MAP", "EXCLUDED_TOURNAMENTS", "EXCLUDED_GAMEWEEKS",
    "POSITION_MAP", "normalise_position",
    # analytics
    "compute_rolling_xgi_per_90",
]



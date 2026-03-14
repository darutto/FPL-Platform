"""fpl-data-core Python package.

Public surface area:

    from fpl_data_core.season_registry import (
        SeasonLayout, get_season_layout,
        list_available_seasons, register_season,
    )
    from fpl_data_core.schemas import (
        ID_COLS, CUMULATIVE_COLS, SNAPSHOT_COLS,
        TOURNAMENT_NAME_MAP, POSITION_MAP, normalise_position,
    )
    from fpl_data_core.stat_calculator import (
        make_discrete, calculate_discrete_gameweek_stats,
        compute_rolling_xgi_per_90,
    )
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
from .stat_calculator import (
    make_discrete,
    calculate_discrete_gameweek_stats,
    compute_rolling_xgi_per_90,
)

__all__ = [
    # season registry
    "SeasonLayout", "SEASON_REGISTRY", "get_season_layout",
    "list_available_seasons", "register_season", "load_registry_from_yaml",
    # schemas
    "ID_COLS", "CUMULATIVE_COLS", "SNAPSHOT_COLS",
    "TOURNAMENT_NAME_MAP", "EXCLUDED_TOURNAMENTS", "EXCLUDED_GAMEWEEKS",
    "POSITION_MAP", "normalise_position",
    # stat calculator
    "make_discrete", "calculate_discrete_gameweek_stats",
    "compute_rolling_xgi_per_90",
]



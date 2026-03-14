"""fpl-api-client Python package.

Public surface area:

    from fpl_api_client.fpl_client import (
        get_bootstrap, get_players, get_teams,
        get_current_gameweek, get_fixtures,
        get_fixture_difficulty_map, get_player_history,
    )

    from fpl_api_client.football_data_client import FootballDataClient
"""

from .fpl_client import (
    get_bootstrap,
    get_players,
    get_teams,
    get_current_gameweek,
    get_fixtures,
    get_fixture_difficulty_map,
    get_player_history,
    fetch_json,
)
from .football_data_client import FootballDataClient

__all__ = [
    "get_bootstrap",
    "get_players",
    "get_teams",
    "get_current_gameweek",
    "get_fixtures",
    "get_fixture_difficulty_map",
    "get_player_history",
    "fetch_json",
    "FootballDataClient",
]



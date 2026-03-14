"""
fpl_api_client
==============
Python client for the official FPL API.

Phase 1c public surface (bootstrap slice):

    from fpl_api_client import get_bootstrap, get_players, get_teams, get_current_gameweek

Phase 4a additions (fixtures slice):

    from fpl_api_client import get_fixtures, get_fixture_difficulty_map

Reference: fpl-api-client/python/fpl_client.py (audit copy — do not modify)
"""

from .fpl_client import (
    get_bootstrap,
    get_players,
    get_teams,
    get_current_gameweek,
    get_fixtures,
    get_fixture_difficulty_map,
)

__all__ = [
    "get_bootstrap",
    "get_players",
    "get_teams",
    "get_current_gameweek",
    "get_fixtures",
    "get_fixture_difficulty_map",
]



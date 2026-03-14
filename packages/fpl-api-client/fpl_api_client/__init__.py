"""
fpl_api_client
==============
Bootstrap-only Python client for the official FPL API.

Phase 1c public surface (bootstrap slice):

    from fpl_api_client import get_bootstrap, get_players, get_teams, get_current_gameweek

Future slices (not yet exposed):
    - get_fixtures / get_fixture_difficulty_map  (Phase 2)
    - get_player_history                         (Phase 2)
    - FootballDataClient (football-data.org)     (Phase 3)

Reference: fpl-api-client/python/fpl_client.py (audit copy — do not modify)
"""

from .fpl_client import (
    get_bootstrap,
    get_players,
    get_teams,
    get_current_gameweek,
)

__all__ = [
    "get_bootstrap",
    "get_players",
    "get_teams",
    "get_current_gameweek",
]



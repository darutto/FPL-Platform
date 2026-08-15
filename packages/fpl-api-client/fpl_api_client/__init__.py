"""
fpl_api_client
==============
Python client for the official FPL API.

Phase 1c public surface (bootstrap slice):

    from fpl_api_client import get_bootstrap, get_players, get_teams, get_current_gameweek

Phase 4a additions (fixtures slice):

    from fpl_api_client import get_fixtures, get_fixture_difficulty_map

Preseason reweight addition (season-launch guard for form-based scoring):

    from fpl_api_client import is_form_informative

Reference: fpl-api-client/audit-reference/fpl_client.py (audit copy — do not modify)
"""

from .fpl_client import (
    get_bootstrap,
    get_players,
    get_teams,
    get_current_gameweek,
    get_fixtures,
    get_fixture_difficulty_map,
    is_form_informative,
)

__all__ = [
    "get_bootstrap",
    "get_players",
    "get_teams",
    "get_current_gameweek",
    "get_fixtures",
    "get_fixture_difficulty_map",
    "is_form_informative",
]



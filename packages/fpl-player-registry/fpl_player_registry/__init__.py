"""
fpl_player_registry
====================
Bootstrap-based canonical player identity registry. Phase 1d public surface.

    from fpl_player_registry import PlayerRecord, PlayerRegistry, build_registry, KNOWN_NICKNAMES

Input comes from fpl_api_client bootstrap data:

    from fpl_api_client import get_bootstrap, get_players, get_teams
    bootstrap = get_bootstrap()
    registry = build_registry(get_players(bootstrap), get_teams(bootstrap))

Phase 1d excludes (future slices):
    - SeasonIdMapper  (cross-season CSV-based ID mapping — Phase 2)
    - Broad fuzzy matching (Phase 2+)

Reference: fpl-player-registry/python/player_registry.py (audit copy — do not modify)
"""

from .nicknames import KNOWN_NICKNAMES
from .registry import PlayerRecord, PlayerRegistry, build_registry

__all__ = [
    "PlayerRecord",
    "PlayerRegistry",
    "build_registry",
    "KNOWN_NICKNAMES",
]
"""
worldcup_api_client
====================
HTTP client for the FIFA Fantasy World Cup 2026 public feed
(``https://play.fifa.com/json/fantasy/``).

Mirrors ``fpl_api_client`` in spirit (thin client, retry/backoff) with two
upgrades required by a live tournament:

* ``httpx`` transport instead of ``requests``.
* In-process tiered TTL cache (semi-static 5 min for squads/players,
  volatile 20 s for rounds/live scores).

No API key or configuration is required — this feed is free and public.
``live_scores``, ``fixtures``, ``squad`` are light transforms of the raw
feed; ``standings``, ``top_scorers``, ``head_to_head`` are computed from it.
``get_lineup``/``get_match_stats`` return a graceful "not available" result
since this feed has no lineup/match-stats data.
"""

from .openfootball_client import (  # noqa: F401
    TTL_BRACKET_S,
    clear_bracket_cache,
    get_bracket,
)
from .player_ids import UnknownPlayerError  # noqa: F401
from .team_ids import UnknownTeamError  # noqa: F401
from .wc2022_data import WC2022DataError, get_player_wc2022_summary, get_wc2022_results  # noqa: F401
from .wc_client import (  # noqa: F401
    WorldCupAPIError,
    TTL_STATIC_S,
    TTL_SEMI_STATIC_S,
    TTL_LIVE_S,
    clear_cache,
    fetch_json,
    get_live_scores,
    get_fixtures,
    get_squad,
    get_lineup,
    get_standings,
    get_top_scorers,
    get_top_assists,
    get_fantasy_top_players,
    get_head_to_head,
    get_player_info,
    get_match_stats,
)

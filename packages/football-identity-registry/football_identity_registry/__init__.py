"""Provider-neutral deterministic identity crosswalk foundation."""

from .matcher import MATCH_TIERS, match_player
from .models import CandidatePlayer, MatchResult, SourcePlayer
from .normalization import normalize_name

__all__ = ["CandidatePlayer", "MATCH_TIERS", "MatchResult", "SourcePlayer", "match_player", "normalize_name"]

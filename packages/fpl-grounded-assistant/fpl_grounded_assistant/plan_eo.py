"""EO numbers for the plan_to_sign card: read from caches only, never a job, never a GET.

``plan_to_sign`` answers chip taps with no model and must stay fast, so this module only LOOKS:

* near your rank: ``NearRankEOService.peek`` (a READY result already in the process cache; a missing or
  ``computing`` job is simply "no number" -- nothing is started, nothing waits). The job is started by the warm
  path (``eo_warm``).
* the top 10K: ``TierEOReader.latest_cached`` (the file the warm path pre-read; a cold cache is "no number" --
  no R2 GET happens on a tap).

Every number is the player's ``owned_pct`` (a plain percentage, rounded). Any failure, a flag that is off, or no
data gives ``None`` and the card says nothing: it is then identical to a card without this module.

The result is attached to the tool output as ``eo`` (``plan_card`` words it)::

    {"near": {"target": 31, "sold": {"13": 4}},   # absent when near-rank has no ready data
     "top":  {"target": 45}}                       # absent when the top 10K file is not cached
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .orch_config import is_near_rank_eo_enabled, is_tier_eo_enabled

_LOG = logging.getLogger(__name__)

#: The target is worth a "covers you" line when this share of the managers near the user's rank owns him ...
TARGET_NEAR_COVER_PCT: float = 25.0
#: ... or, as the aspirational line, this share of the top 10K.
TARGET_TOP_COVER_PCT: float = 40.0
#: Selling a premium "does not expose" the user when no more than this share near their rank owns him.
SOLD_NO_EXPOSURE_PCT: float = 10.0


def _pct(players: dict[str, Any], pid: int) -> int:
    """A player's ownership in a group's data; absent means nobody in the sample has him."""
    stats = players.get(str(pid)) or {}
    value = stats.get("owned_pct")
    return int(round(float(value))) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def read(bootstrap: dict[str, Any], target_id: int, sold_ids: set[int], now: datetime | None = None) -> dict[str, Any] | None:
    """The cached EO numbers for the target and the players the plan sells, or ``None`` when there are none."""
    near_on, tier_on = is_near_rank_eo_enabled(), is_tier_eo_enabled()
    if not (near_on or tier_on):
        return None
    try:
        from .near_rank_eo_tool import _season, get_service, gw_and_valid_until  # noqa: PLC0415

        gw, _ = gw_and_valid_until(bootstrap.get("events") or [], now or datetime.now(timezone.utc))
        season = _season(bootstrap)
        if gw is None or season is None:
            return None
        out: dict[str, Any] = {}
        team_id = bootstrap.get("_my_team_id")
        if near_on and team_id:
            data = get_service().peek(season, gw, int(team_id))
            if data is not None:
                players = data.get("players") or {}
                out["near"] = {"target": _pct(players, target_id), "sold": {str(pid): _pct(players, pid) for pid in sorted(sold_ids)}}
        if tier_on:
            from . import tier_eo_reader  # noqa: PLC0415

            data = tier_eo_reader.get_reader().latest_cached(season, gw, "top10k")
            if data is not None:
                out["top"] = {"target": _pct(data.get("players") or {}, target_id)}
        return out or None
    except Exception:  # noqa: BLE001  (a number on a card is never worth an error)
        _LOG.warning("plan_eo read failed", exc_info=True)
        return None

"""Ownership numbers for the plan_to_sign card: read from caches only, never a job, never a GET.

``plan_to_sign`` answers chip taps with no model and must stay fast, so this module only LOOKS:

* near your rank: ``NearRankEOService.peek`` (a READY result already in the process cache; a missing or
  ``computing`` job is simply "no number" -- nothing is started, nothing waits). The job is started by the warm
  path (``eo_warm``).
* the top 10K: ``TierEOReader.latest_cached`` (the file the warm path pre-read; a cold cache is "no number" --
  no R2 GET happens on a tap).

Every number is the player's ``owned_pct`` (a plain ownership percentage, rounded), for the target AND for every
player any option sells (the card needs the net picture, not the target alone). A player ABSENT from a sample is 0
(nobody in it has him); a row that is PRESENT but has no valid ``owned_pct`` is ``None``: no claim is made from bad
data. Any failure, a flag that is off, or no data gives ``None`` and the card says nothing: it is then identical to
a card without this module.

The result is attached to the tool output as ``ownership`` and is hidden from the model (it only words one card
line; named explicitly so nobody reads it as EO)::

    {"near_rank_owned_pct": {"target": 31, "sold": {"13": 4, "14": None}},   # absent: no ready near-rank data
     "top10k_owned_pct":    {"target": 45, "sold": {"13": 12, "14": 0}}}     # absent: file not cached
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

# -- the "differential" line: DISPLAY conditions, not predictors ---------------------------------------------------
# The low-ownership backtest did NOT show a predictive edge: nothing here says a low-owned player will do well, and
# nobody should reword the line into a forecast ("will score", "great pick"). The line only states facts the card can
# back: few managers own him (so IF he scores the user gains on those who do not), and the existing PlanSignals say he
# is a regular starter with a favourable run and an xGI/90 in the top of his position. Missing data: no line.
#: Few own him: at most this share (near your rank first, the top 10K when near-rank has no data).
LOW_OWNED_PCT: float = 10.0
#: Favourable run: at least this many fixtures in the window, an average FDR band CLEARLY below neutral (the official
#: FDR band runs 1 = easiest .. 5 = hardest, 3 = neutral, so 3.0 would be a neutral run), few hard ones.
FIXTURE_MIN_GAMES: int = 3
FIXTURE_MAX_AVG_BAND: float = 2.6
FIXTURE_MAX_HARD: int = 1
#: "Regular starter" needs a start share of the finished gameweeks at least the shared ``STARTS_SHARE_FIRES`` (0.8,
#: set for "started 9 of 10"); a test pins it at 0.75 or more so lowering it elsewhere cannot weaken this claim.
REGULAR_STARTER_MIN_SHARE: float = 0.75


def _pct(players: dict[str, Any], pid: int) -> int | None:
    """Ownership in a group's data: 0 when the player is absent from the sample, None when his row is unusable."""
    row = players.get(str(pid))
    if row is None:
        return 0
    value = row.get("owned_pct") if isinstance(row, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
        return None
    return int(round(float(value)))


def _reference(players: Any, target_id: int, sold_ids: set[int]) -> dict[str, Any] | None:
    """One group's numbers, or None when its data is unusable or the target's own number is."""
    if not isinstance(players, dict):
        return None
    target = _pct(players, target_id)
    if target is None:
        return None
    return {"target": target, "sold": {str(pid): _pct(players, pid) for pid in sorted(sold_ids)}}


def target_signals(signals: Any, pid: int) -> dict[str, bool]:
    """The target's display conditions from the existing ``PlanSignals`` (no new score, no xPts).

    ``nailed``: available (availability tier 2) AND a regular starter: his ``starts`` must be PRESENT and the share of
    the finished gameweeks he started at least ``max(STARTS_SHARE_FIRES, REGULAR_STARTER_MIN_SHARE)``, with enough
    gameweeks finished for a share to mean something. Tier 2 alone is not enough: it is also what a player with no
    ``starts`` data gets. ``fixtures``: a favourable run (see the constants above). ``xgi_top``: his minutes-shrunk xGI/90 is in the top of
    his position (the same "xgi" reason as the top status; early in the season there is no cut-off, so it is False).
    Anything missing or failing is False.
    """
    try:
        from .player_conclusions import STARTS_SHARE_FIRES  # noqa: PLC0415

        element = signals.elements[pid]
        finished = int(signals.finished)
        starts = element.get("starts")
        regular = (not signals.early_season and finished > 0 and isinstance(starts, (int, float))
                   and not isinstance(starts, bool)
                   and min(starts, finished) / finished >= max(STARTS_SHARE_FIRES, REGULAR_STARTER_MIN_SHARE))
        nailed = signals.availability(pid)["tier"] == 2 and regular
        fx = signals.fixtures(pid)
        band = fx.get("avg_band")
        fixtures = (fx.get("games", 0) >= FIXTURE_MIN_GAMES and band is not None and band <= FIXTURE_MAX_AVG_BAND
                    and fx.get("hard", 99) <= FIXTURE_MAX_HARD)
        xgi_top = "xgi" in signals.top(pid)["reasons"]
        return {"nailed": bool(nailed), "fixtures": bool(fixtures), "xgi_top": bool(xgi_top)}
    except Exception:  # noqa: BLE001  (a missing signal is "no line", never an error)
        _LOG.warning("plan_eo target_signals failed", exc_info=True)
        return {"nailed": False, "fixtures": False, "xgi_top": False}


def read(bootstrap: dict[str, Any], target_id: int, sold_ids: set[int], now: datetime | None = None) -> dict[str, Any] | None:
    """The cached ownership numbers for the target and the players the plan sells, or ``None`` when there are none."""
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
            ref = _reference((data or {}).get("players"), target_id, sold_ids) if data is not None else None
            if ref is not None:
                out["near_rank_owned_pct"] = ref
        if tier_on:
            from . import tier_eo_reader  # noqa: PLC0415

            data = tier_eo_reader.get_reader().latest_cached(season, gw, "top10k")
            ref = _reference((data or {}).get("players"), target_id, sold_ids) if data is not None else None
            if ref is not None:
                out["top10k_owned_pct"] = ref
        return out or None
    except Exception:  # noqa: BLE001  (a number on a card is never worth an error)
        _LOG.warning("plan_eo read failed", exc_info=True)
        return None

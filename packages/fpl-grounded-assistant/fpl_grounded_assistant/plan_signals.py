"""Football signals ``plan_to_sign`` orders its options by (PR 1 of the transfer redesign).

Pure and offline: everything is read from the loaded FPL bootstrap, nothing is fetched. Three families:

* **Top status** -- a "top" player of his position is not sold lightly. A player is a top when ANY of:
  price in the top :data:`TOP_PRICE_SHARE` of his position, minutes-shrunk xGI/90 in the top
  :data:`TOP_XGI_SHARE` of his position, or owned by at least :data:`TOP_OWNERSHIP_PCT` % of managers.
  The position pool is the players with at least :data:`~player_conclusions.MIN_POOL_MINUTES` minutes
  (the same pool the player card's percentile lines use); ties at the cut-off are all in.
  The ownership test lives behind ONE function, :func:`ownership_is_top`, because it is meant to be
  replaced by the tier-based effective ownership the project is building.
* **Availability tier** -- 0 unavailable, 1 doubtful or a rotation risk, 2 a nailed starter.
* **Fixture window** -- the club's next :data:`FIXTURE_WINDOW` gameweeks from ``fixture_outlook``,
  starting at :func:`first_affected_gw` (the next gameweek once the current one's deadline has passed)
  (the official FDR band 1-5; hard is 4 or 5): average band and the number of hard fixtures.

Early in the season (fewer than :data:`EARLY_SEASON_GWS` finished gameweeks) a rate or a percentile says
little: ``early_season`` is exposed so the caller can fall back to the strict rule, the xGI test is off and
the position pool is everyone who has played.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .find_players import _safe_float, _safe_int
from .fixture_outlook import get_team_outlook
from .player_conclusions import (
    MIN_POOL_MINUTES,
    STARTS_SHARE_FIRES,
    _availability as _availability_conclusion,
    _set_pieces,
)
from .rank_players_by_metric import finished_gameweeks
from .scoring_shared import _derive_scoring_inputs

TOP_PRICE_SHARE: float = 0.10
TOP_XGI_SHARE: float = 0.15
#: Owned by at least this share of managers (percent). Replace by tier EO behind :func:`ownership_is_top`.
TOP_OWNERSHIP_PCT: float = 20.0
#: Gameweeks of fixtures looked at.
FIXTURE_WINDOW: int = 5
#: A fixture band at or above this is hard (same cut as ``fixture_outlook._classify``).
HARD_BAND: int = 4
#: Below this many finished gameweeks a top may only be sold when he is the only way to fund the target.
EARLY_SEASON_GWS: int = 5

AVAIL_OUT, AVAIL_RISK, AVAIL_NAILED = 0, 1, 2

#: FPL position -> fixture axis: defenders and keepers live off the opponent's attack, forwards off its defence.
_AXIS_BY_POSITION = {1: "defence", 2: "defence", 3: "attack", 4: "attack"}


def first_affected_gw(bootstrap: dict[str, Any], now: datetime | None = None) -> int | None:
    """The first gameweek a transfer made now can affect.

    ``get_current_gameweek`` names the gameweek in progress (``is_current``, not finished), but once its
    deadline has passed the squad is locked for it: a transfer first counts from the next one. Between
    gameweeks (``is_next``) the answer is that gameweek. Without a usable ``deadline_time`` the current
    one is kept.
    """
    from fpl_api_client import get_current_gameweek

    current = get_current_gameweek(bootstrap)
    if current is None:
        return None
    events = {_safe_int(ev.get("id")): ev for ev in bootstrap.get("events") or []}
    event = events.get(current) or {}
    raw = event.get("deadline_time")
    if not event.get("is_current") or not isinstance(raw, str) or (current + 1) not in events:
        return current
    try:
        deadline = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return current
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    moment = now or datetime.now(timezone.utc)
    return current + 1 if moment >= deadline else current


def set_piece_count(element: dict[str, Any]) -> int:
    """How many set pieces (penalties, direct free kicks, corners) he is first choice for."""
    flagged = _set_pieces(element)
    return len(flagged["params"]["pieces"]) if flagged else 0


def ownership_is_top(element: dict[str, Any]) -> bool:
    """Owned by enough managers to count as a top. The single place to swap in tier-based EO later."""
    return _safe_float(element.get("selected_by_percent")) >= TOP_OWNERSHIP_PCT


def _cutoff(values: list[float], share: float) -> float | None:
    """The value a player must reach (inclusive) to be in the top *share* of *values*; ties are in."""
    if not values:
        return None
    k = max(1, int(math.floor(len(values) * share)))
    return sorted(values, reverse=True)[k - 1]


class PlanSignals:
    """Per-call cache of the signals; build once per bootstrap."""

    def __init__(self, bootstrap: dict[str, Any], *, now: datetime | None = None) -> None:
        self.bootstrap = bootstrap
        self.elements: dict[int, dict[str, Any]] = {
            _safe_int(el.get("id")): el for el in bootstrap.get("elements", []) if el.get("id") is not None
        }
        self.finished = finished_gameweeks(bootstrap)
        self.early_season = self.finished < EARLY_SEASON_GWS
        self._fdr_map = bootstrap.get("fixture_difficulty_map", {}) or {}
        self._team_fixtures = bootstrap.get("team_fixtures") or {}
        from fpl_api_client import get_current_gameweek

        self._current_gw = get_current_gameweek(bootstrap)
        #: First gameweek a transfer can affect: the fixture window starts here, not at the one in progress.
        self.window_gw = first_affected_gw(bootstrap, now)
        self._cutoffs: dict[int, tuple[float | None, float | None]] | None = None
        self._xgi: dict[int, float] = {}
        self._fixtures: dict[tuple[int, str], dict[str, Any]] = {}

    # -- top status -------------------------------------------------------

    def xgi(self, pid: int) -> float:
        """Minutes-shrunk xGI/90 -- the same figure ``plan_to_sign`` values players on."""
        if pid not in self._xgi:
            inputs = _derive_scoring_inputs(self.elements[pid], self._fdr_map, self._team_fixtures, self._current_gw)
            self._xgi[pid] = float(inputs["xgi_per_90_shrunk"])
        return self._xgi[pid]

    def _position_cutoffs(self) -> dict[int, tuple[float | None, float | None]]:
        """Per position: (price cut-off, xGI cut-off). The xGI cut-off is None early in the season."""
        if self._cutoffs is None:
            floor = 1 if self.early_season else MIN_POOL_MINUTES
            pools: dict[int, list[int]] = {}
            for pid, el in self.elements.items():
                if _safe_int(el.get("minutes")) >= floor:
                    pools.setdefault(_safe_int(el.get("element_type")), []).append(pid)
            self._cutoffs = {}
            for position, ids in pools.items():
                price = _cutoff([float(_safe_int(self.elements[i].get("now_cost"))) for i in ids], TOP_PRICE_SHARE)
                xgi = None if self.early_season else _cutoff([self.xgi(i) for i in ids if self.xgi(i) > 0], TOP_XGI_SHARE)
                self._cutoffs[position] = (price, xgi)
        return self._cutoffs

    def top(self, pid: int) -> dict[str, Any]:
        """``{"is_top": bool, "reasons": [...]}`` with reasons among ``price``, ``xgi``, ``owned`` in that order."""
        el = self.elements[pid]
        reasons: list[str] = []
        price_cut, xgi_cut = self._position_cutoffs().get(_safe_int(el.get("element_type")), (None, None))
        floor = 1 if self.early_season else MIN_POOL_MINUTES
        in_pool = _safe_int(el.get("minutes")) >= floor
        if in_pool and price_cut is not None and _safe_int(el.get("now_cost")) >= price_cut:
            reasons.append("price")
        if in_pool and xgi_cut is not None and self.xgi(pid) > 0 and self.xgi(pid) >= xgi_cut:
            reasons.append("xgi")
        if ownership_is_top(el):
            reasons.append("owned")
        return {"is_top": bool(reasons), "reasons": reasons}

    # -- availability and minutes ----------------------------------------

    def availability(self, pid: int) -> dict[str, Any]:
        """``{"tier": 0|1|2, "reason": "unavailable"|"doubt"|"rotation"|None}``.

        0 when FPL does not list him as available and gives no chance of playing; 1 for a doubt (a chance
        below 100) or, once enough gameweeks have finished, a start share under
        :data:`~player_conclusions.STARTS_SHARE_FIRES`; 2 otherwise.
        """
        el = self.elements[pid]
        flagged = _availability_conclusion(el)
        if flagged is not None:
            chance = flagged["params"]["chance"]
            status = flagged["params"]["status"]
            if chance == 0 or (chance is None and status in ("i", "s", "u", "n")):
                return {"tier": AVAIL_OUT, "reason": "unavailable"}
            return {"tier": AVAIL_RISK, "reason": "doubt"}
        if not self.early_season:
            starts = min(_safe_int(el.get("starts")), self.finished)
            if el.get("starts") is not None and starts < STARTS_SHARE_FIRES * self.finished:
                return {"tier": AVAIL_RISK, "reason": "rotation"}
        return {"tier": AVAIL_NAILED, "reason": None}

    # -- fixtures ---------------------------------------------------------

    def fixtures(self, pid: int) -> dict[str, Any]:
        """The club's next :data:`FIXTURE_WINDOW` gameweeks: ``avg_band`` (None with no fixture), ``hard``, ``games``."""
        el = self.elements[pid]
        team = _safe_int(el.get("team"))
        axis = _AXIS_BY_POSITION.get(_safe_int(el.get("element_type")), "attack")
        key = (team, axis)
        if key not in self._fixtures:
            outlook = get_team_outlook(self.bootstrap, team, axis, horizon=FIXTURE_WINDOW, _current_gw=self.window_gw)
            bands = [fx["band"] for gw in outlook["series"] for fx in (gw["fixtures"] or [])]
            self._fixtures[key] = {
                "avg_band": round(sum(bands) / len(bands), 2) if bands else None,
                "hard": sum(1 for b in bands if b >= HARD_BAND),
                "games": len(bands),
            }
        return self._fixtures[key]

"""The player card's verdict: 0-3 one-line conclusions the card itself does NOT show.

Approved 2026-11-11 to replace the deterministic text dump above the card (which repeated the card's own numbers).
Each conclusion is shown only when its rule fires; when none fires there is no verdict block at all.

Everything comes from data already loaded for the snapshot -- the FPL bootstrap, the snapshot's own ``zonal``
block and the position facts the caller reads from the per-build lineup index (player_signals.position_fact) -- so
this adds no call of any kind. Conclusions are structured (``key`` + ``params`` + ``evidence``), never
pre-rendered strings: the UI owns the wording in each locale.

Priority (max :data:`MAX_CONCLUSIONS`, first wins):

1. points source -- ``points_attack`` / ``points_defence`` / ``points_clean_sheets``: the one with the highest
   percentile among the player's own FPL position (pool: :data:`MIN_POOL_MINUTES`+ minutes), when it reaches
   :data:`PERCENTILE_FIRES`. Evidence ``top N %`` names the metric.
2. ``position`` -- he starts off his FPL line («Juega de extremo · 8 de 10»; rule and window in player_signals). Second
   because it often explains the first («muy ofensivo para ser defensa» because he plays on the wing). With the cap
   of 3 it pushes ``starts`` out first, then ``zonal``.
3. ``set_pieces`` -- first in FPL's penalties / direct free kicks / corners order; names only the pieces that apply.
4. ``zonal`` -- the snapshot's zonal block already carries at least one favourable matchup (information only we have,
   and actionable: it ranks above the starts line).
5. ``starts`` -- started at least :data:`STARTS_SHARE_FIRES` of the finished gameweeks, and is available now (when
   doubtful/injured the card already shows it, and a past starts record would read as a contradiction). The
   denominator is the finished gameweeks, so a late signing can fall short of the threshold.

Never raises: a malformed input drops that conclusion only.
"""
from __future__ import annotations

import math
from typing import Any

#: At most this many lines above the card -- more stops being a verdict and becomes a list to read.
MAX_CONCLUSIONS: int = 3

#: Minutes a player needs to be in a percentile pool, and to get a points-source line himself. 450 = five full
#: matches: below that, per-90 rates are dominated by a few cameo minutes (see the per-90 desc floor bug).
MIN_POOL_MINUTES: int = 450

#: A points-source line fires at the 80th percentile of his position, i.e. "top 20 %" or better. Below that the
#: claim "de los que más ..." stops being true enough to say out loud.
PERCENTILE_FIRES: float = 80.0

#: Evidence shows "top N %" with N rounded to this step (and never below it): the exact rank is false precision
#: on 10 gameweeks of data, and "top 5 %" reads better than "top 3 %".
TOP_PCT_STEP: int = 5

#: "Titular en 9 de 10" fires from 80 % of the finished gameweeks started: a regular starter, not a rotation risk.
STARTS_SHARE_FIRES: float = 0.8

#: ...but only once enough gameweeks have finished for "N de M" to mean something ("1 de 1" says nothing).
MIN_FINISHED_GWS: int = 5

_POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

#: Points-source metrics per position, in tie-break order: (conclusion key, metric id, bootstrap field).
_POINTS_METRICS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "GKP": (("points_clean_sheets", "cs_per_90", "clean_sheets_per_90"),),
    "DEF": (
        ("points_attack", "xgi_per_90", "expected_goal_involvements_per_90"),
        ("points_defence", "dc_per_90", "defensive_contribution_per_90"),
        ("points_clean_sheets", "cs_per_90", "clean_sheets_per_90"),
    ),
    "MID": (
        ("points_attack", "xgi_per_90", "expected_goal_involvements_per_90"),
        ("points_defence", "dc_per_90", "defensive_contribution_per_90"),
    ),
    "FWD": (("points_attack", "xgi_per_90", "expected_goal_involvements_per_90"),),
}

#: FPL's set-piece order fields -> the piece id the UI words. Order 1 = first-choice taker.
_SET_PIECES: tuple[tuple[str, str], ...] = (
    ("penalties_order", "penalties"),
    ("direct_freekicks_order", "free_kicks"),
    ("corners_and_indirect_freekicks_order", "corners"),
)


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _metric(element: dict[str, Any], field: str) -> float | None:
    """The per-90 field from the bootstrap; computed from the season total when FPL leaves it out."""
    value = _num(element.get(field))
    if value is not None:
        return value
    total = _num(element.get(field.removesuffix("_per_90")))
    minutes = _num(element.get("minutes"))
    if total is None or not minutes:
        return None
    return total * 90.0 / minutes


def _percentile(value: float, pool: list[float]) -> float:
    """Share of the pool strictly below *value*, 0-100."""
    return 100.0 * sum(1 for v in pool if v < value) / len(pool)


def top_pct(percentile: float) -> int:
    """"top N %" from a percentile: N rounded to :data:`TOP_PCT_STEP`, never below it."""
    raw = 100.0 - percentile
    return max(TOP_PCT_STEP, int(math.floor(raw / TOP_PCT_STEP + 0.5)) * TOP_PCT_STEP)


def _points_source(element: dict[str, Any], position: str, elements: list[dict[str, Any]]) -> dict[str, Any] | None:
    if (_num(element.get("minutes")) or 0) < MIN_POOL_MINUTES:
        return None
    pool_elements = [
        e for e in elements
        if _POSITIONS.get(int(_num(e.get("element_type")) or 0)) == position
        and (_num(e.get("minutes")) or 0) >= MIN_POOL_MINUTES
    ]
    best: tuple[float, str, str] | None = None
    for key, metric_id, field in _POINTS_METRICS.get(position, ()):
        value = _metric(element, field)
        pool = [v for v in (_metric(e, field) for e in pool_elements) if v is not None]
        if value is None or not pool or value <= 0:
            continue
        pct = _percentile(value, pool)
        if pct >= PERCENTILE_FIRES and (best is None or pct > best[0]):
            best = (pct, key, metric_id)
    if best is None:
        return None
    pct, key, metric_id = best
    return {
        "key": key,
        "params": {"position": position},
        "evidence": {"metric": metric_id, "top_pct": top_pct(pct), "position": position},
    }


def _set_pieces(element: dict[str, Any]) -> dict[str, Any] | None:
    pieces = [piece for field, piece in _SET_PIECES if _num(element.get(field)) == 1]
    if not pieces:
        return None
    return {"key": "set_pieces", "params": {"pieces": pieces}, "evidence": None}


def _starts(element: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any] | None:
    if element.get("status") != "a":
        return None
    finished = sum(1 for ev in bootstrap.get("events") or [] if ev.get("finished"))
    starts = _num(element.get("starts"))
    if starts is None or finished < MIN_FINISHED_GWS:
        return None
    starts_i = min(int(starts), finished)  # a double gameweek can't make it "11 de 10"
    if starts_i < STARTS_SHARE_FIRES * finished:
        return None
    return {"key": "starts", "params": {"starts": starts_i, "games": finished}, "evidence": None}


def _zonal(zonal: Any) -> dict[str, Any] | None:
    if not isinstance(zonal, dict):
        return None
    opponents: list[str] = []
    for fx in zonal.get("fixtures") or []:
        if isinstance(fx, dict) and fx.get("status") == "favorable":
            short = str(fx.get("opponent_short") or "")
            if short and short not in opponents:
                opponents.append(short)
    if not opponents:
        return None
    return {"key": "zonal", "params": {"opponents": opponents}, "evidence": None}


def _position(position: Any) -> dict[str, Any] | None:
    if not isinstance(position, dict):
        return None
    starts, games = position.get("starts"), position.get("games")
    if not isinstance(starts, int) or not isinstance(games, int) or not 0 < starts <= games:
        return None
    named = ({"role": position["role"]} if isinstance(position.get("role"), str)
             else {"line": position["line"]} if isinstance(position.get("line"), str) else None)
    if named is None:
        return None
    return {"key": "position", "params": {**named, "starts": starts, "games": games}, "evidence": None}


def player_conclusions(
    element: dict[str, Any], bootstrap: dict[str, Any], zonal: Any = None, *, position: Any = None,
) -> list[dict[str, Any]]:
    """The card's conclusions for one bootstrap *element*, in priority order, at most :data:`MAX_CONCLUSIONS`.

    *zonal* is the snapshot's own ``zonal`` block (or None); *position* is
    ``player_signals.position_fact`` (or None). Empty list when no rule fires.
    """
    fpl_position = _POSITIONS.get(int(_num(element.get("element_type")) or 0))
    elements = bootstrap.get("elements") or []
    rules = (
        lambda: _points_source(element, fpl_position, elements) if fpl_position else None,
        lambda: _position(position),
        lambda: _set_pieces(element),
        lambda: _zonal(zonal),
        lambda: _starts(element, bootstrap),
    )
    out: list[dict[str, Any]] = []
    for rule in rules:
        try:
            item = rule()
        except Exception:  # noqa: BLE001 -- a bad datum drops this line only
            item = None
        if item is not None:
            out.append(item)
        if len(out) == MAX_CONCLUSIONS:
            break
    return out

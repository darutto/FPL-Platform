"""Is a top player in decline? The trend check ``plan_to_sign`` runs before it offers to sell one (PR 3 of 4).

The bootstrap has season totals and a 30-day form figure, nothing per gameweek, so the trend comes from FPL's
free ``element-summary`` history, fetched only for the tops a plan proposes to sell (at most
:data:`MAX_FETCHES` calls per plan, in parallel, under one deadline). The fetch reuses
``player_form._fetch_element_summary``: its wall-clock budget, circuit breaker and owned-store fallback.

"Declining" needs all three (Leo, 2026-11-22):

* **form down** -- points per appearance over his last :data:`RECENT_GAMES` appearances are at least
  :data:`DECLINE_DROP` below his season average;
* **recent xGI falling** -- xGI/90 over those appearances is at least :data:`DECLINE_DROP` below his season
  rate (needs 90 recent minutes);
* **a hard run** -- at least :data:`HARD_FIXTURES_NEEDED` of his next five fixtures are band 4-5
  (from ``plan_signals``).

Anything missing -- the fetch failed, fewer than :data:`MIN_APPEARANCES` appearances, no minutes -- is *not*
decline: the caller then sells a top only when he is the only way to fund the target.
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any

#: Element-summary calls per plan.
MAX_FETCHES: int = 5
#: One deadline for all the parallel fetches, seconds.
FETCH_DEADLINE_S: float = 8.0
#: Appearances needed before a trend means anything.
MIN_APPEARANCES: int = 5
#: His most recent appearances compared with his season.
RECENT_GAMES: int = 3
#: "Down" means at least this share below the season figure.
DECLINE_DROP: float = 0.20
#: Recent minutes needed to read a recent xGI/90.
MIN_RECENT_MINUTES: int = 90
#: Hard fixtures (band 4-5) in the next five needed.
HARD_FIXTURES_NEEDED: int = 3
#: Last gameweeks whose starts are reported.
STARTS_WINDOW: int = 5


def _num(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def _fetch_summary(element_id: int, bootstrap: dict[str, Any]) -> dict[str, Any] | None:
    """The seam tests replace. Live path: ``player_form._fetch_element_summary``."""
    from .player_form import _fetch_element_summary

    return _fetch_element_summary(element_id, bootstrap)


def fetch_summaries(bootstrap: dict[str, Any], ids: list[int]) -> dict[int, dict[str, Any] | None]:
    """Element summaries for *ids* (at most :data:`MAX_FETCHES`), ``None`` for any that failed."""
    ids = list(dict.fromkeys(ids))[:MAX_FETCHES]
    out: dict[int, dict[str, Any] | None] = {pid: None for pid in ids}
    if not ids:
        return out
    pool = ThreadPoolExecutor(max_workers=len(ids))
    try:
        futures = {pool.submit(_fetch_summary, pid, bootstrap): pid for pid in ids}
        done, _ = wait(futures, timeout=FETCH_DEADLINE_S)
        for future in done:
            try:
                result = future.result()
            except Exception:  # noqa: BLE001 - a failed fetch is "no trend", never an error
                continue
            out[futures[future]] = result if isinstance(result, dict) else None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return out


def assess_trend(summary: dict[str, Any] | None, *, hard_fixtures: int) -> dict[str, Any]:
    """``status`` (``ok`` / ``unavailable`` / ``insufficient``), the three tests, ``declining`` and recent starts."""
    result: dict[str, Any] = {
        "status": "unavailable", "declining": False, "form_down": False, "xgi_down": False,
        "hard_run": hard_fixtures >= HARD_FIXTURES_NEEDED, "hard_fixtures": hard_fixtures,
        "form_recent": None, "form_season": None, "xgi_recent": None, "xgi_season": None, "recent_starts": None,
    }
    history = summary.get("history") if isinstance(summary, dict) else None
    if not isinstance(history, list):
        return result
    rows = sorted((h for h in history if isinstance(h, dict)), key=lambda h: _num(h.get("round")))
    result["status"] = "insufficient"
    window = rows[-STARTS_WINDOW:]
    if window:
        result["recent_starts"] = sum(
            1 for h in window if (_num(h["starts"]) >= 1 if "starts" in h else _num(h.get("minutes")) >= 60)
        )
    played = [h for h in rows if _num(h.get("minutes")) > 0]
    if len(played) < MIN_APPEARANCES:
        return result
    recent = played[-RECENT_GAMES:]
    season_pts = sum(_num(h.get("total_points")) for h in played) / len(played)
    recent_pts = sum(_num(h.get("total_points")) for h in recent) / len(recent)
    season_min = sum(_num(h.get("minutes")) for h in played)
    recent_min = sum(_num(h.get("minutes")) for h in recent)
    season_xgi = sum(_num(h.get("expected_goal_involvements")) for h in played) * 90 / season_min
    result.update(status="ok", form_recent=round(recent_pts, 2), form_season=round(season_pts, 2), xgi_season=round(season_xgi, 3))
    result["form_down"] = recent_pts < season_pts * (1 - DECLINE_DROP)
    if recent_min >= MIN_RECENT_MINUTES:
        recent_xgi = sum(_num(h.get("expected_goal_involvements")) for h in recent) * 90 / recent_min
        result["xgi_recent"] = round(recent_xgi, 3)
        result["xgi_down"] = recent_xgi < season_xgi * (1 - DECLINE_DROP)
    result["declining"] = bool(result["form_down"] and result["xgi_down"] and result["hard_run"])
    return result

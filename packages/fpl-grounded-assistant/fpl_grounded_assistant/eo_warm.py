"""Precompute of the EO jobs, so the first question finds them done (or nearly).

``warm`` is THE entry point and is meant to be called from anywhere that learns a user's team or main league:
the chat's team-connect / league-change call (``POST /eo/warm``), the first /ask or /session turn that carries a
team id, and later an onboarding page's save. It never blocks and never raises: a ``JobService.status`` call only
starts a background job (or reads the cache) and returns.

Cost rules (a near-rank job is ~130 FPL requests):
* Both flags off -> nothing happens (nothing is memoised either).
* One job per (user, season, gameweek, target): a memo makes every later call for the same target a no-op for the
  rest of the gameweek, so /ask can call this on every turn. A different team or league is a different target, but
  a user may warm at most ``MAX_TARGETS_PER_KIND`` distinct targets per kind per gameweek (the ids are the client's,
  as on /ask, so a caller cannot make us start unbounded jobs by varying them).
* A claim is given back when nothing started and the service did not already hold the job (it raised, or answered
  busy/unavailable), so a failed warm-up does not use up the user's gameweek.
* Jobs go through the existing JobService: single-flight, the shared limiter, the per-job budget, max 2 jobs / 20 queued.
* A counter of jobs started (no ids) is logged and shown on /healthz.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from .orch_config import is_league_eo_enabled, is_near_rank_eo_enabled

_LOG = logging.getLogger(__name__)
_MAX_MEMO = 20_000
MAX_TARGETS_PER_KIND = 3

_LOCK = threading.Lock()
_MEMO: set[tuple[str, str, int, str, int]] = set()
_COUNTS: dict[str, int] = {"near_started": 0, "league_started": 0, "memo_skips": 0}


def counters() -> dict[str, int]:
    """Warm jobs started so far (no ids), for /healthz."""
    with _LOCK:
        return dict(_COUNTS)


def reset() -> None:
    """Forget the memo and the counters (tests)."""
    with _LOCK:
        _MEMO.clear()
        for k in _COUNTS:
            _COUNTS[k] = 0


def _claim(user_key: str, season: str, gw: int, kind: str, target: int) -> bool:
    """True the first time this user warms this target this gameweek."""
    key = (user_key, season, gw, kind, target)
    with _LOCK:
        if key in _MEMO:
            _COUNTS["memo_skips"] += 1
            return False
        if sum(1 for k in _MEMO if k[:4] == key[:4]) >= MAX_TARGETS_PER_KIND:
            _COUNTS["memo_skips"] += 1
            return False
        if len(_MEMO) >= _MAX_MEMO:
            _MEMO.difference_update({k for k in _MEMO if k[2] != gw or k[1] != season})
            if len(_MEMO) >= _MAX_MEMO:
                _MEMO.clear()
        _MEMO.add(key)
        return True


def _unclaim(user_key: str, season: str, gw: int, kind: str, target: int) -> None:
    with _LOCK:
        _MEMO.discard((user_key, season, gw, kind, target))


def _run(svc: Any, claim: tuple[str, str, int, str, int], *args: Any, **kw: Any) -> bool:
    """Call ``svc.status``; True if it started a job. Gives the claim back unless the job now exists."""
    before = svc.started
    try:
        result = svc.status(*args, **kw)
    except Exception:
        _unclaim(*claim)
        raise
    if result.get("status") == "unavailable":
        _unclaim(*claim)
    return svc.started > before


def warm(bootstrap: dict[str, Any] | None, team_id: int, league_id: int | None = None, *, user_key: str,
         now: datetime | None = None) -> dict[str, bool]:
    """Start the near-rank job for *team_id* and, when *league_id* is given, the league job.

    Returns which kinds this call started (``{"near": bool, "league": bool}``). Safe to call on every request.
    """
    started = {"near": False, "league": False}
    near_on, league_on = is_near_rank_eo_enabled(), is_league_eo_enabled()
    if not (near_on or league_on) or not user_key:
        return started
    try:
        from .near_rank_eo_tool import _season, gw_and_valid_until  # noqa: PLC0415

        boot = bootstrap or {}
        gw, valid_until = gw_and_valid_until(boot.get("events") or [], now or datetime.now(timezone.utc))
        season = _season(boot)
        if gw is None or season is None or not isinstance(team_id, int) or team_id < 1:
            return started
        if near_on and _claim(user_key, season, gw, "near", team_id):
            from . import near_rank_eo_tool as near  # noqa: PLC0415

            svc = near.get_service()
            started["near"] = _run(svc, (user_key, season, gw, "near", team_id), season, gw, team_id,
                                   valid_until=valid_until)
        if league_on and league_id is not None and _claim(user_key, season, gw, "league", league_id):
            from . import league_eo_tool as league  # noqa: PLC0415

            svc = league.get_service()
            started["league"] = _run(svc, (user_key, season, gw, "league", league_id), season, gw, team_id,
                                     league_id, valid_until=valid_until)
    except Exception:  # noqa: BLE001  (a warm-up must never cost a request)
        _LOG.warning("eo_warm failed", exc_info=True)
        return started
    for kind, did in started.items():
        if did:
            with _LOCK:
                _COUNTS[f"{kind}_started"] += 1
                total = _COUNTS[f"{kind}_started"]
            _LOG.info("eo_warm job started kind=%s total=%d", kind, total)
    return started

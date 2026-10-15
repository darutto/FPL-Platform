"""Multi-competition calendar endpoint logic (``GET /fixtures/competitions``). Dev-only data.

Source of the data is the local Sportmonks trial capture (``live_trial_local``
provenance, never published). The endpoint therefore answers ``available: false``
unless BOTH dev variables are set: ``FI_DEV_ALLOW_LIVE_TRIAL_LOCAL=1`` and
``FI_DEV_LIVE_TRIAL_CAPTURE=<path to capture.json>``. Neither variable may appear
in any prod path (Dockerfile, deploy config, CI); a test greps for it.

The tier is decided here, on the server, from the tier the caller passes in (the
single ``tier_of(request)`` seam in ``fpl_server``, which i153 will harden). The free
payload is a constant, ``{"available": true, "tier": "free"}``: it is never a filtered
copy of the premium one, so it cannot leak an opponent, a competition or even a count.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from football_intelligence.live_trial_calendar import build_calendar

ENV_ALLOW = "FI_DEV_ALLOW_LIVE_TRIAL_LOCAL"
ENV_CAPTURE = "FI_DEV_LIVE_TRIAL_CAPTURE"
#: Tiers that get the detail: Gafete de cancha ($5, patreon_basic) and above (Leo, 2026-10-14).
#: Every other tier (patreon_tribuna $1, free) gets the counts-only view with the lock mark.
DETAIL_TIERS = frozenset({"patreon_basic", "patreon_plus", "patreon_premium"})
#: PRODUCT constants, decided by Leo (not M3 thresholds: M3 has none for rest days).
#: ROTATION_REST_DAYS (2026-10-14): a Premier League match warns of possible rotation when the
#: club's previous match was this many WHOLE days before it or fewer (floor(hours/24) between
#: kickoffs: 3 whole days = 72h to <96h, so Tuesday night -> Saturday afternoon warns; 96h does not).
#: ROTATION_AFTER (decided by Leo 2026-10-14: only after a European/cup match): the notice needs the
#: previous match to be one of these competitions (UEFA Super Cup included: a European match, added
#: at Leo's "after Europe or cup" intent); PL -> PL never warns. Rest days are always shown.
ROTATION_REST_DAYS = 3
ROTATION_AFTER = frozenset({"UCL", "UEL", "UECL", "UEFA-SC", "FA", "EFL"})

_cache: dict[tuple[str, float], dict[str, list[dict[str, Any]]]] = {}


def _calendar() -> dict[str, list[dict[str, Any]]] | None:
    """The trial calendar, or None when the dev gate is closed or the capture is absent."""
    if os.environ.get(ENV_ALLOW, "").strip() != "1":
        return None
    raw = os.environ.get(ENV_CAPTURE, "").strip()
    path = Path(raw) if raw else None
    if path is None or not path.is_file():
        return None
    key = (str(path), path.stat().st_mtime)
    if key not in _cache:
        _cache.clear()
        _cache[key] = build_calendar(json.loads(path.read_text(encoding="utf-8")))
    return _cache[key]


def _in_window(match: dict[str, Any], date_from: str | None, date_to: str | None) -> bool:
    day = match["kickoff_utc"][:10]
    return (date_from is None or day >= date_from) and (date_to is None or day <= date_to)


def _rotates(m: dict[str, Any]) -> bool:
    """The rotation notice rule (see ROTATION_REST_DAYS / ROTATION_AFTER) for one Premier League match."""
    days = m["rest_whole_days_before"]
    return days is not None and days <= ROTATION_REST_DAYS and m["previous_competition"] in ROTATION_AFTER


def competitions_response(tier: str, team: str | None, date_from: str | None, date_to: str | None) -> dict[str, Any]:
    calendar = _calendar()
    if calendar is None:
        return {"available": False}
    if tier in DETAIL_TIERS:
        wanted = {code: ms for code, ms in calendar.items() if team is None or code == team.strip().upper()}
        # Premium only: free never gets the notice nor a hint of it. `matches` are the other
        # competitions; `pl_matches` carry the Premier League kickoffs so the board can lay
        # both on one timeline in real date order, each with the whole rest days before it.
        return {"available": True, "tier": "premium", "teams": {
            code: {
                "matches": [
                    {k: m[k] for k in ("kickoff_utc", "week", "gameweek", "competition", "venue", "opponent",
                                       "opponent_code", "rest_days_before", "rest_whole_days_before",
                                       "rest_days_after", "previous_competition")}
                    for m in ms if not m["is_pl"] and _in_window(m, date_from, date_to)],
                "pl_matches": [
                    {**{k: m[k] for k in ("kickoff_utc", "week", "gameweek", "venue", "opponent", "opponent_code",
                                          "rest_whole_days_before", "previous_competition")},
                     "rotation": _rotates(m)}
                    for m in ms if m["is_pl"] and _in_window(m, date_from, date_to)]}
            for code, ms in wanted.items()}}
    # Free/Tribuna: the layer exists and is locked, and that is ALL they are told. No rival,
    # competition, rest or per-week count: nothing about the calendar leaves the server.
    return {"available": True, "tier": "free"}

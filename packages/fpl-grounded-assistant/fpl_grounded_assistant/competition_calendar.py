"""Multi-competition calendar endpoint logic (``GET /fixtures/competitions``). Dev-only data.

Source of the data is the local Sportmonks trial capture (``live_trial_local``
provenance, never published). The endpoint therefore answers ``available: false``
unless BOTH dev variables are set: ``FI_DEV_ALLOW_LIVE_TRIAL_LOCAL=1`` and
``FI_DEV_LIVE_TRIAL_CAPTURE=<path to capture.json>``. Neither variable may appear
in any prod path (Dockerfile, deploy config, CI); a test greps for it.

The tier is decided here, on the server, from the tier the caller passes in (the
single ``tier_of(request)`` seam in ``fpl_server``, which i153 will harden). The free
payload is built from scratch out of per-week counts: it is never a filtered copy
of the premium one, so it cannot leak an opponent or a competition by construction.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from football_intelligence.ingestion.live_trial_calendar import build_calendar

ENV_ALLOW = "FI_DEV_ALLOW_LIVE_TRIAL_LOCAL"
ENV_CAPTURE = "FI_DEV_LIVE_TRIAL_CAPTURE"
#: Tiers that get the detail. Pending Leo's confirmation of the tier split;
#: every other tier (including patreon_basic, patreon_tribuna) gets the free view.
DETAIL_TIERS = frozenset({"patreon_plus", "patreon_premium"})

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


def competitions_response(tier: str, team: str | None, date_from: str | None, date_to: str | None) -> dict[str, Any]:
    calendar = _calendar()
    if calendar is None:
        return {"available": False}
    wanted = {code: ms for code, ms in calendar.items() if team is None or code == team.strip().upper()}
    if tier in DETAIL_TIERS:
        return {"available": True, "tier": "premium", "teams": {
            code: {"matches": [
                {k: m[k] for k in ("kickoff_utc", "week", "competition", "venue", "opponent",
                                   "rest_days_before", "rest_days_after")}
                for m in ms if not m["is_pl"] and _in_window(m, date_from, date_to)]}
            for code, ms in wanted.items()}}
    return {"available": True, "tier": "free", "teams": {
        code: {"extra_by_week": dict(sorted(Counter(
            m["week"] for m in ms if not m["is_pl"] and _in_window(m, date_from, date_to)).items()))}
        for code, ms in wanted.items()}}

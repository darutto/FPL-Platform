"""Automatic retry of a ``computing`` EO answer: the marker and the deterministic poll.

When ``get_league_eo`` / ``get_near_rank_eo`` answer ``computing`` the chat shows the model's short
"not ready yet" text, and the response also carries ``pending`` (``pending_marker``). The UI then calls
``POST /eo/poll`` every few seconds. That path is this module's ``poll``: it runs the SAME tool function the
model would (so membership, single-flight, the global limiter, the budget and the job caps are the existing
ones), and turns a ready result into a card plus one catalogue line. No orchestrator, no model, no tokens.

The module is framework-free; ``fpl_server`` maps its answers to HTTP.
"""
from __future__ import annotations

import hmac
import os
import threading
import time
from typing import Any, Callable, Mapping

from .catalogue import t
from .locale_types import DEFAULT_LOCALE, Locale

POLL_TOOLS = ("get_league_eo", "get_near_rank_eo")
POLL_S = 4              # the UI's interval between polls
MAX_WAIT_S = 60         # the UI stops after this long and offers «Reintentar»
POLL_MIN_INTERVAL_S = 2.0   # per user: at most one poll every 2 s
MAX_ID = 10 ** 10           # an FPL entry / league id is far below this
_MAX_TRACKED_USERS = 5000


def pending_marker(tool_name: str | None, raw_output: dict[str, Any]) -> dict[str, Any] | None:
    """The marker for a ``computing`` answer of one of the two tools, or ``None``.

    A league answer needs its resolved ``league_id`` (the tool echoes it); without one a poll could not name
    what it is waiting for, so there is no marker and the model's text stands.
    """
    if tool_name not in POLL_TOOLS or raw_output.get("status") != "computing":
        return None
    marker: dict[str, Any] = {"tool": tool_name, "eta_s": int(raw_output.get("eta_s") or 20),
                              "poll_s": POLL_S, "max_s": MAX_WAIT_S}
    if tool_name == "get_league_eo":
        league_id = raw_output.get("league_id")
        if not isinstance(league_id, int) or isinstance(league_id, bool) or league_id < 1:
            return None
        marker["league_id"] = league_id
    return marker


class RateGate:
    """At most one call per ``min_interval_s`` per key (a hashed user id). Thread-safe and bounded."""

    def __init__(self, min_interval_s: float, clock: Callable[[], float] = time.monotonic):
        self._min, self._clock = min_interval_s, clock
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < self._min:
                return False
            if len(self._last) >= _MAX_TRACKED_USERS:
                self._last = {k: v for k, v in self._last.items() if now - v < self._min}
            self._last[key] = now
            return True


def caller_id(headers: Mapping[str, str]) -> str | None:
    """The raw user id of a signed-in caller, or ``None`` (anonymous, or not from our own frontend).

    The Next middleware sets ``X-User-Id`` from the Clerk session only; the proxy adds ``X-Internal-Token``
    for a signed-in user. When ``FPL_INTERNAL_TOKEN`` is configured the token must match, so a direct POST
    to this public backend cannot claim a user id. Without the variable (local dev) the id alone counts.
    """
    raw = (headers.get("X-User-Id") or "").strip()
    if not raw or raw == "anonymous":
        return None
    token = os.environ.get("FPL_INTERNAL_TOKEN", "").strip()
    if token and not hmac.compare_digest(headers.get("X-Internal-Token", ""), token):
        return None
    return raw


def _locale(value: str | None) -> Locale:
    v = (value or "").strip().lower()
    return v if v in ("es", "en") else DEFAULT_LOCALE  # type: ignore[return-value]


def poll(tool: str, team_id: int, league_id: int | None, bootstrap: dict[str, Any] | None,
         locale: str | None = None) -> dict[str, Any]:
    """One poll: ``computing`` | ``ready`` (card + text + chips) | ``unavailable`` | ``disabled``."""
    from .atomic_tool_cards import maybe_atomic_tool_card  # noqa: PLC0415
    from .generic_card import generic_card_to_dict  # noqa: PLC0415
    from .harness import _eo_switch_chips  # noqa: PLC0415
    from .league_eo_tool import get_league_eo  # noqa: PLC0415
    from .near_rank_eo_tool import get_near_rank_eo  # noqa: PLC0415

    if tool not in POLL_TOOLS:
        return {"status": "unavailable", "reason": "unknown_tool"}
    loc = _locale(locale)
    boot = dict(bootstrap or {})
    boot["_my_team_id"] = team_id
    if league_id is not None:
        boot["_my_league_id"] = league_id
    raw = get_league_eo(boot) if tool == "get_league_eo" else get_near_rank_eo(boot)
    status = raw.get("status")
    if status == "disabled":
        return {"status": "disabled"}
    if status == "computing":
        return {"status": "computing", "eta_s": int(raw.get("eta_s") or 20), "poll_s": POLL_S}
    card = maybe_atomic_tool_card(tool, raw, None, loc) if status == "ok" and not raw.get("stage") else None
    if card is None:
        return {"status": "unavailable", "reason": str(raw.get("reason") or raw.get("stage") or raw.get("code") or "error")}
    return {
        "status": "ready",
        "text": t("eo_poll.ready", loc, title=card.title, gw=raw.get("gw")),
        "generic_card": generic_card_to_dict(card),
        "suggestions": _eo_switch_chips(tool, raw, loc),
    }

"""The parts of POST /card: the request, the rate limit and the audit line.

A card without a chat turn: no model, no chat session, no quota turn (``check_quota`` and ``record_turn`` are
never called: recording counts a message even at zero tokens). Every call writes one audit line with enums
only, and is rate-limited per user.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from fpl_grounded_assistant.audit import make_audit_entry, write_audit_entry
from fpl_grounded_assistant.locale_types import DEFAULT_LOCALE, Locale
from fpl_grounded_assistant.team_card import build_team_card, data_stamp

_LOG = logging.getLogger(__name__)

CARD_VERSION = 1
RATE_LIMIT_CALLS = 60
RATE_LIMIT_WINDOW_S = 60.0
_MAX_TRACKED_USERS = 10_000


class CardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    v: Literal[1] = 1
    kind: Literal["team"]
    team_id: StrictInt = Field(gt=0, lt=1000)
    locale: str | None = Field(default=None, max_length=8)


class WindowLimit:
    """At most ``calls`` per ``window_s`` per key (a hashed user id). Thread-safe and bounded."""

    def __init__(self, calls: int, window_s: float, clock: Callable[[], float] = time.monotonic):
        self._calls, self._window, self._clock = calls, window_s, clock
        self._seen: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            if key not in self._seen and len(self._seen) >= _MAX_TRACKED_USERS:
                self._seen = {k: q for k, q in self._seen.items() if q and now - q[-1] < self._window}
            queue = self._seen.setdefault(key, deque())
            while queue and now - queue[0] >= self._window:
                queue.popleft()
            if len(queue) >= self._calls:
                return False
            queue.append(now)
            return True


def audit_card(*, user_id: str, tier: str, kind: str, outcome: str, latency_ms: int, locale: str) -> None:
    """One line per call. No question, no text, no names."""
    entry = make_audit_entry(user_id=user_id, tier=tier, question="", branch="card", outcome=outcome,
                             intent=None, tokens={}, provider=None, model=None, locale=locale,
                             card_kind=kind, latency_ms=latency_ms)
    try:
        write_audit_entry(entry)
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("audit write failed: %s", exc)


def card_locale(value: str | None) -> Locale:
    v = (value or "").strip().lower()
    return v if v in ("es", "en") else DEFAULT_LOCALE  # type: ignore[return-value]


def build_card(req: CardRequest, bootstrap: dict[str, Any], locale: Locale) -> dict[str, Any] | None:
    """The response body, or ``None`` when the subject does not exist."""
    return card_body(req.team_id, bootstrap, locale)


def card_body(team_id: int, bootstrap: dict[str, Any], locale: Locale) -> dict[str, Any] | None:
    """One team card as served: by ``POST /card`` and inside a chat answer to a bare club name."""
    card = build_team_card(team_id, bootstrap, locale)
    if card is None:
        return None
    return {"v": CARD_VERSION, "kind": "team", "card": card, "data_stamp": data_stamp(card)}

"""
fpl_grounded_assistant.quota
==============================
Phase P3.1: Per-user token meter with daily/monthly rolling windows.
Phase P3.3: Redis-backed persistence (falls back to in-memory when
REDIS_URL is unset, e.g. local dev/tests).

Public API
----------
check_quota(user_id, tier)   -> QuotaCheck (pre-call gate)
record_turn(user_id, tokens_used, tier) -> None (post-call accounting)
get_quota_status(user_id, tier) -> QuotaCheck (read-only, for UI indicator)
reset_quota(user_id=None)    -> None (tests + emergency reset)

Storage
-------
When REDIS_URL is set: four counters per user (daily/monthly x
tokens/messages), each INCRBY'd per turn with an EXPIRE set on first write
so the window starts at first activity rather than a fixed calendar
boundary. This survives process restarts/redeploys, unlike the previous
pure in-memory dict.

When REDIS_URL is unset (local dev, smoke tests): falls back to the
original in-memory dict keyed by user_id, with a rolling list of
(timestamp: float, tokens: int, msg_count: int) tuples per window,
pruned on each access. Not persistent — fine for local/offline use, never
used in production (Railway always sets REDIS_URL).

Soft-fail UX
------------
When check_quota() returns allowed=False, the caller (fpl_server.py)
returns an AskResponse with outcome="quota_exceeded" and the localized
upgrade prompt.  The connection is never dropped.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# Tier registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QuotaTier:
    """A single Patreon tier's caps."""

    name: str                     # e.g. "free", "patreon_basic", "patreon_premium"
    daily_token_cap: int          # rolling 24h window
    monthly_token_cap: int        # rolling 30d window
    daily_message_cap: int        # alternative cap (whichever hits first)
    monthly_message_cap: int


TIERS: dict[str, QuotaTier] = {
    # Cap design: the message cap is the binding limit for normal use; the
    # token cap is a generous abuse ceiling sized to the measured heavy turn
    # (~23K tokens p95 under the LLM-primary orchestrator, incl. evaluator +
    # retry), i.e. daily_token_cap ≈ daily_message_cap × ~23K. This lets a user
    # spend all their messages even on complex turns, while only pathological
    # turns trip the token wall. Revisit once more orchestrator token data
    # accrues (v1 sized off n=14 audited turns).
    "free": QuotaTier(
        name="free",
        daily_token_cap=75_000,
        monthly_token_cap=600_000,
        daily_message_cap=5,
        monthly_message_cap=30,
    ),
    "patreon_basic": QuotaTier(
        name="patreon_basic",
        daily_token_cap=700_000,
        monthly_token_cap=7_000_000,
        daily_message_cap=30,
        monthly_message_cap=600,
    ),
    "patreon_plus": QuotaTier(
        name="patreon_plus",
        daily_token_cap=1_400_000,
        monthly_token_cap=14_000_000,
        daily_message_cap=60,
        monthly_message_cap=1_200,
    ),
    "patreon_premium": QuotaTier(
        name="patreon_premium",
        daily_token_cap=3_500_000,
        monthly_token_cap=35_000_000,
        daily_message_cap=150,
        monthly_message_cap=3_000,
    ),
}

# Fallback tier used when an unknown tier name is supplied.
_DEFAULT_TIER_NAME: str = "free"

# Window sizes in seconds.
_DAILY_WINDOW_S:   float = 86_400.0   # 24 hours
_MONTHLY_WINDOW_S: float = 2_592_000.0  # 30 days


# ---------------------------------------------------------------------------
# QuotaCheck result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QuotaCheck:
    """Result of a pre-call quota check (or a read-only status fetch)."""

    allowed: bool
    tier: str
    daily_tokens_used: int
    daily_message_count: int
    monthly_tokens_used: int
    monthly_message_count: int
    daily_token_cap: int
    monthly_token_cap: int
    daily_message_cap: int
    monthly_message_cap: int
    reason: str | None               # populated when allowed=False
    upgrade_prompt_es: str | None    # Spanish upgrade message
    upgrade_prompt_en: str | None    # English upgrade message


# ---------------------------------------------------------------------------
# Storage backends
# ---------------------------------------------------------------------------

class _Backend(Protocol):
    def get_counts(self, user_id: str) -> tuple[int, int, int, int]:
        """Return (daily_tokens, daily_msgs, monthly_tokens, monthly_msgs)."""
        ...

    def record(self, user_id: str, tokens_used: int) -> None: ...

    def reset(self, user_id: str | None) -> None: ...


@dataclass
class _UserBucket:
    daily:   list[tuple[float, int, int]] = field(default_factory=list)
    monthly: list[tuple[float, int, int]] = field(default_factory=list)


class _InMemoryBackend:
    """Original dict-based store. Not persistent — local dev/tests only."""

    def __init__(self) -> None:
        self._store: dict[str, _UserBucket] = {}

    def _get_bucket(self, user_id: str) -> _UserBucket:
        if user_id not in self._store:
            self._store[user_id] = _UserBucket()
        return self._store[user_id]

    @staticmethod
    def _prune(bucket: _UserBucket, now: float) -> None:
        daily_cutoff   = now - _DAILY_WINDOW_S
        monthly_cutoff = now - _MONTHLY_WINDOW_S
        bucket.daily   = [(ts, tok, msg) for ts, tok, msg in bucket.daily   if ts > daily_cutoff]
        bucket.monthly = [(ts, tok, msg) for ts, tok, msg in bucket.monthly if ts > monthly_cutoff]

    @staticmethod
    def _sum(entries: list[tuple[float, int, int]]) -> tuple[int, int]:
        return sum(tok for _, tok, _ in entries), sum(msg for _, _, msg in entries)

    def get_counts(self, user_id: str) -> tuple[int, int, int, int]:
        now = time.time()
        bucket = self._get_bucket(user_id)
        self._prune(bucket, now)
        daily_tokens, daily_msgs = self._sum(bucket.daily)
        monthly_tokens, monthly_msgs = self._sum(bucket.monthly)
        return daily_tokens, daily_msgs, monthly_tokens, monthly_msgs

    def record(self, user_id: str, tokens_used: int) -> None:
        now = time.time()
        bucket = self._get_bucket(user_id)
        self._prune(bucket, now)
        entry = (now, max(0, tokens_used), 1)
        bucket.daily.append(entry)
        bucket.monthly.append(entry)

    def reset(self, user_id: str | None) -> None:
        if user_id is None:
            self._store.clear()
        elif user_id in self._store:
            del self._store[user_id]


def _redis_key(user_id: str, window: str, kind: str) -> str:
    return f"quota:{window}:{kind}:{user_id}"


class _RedisBackend:
    """Persistent store backed by Redis (REDIS_URL). Survives restarts.

    Counters use a "window starts at first activity" semantic rather than a
    true sliding window: each of the four counters (daily/monthly x
    tokens/messages) gets its TTL set only on the write that creates it
    (detected via INCRBY's return value equalling the increment), so the
    window resets ~24h/30d after the user's first turn in that window, not
    at a fixed calendar boundary. Operationally equivalent to the prior
    rolling-window behaviour for cap-enforcement purposes, far cheaper than
    storing every turn as a separate entry.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def get_counts(self, user_id: str) -> tuple[int, int, int, int]:
        pipe = self._client.pipeline()
        pipe.get(_redis_key(user_id, "daily", "tokens"))
        pipe.get(_redis_key(user_id, "daily", "msgs"))
        pipe.get(_redis_key(user_id, "monthly", "tokens"))
        pipe.get(_redis_key(user_id, "monthly", "msgs"))
        daily_tokens, daily_msgs, monthly_tokens, monthly_msgs = pipe.execute()
        return (
            int(daily_tokens or 0),
            int(daily_msgs or 0),
            int(monthly_tokens or 0),
            int(monthly_msgs or 0),
        )

    def record(self, user_id: str, tokens_used: int) -> None:
        tokens_used = max(0, tokens_used)
        for key, amount, ttl in (
            (_redis_key(user_id, "daily", "tokens"),   tokens_used, _DAILY_WINDOW_S),
            (_redis_key(user_id, "daily", "msgs"),     1,           _DAILY_WINDOW_S),
            (_redis_key(user_id, "monthly", "tokens"), tokens_used, _MONTHLY_WINDOW_S),
            (_redis_key(user_id, "monthly", "msgs"),   1,           _MONTHLY_WINDOW_S),
        ):
            new_value = self._client.incrby(key, amount)
            if new_value == amount:
                # Key didn't exist before this write — start its window now.
                self._client.expire(key, int(ttl))

    def reset(self, user_id: str | None) -> None:
        if user_id is None:
            for key in self._client.scan_iter(match="quota:*"):
                self._client.delete(key)
        else:
            self._client.delete(
                _redis_key(user_id, "daily", "tokens"),
                _redis_key(user_id, "daily", "msgs"),
                _redis_key(user_id, "monthly", "tokens"),
                _redis_key(user_id, "monthly", "msgs"),
            )


def _make_backend() -> _Backend:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return _InMemoryBackend()
    import redis as redis_lib  # local import: optional dependency, only needed when REDIS_URL is set
    client = redis_lib.from_url(redis_url, decode_responses=True)
    return _RedisBackend(client)


_backend: _Backend = _make_backend()


# ---------------------------------------------------------------------------
# Upgrade prompts
# ---------------------------------------------------------------------------

def _upgrade_prompts(tier_name: str) -> tuple[str, str]:
    """Return (spanish_prompt, english_prompt) for a quota-exceeded message."""
    if tier_name == "free":
        es = (
            "Has alcanzado tu límite diario gratuito. "
            "Únete al Club Bendito Fantasy en Patreon para obtener más mensajes."
        )
        en = (
            "You've reached your free daily limit. "
            "Upgrade to Patreon Basic to get more messages."
        )
    elif tier_name == "patreon_basic":
        es = (
            "Has alcanzado tu límite diario de Gafete de cancha. "
            "Tu cuota diaria se renueva en 24 horas. "
            "Sube a Socio Junior para búsqueda web y el doble de mensajes."
        )
        en = (
            "You've reached your Gafete de cancha daily limit. "
            "Your daily quota resets in 24 hours. "
            "Upgrade to Socio Junior for web search and double the messages."
        )
    elif tier_name == "patreon_plus":
        es = (
            "Has alcanzado tu límite diario de Socio Junior. "
            "Tu cuota diaria se renueva en 24 horas. "
            "Sube a Ejecutivo para un límite mucho mayor."
        )
        en = (
            "You've reached your Socio Junior daily limit. "
            "Your daily quota resets in 24 hours. "
            "Upgrade to Ejecutivo for a much higher limit."
        )
    else:
        es = (
            "Has alcanzado tu límite de uso. "
            "Tu cuota se renueva en 24 horas."
        )
        en = (
            "You've reached your usage limit. "
            "Your quota resets in 24 hours."
        )
    return es, en


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_quota(user_id: str, tier: str = "free") -> QuotaCheck:
    """Check whether a user is within quota before invoking the LLM.

    Parameters
    ----------
    user_id:
        Opaque user identifier.  ``"anonymous"`` is a valid value used as the
        default when no ``X-User-Id`` header is present.
    tier:
        One of the keys in ``TIERS`` (``"free"``, ``"patreon_basic"``,
        ``"patreon_premium"``).  Unknown tiers fall back to ``"free"``.

    Returns
    -------
    QuotaCheck
        ``allowed=True`` when the user is within all caps.
        ``allowed=False`` (with ``reason`` + upgrade prompts) when any cap is hit.
    """
    tier_cfg = TIERS.get(tier, TIERS[_DEFAULT_TIER_NAME])

    daily_tokens, daily_msgs, monthly_tokens, monthly_msgs = _backend.get_counts(user_id)

    allowed = True
    reason: str | None = None

    # Check in order: daily token cap, daily message cap, monthly token cap,
    # monthly message cap (whichever is hit first wins).
    if daily_tokens >= tier_cfg.daily_token_cap:
        allowed = False
        reason  = "daily_token_cap_exceeded"
    elif daily_msgs >= tier_cfg.daily_message_cap:
        allowed = False
        reason  = "daily_message_cap_exceeded"
    elif monthly_tokens >= tier_cfg.monthly_token_cap:
        allowed = False
        reason  = "monthly_token_cap_exceeded"
    elif monthly_msgs >= tier_cfg.monthly_message_cap:
        allowed = False
        reason  = "monthly_message_cap_exceeded"

    upgrade_es, upgrade_en = (_upgrade_prompts(tier_cfg.name) if not allowed else (None, None))

    return QuotaCheck(
        allowed=allowed,
        tier=tier_cfg.name,
        daily_tokens_used=daily_tokens,
        daily_message_count=daily_msgs,
        monthly_tokens_used=monthly_tokens,
        monthly_message_count=monthly_msgs,
        daily_token_cap=tier_cfg.daily_token_cap,
        monthly_token_cap=tier_cfg.monthly_token_cap,
        daily_message_cap=tier_cfg.daily_message_cap,
        monthly_message_cap=tier_cfg.monthly_message_cap,
        reason=reason,
        upgrade_prompt_es=upgrade_es,
        upgrade_prompt_en=upgrade_en,
    )


def record_turn(user_id: str, tokens_used: int, tier: str = "free") -> None:
    """Record a completed turn's token usage in the rolling windows.

    Called AFTER the LLM call completes (success OR failure — both count
    toward the cap).  Safe to call with tokens_used=0 (deterministic turns
    that burn no LLM tokens are still counted as 1 message for message caps).

    Parameters
    ----------
    user_id:
        Opaque user identifier.
    tokens_used:
        Total token count for the turn (primary + evaluator + retry).
        0 is acceptable for deterministic turns.
    tier:
        Quota tier label.  Ignored at record time (caps are enforced at
        check_quota time); stored here for future per-tier analytics.
    """
    _backend.record(user_id, tokens_used)


def get_quota_status(user_id: str, tier: str = "free") -> QuotaCheck:
    """Return current quota status without mutating state.

    Used by ``GET /quota`` endpoint and the UI quota indicator (P3.2).
    Semantically identical to ``check_quota()`` — same window logic, same
    return shape.  Kept separate so callers can distinguish between a
    pre-call gate (``check_quota``) and a read-only status fetch.
    """
    return check_quota(user_id, tier)


def reset_quota(user_id: str | None = None) -> None:
    """Reset quota counters.

    Parameters
    ----------
    user_id:
        When not None, clears only that user's bucket.
        When None, clears ALL buckets (used in test teardowns).
    """
    _backend.reset(user_id)

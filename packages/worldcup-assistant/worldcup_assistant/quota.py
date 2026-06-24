"""
worldcup_assistant.quota
==========================
Per-user message/token meter with daily/monthly rolling windows.
Redis-backed persistence (falls back to in-memory when REDIS_URL is
unset, e.g. local dev/tests).

Port of ``fpl_grounded_assistant.quota`` for the WC service. Kept as a
separate copy (not a cross-package import) because the WC and FPL backends
ship as independent Docker images/processes — each owns its own quota
store, keyed by the same tier names so the Patreon ladder reads
identically across both assistants. The two services may point at the
same Redis instance (separate key prefixes already namespace by
user_id only, not by service — if both share one Redis, consider
distinct REDIS_URL databases/prefixes to keep usage analytics separable).

Public API
----------
check_quota(user_id, tier)      -> QuotaCheck (pre-call gate)
record_turn(user_id, tokens, tier) -> None (post-call accounting)
get_quota_status(user_id, tier) -> QuotaCheck (read-only, for UI indicator)
reset_quota(user_id=None)       -> None (tests + emergency reset)
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# Tier registry — names/caps mirror fpl_grounded_assistant.quota.TIERS so the
# Patreon ladder behaves identically across both assistants.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QuotaTier:
    name: str
    daily_token_cap: int
    monthly_token_cap: int
    daily_message_cap: int
    monthly_message_cap: int


TIERS: dict[str, QuotaTier] = {
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

_DEFAULT_TIER_NAME: str = "free"

_DAILY_WINDOW_S:   float = 86_400.0
_MONTHLY_WINDOW_S: float = 2_592_000.0


@dataclass(frozen=True)
class QuotaCheck:
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
    reason: str | None
    upgrade_prompt_es: str | None
    upgrade_prompt_en: str | None


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
    return f"wc-quota:{window}:{kind}:{user_id}"


class _RedisBackend:
    """Persistent store backed by Redis (REDIS_URL). Survives restarts.

    "Window starts at first activity" semantic — see
    fpl_grounded_assistant.quota for the full rationale. Key prefix
    ``wc-quota:`` (vs FPL's ``quota:``) keeps the two services'
    counters distinct if they ever share one Redis instance.
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
            for key in self._client.scan_iter(match="wc-quota:*"):
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


def _upgrade_prompts(tier_name: str) -> tuple[str, str]:
    if tier_name == "free":
        es = (
            "Has alcanzado tu límite diario gratuito. "
            "Únete al Club Bendito Fantasy en Patreon para obtener más mensajes."
        )
        en = (
            "You've reached your free daily limit. "
            "Become a Patreon member to get more messages."
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
        es = "Has alcanzado tu límite de uso. Tu cuota se renueva en 24 horas."
        en = "You've reached your usage limit. Your quota resets in 24 hours."
    return es, en


def check_quota(user_id: str, tier: str = "free") -> QuotaCheck:
    tier_cfg = TIERS.get(tier, TIERS[_DEFAULT_TIER_NAME])

    daily_tokens, daily_msgs, monthly_tokens, monthly_msgs = _backend.get_counts(user_id)

    allowed = True
    reason: str | None = None

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
    _backend.record(user_id, tokens_used)


def get_quota_status(user_id: str, tier: str = "free") -> QuotaCheck:
    return check_quota(user_id, tier)


def reset_quota(user_id: str | None = None) -> None:
    _backend.reset(user_id)

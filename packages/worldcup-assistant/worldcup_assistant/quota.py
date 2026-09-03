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
        # Sized so a full 5-message day and 30-message month actually fit,
        # measured against 903 audited turns in field-notes/artifacts/*.jsonl
        # (mean 27.7K/turn, p95 42.9K — not the ~23K the n=14 sample above
        # suggested). Bootstrapping 5 turns from that distribution costs
        # ~138K at the mean and ~201K at p99, so 75_000 completed 0% of
        # 5-message days and blocked the median user at 3 — the reported bug.
        # 220_000 / 1_100_000 clear p99 for both windows, leaving the message
        # cap as the binding limit and the token cap as the abuse ceiling it
        # is documented to be.
        daily_token_cap=220_000,
        monthly_token_cap=1_100_000,
        daily_message_cap=5,
        monthly_message_cap=30,
    ),
    "patreon_basic": QuotaTier(
        name="patreon_basic",
        # 30 x p99 and 600 x p99 over the 903-turn sample (see header).
        daily_token_cap=1_000_000,
        monthly_token_cap=17_500_000,
        daily_message_cap=30,
        monthly_message_cap=600,
    ),
    "patreon_plus": QuotaTier(
        name="patreon_plus",
        # 60 x p99 and 1200 x p99 over the 903-turn sample (see header).
        daily_token_cap=1_900_000,
        monthly_token_cap=35_000_000,
        daily_message_cap=60,
        monthly_message_cap=1_200,
    ),
    "patreon_premium": QuotaTier(
        name="patreon_premium",
        # 150 x p99 and 3000 x p99 over the 903-turn sample (see header).
        daily_token_cap=4_500_000,
        monthly_token_cap=85_000_000,
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
            self._client.incrby(key, amount)
            # Anchor the window on the write that created the key, and never
            # move it again. We test the key's TTL rather than comparing
            # INCRBY's return value against the increment: those are equal
            # whenever the prior value was 0, which happens routinely because
            # deterministic (@resource, /prompt) turns record tokens_used=0.
            # The old check therefore re-armed EXPIRE on every zero-token turn
            # and again on the first non-zero one, sliding the token window
            # hours past the message window that was opened alongside it — so
            # a user's message counter reset while their token counter did
            # not, and they stayed blocked with messages visibly remaining.
            # After INCRBY the key always exists, so ttl < 0 means "no expiry
            # set yet" and is the only case that may arm one.
            if self._client.ttl(key) < 0:
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


# ---------------------------------------------------------------------------
# Upgrade prompts
# ---------------------------------------------------------------------------

#: Where a quota message sends the user. NOTE: fpl-ui/app/subscribe/page.tsx
#: points at patreon.com/benditofantasy instead — one of the two is wrong and
#: a dead upgrade link converts nobody. Resolve and collapse to one constant.
PATREON_URL: str = "https://www.patreon.com/fpl_asistente"


@dataclass(frozen=True)
class TierOffer:
    """One rung of the paid ladder, as presented in a quota message."""

    tier:        str    # key into TIERS
    display_es:  str    # the tier's name as it reads on Patreon
    price_usd:   int
    web_search:  bool   # headline differentiator from patreon_plus up


#: Ordered cheapest -> priciest. Names, prices and the web-search flag mirror
#: fpl-ui/lib/tiers.ts (SUBSCRIPTION_TIERS + QUOTA_BUCKETS); keep the two in
#: sync. patreon_premium appears at its $15 entry price (Ejecutivo: carne de
#: plata) — the $50 carne de oro shares this quota bucket and differs on
#: community perks only, so it is not a separate rung. The $1 Tribuna tier is
#: absent for the same reason: it maps to the free bucket and adds no messages,
#: so pitching it to a user who just ran out would be a bait.
UPGRADE_LADDER: tuple[TierOffer, ...] = (
    TierOffer("patreon_basic",   "Gafete de cancha", 5,  False),
    TierOffer("patreon_plus",    "Socio Junior",     10, True),
    TierOffer("patreon_premium", "Ejecutivo",        15, True),
)

_TIER_RANK: dict[str, int] = {
    "free": 0, "patreon_basic": 1, "patreon_plus": 2, "patreon_premium": 3,
}

#: True where @resource and /prompt turns bypass the gate (fpl_server.py), so
#: a blocked user can be told what still works. MUST stay False on a surface
#: that gates every turn — promising an escape hatch that does not exist
#: there would be worse than saying nothing.
_HAS_FREE_COMMANDS: bool = False


def _upgrade_prompts(tier_name: str, reason: str | None = None) -> tuple[str, str]:
    """Return (spanish_prompt, english_prompt) for a quota-exceeded message.

    Written to convert rather than merely refuse. A bare "you hit your limit"
    tells the user nothing they can act on; this names the limit actually hit
    and when it lifts, then lists the rungs above their current tier with the
    real Patreon names, prices and the concrete benefit each one adds, and
    closes on a single call to action.

    Caps are read from ``TIERS`` rather than written out, so the pitch cannot
    drift from what the gate enforces. ``reason`` picks the window: a
    ``monthly_*`` cap must never be announced as a daily one.
    """
    monthly  = bool(reason) and reason.startswith("monthly")
    cfg      = TIERS.get(tier_name, TIERS[_DEFAULT_TIER_NAME])
    cap      = cfg.monthly_message_cap if monthly else cfg.daily_message_cap
    win_es   = "al mes" if monthly else "al día"
    win_en   = "monthly" if monthly else "daily"
    renew_es = "30 días" if monthly else "24 horas"
    renew_en = "30 days" if monthly else "24 hours"

    es = [f"Llegaste a tu límite de {cap} mensajes {win_es}. "
          f"Se renueva en {renew_es}."]
    en = [f"You've reached your {win_en} limit of {cap} messages. "
          f"It resets in {renew_en}."]

    offers = [o for o in UPGRADE_LADDER
              if _TIER_RANK.get(o.tier, 0) > _TIER_RANK.get(tier_name, 0)]
    if offers:
        es += ["", "En el Club Bendito Fantasy tienes más:"]
        en += ["", "Club Bendito Fantasy members get more:"]
        for o in offers:
            caps = TIERS[o.tier]
            # Quote the rung's cap for the SAME window the user just hit —
            # answering a monthly block with a daily figure makes the offer
            # hard to compare against the limit that actually stopped them.
            n_es = caps.monthly_message_cap if monthly else caps.daily_message_cap
            es.append(f"• {o.display_es} (${o.price_usd}) — "
                      f"{n_es} mensajes {win_es}"
                      + (" + búsqueda web" if o.web_search else ""))
            en.append(f"• {o.display_es} (${o.price_usd}) — "
                      f"{n_es} messages "
                      + ("a month" if monthly else "a day")
                      + (" + web search" if o.web_search else ""))
        es += ["", f"Únete: {PATREON_URL}"]
        en += ["", f"Join: {PATREON_URL}"]

    if _HAS_FREE_COMMANDS:
        es += ["", "Mientras tanto, los comandos @ y / siguen funcionando "
                   "sin gastar cuota."]
        en += ["", "In the meantime, @ and / commands still work and cost "
                   "no quota."]

    return "\n".join(es), "\n".join(en)


def check_quota(user_id: str, tier: str = "free") -> QuotaCheck:
    tier_cfg = TIERS.get(tier, TIERS[_DEFAULT_TIER_NAME])

    daily_tokens, daily_msgs, monthly_tokens, monthly_msgs = _backend.get_counts(user_id)

    allowed = True
    reason: str | None = None

    # Daily before monthly, and message cap before token cap within each
    # window — see fpl_grounded_assistant.quota for the rationale. The
    # message cap is what the product advertises and the UI renders; the
    # token cap is the abuse ceiling, so the message reason wins a tie.
    if daily_msgs >= tier_cfg.daily_message_cap:
        allowed = False
        reason  = "daily_message_cap_exceeded"
    elif daily_tokens >= tier_cfg.daily_token_cap:
        allowed = False
        reason  = "daily_token_cap_exceeded"
    elif monthly_msgs >= tier_cfg.monthly_message_cap:
        allowed = False
        reason  = "monthly_message_cap_exceeded"
    elif monthly_tokens >= tier_cfg.monthly_token_cap:
        allowed = False
        reason  = "monthly_token_cap_exceeded"

    upgrade_es, upgrade_en = (_upgrade_prompts(tier_cfg.name, reason) if not allowed else (None, None))

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

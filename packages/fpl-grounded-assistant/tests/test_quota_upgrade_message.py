"""Quota gate + upgrade-message tests.

Covers the three defects behind the "blocked with messages remaining"
reports, plus the conversion contract of the upgrade copy.
"""
import math

import pytest

from fpl_grounded_assistant.quota import (
    TIERS,
    UPGRADE_LADDER,
    PATREON_URL,
    _RedisBackend,
    _upgrade_prompts,
    check_quota,
    record_turn,
    reset_quota,
)

# Per-turn cost measured over the 903 audited turns in field-notes/artifacts.
MEAN_TURN = 27_673
SD_TURN = 11_477
P95_TURN = 42_876
# z for the 99th percentile of a normal — spending N messages costs the sum of
# N draws, which concentrates as N grows, so the bar is the p99 of that SUM
# (mean*N + z*sd*sqrt(N)), not N x the per-turn p95. Requiring N x p95 would
# demand every single turn be a heavy one, which no real day looks like.
Z99 = 2.326


@pytest.fixture(autouse=True)
def _clean():
    reset_quota()
    yield
    reset_quota()


# --------------------------------------------------------------------------
# Caps: a tier must let a user spend the message allowance it advertises.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tier", sorted(TIERS))
def test_daily_message_allowance_is_reachable_at_mean_cost(tier):
    """The token cap is an abuse ceiling, not the binding limit."""
    cfg = TIERS[tier]
    for i in range(cfg.daily_message_cap):
        check = check_quota(f"u-{tier}", tier)
        assert check.allowed, (
            f"{tier} blocked at message {i + 1} of {cfg.daily_message_cap} "
            f"({check.reason}) at mean turn cost"
        )
        record_turn(f"u-{tier}", MEAN_TURN, tier)
    after = check_quota(f"u-{tier}", tier)
    assert not after.allowed
    assert after.reason == "daily_message_cap_exceeded"


def _p99_cost(n_messages: int) -> float:
    """p99 token cost of spending *n_messages*, via the CLT."""
    return n_messages * MEAN_TURN + Z99 * SD_TURN * math.sqrt(n_messages)


@pytest.mark.parametrize("tier", sorted(TIERS))
@pytest.mark.parametrize("window", ["daily", "monthly"])
def test_token_cap_covers_full_allowance_at_p99(tier, window):
    cfg = TIERS[tier]
    cap = getattr(cfg, f"{window}_token_cap")
    messages = getattr(cfg, f"{window}_message_cap")
    need = _p99_cost(messages)
    assert cap >= need, (
        f"{tier} {window} token cap {cap:,} cannot cover its own "
        f"{messages}-message allowance (p99 cost {need:,.0f})"
    )


def test_a_single_p95_turn_never_exhausts_a_daily_allowance():
    """One heavy turn must not eat a whole day's token budget."""
    for tier, cfg in TIERS.items():
        assert cfg.daily_token_cap > P95_TURN, tier


def test_message_cap_wins_when_both_caps_trip():
    """The reported limit must be one a user can see in the UI."""
    cfg = TIERS["free"]
    for _ in range(cfg.daily_message_cap):
        record_turn("tie", cfg.daily_token_cap, "free")
    assert check_quota("tie", "free").reason == "daily_message_cap_exceeded"


# --------------------------------------------------------------------------
# Window wording: a monthly cap must never be announced as a daily one.
# --------------------------------------------------------------------------

def test_monthly_reason_never_says_diario():
    es, en = _upgrade_prompts("free", "monthly_message_cap_exceeded")
    assert "mensual" in es or "al mes" in es
    assert "diario" not in es and "al día" not in es.split("Club")[0]
    assert "monthly" in en and "daily" not in en


def test_daily_reason_still_says_daily():
    es, en = _upgrade_prompts("free", "daily_message_cap_exceeded")
    assert "al día" in es and "24 horas" in es
    assert "24 hours" in en


# --------------------------------------------------------------------------
# Conversion contract.
# --------------------------------------------------------------------------

def test_free_user_is_shown_every_paid_rung_with_price_and_benefit():
    es, _ = _upgrade_prompts("free", "daily_message_cap_exceeded")
    for offer in UPGRADE_LADDER:
        assert offer.display_es in es, f"{offer.display_es} missing from pitch"
        assert f"${offer.price_usd}" in es
    assert "búsqueda web" in es, "web search is the plus/premium differentiator"
    assert PATREON_URL in es, "no call to action"


def test_pitch_excludes_the_users_own_tier_and_everything_below():
    es, _ = _upgrade_prompts("patreon_plus", "daily_message_cap_exceeded")
    assert "Socio Junior" not in es, "pitched the tier the user already pays for"
    assert "Gafete de cancha" not in es, "pitched a downgrade"
    assert "Ejecutivo" in es


def test_top_tier_gets_no_upsell():
    es, _ = _upgrade_prompts("patreon_premium", "daily_message_cap_exceeded")
    assert PATREON_URL not in es
    assert "Ejecutivo" not in es


def test_quoted_caps_match_the_registry_and_the_window():
    """The pitch is generated from TIERS, so it cannot drift from the gate."""
    es, _ = _upgrade_prompts("free", "daily_message_cap_exceeded")
    for offer in UPGRADE_LADDER:
        assert str(TIERS[offer.tier].daily_message_cap) in es

    es_m, _ = _upgrade_prompts("free", "monthly_message_cap_exceeded")
    for offer in UPGRADE_LADDER:
        assert str(TIERS[offer.tier].monthly_message_cap) in es_m


def test_message_states_the_cap_that_was_actually_hit():
    es, _ = _upgrade_prompts("free", "daily_message_cap_exceeded")
    assert str(TIERS["free"].daily_message_cap) in es


# --------------------------------------------------------------------------
# patreon_tribuna: the $1 pledge is its own bucket, not an alias for free.
#
# Before this, "Tribuna" ($1/mo) mapped onto the free quota bucket — a
# paying patron got literally the same caps as a non-member, and when they
# ran out the message told them "Unete al Club Bendito Fantasy" (join),
# which they had already done. That is the bug these tests pin.
# --------------------------------------------------------------------------

def test_tribuna_is_a_distinct_bucket_from_free():
    assert TIERS["patreon_tribuna"].daily_message_cap != TIERS["free"].daily_message_cap
    assert TIERS["patreon_tribuna"].daily_message_cap > TIERS["free"].daily_message_cap


def test_only_the_genuinely_unpaid_tier_is_told_to_join():
    """'Unete' (join) must never reach someone who already pays."""
    es_free, en_free = _upgrade_prompts("free", "daily_message_cap_exceeded")
    assert "Únete" in es_free
    assert "Join" in en_free

    for tier in TIERS:
        if tier == "free":
            continue
        es, en = _upgrade_prompts(tier, "daily_message_cap_exceeded")
        assert "Únete" not in es, f"{tier} (a paying tier) was told to join"
        assert "Join" not in en, f"{tier} (a paying tier) was told to join"


def test_tribuna_patron_is_offered_an_upgrade_not_a_join():
    es, en = _upgrade_prompts("patreon_tribuna", "daily_message_cap_exceeded")
    assert "Sube de nivel" in es
    assert "Upgrade" in en
    # Pitched the rungs above Tribuna, never Tribuna itself (offers render as
    # "• <name> ($<price>) — ...", so this bullet form pins it precisely).
    assert "• Tribuna" not in es, "Tribuna patron was pitched their own tier"
    assert "Gafete de cancha" in es
    assert "Ejecutivo" in es


def test_free_users_pitch_includes_tribuna_as_the_first_rung():
    es, _ = _upgrade_prompts("free", "daily_message_cap_exceeded")
    assert "Tribuna" in es
    assert "$1" in es


# --------------------------------------------------------------------------
# Redis window anchoring.
# --------------------------------------------------------------------------

class _FakeRedis:
    """Minimal INCRBY/TTL/EXPIRE with a controllable clock."""

    def __init__(self):
        self.kv, self.exp, self.clock = {}, {}, 0.0

    def incrby(self, k, a):
        self.kv[k] = self.kv.get(k, 0) + a
        return self.kv[k]

    def ttl(self, k):
        if k not in self.kv:
            return -2
        return -1 if k not in self.exp else self.exp[k] - self.clock

    def expire(self, k, t):
        self.exp[k] = self.clock + t


def test_zero_token_turns_do_not_slide_the_token_window():
    """Deterministic turns record 0 tokens; that must not re-arm EXPIRE."""
    r = _FakeRedis()
    backend = _RedisBackend(r)
    for hour in (0, 2, 4):
        r.clock = hour * 3600
        backend.record("u", 0)          # @resource / /prompt turns
    r.clock = 10 * 3600
    backend.record("u", MEAN_TURN)      # first LLM turn

    tokens_expiry = r.exp["quota:daily:tokens:u"]
    msgs_expiry = r.exp["quota:daily:msgs:u"]
    assert tokens_expiry == msgs_expiry, (
        "token and message windows drifted apart — the message counter would "
        "reset while the token counter kept blocking"
    )

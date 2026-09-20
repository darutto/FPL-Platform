"""
fpl_grounded_assistant.model_pricing
====================================
i105: the ONE per-model price table, shared by the production audit line
(``audit.estimate_usd_cost``) and the measurement scripts
(``scripts/measure_tool_routing.py``, ``scripts/run_agentic_loop_experiment.py``).

Until 2026-09-20 there were three tables: ``audit.PROVIDER_PRICING_PER_1M``
(per PROVIDER, gemini pinned at $0.075/M input -- stale), and two hand-copied
per-model tables in the two scripts. The audit priced every prod turn at the
provider default's rate while prod actually ran ``gpt-5.6-luna``, so every
prod cost estimate was wrong. One table, keyed by MODEL, and a cost function
that says ``None`` for a model it does not know instead of billing it at
someone else's tariff.

Public API
----------
PRICING_PER_1M_BY_MODEL             per-1M-token rates keyed by model id
CACHE_READ_INCLUDED_IN_INPUT        providers whose cache count is a subset of input
billable_input_tokens(...)          input tokens charged at the full rate
cost_usd(...)                       cost for one call, or None when unpriced
"""
from __future__ import annotations

#: Per-1M-token pricing BY MODEL. A model absent from this table has no price
#: here, and the absence is reported as such: tokens are still recorded, cost is
#: recorded as unknown. It is never estimated at another model's rates -- a cost
#: computed from the wrong tariff is a number that looks true and is wrong,
#: which is worse than no number at all.
#: OpenAI rates https://developers.openai.com/api/docs/models/ (2026-08-20).
PRICING_PER_1M_BY_MODEL: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0, "cache_read": 0.10},
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00, "cache_read": 0.15},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075},
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20, "cache_read": 0.02},
    "gpt-5.6-terra": {"input": 2.00, "output": 12.00, "cache_read": 0.20},
    "gpt-5.6-sol": {"input": 5.00, "output": 30.00, "cache_read": 0.50},
    # Introductory pricing, same as 3.7 Flash. No published cached-input
    # rate, so cache_read is pinned to the full input rate rather than to a
    # guessed discount: Gemini reports no cache_read tokens today (the field
    # is always 0), so this is inert -- and if that ever changes it will
    # over-bill, never under-bill.
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75, "cache_read": 0.75},
}

#: Providers whose cache_read count is a SUBSET of their input count, so the
#: cached part must be subtracted from the input tokens before pricing or it is
#: billed twice -- once at the full input rate and again at the cache rate.
#:
#: This is not a style choice per provider, it is what each API reports
#: (fpl_grounded_assistant/provider_client.py):
#:   * openai    usage.input_tokens_details.cached_tokens -- a subset of
#:               input_tokens, so it must be subtracted.
#:   * anthropic usage.cache_read_input_tokens -- reported separately and NOT
#:               included in input_tokens, so subtracting it would under-bill.
#:               It stays additive.
#:   * gemini    no cache field at all; always 0, so the distinction is inert
#:               there today.
#: A uniform "fix" applied to all three breaks Anthropic, which is why this is
#: a set and not a global change to the formula.
CACHE_READ_INCLUDED_IN_INPUT: frozenset[str] = frozenset({"openai"})


def billable_input_tokens(input_tokens: int, cache_read_tokens: int,
                          provider: str | None) -> int:
    """Input tokens charged at the FULL input rate, for this provider.

    Where the provider counts cached tokens inside ``input_tokens`` (OpenAI),
    the cached part is removed here and priced separately at the cache rate.
    Where it counts them alongside (Anthropic), every input token is billable
    and the cached ones are added on top by the caller.

    Clamped at zero: a cache count larger than the input count means the two
    numbers did not come from the same call, and a negative charge would turn
    an accounting bug into a discount.
    """
    if provider in CACHE_READ_INCLUDED_IN_INPUT:
        return max(0, input_tokens - cache_read_tokens)
    return input_tokens


def cost_usd(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    *,
    model: str | None,
    provider: str | None,
) -> float | None:
    """Cost for one call, or ``None`` when *model* has no price in the table.

    ``None`` means "unknown", not "free". Callers must render it as unknown
    rather than folding it into a total at 0.0 or at some other model's rates.

    The cached share is priced per provider (see
    ``CACHE_READ_INCLUDED_IN_INPUT``). Charging OpenAI's cached tokens at both
    the input rate and the cache rate inflated a 20-turn luna run from $0.0194
    to $0.0796 -- 4.1x, biased high, and worst exactly on the arm that caches
    most, which is how it distorted a quality-per-cost comparison between
    models.
    """
    prices = PRICING_PER_1M_BY_MODEL.get(model) if model is not None else None
    if not prices:
        return None
    billable_input = billable_input_tokens(input_tokens, cache_read_tokens, provider)
    return (
        billable_input / 1_000_000 * prices["input"]
        + output_tokens / 1_000_000 * prices["output"]
        + cache_read_tokens / 1_000_000 * prices["cache_read"]
    )

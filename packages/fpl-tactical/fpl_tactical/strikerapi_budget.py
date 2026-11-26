"""The one place that decides whether the shot source's credits can pay for the next request.

Every job that buys from StrikerAPI (the zonal shots and the European calendar)
shares one monthly allowance, so both ask here. ``remaining`` is the last
``x-credits-remaining`` header the source sent (``StrikerApiClient.credits_remaining``);
it is unknown until the first reply of a run, and then only the run's own ceiling
bounds the first request.
"""

from __future__ import annotations


def affordable(need: int, remaining: int | None) -> bool:
    """True unless the source has said it has fewer than *need* credits left."""
    return remaining is None or need <= remaining


def within_ceiling(spent: int, need: int, max_credits: int) -> bool:
    """True when spending *need* more keeps the run at or under its own ceiling."""
    return spent + need <= max_credits

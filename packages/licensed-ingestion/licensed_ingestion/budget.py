"""Hard call cap: a Transport wrapper that refuses request N+1 before it reaches the network."""
from __future__ import annotations

from typing import Any, Mapping

from sportmonks_client.transport import Transport, TransportResponse


class BudgetExceeded(RuntimeError):
    """The run's --max-calls is spent. Not a SportmonksError, so the client never retries it."""


class CountingTransport:
    """Counts every request the client makes, retries included, and stops at ``max_calls``."""

    def __init__(self, inner: Transport, max_calls: int) -> None:
        if max_calls < 0:
            raise ValueError("max_calls must be non-negative")
        self.inner = inner
        self.max_calls = max_calls
        self.calls = 0

    def request(self, method: str, url: str, *, params: Mapping[str, Any], timeout: float) -> TransportResponse:
        if self.calls >= self.max_calls:
            raise BudgetExceeded("call budget spent")
        self.calls += 1
        return self.inner.request(method, url, params=params, timeout=timeout)

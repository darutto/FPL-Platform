"""Injectable HTTP transport; the only production network boundary."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

import requests

from .errors import SportmonksRequestError, SportmonksResponseError


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: Any


class Transport(Protocol):
    def request(self, method: str, url: str, *, params: Mapping[str, Any], timeout: float) -> TransportResponse: ...


class RequestsTransport:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def request(self, method: str, url: str, *, params: Mapping[str, Any], timeout: float) -> TransportResponse:
        failure: tuple[str, bool] | None = None
        try:
            response = self._session.request(method, url, params=dict(params), timeout=timeout)
        except requests.RequestException as exc:
            retryable = isinstance(exc, (requests.Timeout, requests.ConnectionError))
            failure = (type(exc).__name__, retryable)
        if failure is not None:
            # Raise after leaving the except block. This prevents both __cause__
            # and the implicit __context__ from retaining a token-bearing error.
            raise SportmonksRequestError(
                f"transport failure ({failure[0]})",
                endpoint="provider request",
                retryable=failure[1],
            ) from None
        json_failure = False
        try:
            body = response.json()
        except ValueError:
            json_failure = True
        if json_failure:
            raise SportmonksResponseError("response body is not valid JSON", endpoint="provider response", status_code=response.status_code) from None
        return TransportResponse(response.status_code, dict(response.headers), body)

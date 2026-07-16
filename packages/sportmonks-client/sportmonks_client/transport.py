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
        try:
            response = self._session.request(method, url, params=dict(params), timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise SportmonksRequestError("transient transport failure", endpoint=url) from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise SportmonksResponseError("response body is not valid JSON", endpoint=url, status_code=response.status_code) from exc
        return TransportResponse(response.status_code, dict(response.headers), body)

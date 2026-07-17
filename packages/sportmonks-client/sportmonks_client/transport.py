"""Injectable HTTP transport; the only production network boundary."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Protocol

import requests

from .errors import SportmonksRequestError, SportmonksResponseError, SportmonksResponseSizeError


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: Any


class Transport(Protocol):
    def request(self, method: str, url: str, *, params: Mapping[str, Any], timeout: float) -> TransportResponse: ...


class RequestsTransport:
    def __init__(self, session: requests.Session | None = None, *, max_response_bytes: int = 4 * 1024 * 1024) -> None:
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._session = session or requests.Session()
        self._max_response_bytes = max_response_bytes

    def request(self, method: str, url: str, *, params: Mapping[str, Any], timeout: float) -> TransportResponse:
        failure: tuple[str, bool] | None = None
        try:
            response = self._session.request(
                method, url, params=dict(params), timeout=timeout,
                allow_redirects=False, stream=True,
            )
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
        try:
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared_size = int(declared)
                except (TypeError, ValueError):
                    declared_size = None
                if declared_size is not None and declared_size > self._max_response_bytes:
                    raise SportmonksResponseSizeError(
                        "response exceeds configured byte limit",
                        endpoint="provider response", status_code=response.status_code,
                    )
            payload = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                payload.extend(chunk)
                if len(payload) > self._max_response_bytes:
                    raise SportmonksResponseSizeError(
                        "response exceeds configured byte limit",
                        endpoint="provider response", status_code=response.status_code,
                    )
            try:
                body = json.loads(bytes(payload).decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise SportmonksResponseError(
                    "response body is not valid JSON", endpoint="provider response",
                    status_code=response.status_code,
                ) from None
            return TransportResponse(response.status_code, dict(response.headers), body)
        finally:
            response.close()

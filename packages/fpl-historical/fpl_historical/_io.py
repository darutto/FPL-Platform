"""
fpl_historical._io
==================
Shared low-level HTTP fetch helpers used by both capture.py and incremental.py.

Extracted from capture.py lines 59–93 so both modules can reuse the same
_fetch_raw retry loop and _write_gz gzip writer without circular imports.

Public names (internal to the fpl_historical package):
    _RETRY_ATTEMPTS     int — number of fetch attempts before giving up
    _RETRY_BACKOFF      float — base backoff seconds (doubled each attempt)
    _fetch_raw(url, timeout) -> (status_code, body_bytes)
    _write_gz(path, data)    -> None
"""

from __future__ import annotations

import gzip
import time
from pathlib import Path

import requests

_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = 1.5  # seconds, doubles each attempt


def _write_gz(path: Path, data: bytes) -> None:
    """Gzip-compress *data* and write to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(data)


def _fetch_raw(url: str, timeout: int = 30) -> tuple[int, bytes]:
    """Fetch *url* and return ``(status_code, body_bytes)``.

    Retries up to ``_RETRY_ATTEMPTS`` times on network errors or 5xx responses
    with exponential backoff. Never raises — returns the last observed status
    code and empty bytes on terminal failure. 4xx responses are returned
    immediately (no retry).

    Uses the raw requests library directly so we can capture the exact
    response bytes (before JSON parsing) for SHA-256 hashing — mirrors the
    retry policy of fpl_api_client.fpl_client.fetch_json, which discards bytes.
    """
    last_status = 0
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code < 500:
                return resp.status_code, resp.content
            last_status = resp.status_code
        except Exception:
            last_status = 0
        if attempt < _RETRY_ATTEMPTS:
            time.sleep(_RETRY_BACKOFF * attempt)
    return last_status, b""

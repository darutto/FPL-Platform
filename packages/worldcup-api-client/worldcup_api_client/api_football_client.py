"""
worldcup_api_client.api_football_client
========================================
Minimal client for api-football.com (v3), used to pull *historical* World
Cup data that the FIFA Fantasy free feed (``wc_client.py``) does not carry:
per-player match stats (minutes, cards, GK saves, key passes, duels,
dribbles, rating), full group standings, and head-to-head across
tournaments/years.

Free-plan constraints (as of 2026-06-13)
-----------------------------------------
- 100 requests/day, 10 requests/minute.
- The free plan does NOT include the current season (2026) for live
  competitions — only seasons 2022-2024 are accessible. So this client is
  for **historical** data only (e.g. WC 2022, league id 1), not live 2026
  enrichment.

Auth
----
Reads ``API_FOOTBALL_KEY`` from the environment (set in
``packages/worldcup-assistant/.env``). Sent as the ``x-apisports-key``
header against ``https://v3.football.api-sports.io``.

This module deliberately has no TTL cache (unlike ``wc_client``) — it is
used by one-shot offline scripts, not the live request path.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

_BASE_URL = "https://v3.football.api-sports.io"
_DEFAULT_TIMEOUT_S: float = 20.0
_RETRY_ATTEMPTS: int = 3
_RETRY_BACKOFF_S: float = 2.0

#: Free-plan rate limit is 10 req/min; pace requests comfortably under that.
MIN_REQUEST_INTERVAL_S: float = 6.5

WORLD_CUP_LEAGUE_ID: int = 1


class ApiFootballError(Exception):
    """Raised on transport failure, non-2xx status, or API-reported error."""


def _api_key() -> str:
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not key:
        raise ApiFootballError(
            "API_FOOTBALL_KEY is not set. Add it to "
            "packages/worldcup-assistant/.env"
        )
    return key


def fetch_json(path: str, params: dict[str, Any] | None = None,
                *, timeout_s: float = _DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """GET ``_BASE_URL + path`` and return the parsed JSON body.

    Raises ``ApiFootballError`` on transport failure (after retries), non-2xx
    status, or a non-empty ``errors`` field in the response body (the API
    returns HTTP 200 even for plan/quota errors).
    """
    headers = {"x-apisports-key": _api_key()}
    url = _BASE_URL + path
    last_err: str | None = None

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            resp = httpx.get(url, params=params or {}, headers=headers, timeout=timeout_s)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
                if attempt < _RETRY_ATTEMPTS:
                    time.sleep(_RETRY_BACKOFF_S * attempt)
                    continue
                break
            if resp.status_code >= 400:
                raise ApiFootballError(f"HTTP {resp.status_code} for {path}: {resp.text[:200]}")
            payload = resp.json()
            errors = payload.get("errors")
            if errors:
                raise ApiFootballError(f"API error for {path}: {errors}")
            return payload
        except ApiFootballError:
            raise
        except httpx.TimeoutException:
            last_err = "timeout"
        except httpx.HTTPError as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        if attempt < _RETRY_ATTEMPTS:
            time.sleep(_RETRY_BACKOFF_S * attempt)

    raise ApiFootballError(f"request failed for {path} after {_RETRY_ATTEMPTS} attempts: {last_err}")


def get_fixtures(season: int, *, league: int = WORLD_CUP_LEAGUE_ID) -> list[dict[str, Any]]:
    """All fixtures for ``league``/``season`` (default: World Cup)."""
    payload = fetch_json("/fixtures", {"league": league, "season": season})
    return payload["response"]


def get_standings(season: int, *, league: int = WORLD_CUP_LEAGUE_ID) -> list[list[dict[str, Any]]]:
    """Group standings tables for ``league``/``season``."""
    payload = fetch_json("/standings", {"league": league, "season": season})
    response = payload["response"]
    if not response:
        return []
    return response[0]["league"]["standings"]


def get_fixture_players(fixture_id: int) -> list[dict[str, Any]]:
    """Per-team, per-player statistics for a single fixture."""
    payload = fetch_json("/fixtures/players", {"fixture": fixture_id})
    return payload["response"]

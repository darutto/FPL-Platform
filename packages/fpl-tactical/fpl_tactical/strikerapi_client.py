"""
fpl_tactical.strikerapi_client
==============================
Thin HTTP client for the StrikerAPI shot source.

    POST https://mcp.strikerapi.com/v1/{tool}   header x-api-key, JSON body
    reply {"data": ...}; headers x-credits-used / x-credits-remaining

Costs (measured by the reviewer, not re-measured here): ``get_shot_map`` 10,
``list_games`` 2. The key comes from ``STRIKERAPI_KEY`` and is never logged
or echoed; every error message is built without it.

The transport is injectable so tests never touch the network: ``transport``
is ``callable(url, headers, body_bytes) -> (status, response_headers, text)``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

BASE_URL = "https://mcp.strikerapi.com/v1/"
ENV_KEY = "STRIKERAPI_KEY"

COST_LIST_GAMES = 2
COST_SHOT_MAP = 10

Transport = Callable[[str, dict, bytes], "tuple[int, dict, str]"]


class StrikerApiError(RuntimeError):
    """The source answered with an error, or could not be reached."""


def _urllib_transport(url: str, headers: dict, body: bytes) -> tuple[int, dict, str]:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed https host
            return resp.status, dict(resp.headers.items()), resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StrikerApiError(f"shot source unreachable: {type(exc).__name__}") from None


@dataclass
class StrikerApiClient:
    api_key: str | None = None
    transport: Transport = _urllib_transport
    credits_remaining: int | None = None
    credits_spent: int = 0
    _calls: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get(ENV_KEY, "").strip() or None

    def call(self, tool: str, body: dict) -> dict:
        if not self.api_key:
            raise StrikerApiError(f"{ENV_KEY} is not set")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "User-Agent": "python-client",
        }
        status, resp_headers, text = self.transport(
            BASE_URL + tool, headers, json.dumps(body).encode("utf-8")
        )
        low = {k.lower(): v for k, v in resp_headers.items()}
        try:
            if "x-credits-remaining" in low:
                self.credits_remaining = int(float(low["x-credits-remaining"]))
            if "x-credits-used" in low:
                self.credits_spent += int(float(low["x-credits-used"]))
        except ValueError:
            pass
        self._calls.append(tool)
        if status != 200:
            raise StrikerApiError(f"{tool} answered HTTP {status}")
        try:
            payload = json.loads(text)
        except ValueError:
            raise StrikerApiError(f"{tool} answered with a non-JSON body") from None
        if not isinstance(payload, dict) or "data" not in payload:
            raise StrikerApiError(f"{tool} answered without a data field")
        return payload["data"]

    def list_games(self, season: int) -> list[dict]:
        """Finished games of the season (PL is the default league), paged 200 at a time."""
        games: list[dict] = []
        offset = 0
        for _ in range(10):  # a season is 380 games: 2 pages; the bound only stops a runaway
            body: dict = {"season": season, "status": "final", "limit": 200}
            if offset:
                body["offset"] = offset
            data = self.call("list_games", body)
            page = data.get("games") if isinstance(data, dict) else None
            if not isinstance(page, list):
                raise StrikerApiError("list_games answered without a games list")
            games.extend(page)
            nxt = data.get("next_offset")
            if not nxt:
                return games
            offset = int(nxt)
        raise StrikerApiError("list_games kept paging")

    def shot_map_for_game(self, game_id: str) -> list[dict]:
        data = self.call("get_shot_map", {"game_id": str(game_id)})
        return _shots_of(data)

    def shot_map_for_team(self, team_code: str, season: int) -> list[dict]:
        data = self.call("get_shot_map", {"team": team_code, "season": season})
        return _shots_of(data)


def _shots_of(data: object) -> list[dict]:
    shots = data.get("shots") if isinstance(data, dict) else None
    if not isinstance(shots, list):
        raise StrikerApiError("get_shot_map answered without a shots list")
    return shots

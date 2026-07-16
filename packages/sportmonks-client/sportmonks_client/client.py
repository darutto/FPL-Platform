"""Typed Sportmonks endpoint client with bounded GET retries and pagination."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .config import SportmonksConfig
from .errors import (SportmonksAuthenticationError, SportmonksPaginationError,
                     SportmonksRateLimitError, SportmonksRequestError, SportmonksResponseError)
from .models import (Coach, Fixture, Formation, Injury, League, LineupEntry, Player,
                     PlayerFixtureStatistic, ProviderEntity, RawResponseSnapshot, Referee,
                     Season, SquadMember, Substitution, Suspension, Team,
                     TeamFixtureStatistic, parse_entity, parse_envelope)
from .transport import RequestsTransport, Transport, TransportResponse

ENDPOINTS: dict[str, tuple[str, type[ProviderEntity]]] = {
    "leagues": ("leagues", League), "seasons": ("seasons", Season),
    "fixtures": ("fixtures", Fixture), "teams": ("teams", Team),
    "squads": ("squads", SquadMember), "players": ("players", Player),
    "lineups": ("lineups", LineupEntry), "formations": ("formations", Formation),
    "substitutions": ("substitutions", Substitution), "injuries": ("injuries", Injury),
    "suspensions": ("suspensions", Suspension), "coaches": ("coaches", Coach),
    "referees": ("referees", Referee), "team_statistics": ("statistics/fixtures/teams", TeamFixtureStatistic),
    "player_statistics": ("statistics/fixtures/players", PlayerFixtureStatistic),
}


class SportmonksClient:
    def __init__(self, config: SportmonksConfig | None = None, *, transport: Transport | None = None,
                 sleep: Callable[[float], None] = time.sleep, offline: bool = False,
                 snapshot_hook: Callable[[RawResponseSnapshot], None] | None = None) -> None:
        self.config = config or SportmonksConfig.from_env()
        self.transport = transport or RequestsTransport()
        self.sleep = sleep
        self.snapshot_hook = snapshot_hook
        self.token = None if offline else self.config.require_token()

    @classmethod
    def offline(cls, transport: Transport, *, config: SportmonksConfig | None = None, **kwargs: Any) -> "SportmonksClient":
        return cls(config, transport=transport, offline=True, **kwargs)

    def _request(self, endpoint: str, params: Mapping[str, Any]) -> TransportResponse:
        url = f"{self.config.base_url}/{endpoint.lstrip('/')}"
        clean_params = dict(params)
        if self.token:
            clean_params["api_token"] = self.token
        attempts = self.config.max_retries + 1
        last_rate_limit: TransportResponse | None = None
        for attempt in range(attempts):
            try:
                response = self.transport.request("GET", url, params=clean_params, timeout=self.config.timeout_seconds)
            except SportmonksRequestError:
                if attempt + 1 >= attempts:
                    raise
                self.sleep(self.config.backoff_seconds * (2 ** attempt))
                continue
            status = response.status
            if status in (401, 403):
                raise SportmonksAuthenticationError("authentication failed", endpoint=endpoint, status_code=status)
            if status == 429:
                last_rate_limit = response
                if attempt + 1 >= attempts:
                    break
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after is not None else self.config.backoff_seconds * (2 ** attempt)
                except ValueError:
                    delay = self.config.backoff_seconds * (2 ** attempt)
                self.sleep(delay)
                continue
            if 500 <= status <= 599:
                if attempt + 1 >= attempts:
                    raise SportmonksRequestError("retryable server error exhausted", endpoint=endpoint, status_code=status)
                self.sleep(self.config.backoff_seconds * (2 ** attempt))
                continue
            if status >= 400:
                raise SportmonksRequestError("non-retryable request failure", endpoint=endpoint, status_code=status)
            if self.snapshot_hook:
                self.snapshot_hook(RawResponseSnapshot(
                    endpoint, {k: v for k, v in clean_params.items() if k != "api_token"},
                    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), status,
                    {}, response.body if isinstance(response.body, dict) else {"data": response.body},
                ))
            return response
        raise SportmonksRateLimitError("rate limit exhausted", endpoint=endpoint, status_code=last_rate_limit.status if last_rate_limit else 429)

    def iter_entities(self, family: str, *, params: Mapping[str, Any] | None = None):
        endpoint, model = ENDPOINTS[family]
        request_params = dict(params or {})
        seen: set[int] = set()
        page = int(request_params.get("page", 1))
        for _ in range(self.config.max_pages):
            if page in seen:
                raise SportmonksPaginationError("pagination loop detected", endpoint=endpoint)
            seen.add(page)
            request_params["page"] = page
            envelope = parse_envelope(self._request(endpoint, request_params).body, endpoint)
            for item in envelope.data:
                yield parse_entity(model, item, endpoint)
            if envelope.pagination is None:
                if page != 1:
                    raise SportmonksPaginationError("pagination disappeared after first page", endpoint=endpoint)
                return
            if not envelope.pagination.has_more:
                return
            next_page = envelope.pagination.next_page or envelope.pagination.current_page + 1
            if next_page <= 0:
                raise SportmonksPaginationError("invalid next page", endpoint=endpoint)
            page = next_page
        raise SportmonksPaginationError("maximum page limit exceeded", endpoint=endpoint)

    def _list(self, family: str, **params: Any) -> tuple[ProviderEntity, ...]:
        return tuple(self.iter_entities(family, params=params))

    def leagues(self, **params: Any): return self._list("leagues", **params)
    def seasons(self, **params: Any): return self._list("seasons", **params)
    def fixtures(self, **params: Any): return self._list("fixtures", **params)
    def teams(self, **params: Any): return self._list("teams", **params)
    def squads(self, **params: Any): return self._list("squads", **params)
    def players(self, **params: Any): return self._list("players", **params)
    def lineups(self, **params: Any): return self._list("lineups", **params)
    def formations(self, **params: Any): return self._list("formations", **params)
    def substitutions(self, **params: Any): return self._list("substitutions", **params)
    def injuries(self, **params: Any): return self._list("injuries", **params)
    def suspensions(self, **params: Any): return self._list("suspensions", **params)
    def coaches(self, **params: Any): return self._list("coaches", **params)
    def referees(self, **params: Any): return self._list("referees", **params)
    def team_fixture_statistics(self, **params: Any): return self._list("team_statistics", **params)
    def player_fixture_statistics(self, **params: Any): return self._list("player_statistics", **params)

"""Typed Sportmonks endpoint client with bounded GET retries and pagination."""
from __future__ import annotations

import re
import time
import math
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, NamedTuple

from .config import SportmonksConfig
from .errors import (SportmonksAuthenticationError, SportmonksPaginationError,
                     SportmonksRateLimitError, SportmonksRequestError, SportmonksResponseError)
from .models import (Coach, Fixture, Formation, Injury, League, LineupEntry, Player,
                     PlayerFixtureStatistic, ProviderEntity, RawResponseSnapshot, Referee,
                     Season, SquadMember, Substitution, Suspension, Team,
                     TeamFixtureStatistic, parse_entity, parse_envelope)
from .transport import RequestsTransport, Transport, TransportResponse

class Route(NamedTuple):
    """How a family is reached on the live v3 API.

    Index 0 and 1 stay ``(path, model)`` so ``ENDPOINTS[family][0]`` still names
    the mock key. ``path`` may carry ``{placeholders}`` filled from ``scope``
    (``squads/teams/{team_id}``). A *derived* family has no endpoint of its own:
    it is a nested list inside another route's records (``extract``, dotted for
    two levels), requested through ``include``. ``where`` keeps only nested rows
    whose field equals the given value (``("category", "injury")`` on a
    ``sideline`` row; ``("type_id", 18)`` on an event). ``unwrap`` hoists a
    nested object's fields over the row (sidelined rows nest the real record
    under ``sideline``). See CONTRACT.md "Family routes".
    """
    path: str
    model: type[ProviderEntity]
    include: str | None = None
    extract: str | None = None
    where: tuple[str, Any] | None = None
    unwrap: str | None = None


_WINDOW = "fixtures/between/{start}/{end}"
#: Live-verified 2026-10-11 (FI-9 day 0). 404 at the root: squads, lineups,
#: formations, substitutions, injuries, suspensions, statistics/fixtures/*.
ENDPOINTS: dict[str, Route] = {
    "leagues": Route("leagues", League),
    "seasons": Route("seasons", Season),
    "fixtures": Route("fixtures", Fixture),
    "teams": Route("teams/seasons/{season_id}", Team),
    "squads": Route("squads/teams/{team_id}", SquadMember),
    "players": Route("players", Player),
    "lineups": Route(_WINDOW, LineupEntry, include="lineups", extract="lineups"),
    "formations": Route(_WINDOW, Formation, include="formations", extract="formations"),
    "substitutions": Route(_WINDOW, Substitution, include="events", extract="events", where=("type_id", 18)),
    "injuries": Route(_WINDOW, Injury, include="sidelined.sideline", extract="sidelined",
                      where=("category", "injury"), unwrap="sideline"),
    "suspensions": Route(_WINDOW, Suspension, include="sidelined.sideline", extract="sidelined",
                         where=("category", "suspended"), unwrap="sideline"),
    "coaches": Route("coaches", Coach),
    "referees": Route("referees", Referee),
    "team_statistics": Route(_WINDOW, TeamFixtureStatistic, include="statistics", extract="statistics"),
    "player_statistics": Route(_WINDOW, PlayerFixtureStatistic, include="lineups.details",
                               extract="lineups.details"),
}
#: Routes the scripts use that are not one of the fifteen families swept for
#: objective 1. ``team_fixtures`` is one club's fixtures across every
#: competition the plan covers (Arsenal 2026-27: PL 38, UCL 8, Carabao 2).
EXTRA_ROUTES: dict[str, Route] = {
    "team_fixtures": Route("fixtures/between/{start}/{end}/{team_id}", Fixture),
}


def get_route(family: str) -> Route:
    return ENDPOINTS[family] if family in ENDPOINTS else EXTRA_ROUTES[family]


_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def route_path(family: str, scope: Mapping[str, Any] | None = None) -> str:
    path = get_route(family).path
    missing = [n for n in _PLACEHOLDER.findall(path) if n not in (scope or {})]
    if missing:
        raise SportmonksRequestError(f"route {family!r} needs scope {missing}", endpoint=path)
    return _PLACEHOLDER.sub(lambda m: str(scope[m.group(1)]), path)


def _flatten(item: Mapping[str, Any], dotted: str) -> list[Mapping[str, Any]]:
    nodes: list[Any] = [item]
    for key in dotted.split("."):
        nodes = [child for node in nodes if isinstance(node, Mapping)
                 for child in (node.get(key) if isinstance(node.get(key), list) else [])]
    return nodes


MAX_RETRY_AFTER_SECONDS = 60.0
SNAPSHOT_RESPONSE_HEADERS = frozenset({
    "content-type", "date", "retry-after", "x-ratelimit-limit",
    "x-ratelimit-remaining", "x-ratelimit-reset", "x-request-id",
})


class SportmonksClient:
    def __init__(self, config: SportmonksConfig | None = None, *, transport: Transport | None = None,
                 sleep: Callable[[float], None] = time.sleep, offline: bool = False,
                 snapshot_hook: Callable[[RawResponseSnapshot], None] | None = None) -> None:
        self.config = config or SportmonksConfig.from_env()
        self.transport = transport or RequestsTransport(
            max_response_bytes=self.config.max_response_bytes
        )
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
            except SportmonksRequestError as exc:
                if not exc.retryable or attempt + 1 >= attempts:
                    raise
                self.sleep(self._backoff(attempt))
                continue
            status = response.status
            if status in (401, 403):
                raise SportmonksAuthenticationError("authentication failed", endpoint=endpoint, status_code=status)
            if 300 <= status <= 399:
                raise SportmonksRequestError("redirect refused", endpoint=endpoint, status_code=status)
            if status == 429:
                last_rate_limit = response
                if attempt + 1 >= attempts:
                    break
                delay = self._retry_delay(response.headers.get("Retry-After"), attempt)
                self.sleep(delay)
                continue
            if 500 <= status <= 599:
                if attempt + 1 >= attempts:
                    raise SportmonksRequestError("retryable server error exhausted", endpoint=endpoint, status_code=status)
                self.sleep(self._backoff(attempt))
                continue
            if status >= 400:
                raise SportmonksRequestError("non-retryable request failure", endpoint=endpoint, status_code=status)
            if self.snapshot_hook:
                self.snapshot_hook(RawResponseSnapshot(
                    endpoint, {k: v for k, v in clean_params.items() if k != "api_token"},
                    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), status,
                    {
                        key.casefold(): value for key, value in response.headers.items()
                        if key.casefold() in SNAPSHOT_RESPONSE_HEADERS
                    }, response.body if isinstance(response.body, dict) else {"data": response.body},
                ))
            return response
        raise SportmonksRateLimitError("rate limit exhausted", endpoint=endpoint, status_code=last_rate_limit.status if last_rate_limit else 429)

    def _backoff(self, attempt: int) -> float:
        value = self.config.backoff_seconds * (2 ** attempt)
        if not math.isfinite(value) or value < 0:
            value = 0.0
        return min(value, MAX_RETRY_AFTER_SECONDS)

    def _retry_delay(self, retry_after: str | None, attempt: int) -> float:
        try:
            value = float(retry_after) if retry_after is not None else float("nan")
        except (TypeError, ValueError):
            return self._backoff(attempt)
        if not math.isfinite(value) or value < 0:
            return self._backoff(attempt)
        return min(value, MAX_RETRY_AFTER_SECONDS)

    def fetch_page(self, family: str, *, params: Mapping[str, Any] | None = None,
                   scope: Mapping[str, Any] | None = None) -> tuple[ProviderEntity, ...]:
        """Fetch and parse exactly one page, regardless of has_more metadata."""
        route = get_route(family)
        endpoint = route_path(family, scope)
        envelope = parse_envelope(self._request(endpoint, self._params(route, params)).body, endpoint)
        return tuple(self._records(route, envelope, endpoint))

    @staticmethod
    def _params(route: Route, params: Mapping[str, Any] | None) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        if route.include:
            merged["include"] = route.include
        merged.update(params or {})
        return merged

    @staticmethod
    def _records(route: Route, envelope, endpoint: str):
        seen: set[Any] = set()
        for item in envelope.data:
            rows = [item] if route.extract is None else _flatten(item, route.extract)
            for row in rows:
                if route.unwrap and isinstance(row.get(route.unwrap), Mapping):
                    row = {**row, **row[route.unwrap]}
                    row.pop(route.unwrap, None)
                if route.where and row.get(route.where[0]) != route.where[1]:
                    continue
                if route.unwrap:
                    if row.get("id") in seen:
                        continue  # one sideline row repeats on every fixture it spans
                    seen.add(row.get("id"))
                yield parse_entity(route.model, row, endpoint)

    def iter_entities(self, family: str, *, params: Mapping[str, Any] | None = None,
                      scope: Mapping[str, Any] | None = None, max_pages: int | None = None):
        """Walk a family; ``max_pages`` bounds this call (default: config.max_pages).

        Hitting the bound raises SportmonksPaginationError("maximum page limit exceeded"),
        so a bounded sweep cannot silently mistake a truncated family for a complete one.
        """
        route = get_route(family)
        endpoint = route_path(family, scope)
        request_params = self._params(route, params)
        seen: set[int] = set()
        page = int(request_params.get("page", 1))
        for _ in range(max_pages or self.config.max_pages):
            if page in seen:
                raise SportmonksPaginationError("pagination loop detected", endpoint=endpoint)
            seen.add(page)
            request_params["page"] = page
            envelope = parse_envelope(self._request(endpoint, request_params).body, endpoint)
            yield from self._records(route, envelope, endpoint)
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

    def _list(self, family: str, scope: Mapping[str, Any] | None = None, **params: Any) -> tuple[ProviderEntity, ...]:
        return tuple(self.iter_entities(family, params=params, scope=scope))

    def leagues(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("leagues", scope, **params)
    def seasons(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("seasons", scope, **params)
    def fixtures(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("fixtures", scope, **params)
    def teams(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("teams", scope, **params)
    def squads(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("squads", scope, **params)
    def players(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("players", scope, **params)
    def lineups(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("lineups", scope, **params)
    def formations(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("formations", scope, **params)
    def substitutions(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("substitutions", scope, **params)
    def injuries(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("injuries", scope, **params)
    def suspensions(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("suspensions", scope, **params)
    def coaches(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("coaches", scope, **params)
    def referees(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("referees", scope, **params)
    def team_fixture_statistics(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("team_statistics", scope, **params)
    def player_fixture_statistics(self, scope: Mapping[str, Any] | None = None, **params: Any): return self._list("player_statistics", scope, **params)

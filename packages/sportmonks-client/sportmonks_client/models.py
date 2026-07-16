"""Provider-owned response, pagination, snapshot, and endpoint models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import SportmonksSchemaError


@dataclass(frozen=True)
class Pagination:
    current_page: int
    has_more: bool
    next_page: int | None = None


@dataclass(frozen=True)
class ResponseEnvelope:
    data: tuple[Mapping[str, Any], ...]
    pagination: Pagination | None
    raw_meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawResponseSnapshot:
    endpoint: str
    requested_parameters: Mapping[str, Any]
    fetched_at: str
    status: int
    response_metadata: Mapping[str, Any]
    raw_payload: Mapping[str, Any]
    schema_version: int = 1


@dataclass(frozen=True)
class ProviderEntity:
    provider_id: int
    source_endpoint: str
    raw_fields: Mapping[str, Any]


class League(ProviderEntity): pass
class Season(ProviderEntity): pass
class Fixture(ProviderEntity): pass
class Team(ProviderEntity): pass
class SquadMember(ProviderEntity): pass
class Player(ProviderEntity): pass
class LineupEntry(ProviderEntity): pass
class Formation(ProviderEntity): pass
class Substitution(ProviderEntity): pass
class Injury(ProviderEntity): pass
class Suspension(ProviderEntity): pass
class Coach(ProviderEntity): pass
class Referee(ProviderEntity): pass
class TeamFixtureStatistic(ProviderEntity): pass
class PlayerFixtureStatistic(ProviderEntity): pass


def parse_entity(model: type[ProviderEntity], payload: Mapping[str, Any], endpoint: str) -> ProviderEntity:
    provider_id = payload.get("id")
    if not isinstance(provider_id, int):
        raise SportmonksSchemaError("provider entity requires integer id", endpoint=endpoint)
    return model(provider_id, endpoint, dict(payload))


def parse_envelope(payload: Any, endpoint: str) -> ResponseEnvelope:
    if not isinstance(payload, dict) or "data" not in payload or not isinstance(payload["data"], list):
        raise SportmonksSchemaError("malformed response envelope", endpoint=endpoint)
    pagination = None
    raw_pagination = payload.get("pagination") or payload.get("meta", {}).get("pagination")
    if raw_pagination is not None:
        if not isinstance(raw_pagination, dict) or not isinstance(raw_pagination.get("current_page"), int):
            raise SportmonksSchemaError("malformed pagination metadata", endpoint=endpoint)
        has_more = raw_pagination.get("has_more")
        if not isinstance(has_more, bool):
            raise SportmonksSchemaError("pagination has_more must be boolean", endpoint=endpoint)
        next_page = raw_pagination.get("next_page")
        if next_page is not None and not isinstance(next_page, int):
            raise SportmonksSchemaError("pagination next_page must be integer or null", endpoint=endpoint)
        pagination = Pagination(raw_pagination["current_page"], has_more, next_page)
    return ResponseEnvelope(tuple(dict(item) for item in payload["data"]), pagination, dict(payload.get("meta") or {}))

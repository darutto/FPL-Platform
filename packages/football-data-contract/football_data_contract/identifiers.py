"""Provider-neutral deterministic canonical identifier rules."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable


CANONICAL_ID_HASH_LENGTH = 24
CANONICAL_ID_PREFIXES = {
    "player": "player_",
    "team": "team_",
    "competition": "competition_",
    "season": "season_",
    "fixture": "fixture_",
}
FINGERPRINT_SEPARATOR = "|"

_SPECIALS = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "ß": "ss"})
_TEAM_KEY_SEGMENT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class CanonicalIdCollisionError(ValueError):
    """Different governed fingerprints produced the same canonical ID."""


def _validate_component(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    if value != value.strip():
        raise ValueError(f"{field_name} must not have leading or trailing whitespace")
    if FINGERPRINT_SEPARATOR in value:
        raise ValueError(f"{field_name} must not contain reserved separator '|'")
    return value


def validate_team_registry_key(registry_key: str) -> tuple[str, str, str, str]:
    """Validate jurisdiction|stable_club_key|category|squad_level."""
    if not isinstance(registry_key, str) or not registry_key:
        raise ValueError("team registry key must not be empty")
    if registry_key != registry_key.strip():
        raise ValueError("team registry key must not have leading or trailing whitespace")
    segments = registry_key.split(FINGERPRINT_SEPARATOR)
    if len(segments) != 4 or any(not segment for segment in segments):
        raise ValueError("team registry key must contain exactly four non-empty segments")
    if any(_TEAM_KEY_SEGMENT.fullmatch(segment) is None for segment in segments):
        raise ValueError("team registry key segments must use lowercase ASCII letters, digits, and single hyphens")
    return tuple(segments)  # type: ignore[return-value]


def normalize_identity_name(value: str) -> str:
    """Return the governed player-fingerprint spelling normalization."""
    folded = unicodedata.normalize("NFKD", value.translate(_SPECIALS).casefold())
    unaccented = "".join(character for character in folded if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^\w]+", " ", unaccented, flags=re.UNICODE).split())


def _mint(entity_type: str, fingerprint: str) -> str:
    prefix = CANONICAL_ID_PREFIXES[entity_type]
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return f"{prefix}{digest[:CANONICAL_ID_HASH_LENGTH]}"


def player_identity_fingerprint(authoritative_name: str, birth_date: str | None) -> str:
    _validate_component(authoritative_name, "authoritative_name")
    if birth_date is not None:
        _validate_component(birth_date, "birth_date")
    return f"player|{normalize_identity_name(authoritative_name)}|{birth_date or ''}"


def canonical_player_id(authoritative_name: str, birth_date: str | None) -> str:
    return _mint("player", player_identity_fingerprint(authoritative_name, birth_date))


def canonical_team_id(registry_key: str) -> str:
    """Mint from an operator-governed immutable club/category registry key."""
    validate_team_registry_key(registry_key)
    return _mint("team", f"team|{registry_key}")


def canonical_competition_id(governing_body: str, registry_key: str, category: str) -> str:
    _validate_component(governing_body, "governing_body")
    _validate_component(registry_key, "competition registry_key")
    _validate_component(category, "competition category")
    return _mint("competition", f"competition|{governing_body}|{registry_key}|{category}")


def canonical_season_id(competition_id: str, edition_key: str) -> str:
    validate_canonical_id("competition", competition_id)
    _validate_component(edition_key, "season edition_key")
    return _mint("season", f"season|{competition_id}|{edition_key}")


def canonical_fixture_id(
    competition_id: str,
    season_id: str,
    home_team_id: str,
    away_team_id: str,
    fixture_key: str,
) -> str:
    """Mint from governed scheduling identity; kickoff is deliberately excluded."""
    validate_canonical_id("competition", competition_id)
    validate_canonical_id("season", season_id)
    validate_canonical_id("team", home_team_id)
    validate_canonical_id("team", away_team_id)
    _validate_component(fixture_key, "fixture scheduling key")
    return _mint(
        "fixture",
        f"fixture|{competition_id}|{season_id}|{home_team_id}|{away_team_id}|{fixture_key}",
    )


def validate_canonical_id(entity_type: str, value: str) -> None:
    prefix = CANONICAL_ID_PREFIXES[entity_type]
    if re.fullmatch(re.escape(prefix) + rf"[0-9a-f]{{{CANONICAL_ID_HASH_LENGTH}}}", value) is None:
        raise ValueError(f"invalid {entity_type} canonical id")


def assert_no_canonical_id_collisions(entries: Iterable[tuple[str, str]]) -> None:
    """Fail when one canonical ID is associated with distinct fingerprints."""
    seen: dict[str, str] = {}
    for canonical_id, fingerprint in entries:
        if canonical_id in seen and seen[canonical_id] != fingerprint:
            raise CanonicalIdCollisionError(f"canonical id collision: {canonical_id}")
        seen[canonical_id] = fingerprint

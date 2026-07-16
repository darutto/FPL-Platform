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

_SPECIALS = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "ß": "ss"})


class CanonicalIdCollisionError(ValueError):
    """Different governed fingerprints produced the same canonical ID."""


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
    return f"player|{normalize_identity_name(authoritative_name)}|{birth_date or ''}"


def canonical_player_id(authoritative_name: str, birth_date: str | None) -> str:
    return _mint("player", player_identity_fingerprint(authoritative_name, birth_date))


def canonical_team_id(registry_key: str) -> str:
    """Mint from an operator-governed immutable club/category registry key."""
    return _mint("team", f"team|{registry_key}")


def canonical_competition_id(governing_body: str, registry_key: str, category: str) -> str:
    return _mint("competition", f"competition|{governing_body}|{registry_key}|{category}")


def canonical_season_id(competition_id: str, edition_key: str) -> str:
    validate_canonical_id("competition", competition_id)
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

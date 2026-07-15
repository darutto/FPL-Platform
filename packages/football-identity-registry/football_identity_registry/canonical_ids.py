"""Stable canonical identifiers derived without provider identifiers."""
from __future__ import annotations

import hashlib

from .normalization import normalize_name


class CanonicalIdCollisionError(ValueError):
    pass


def identity_fingerprint(full_name: str, birth_date: str | None) -> str:
    return f"player|{normalize_name(full_name)}|{birth_date or ''}"


def canonical_player_id(full_name: str, birth_date: str | None) -> str:
    digest = hashlib.sha256(identity_fingerprint(full_name, birth_date).encode("utf-8")).hexdigest()
    return f"player_{digest[:24]}"


def assert_no_id_collisions(identities: list[tuple[str, str | None]]) -> None:
    seen: dict[str, str] = {}
    for full_name, birth_date in identities:
        canonical_id = canonical_player_id(full_name, birth_date)
        fingerprint = identity_fingerprint(full_name, birth_date)
        if canonical_id in seen and seen[canonical_id] != fingerprint:
            raise CanonicalIdCollisionError(f"canonical id collision: {canonical_id}")
        seen[canonical_id] = fingerprint

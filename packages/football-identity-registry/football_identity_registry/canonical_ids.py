"""Stable canonical identifiers derived without provider identifiers."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from football_data_contract import (
    CanonicalIdCollisionError,
    assert_no_canonical_id_collisions,
    canonical_player_id,
    player_identity_fingerprint,
)

from .normalization import normalize_name

class IdentityIndistinguishableError(CanonicalIdCollisionError):
    """Distinct candidate records collapse to the same governed fingerprint."""


def identity_fingerprint(full_name: str, birth_date: str | None) -> str:
    return player_identity_fingerprint(full_name, birth_date)


def assert_no_id_collisions(identities: list[tuple[str, str | None]]) -> None:
    assert_no_canonical_id_collisions(
        (canonical_player_id(full_name, birth_date), identity_fingerprint(full_name, birth_date))
        for full_name, birth_date in identities
    )


def assert_candidates_distinguishable(candidates: Sequence[Mapping[str, object]]) -> None:
    """Fail closed when distinct candidate metadata shares one fingerprint.

    Exact duplicate rows are harmless and are deduplicated by the builder.
    Input order cannot affect the grouped comparison or diagnostic.
    """
    grouped: dict[str, set[tuple[str, str, str, str]]] = {}
    for item in candidates:
        fingerprint = identity_fingerprint(str(item["full_name"]), item.get("birth_date") or None)  # type: ignore[arg-type]
        signature = (
            normalize_name(str(item["full_name"])),
            str(item.get("birth_date") or ""),
            str(item.get("team_provider_id") or ""),
            normalize_name(str(item.get("known_name") or "")),
        )
        grouped.setdefault(fingerprint, set()).add(signature)
    conflicts = sorted(fingerprint for fingerprint, signatures in grouped.items() if len(signatures) > 1)
    if conflicts:
        raise IdentityIndistinguishableError(
            "distinct candidates share canonical fingerprint: " + ", ".join(conflicts)
        )

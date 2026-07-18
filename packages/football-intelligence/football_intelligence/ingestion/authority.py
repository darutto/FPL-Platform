"""Owned-player authority precedence used before provider normalization."""
from __future__ import annotations


def select_player_authority(current: dict | None, historical: dict | None,
                            existing_crosswalk: dict | None) -> dict | None:
    """Existing identity wins; otherwise current FPL wins, then historical."""
    if current and historical:
        for field in ("full_name", "birth_date"):
            if current.get(field) and historical.get(field) and current[field] != historical[field]:
                raise ValueError(f"authoritative player conflict: {field}")
    if existing_crosswalk:
        return dict(existing_crosswalk)
    return dict(current or historical) if (current or historical) else None

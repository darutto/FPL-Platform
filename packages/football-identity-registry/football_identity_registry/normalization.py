"""Provider-neutral, deterministic name normalization."""
from __future__ import annotations

from football_data_contract import normalize_identity_name


def normalize_name(value: str) -> str:
    """Compatibility alias for the canonical fingerprint normalization."""
    return normalize_identity_name(value)


def surname(value: str) -> str:
    parts = normalize_name(value).split()
    return parts[-1] if parts else ""

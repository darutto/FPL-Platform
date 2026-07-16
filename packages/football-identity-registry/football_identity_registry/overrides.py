"""Checked-in, schema-validated operator overrides."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from football_data_contract import ProviderIdentifier, validate_canonical_id


class OverrideSchemaError(ValueError):
    pass


def load_overrides(path: Path) -> dict[tuple[ProviderIdentifier, str], str]:
    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict) or set(payload) != {"version", "overrides"} or payload["version"] != 1 or not isinstance(payload["overrides"], list):
        raise OverrideSchemaError("overrides.yaml must contain version: 1 and an overrides list")
    result: dict[tuple[ProviderIdentifier, str], str] = {}
    for index, item in enumerate(payload["overrides"]):
        required = {"provider", "provider_id", "canonical_player_id", "reason"}
        if not isinstance(item, dict) or set(item) != required or not all(isinstance(item[k], str) and item[k].strip() for k in required):
            raise OverrideSchemaError(f"invalid override at index {index}")
        try:
            provider = ProviderIdentifier(item["provider"])
            validate_canonical_id("player", item["canonical_player_id"])
        except ValueError as exc:
            raise OverrideSchemaError(f"invalid override at index {index}: {exc}") from exc
        key = (provider, item["provider_id"])
        if key in result:
            raise OverrideSchemaError(f"duplicate override: {key}")
        result[key] = item["canonical_player_id"]
    return result

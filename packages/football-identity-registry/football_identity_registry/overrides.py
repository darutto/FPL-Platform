"""Checked-in, schema-validated operator overrides."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class OverrideSchemaError(ValueError):
    pass


def load_overrides(path: Path) -> dict[tuple[str, str], str]:
    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict) or set(payload) != {"version", "overrides"} or payload["version"] != 1 or not isinstance(payload["overrides"], list):
        raise OverrideSchemaError("overrides.yaml must contain version: 1 and an overrides list")
    result: dict[tuple[str, str], str] = {}
    for index, item in enumerate(payload["overrides"]):
        required = {"provider", "provider_id", "canonical_player_id", "reason"}
        if not isinstance(item, dict) or set(item) != required or not all(isinstance(item[k], str) and item[k].strip() for k in required):
            raise OverrideSchemaError(f"invalid override at index {index}")
        key = (item["provider"], item["provider_id"])
        if key in result:
            raise OverrideSchemaError(f"duplicate override: {key}")
        result[key] = item["canonical_player_id"]
    return result

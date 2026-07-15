"""Atomic parquet crosswalk store and validity-range reconciliation."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

PLAYER_COLUMNS = (
    "canonical_player_id", "provider", "provider_id", "normalized_name", "full_name",
    "team_provider_id", "birth_date", "valid_from", "valid_to", "match_method",
    "match_confidence", "manual_override",
)
OTHER_COLUMNS = {
    "team": ("canonical_team_id", "provider", "provider_id", "name", "valid_from", "valid_to"),
    "fixture": ("canonical_fixture_id", "provider", "provider_id", "valid_from", "valid_to"),
    "competition": ("canonical_competition_id", "provider", "provider_id", "name", "valid_from", "valid_to"),
}


@dataclass(frozen=True)
class PlayerIdentityRow:
    canonical_player_id: str
    provider: str
    provider_id: str
    normalized_name: str
    full_name: str
    team_provider_id: str | None
    birth_date: str | None
    valid_from: str
    valid_to: str | None
    match_method: str
    match_confidence: float
    manual_override: bool


def identity_root() -> Path:
    return Path(os.environ.get("FPL_FOOTBALL_ROOT", "data/football")) / "identity"


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _atomic_parquet(path: Path, records: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pd.DataFrame(records, columns=columns).to_parquet(tmp, index=False)
    os.replace(tmp, path)


def reconcile_player_rows(existing: Iterable[PlayerIdentityRow], incoming: Iterable[PlayerIdentityRow]) -> list[PlayerIdentityRow]:
    """Close stale team-scoped rows and append replacements without overwriting history."""
    rows = list(existing)
    for new in incoming:
        duplicate = next((r for r in rows if r == new), None)
        if duplicate:
            continue
        for index, old in enumerate(rows):
            same_source = old.provider == new.provider and old.provider_id == new.provider_id
            changed_scope = old.team_provider_id != new.team_provider_id or old.canonical_player_id != new.canonical_player_id
            if same_source and old.valid_to is None and changed_scope:
                close_date = (date.fromisoformat(new.valid_from) - timedelta(days=1)).isoformat()
                rows[index] = replace(old, valid_to=close_date)
        rows.append(new)
    return sorted(rows, key=lambda r: (r.provider, r.provider_id, r.valid_from, r.canonical_player_id))


def verify_player_rows(rows: Iterable[PlayerIdentityRow]) -> list[str]:
    errors: list[str] = []
    active: dict[tuple[str, str], str] = {}
    for row in rows:
        if not 0 <= row.match_confidence <= 1:
            errors.append(f"confidence out of range: {row.provider}/{row.provider_id}")
        if row.valid_to and row.valid_to < row.valid_from:
            errors.append(f"invalid validity range: {row.provider}/{row.provider_id}")
        if row.valid_to is None:
            key = (row.provider, row.provider_id)
            if key in active and active[key] != row.canonical_player_id:
                errors.append(f"conflicting active mapping: {row.provider}/{row.provider_id}")
            active[key] = row.canonical_player_id
    return errors


class IdentityStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or identity_root()

    def read_players(self) -> list[PlayerIdentityRow]:
        path = self.root / "player_identity.parquet"
        if not path.exists():
            return []
        frame = pd.read_parquet(path)
        records = frame.astype(object).where(pd.notna(frame), None).to_dict("records")
        return [PlayerIdentityRow(**record) for record in records]

    def write(self, players: Iterable[PlayerIdentityRow], *, run_id: str, generated_at: str, queue: list[dict[str, Any]]) -> None:
        rows = list(players)
        errors = verify_player_rows(rows)
        if errors:
            raise ValueError("; ".join(errors))
        _atomic_parquet(self.root / "player_identity.parquet", [asdict(r) for r in rows], PLAYER_COLUMNS)
        for name, columns in OTHER_COLUMNS.items():
            path = self.root / f"{name}_identity.parquet"
            if not path.exists():
                _atomic_parquet(path, [], columns)
        _atomic_json(self.root / "ambiguity_queue.json", {"schema_version": 1, "items": queue})
        _atomic_json(self.root / "_identity_latest.json", {
            "schema_version": 1, "run_id": run_id, "generated_at": generated_at,
            "player_rows": len(rows), "unresolved": len(queue),
        })

    def verify(self) -> list[str]:
        required = [self.root / f"{name}_identity.parquet" for name in ("player", "team", "fixture", "competition")]
        errors = [f"missing {path.name}" for path in required if not path.is_file()]
        return errors + verify_player_rows(self.read_players())

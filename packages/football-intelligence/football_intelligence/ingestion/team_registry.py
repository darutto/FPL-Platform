"""Governed team seed and exact provider crosswalk resolution."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from football_data_contract import canonical_team_id, validate_team_registry_key


@dataclass(frozen=True)
class TeamSeed:
    canonical_team_id: str
    registry_key: str
    display_name: str
    jurisdiction: str
    category: str
    squad_level: str
    valid_from: str
    valid_to: str | None
    provenance: str
    status: str
    notes: str


@dataclass(frozen=True)
class TeamCrosswalk:
    provider: str
    provider_id: str
    canonical_team_id: str
    valid_from: str
    valid_to: str | None
    provenance: str


class TeamRegistry:
    def __init__(self, teams: tuple[TeamSeed, ...], crosswalks: tuple[TeamCrosswalk, ...]):
        self.teams = tuple(sorted(teams, key=lambda item: item.registry_key))
        self.crosswalks = tuple(sorted(crosswalks, key=lambda item: (item.provider, item.provider_id, item.valid_from)))
        ids = {item.canonical_team_id for item in self.teams}
        if len(ids) != len(self.teams):
            raise ValueError("duplicate canonical team")
        for item in self.teams:
            validate_team_registry_key(item.registry_key)
            if canonical_team_id(item.registry_key) != item.canonical_team_id:
                raise ValueError("seeded team id does not match registry key")
        seen: dict[tuple[str, str], list[TeamCrosswalk]] = {}
        for row in self.crosswalks:
            if row.canonical_team_id not in ids:
                raise ValueError("team crosswalk references unknown canonical team")
            seen.setdefault((row.provider, row.provider_id), []).append(row)
        for key, rows in seen.items():
            ordered = sorted(rows, key=lambda item: item.valid_from)
            for left, right in zip(ordered, ordered[1:]):
                if left.valid_to is None or left.valid_to >= right.valid_from:
                    raise ValueError(f"overlapping team mapping: {key[0]}/{key[1]}")

    def resolve(self, provider: str, provider_id: str, on_date: str) -> str | None:
        target = date.fromisoformat(on_date)
        matches = [row for row in self.crosswalks if row.provider == provider and row.provider_id == provider_id
                   and date.fromisoformat(row.valid_from) <= target
                   and (row.valid_to is None or target <= date.fromisoformat(row.valid_to))]
        if len(matches) > 1:
            raise ValueError("ambiguous active team mapping")
        return matches[0].canonical_team_id if matches else None


def load_team_registry(path: Path) -> TeamRegistry:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TeamRegistry(
        tuple(TeamSeed(**row) for row in payload["teams"]),
        tuple(TeamCrosswalk(**row) for row in payload["crosswalks"]),
    )

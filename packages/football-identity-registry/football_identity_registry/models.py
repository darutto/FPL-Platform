"""Immutable inputs and outputs for deterministic identity matching."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourcePlayer:
    provider: str
    provider_id: str
    full_name: str
    team_provider_id: str | None = None
    birth_date: str | None = None
    known_name: str | None = None


@dataclass(frozen=True)
class CandidatePlayer:
    canonical_player_id: str
    full_name: str
    team_provider_id: str | None = None
    birth_date: str | None = None
    known_name: str | None = None


@dataclass(frozen=True)
class CandidateEvidence:
    canonical_player_id: str
    full_name: str
    matched_fields: tuple[str, ...]


@dataclass(frozen=True)
class MatchResult:
    source: SourcePlayer
    canonical_player_id: str | None
    match_method: str | None
    match_confidence: float | None
    candidates: tuple[CandidateEvidence, ...] = ()
    reason: str | None = None

    @property
    def matched(self) -> bool:
        return self.canonical_player_id is not None

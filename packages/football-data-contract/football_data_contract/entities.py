"""Immutable provider-neutral canonical football entities."""
from dataclasses import dataclass

from .enums import (
    AvailabilityState,
    CompetitionTier,
    FixtureStatus,
    Flank,
    FormationDepth,
    StartingRole,
)
from .provenance import Provenance


@dataclass(frozen=True)
class CanonicalPlayer:
    player_id: str
    full_name: str
    known_name: str
    birth_date: str | None
    nationality: str | None
    positions_nominal: tuple[str, ...]
    provenance: Provenance


@dataclass(frozen=True)
class CanonicalTeam:
    team_id: str
    name: str
    short_code: str
    provenance: Provenance


@dataclass(frozen=True)
class CanonicalCompetition:
    competition_id: str
    name: str
    tier: CompetitionTier
    country: str | None
    provenance: Provenance


@dataclass(frozen=True)
class CanonicalSeason:
    season_id: str
    label: str
    competition_id: str
    provenance: Provenance


@dataclass(frozen=True)
class CanonicalFixture:
    fixture_id: str
    season_id: str
    competition_id: str
    kickoff_utc: str
    home_team_id: str
    away_team_id: str
    status: FixtureStatus
    gameweek: int | None
    provenance: Provenance


@dataclass(frozen=True)
class PlayerMatchAppearance:
    fixture_id: str
    player_id: str
    team_id: str
    started: bool
    minutes: int
    sub_on_minute: int | None
    sub_off_minute: int | None
    replaced_by: str | None
    provenance: Provenance


@dataclass(frozen=True)
class PlayerMatchRole:
    fixture_id: str
    player_id: str
    formation: str
    grid_slot: str | None
    detailed_position: str | None
    derived_flank: Flank | None
    formation_depth: FormationDepth | None
    starting_role: StartingRole
    provenance: Provenance


@dataclass(frozen=True)
class Formation:
    fixture_id: str
    team_id: str
    formation_string: str
    source_timestamp: str
    provenance: Provenance


@dataclass(frozen=True)
class AvailabilityStatus:
    player_id: str
    as_of_utc: str
    state: AvailabilityState
    detail: str | None
    expected_return: str | None
    provenance: Provenance


@dataclass(frozen=True)
class InjuryRecord:
    player_id: str
    recorded_at_utc: str
    detail: str
    expected_return: str | None
    resolved_at_utc: str | None
    provenance: Provenance


@dataclass(frozen=True)
class SuspensionRecord:
    player_id: str
    recorded_at_utc: str
    reason: str
    starts_on: str | None
    ends_on: str | None
    fixtures_remaining: int | None
    provenance: Provenance


@dataclass(frozen=True)
class Substitution:
    fixture_id: str
    team_id: str
    player_off_id: str
    player_on_id: str
    minute: int
    provenance: Provenance


@dataclass(frozen=True)
class TeamMatchStats:
    fixture_id: str
    team_id: str
    possession_pct: float | None
    shots: int | None
    shots_on_target: int | None
    expected_goals: float | None
    provenance: Provenance


@dataclass(frozen=True)
class PlayerMatchStats:
    fixture_id: str
    player_id: str
    team_id: str
    minutes: int
    goals: int
    assists: int
    shots: int | None
    expected_goals: float | None
    expected_assists: float | None
    tackles: int | None
    interceptions: int | None
    provenance: Provenance

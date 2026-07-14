# football-data-contract · FI-1 contract

This package is the immutable, provider-neutral boundary between source
adapters and football-intelligence consumers. It contains contracts only: no
network access, normalization, persistence, feature computation, advice, or UI
rendering.

## Import and provider-neutrality boundary

Production modules may import only the Python standard library and other
modules inside `football_data_contract`. Imports from `fpl_*`,
`sportmonks_*`, HTTP clients, or provider clients are prohibited. Provider
payload keys and response shapes belong solely to their adapter. Provider names
appear here only in the closed `ProviderIdentifier` vocabulary used for
traceability.

Tactical fields describe lineup deployment: `derived_flank`,
`formation_depth`, and `starting_role`. They must never claim to represent a
player's average operating position.

## Closed vocabularies

| Enum | Values |
|---|---|
| `ProviderIdentifier` | `fpl`, `understat`, `sportmonks`, `vaastav` |
| `AvailabilityState` | `available`, `doubtful`, `injured`, `suspended`, `unregistered`, `unknown` |
| `CompetitionTier` | `league`, `domestic_cup`, `continental` |
| `FixtureStatus` | `scheduled`, `live`, `completed`, `postponed`, `cancelled`, `abandoned`, `unknown` |
| `Flank` | `left`, `central`, `right` |
| `FormationDepth` | `deep`, `mid`, `advanced` |
| `StartingRole` | `starter`, `substitute` |
| `SignalBasis` | `observed`, `inferred_proxy` |
| `EvidenceDirection` | `positive`, `negative`, `neutral` |
| `SubjectType` | `player`, `team`, `fixture` |

Adapters must map source values into these enums or emit a normalization
warning. Raw provider strings must not pass through.

## Canonical entities

All structures are frozen dataclasses. Every canonical data record carries a
`provenance: Provenance` field.

| Type | Fields, in stable serialization order |
|---|---|
| `CanonicalPlayer` | `player_id: str`, `full_name: str`, `known_name: str`, `birth_date: str|null`, `nationality: str|null`, `positions_nominal: tuple[str,...]`, `provenance` |
| `CanonicalTeam` | `team_id: str`, `name: str`, `short_code: str`, `provenance` |
| `CanonicalCompetition` | `competition_id: str`, `name: str`, `tier: CompetitionTier`, `country: str|null`, `provenance` |
| `CanonicalSeason` | `season_id: str`, `label: str`, `competition_id: str`, `provenance` |
| `CanonicalFixture` | `fixture_id: str`, `season_id: str`, `competition_id: str`, `kickoff_utc: str`, `home_team_id: str`, `away_team_id: str`, `status: FixtureStatus`, `gameweek: int|null`, `provenance` |
| `PlayerMatchAppearance` | `fixture_id`, `player_id`, `team_id`, `started: bool`, `minutes: int`, `sub_on_minute: int|null`, `sub_off_minute: int|null`, `replaced_by: str|null`, `provenance` |
| `PlayerMatchRole` | `fixture_id`, `player_id`, `formation: str`, `grid_slot: str|null`, `detailed_position: str|null`, `derived_flank: Flank|null`, `formation_depth: FormationDepth|null`, `starting_role: StartingRole`, `provenance` |
| `Formation` | `fixture_id`, `team_id`, `formation_string: str`, `source_timestamp: str`, `provenance` |
| `AvailabilityStatus` | `player_id`, `as_of_utc: str`, `state: AvailabilityState`, `detail: str|null`, `expected_return: str|null`, `provenance` |
| `InjuryRecord` | `player_id`, `recorded_at_utc: str`, `detail: str`, `expected_return: str|null`, `resolved_at_utc: str|null`, `provenance` |
| `SuspensionRecord` | `player_id`, `recorded_at_utc: str`, `reason: str`, `starts_on: str|null`, `ends_on: str|null`, `fixtures_remaining: int|null`, `provenance` |
| `Substitution` | `fixture_id`, `team_id`, `player_off_id`, `player_on_id`, `minute: int`, `provenance` |
| `TeamMatchStats` | `fixture_id`, `team_id`, `possession_pct: float|null`, `shots: int|null`, `shots_on_target: int|null`, `expected_goals: float|null`, `provenance` |
| `PlayerMatchStats` | `fixture_id`, `player_id`, `team_id`, `minutes: int`, `goals: int`, `assists: int`, `shots: int|null`, `expected_goals: float|null`, `expected_assists: float|null`, `tackles: int|null`, `interceptions: int|null`, `provenance` |

Canonical identifiers use the prefixes described by the implementation plan
(`cp_`, `ct_`, `cc_`, and `cf_`). Validation and identifier generation belong
to adapters/identity work in later slices; FI-1 does not guess or generate IDs.

## Traceability

| Type | Fields |
|---|---|
| `ProviderRef` | `provider: ProviderIdentifier`, `provider_id: str`, `valid_from: str`, `valid_to: str|null` |
| `Provenance` | `source_provider: ProviderIdentifier`, `ingested_at: str`, `source_timestamp: str|null`, `ingestion_run_id: str`, `model_version: str|null` |

`ingested_at` and non-null `source_timestamp` must be ISO-8601 timestamps with
an explicit UTC offset. `Z` and `+00:00` are accepted. Dates used for validity
or expected return are ISO calendar dates unless a later storage contract
explicitly narrows them.

## EvidenceItem

Field order is part of the serialization contract and is mirrored in
`packages/fpl-ui/lib/evidence.ts`.

| Field | Type | Semantics |
|---|---|---|
| `code` | `str` | Member of the closed `EVIDENCE_CODES` registry |
| `label` | `str` | Short human label; presentation may localize it |
| `subject_type` | `SubjectType` | `player`, `team`, or `fixture` |
| `subject_id` | `str` | Canonical subject identifier |
| `fixture_id` | `str|null` | Canonical fixture when evidence is fixture-specific |
| `impact` | `float` | Inclusive `[-10.0, 10.0]` |
| `direction` | `EvidenceDirection` | Positive iff impact > 0, negative iff < 0, neutral iff 0 |
| `confidence` | `float` | Inclusive `[0.0, 1.0]`, deterministic and rule-derived |
| `basis` | `SignalBasis` | Confirmed observation or explicitly inferred proxy |
| `summary` | `str` | Grounded factual sentence; producers must not use recommendation verbs |
| `source_features` | `tuple[str,...]` | Immutable names of producing features |
| `model_version` | `str` | `<module-slug>-v<N>`; bump on behavioral change |
| `calculated_at` | `str` | ISO-8601 UTC timestamp with `Z` or `+00:00` |

Observed evidence is directly supported by canonical source facts. An
`inferred_proxy` is a deterministic derivation whose limitation must remain
visible to consumers. Missing inputs omit evidence; they never cause evidence
to be fabricated. Advice and recommendation decisions are not evidence fields.

### Initial EVIDENCE_CODES registry

`MINUTES_CONFIDENCE_HIGH`, `MINUTES_CONFIDENCE_LOW`, `ROTATION_RISK`,
`CAMEO_RISK`, `ROLE_STABLE`, `ROLE_CHANGED`, `OUT_OF_POSITION`,
`OPPONENT_FLANK_WEAKNESS`, `OPPONENT_UNIT_DISRUPTION`, `FIXTURE_CONGESTION`,
`REST_ADVANTAGE`, `SET_PIECE_ROLE`, `AVAILABILITY_DOUBT`.

Codes are identifiers, not prose. Additions require a documented contract
change plus Python/TypeScript parity updates. Renames, removals, or semantic
reuse of an existing code are breaking.

## Change and versioning rules

- Additive optional fields require an approved slice, documentation, and parity
  tests before consumers use them.
- Removing or renaming fields, changing order/type/nullability, changing enum or
  code meaning, or widening a closed vocabulary is a contract change.
- Behavioral changes to evidence production require a `model_version` bump;
  the contract itself does not compute evidence.
- Python is authoritative for these domain contracts. Only approved HTTP/UI
  boundary types are mirrored in TypeScript; FI-1 mirrors `EvidenceItem` only.
- FI-1 does not add evidence to `FinalResponse` or any HTTP response. That
  exposure remains FI-7.

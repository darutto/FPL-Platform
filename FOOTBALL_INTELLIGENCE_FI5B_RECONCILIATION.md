# FI-5b / FI-6 architectural reconciliation

**Status:** approved; FI-5b(a) implemented and under review

**Base:** `main@559d6cd7c1e68459a84316a7c3e650cbe63804c6`

**Decision:** approved for implementation in the frozen FI-5b(a), FI-5b(b), FI-6 sequence

## Conflict statement

The approved FI-6 procedures cannot be reproduced from a validated
`fi5-registry-v1` build.

- M1 requires a recency-weighted last-six start history, separate start/cameo
  evidence, and separate conditional minute means. V1 retains only last-five
  aggregate start share, cameo share, and a single combined minute mean.
- M2 requires auditable role distributions and last-three versus prior-seven
  modal-role comparison. V1 retains only the final modal role, stability,
  flank summary, formation depth, and out-of-position score.
- M3 requires competition stage, historically correct league-position band,
  and leading as well as trailing schedule context. Current canonical fixtures
  have none of those and retain no as-known-at-cutoff schedule history.

Reconstructing these inputs inside FI-6 would either be impossible or would
bypass the validated feature-build and strict pre-kickoff boundaries. Reducing
the module procedures to fit v1 would silently weaken the governing formulas.

## Decision

Adopt **Option A: complete every M1-M3 prerequisite before FI-6**.

The revised sequence is:

1. FI-5b(a) — provider-neutral canonical scheduling context v2.
2. FI-5b(b) — module-enablement feature registry/schema v2.
3. FI-6 — M1, M2, and M3 active; M4 and M5 non-operational skeletons.

This option preserves the original FI-6 definition, keeps intelligence outputs
out of the feature layer, and centralizes temporal reconstruction where it can
be validated and replayed. M3 may return `missing_context` for an individual
row when its required as-of standings or schedule context is unavailable, but
M3 remains an active implementation and must produce pinned golden output where
complete mock context exists. All three active modules are required for FI-6
completion.

## Canonical contract delta — FI-5b(a)

Existing canonical schema v1 remains readable and immutable. Canonical schema
v2 adds the following provider-neutral context.

| Field/dataset | Owner and grain | Dtype | Unit/vocabulary | Cutoff and missing policy | Consumer |
|---|---|---|---|---|---|
| `fixtures.competition_stage` | canonical fixture | string | closed `CompetitionStage` enum | value known at fixture observation; `unknown` when unmapped | M3 context feature |
| `fixture_schedule_snapshots.fixture_id` | schedule snapshot | string | canonical ID | required | leading/trailing schedule windows |
| `fixture_schedule_snapshots.observed_at_utc` | schedule snapshot | string | UTC ISO | must be strictly before target cutoff | leakage boundary |
| `fixture_schedule_snapshots.scheduled_kickoff_utc` | schedule snapshot | string | UTC ISO | latest observation strictly before cutoff wins | M3 windows |
| `fixture_schedule_snapshots.status` | schedule snapshot | string | closed fixture status | unknown values rejected/quarantined | M3 windows |
| `fixture_schedule_snapshots.competition_tier` | schedule snapshot | string | existing closed competition tier | unavailable excludes weighted contribution | M3 weighting |
| `team_standing_snapshots.{competition_id,season_id,team_id}` | team standing as-of snapshot | string | canonical IDs | required composite identity | M3 priority |
| `team_standing_snapshots.as_of_utc` | team standing snapshot | string | UTC ISO | strictly before target cutoff | leakage boundary |
| `team_standing_snapshots.observed_position` | team standing snapshot | Int64 | 1-based rank | nullable; audit-only | discrepancy audit |
| `team_standing_snapshots.{played,wins,draws,losses,goals_for,goals_against,goal_difference}` | team standing snapshot | Int64 | counts | required for a complete table identity | band derivation |
| `team_standing_snapshots.{points_before_deduction,points_deduction}` | team standing snapshot | Int64 | points | required; deduction zero is a true zero | band derivation/audit |

`CompetitionStage` is provider-neutral and closed: `league`, `qualification`,
`group`, `league_phase`, `round_of_32`, `round_of_16`, `quarter_final`,
`semi_final`, `final`, `replay`, `unknown`. Provider values never cross this
boundary. Mock-only mappings carry `assumption_status=mock_validated`; unknown
is retained rather than guessed.

League-position band is not canonical and never uses provider-supplied position
as ranking authority. It is recomputed from one standings table identity,
defined as `(competition_id, season_id, as_of_utc)`. An **active team** is every
canonical team participating in the selected competition-season table identity
at `as_of_utc`, as defined by the governed canonical competition-membership
contract. Membership is not inferred from standings rows and is not coupled to
a storage representation.

For a target cutoff, select the latest complete standings table identity whose
`as_of_utc < cutoff_utc`. A table identity is complete only when every active
team has exactly one valid row with all recomputation inputs and no non-active
team is present. Rank active teams by this literal chain: adjusted points
descending, goal difference descending, goals scored descending, wins
descending, then canonical `team_id` ascending as the final deterministic
tie-break. Adjusted points equal `points_before_deduction - points_deduction`.
`observed_position` is audit-only and never overrides recomputed rank. A
provider-observed/recomputed mismatch emits a deterministic warning containing
canonical keys only. Missing observed position is allowed; missing
recomputation inputs makes the table identity unavailable.

For league size `N` and recomputed one-based rank `r`, calculate
`q = floor(4 * (r - 1) / N)`: `0=top`, `1=upper_mid`, `2=lower_mid`, and
`3=bottom`. The formula is unchanged when `N` is not divisible by four or is
below four. Current standings, later corrections, incomplete table identities,
and provider position cannot backfill historical targets.

### Canonical snapshot identity, selection, and replay rules

`fixture_schedule_snapshots` has grain one normalized observation of one
canonical fixture at one observation timestamp and primary key
`(fixture_id, observed_at_utc)`. Identical normalized rows at an equal timestamp
collapse; differing values for the same key fail the build, so provider order
never chooses a winner. As-of selection retains `observed_at_utc < cutoff_utc`
and selects the greatest timestamp independently per fixture. Raw snapshots join
many-to-one to canonical fixtures; a selected snapshot joins zero-or-one to one;
scheduling-window joins may not expand fixture keys. Validation covers keys,
UTC timestamps, strict cutoff, fixture foreign keys, closed vocabularies,
kickoff validity, equal-timestamp conflicts, post-selection uniqueness, stable
`(fixture_id, observed_at_utc)` sorting, and identical semantic/parquet hashes
after input reversal and replay.

`team_standing_snapshots` has grain one active-team row in one complete table
identity, primary key `(competition_id, season_id, as_of_utc, team_id)`, and
table identity `(competition_id, season_id, as_of_utc)`. The governed canonical
competition-membership contract effective at `as_of_utc` is the sole membership
authority. Each table identity contains exactly one row per active team and no
non-active team. Identical normalized equal-timestamp rows collapse; conflicting
rows or differing table versions at the same timestamp fail. As-of selection
retains identities strictly before cutoff, discards invalid/incomplete
identities, selects the latest complete identity for the target
competition-season, resolves membership independently, and uses only rows from
that identity—timestamps are never combined.

Standing rows join many-to-one to their canonical competition, season, team,
and effective membership. The selected table identity must match the
independently resolved active-team set exactly one-to-one; the target team joins
exactly one-to-one when context exists. Duplicate or many-to-many expansion
fails before derivation. Validation covers keys, foreign keys, membership,
strict UTC cutoff, nonnegative counts, `played = wins + draws + losses`,
`goal_difference = goals_for - goals_against`, deductions, observed-position
bounds, stable `(competition_id, season_id, as_of_utc, team_id)` sorting, and
deterministic selection, ranking, warnings, and hashes.

FI-5b(a) must independently prove every ranking tie-break, deductions,
observed/recomputed agreement and disagreement, membership changes, that
standings rows cannot create/remove active teams, missing/extraneous team and
ranking-input failures, quartiles for divisible/non-divisible/sub-four league
sizes, exact-cutoff and later-snapshot exclusion, join cardinality, input-order
independence, and deterministic replay.

## Feature contract delta — FI-5b(b)

`fi5-registry-v1`, feature schema 1, and existing v1 build manifests remain
immutable. FI-5b mints `fi5-registry-v2`, `fi5-engine-v2`, feature manifest
schema 2, and cutoff policy `strictly-before-kickoff-v2`. V2 is additive at the
build-family level; it does not reinterpret or overwrite a v1 build.

### M1 sufficient statistics

All fields remain at `player_as_of_fixture` grain.

| Field | Dtype | Unit/range | Window and missing policy | Consumer |
|---|---|---|---|---|
| `weighted_start_share_last_6` | Float64 | fraction `[0,1]` | last six eligible team league fixtures during governed squad membership; null below one eligible fixture | M1 |
| `weighted_start_numerator_last_6` | Float64 | weight `[0,21]` | sum of recency weights for starts | audit/M1 |
| `weighted_start_denominator_last_6` | Float64 | weight `[0,21]` | sum of available recency weights; zero only with no evidence | audit/M1 |
| `starts_last_6` | Int64 | count `[0,6]` | true zero with eligible appearances | M1 |
| `appearances_last_6` | Int64 | count `[0,6]` | true zero | sufficiency |
| `cameo_appearances_last_6` | Int64 | count `[0,6]` | non-start appearances with minutes greater than zero | M1 |
| `mean_minutes_when_started_last_6` | Float64 | minutes `[0,120]` | null when no starts | M1 |
| `mean_minutes_when_cameo_last_6` | Float64 | minutes `[0,120]` | null when no positive-minute cameos | M1 |
| `recency_weight_version` | string | `m1-recency-weights-v1` | required when observations exist | M1/audit |

Recency weights are literal `1,2,3,4,5,6` from oldest to newest among the last
six eligible team league fixtures. A governed squad member who does not appear
consumes a fixture slot with start and cameo indicators false; appearance and
conditional-minute counts remain independently auditable. Availability multiplier and trailing
congestion remain governed FI-5 inputs. `start_probability`,
`expected_minutes`, `rotation_risk`, and module confidence remain FI-6 outputs
and must not be persisted as FI-5 features.

### M2 sufficient statistics

Complex role history is normalized rather than encoded in opaque JSON.

`player_role_window_summary` grain is
`(fixture_id, team_id, player_id, window_segment)`, where `window_segment` is
`last_10`, `last_3`, or `prior_7`.

| Field | Dtype | Unit/range | Missing policy |
|---|---|---|---|
| `eligible_starts` | Int64 | count `[0,10]` | true zero |
| `mapped_starts` | Int64 | count `[0,10]` | true zero |
| `unmapped_starts` | Int64 | count `[0,10]` | true zero |
| `modal_role` | string | closed role vocabulary | null with no mapped starts |
| `role_change_comparable` | boolean | flag | false unless both comparison windows have evidence |
| `role_mapping_version` | string | `role-map-v2` | required |
| `role_basis` | string | `observed` or `inferred_proxy` | required |

`player_role_distribution` grain is
`(fixture_id, team_id, player_id, window_segment, role, flank, formation_depth)`.
It adds `role_count:Int64` (`[1,10]`) and `role_share:Float64` (`[0,1]`). Shares
use all eligible starts, including unmapped starts, as the denominator. Empty
windows produce a summary row and no distribution rows. Formation, grid-slot,
and detailed-position source rows remain canonical inputs; the feature output
stores mapped sufficient statistics and mapping provenance, not raw provider
coordinates.

### M3 sufficient statistics

`team_fixture_context_v2` grain is `(fixture_id, team_id)`.

| Field | Dtype | Unit/range | Cutoff and missing policy | Consumer |
|---|---|---|---|---|
| `weighted_trailing_congestion_21d` | Float64 | weighted fixtures `[0,40]` | completed kickoffs in `[cutoff-21d, cutoff)` | M3 |
| `weighted_leading_congestion_21d` | Float64 | weighted fixtures `[0,40]` | schedule observations known before cutoff with kickoff in `(cutoff, cutoff+21d]` | M3 |
| `trailing_fixtures_considered` | Int64 | count | true zero | provenance |
| `leading_fixtures_considered` | Int64 | count | true zero | provenance |
| `previous_rest_days` | Float64 | days `[0,365]` | null without prior completed fixture | M3 |
| `next_rest_days` | Float64 | days `[0,365]` | null without known next fixture | M3 |
| `target_competition_tier` | string | closed tier | null/unknown gives `missing_context` for dependent output | M3 |
| `target_competition_stage` | string | closed stage | `unknown` gives `missing_context` for fixture priority | M3 |
| `league_position_band` | string | `top/upper_mid/lower_mid/bottom/unknown` | latest valid as-of snapshot only | M3 |
| `schedule_context_as_of_utc` | string | UTC ISO | latest contributing observation; null without leading context | provenance |
| `standing_context_as_of_utc` | string | UTC ISO | strictly before cutoff; null when unavailable | provenance |
| `competition_weight_version` | string | `competition-weights-v1` | required | M3/audit |

Competition weights are governed in one FI-5b constants table and versioned;
the proposed v1 values for architectural approval are league `1.0`, domestic
cup `1.0`, and continental `1.25`. FI-6 owns the fixture-priority lookup and
rotation intelligence; FI-5b owns only auditable scheduling sufficient
statistics and context.

## Validation, compatibility, and provenance

- FI-6 supports v2 exclusively. A v1 feature pointer/build fails with typed
  `unsupported_feature_contract`; it is never auto-upgraded at module runtime.
- An explicit offline FI-5b rebuild from a validated canonical v2 build is the
  migration path. V1 builds remain readable by v1 tooling and are never mutated.
- Every v2 row binds canonical build ID/hash, feature build ID/hash at the build
  boundary, feature registry/engine/cutoff versions, target keys and cutoff,
  family-specific evidence counts/window timestamps, mapping/weight versions,
  and assumption status.
- Target, same-time, and future lineup/formation records are excluded. Leading
  schedule inputs are permitted only when their observation timestamp is
  strictly before cutoff; later corrections cannot rewrite historical context.
- Required columns, exact dtypes, primary keys, foreign keys, finite ranges,
  enum closure, source hashes, path containment, and symlink safety fail closed.
- Two identical canonical-v2 inputs produce identical row sets, ordering,
  values, nulls, dtypes, reports, semantic hashes, and parquet hashes across
  output roots and input-row order.
- No feature duplicates an FI-6 probability, confidence, recommendation, or
  evidence output.

## Revised phase sequence and definitions of done

### FI-5b(a) — canonical scheduling context v2

DoD: provider-neutral stage enum, fixture schedule snapshots, and as-of standing
snapshots are frozen and documented; mock normalizers and canonical schema-v2
build/replay/validation are deterministic; historical cutoff, tie, deduction,
postponement, unknown-stage, containment, rollback, and no-network tests pass.
No feature or module computation is added.

### FI-5b(b) — module-enablement features v2

DoD: the three v2 feature families above are built only from validated canonical
v2 inputs; the two inherited FI-5 tests causally pin a completed same-time
candidate and an unrelated third-team congestion fixture; target/future
leakage, exact windows, minimum evidence, ordering, source binding, replay,
rollback, path safety, and no-network tests pass. V1 remains immutable and a
v1/v2 compatibility matrix is documented. No intelligence output is added.

### FI-6 — intelligence modules v1

DoD: M1-M3 consume validated FI-5b v2 builds exclusively and emit the exact
plan-governed typed outputs/evidence on independent golden anchors. Complete
mock context produces active M1-M3 output; per-row absent stage/standing context
produces deterministic `missing_context` only for dependent M3 outputs. M4/M5
remain mechanically non-operational skeletons. Module-order independence,
temporal integrity, immutable intelligence builds, provenance, replay,
validation, rollback, containment, no-network, and runner/gate propagation are
proven. No recommendation, tool, route, FinalResponse, or UI integration occurs.

## Risk assessment

- **Leakage:** leading schedules and standings are especially vulnerable to
  using today's corrected state. Snapshot observation timestamps and strict
  as-of selection are mandatory; final-state fixture rows are insufficient.
- **Historical standings:** deductions, missing tie data, postponed matches, and
  later corrections can change ranks. Unknown inputs produce `unknown`, never a
  reconstructed guess from current standings.
- **Provider assumptions:** competition-stage mappings and leading schedules are
  mock-validated before the trial and must carry that assumption status.
- **Mock-only stage:** golden M3 output demonstrates mechanics, not live payload
  validity. FI-9 remains the live-validation gate.
- **Schema expansion:** canonical schema v2 and feature schema v2 increase
  migration and gate cost. Versioned parallel builds prevent reinterpretation.
- **Duplicate computation:** FI-5b computes sufficient statistics and contextual
  lookups; FI-6 alone owns probabilities, expected minutes, risk, confidence,
  fixture priority, evidence, and module decisions.

## Scope statement

This artifact records the approved architecture. FI-5b(a) is merged and
complete. FI-5b(b) is implemented and under review. FI-6 remains blocked and
FI-7 remains unstarted.

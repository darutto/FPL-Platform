# FI-5 feature contract

FI-5 produces deterministic, provider-neutral `player_as_of_fixture` rows from
one validated local `RuntimeBuildHandle`. It performs no remote read, provider
call, prediction, recommendation, assistant integration, or UI work.

## Registry and catalog

Registry `fi5-registry-v1`, engine `fi5-engine-v1`, and cutoff policy
`strictly-before-kickoff-v1` govern thirteen stable features:

- role/deployment: `primary_role`, `role_stability`, `flank`,
  `flank_distribution`, `formation_depth`, `out_of_position_score`;
- participation inputs: `start_share_last_5`, `mean_minutes_last_5`,
  `cameo_share_last_5`, `rotation_tendency`;
- scheduling: `rest_days`, `fixture_congestion_index` (prior 21 days);
- availability: `availability_multiplier`.

Fractions use `[0,1]`, minutes use `[0,120]`, rest uses days, and congestion is
a count. Role features use the last ten eligible starts; participation uses the
last five eligible appearances. Missing history remains null with
`missing_reason=insufficient_history`; this row field describes participation-
history absence only, not role mapping or feature-family-specific null causes.
An unused-substitute lineup record with zero minutes is an appearance record and
therefore consumes a last-five slot. Congestion is a true zero when no prior
fixture exists. Availability is 1.0 available, 0.5 for an effective injury,
and 0.0 for an effective suspension. These are deterministic status encodings,
not medical or selection predictions.

Role and participation windows remain within the target competition and season;
the 21-day scheduling congestion count intentionally includes all competitions
for the team because physical turnaround crosses competition boundaries.

## Leakage and cutoff

Only fixtures with kickoff strictly before the target kickoff contribute. The
target fixture and later fixtures never contribute. Same-time fixtures are not
eligible; fixture ID is the deterministic secondary ordering key. Postponement
keeps fixture identity but changes explicit eligibility through corrected
kickoff. Injury/suspension records must be recorded before cutoff and unresolved
at cutoff. Lineups at or after target kickoff are excluded. Abandoned or
incomplete/abandoned fixtures do not contribute to v1 windows.

## Provenance and output

Every row carries canonical build and manifest hash, target fixture/team/player,
cutoff, engine version, and registry version. `eligible_observations` and
`window_start_utc` are specifically participation provenance: respectively the
number of eligible last-five appearance rows and the most recent eligible
appearance kickoff. They do not claim to describe the independent deployment,
congestion, or availability windows.

The v1 emitted flank vocabulary is `left`, `right`, and `center`; it emits
neither `central` nor `mixed`. Role and flank distributions retain unmapped
starts in their denominator, so mapped shares may sum below 1.
The immutable local layout is:

```text
features/builds/<id>/manifest.json
features/builds/<id>/datasets/player_fixture_features.parquet
features/builds/<id>/reports/{warnings,exclusions}.json
features/_features_latest.json
```

Manifest schema 1 binds the canonical build ID and exact manifest hash, engine,
registry, families, paths, schemas, rows, semantic and byte hashes, counts,
cutoff policy, assumption status, and build timestamp. Paths and build IDs are
strict, relative, contained, and symlink-safe. Staging is validated before an
immutable directory finalize; the feature pointer swaps last. Failure retains
the previous pointer/build.

Stable sorting, explicit windows, canonical JSON, stable parquet schemas, and
literal golden assertions provide deterministic replay. No wall clock, locale,
provider ordering, input row order, temporary path, or remote state contributes.

## CLI and limitations

`python -m football_intelligence.features build` and `validate` require an
explicit canonical root and feature build selection. They are offline and do
not publish remotely. The mock corpus is intentionally small; role mapping is a
closed v1 table and unmatched canonical detailed positions remain null. FI-6
intelligence modules and predictive interpretations are deferred.

## FI-5b(b) feature contract v2

FI-5b(b) is an additive, offline-only build family. It does not reinterpret or
replace the v1 registry, datasets, validator, build path, or pointer. Registry
`fi5-registry-v2`, engine `fi5-engine-v2`, manifest schema 2, and cutoff policy
`strictly-before-kickoff-v2` are exact compatibility boundaries. V2 requires a
validated canonical-v1 base build for governed squad/lineup history and a
validated `canonical-context-v2` build (canonical schema 2, manifest schema 2)
for as-known scheduling and standings. Both source build IDs and exact manifest
hashes are bound. Neither source is inferred from aggregate v1 features or an
unversioned “latest” fallback.
The closed registry contains all 30 approved M1/M2/M3 fields with explicit
grain, dtype, nullability, unit/vocabulary, source datasets, cutoff, window,
minimum evidence, missingness, and consumer. Its stable ordered JSON has a
SHA-256 hash pinned in every manifest; reordering or changing any contract field
changes the hash.
Each persisted row carries its feature build ID; the manifest binds that ID to
the exact per-dataset semantic and byte hashes, avoiding a circular in-row
manifest-hash dependency while preserving complete build provenance.

| Dataset | Primary key | Purpose |
|---|---|---|
| `player_fixture_module_inputs` | `(fixture_id, team_id, player_id)` | M1 sufficient statistics |
| `player_role_window_summary` | `(fixture_id, team_id, player_id, window_segment)` | M2 window sufficiency and modal role |
| `player_role_distribution` | `(fixture_id, team_id, player_id, window_segment, role, flank, formation_depth)` | normalized M2 distribution |
| `team_fixture_context_v2` | `(fixture_id, team_id)` | M3 schedule and table context |

M1 exposes `weighted_start_share_last_6`, its numerator/denominator,
`starts_last_6`, `appearances_last_6`, `cameo_appearances_last_6`, separate
start- and cameo-conditioned mean minutes, and `recency_weight_version`.
Weights are literal `1..6` oldest to newest. An eligible governed team league
fixture consumes a slot even on nonappearance. No history gives a null share,
zero denominator/counts, null conditional means, and null weight version.
Probability, expected minutes, risk, and confidence remain FI-6 outputs.

M2 emits summary rows for `last_10`, `last_3`, and non-overlapping `prior_7`.
Empty windows retain a zero-count summary and no distribution rows. The closed
map is `role-map-v2`; unmapped eligible starts remain in the share denominator.
`role_change_comparable` states only whether comparison is possible, not a
role-change conclusion. Raw provider coordinates and opaque JSON are excluded.

M3 exposes weighted trailing completed fixtures in `[cutoff-21d, cutoff)`,
leading fixtures known before cutoff with kickoff in `(cutoff, cutoff+21d]`,
counts, prior/next rest, target tier/stage, recomputed historical league band,
selected context timestamps, and `competition-weights-v1`. Weights are league
`1.0`, domestic cup `1.0`, and continental `1.25`. Missing standings remain
`unknown` with null as-of; missing context is never backfilled from current
state.

`previous_rest_days` and `next_rest_days` are independent of the 21-day
congestion collections. They use respectively the nearest eligible completed
fixture strictly before kickoff and the nearest eligible known scheduled
fixture strictly after kickoff, up to the governed 365-day bound. Same-kickoff
fixtures are neither previous nor next anchors. A missing eligible anchor is
represented by null even when the corresponding 21-day count is a valid zero.

All eligibility is strict at cutoff. Same-time/future lineup evidence and
schedule observations at or after cutoff are excluded. Exact ordered schemas,
closed vocabularies, unique keys, stable sorting, finite ranges, contained
literal paths, source hashes, semantic hashes, and parquet hashes fail closed.
Validation precedes immutable finalization and pointer publication.

```text
features/builds-v2/<id>/manifest.json
features/builds-v2/<id>/datasets/{player_fixture_module_inputs,player_role_window_summary,player_role_distribution,team_fixture_context_v2}.parquet
features/builds-v2/<id>/reports/{warnings,exclusions}.json
features/_features_v2_latest.json
```

Python entry points are `build_features_v2`, `validate_feature_build_v2`, and
`replay_feature_build_v2`; the focused gate is
`python packages/fpl-grounded-assistant/run_phase_fi5bb_tests.py`. V1 and v2
validators reject the other contract. FI-5b(b) also makes membership-overlap
validation unconditional, declares `points_before_deduction` nonnegative, and
closes canonical-context-v2 manifest fields. The pinned phase-coupled
`fi5ba-v1` mock-normalizer name is documented and deferred until a deliberate
canonical version can replace it without compatibility churn.

## FI-6a module-consumption boundary

FI-6a consumes only a fully validated `module-enablement-features-v2` build
bound to its validated canonical-v1 and canonical-context-v2 sources. A
recognizable FI-5 v1 manifest fails with typed
`unsupported_feature_contract`; hash, schema, version, registry, path, and
source-binding corruption remains a validation failure and must not degrade to
`missing_context`. Only an absent build or absent target row degrades to
`missing_context`.

`evaluate_expected_minutes` is pure over frozen, provider-neutral inputs. Its
availability state and chance-of-playing fraction are explicit versioned
evaluator inputs rather than resurrected FI-5 v1 features, using the closed
input version `availability-input-v1`. The coefficients are centralized as
`expected-minutes-hand-tuned-v1`; they are heuristic and
must be backtested before being treated as calibrated probabilities. The model
version is `expected-minutes-v1`.

FI-6 replay is deterministic reevaluation: the same validated v2 build,
explicit evaluator inputs, and explicit UTC `calculated_at` produce identical
frozen results and evidence. No wall clock participates. FI-6a creates no
intelligence store, manifest, pointer, or persisted evidence. Optional
`intelligence_evidence.parquet` remains deferred to backtesting. Tools,
responses, orchestration, recommendations, routes, and UI exposure remain
FI-7 scope.

Pure FI-6 evaluator behavior, including M2 consumption of these governed role
rows, is owned by [`MODULE_CONTRACT.md`](MODULE_CONTRACT.md). This reference
adds no FI-5 feature or storage semantics.

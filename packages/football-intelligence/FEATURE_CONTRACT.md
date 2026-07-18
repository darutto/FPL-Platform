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

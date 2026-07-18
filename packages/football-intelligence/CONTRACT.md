# Football intelligence ingestion contract â€” FI-4a

## Status and boundary

FI-4a is offline-only. `football_intelligence.ingestion` converts checked-in,
documentation-derived Sportmonks mock snapshots to provider-neutral canonical
parquet. It has no token, HTTP, R2, workflow, server, assistant, tool, UI,
feature, or intelligence-module integration. FI-4b distribution and runtime
integration is explicitly deferred.

Dependency direction is one-way: provider-owned records enter the FI-4a adapter,
which emits `football-data-contract` identities and canonical rows. The
canonical package never imports this package or `sportmonks-client`; the
provider client owns no persistence.

## Team registry and player authority

`team_registry_seed.json` owns the minimal Arsenal/Chelsea seed needed by the
fixture. Keys use `jurisdiction|stable-club-key|category|squad-level`, and each
segment is lowercase ASCII letters/digits with single hyphens. Display labels
are aliases, never keys. Exact, validity-dated crosswalks cover FPL, Understat,
mock Sportmonks, and vaastav identifiers. Duplicate active or overlapping
provider mappings fail closed. Sportmonks identifiers are explicitly mock-only
and `unverified_against_live`; there is no fuzzy team matching.

Player authority order is: an existing valid canonical crosswalk first (to
avoid reminting); otherwise the current owned FPL record; otherwise an owned
historical FPL/vaastav record. Conflicting authoritative names or birth dates
enter reconciliation by raising a conflict. Sportmonks names and IDs never mint
players. Unmatched provider players are quarantined.

## Governed identity grammars

Season edition keys are `YYYY-YYYY` with consecutive years, `YYYY`, or
`special-<lowercase-hyphen-slug>`. Examples: `2025-2026`, `2026`, and
`special-centenary`. Provider season IDs are excluded.

Fixture scheduling keys are:

- `league-home-meeting-1|2` or `league-away-meeting-1|2`;
- `cup-<round>-leg-1|2`, `cup-<round>-replay-N`, or `cup-<round>-single`;
- `replacement-N` for an abandoned/replayed replacement;
- `neutral-<event-slug>` for neutral-venue matches.

The Premier League's two meetings are distinct through home/away and meeting
number. Kickoff and provider fixture ID are excluded, so a postponement or
provider-ID correction does not remint the fixture.

## Normalization and quarantine

The adapter covers competitions, seasons, teams, fixtures, players, squads,
lineups, formations, substitutions, injuries, suspensions, coaches, referees,
team fixture statistics, and player fixture statistics. Every valid row has a
safe provider reference, ingestion run, schema version, and source timestamp
where available. Required foreign keys resolve before publication; home and
away differ; primary keys are unique. No unsupported football meaning is
inferred. Coaches/referees are represented by provider-neutral names plus their
team/fixture association and provenance because FI-4a has no governed canonical
person-ID contract for those roles.

Deterministic quarantine entries contain only `reason`, `family`, and a safe
`provider/provider-id` referenceâ€”never a token or payload dump. Reasons cover
unmatched/ambiguous players, missing team or foreign-key mappings, invalid key
grammar, duplicate keys, unknown values, and schema failures as applicable.
Invalid required references are never persisted as canonical rows. Unknown
non-fatal values produce sorted warnings. Failed staging is deleted; reports
for successful builds remain with the immutable build.

## Store, schemas, and publication

`FPL_FOOTBALL_ROOT` defaults to `data/football`. Layout:

```text
_football_latest.json
builds/<build-id>/manifest.json
builds/<build-id>/canonical/<entity>.parquet
builds/<build-id>/reports/{build_report,warnings,quarantine}.json
.staging/<temporary-build>/
```

`schemas.py` is authoritative for ordered columns, pandas dtypes, nullability,
primary keys, and schema version. Strings use pandas `string`, integers `Int64`,
floats `Float64`, and booleans `boolean`; timestamps are canonical UTC strings.
Rows are stable-sorted by primary key. Provider payload column names are not
copied into canonical parquet.

All parquet files are staged, reread, dtype-validated, foreign-key-validated,
and hashed before publication. The completed staging directory is moved into an
immutable build directory, then `_football_latest.json` is atomically replaced.
If any step fails, the prior pointer and active build remain untouched.

Manifest entity paths must be non-empty strings of the exact form
`canonical/<name>.parquet`. Absolute, drive-qualified, UNC, backslash, and `..`
paths are rejected before any file read. The resolved file must remain under the
resolved build root and be a regular file, so symlink escapes fail closed.
Active build IDs use the complete grammar `[a-z0-9]+(?:-[a-z0-9]+)*`; the
resolved target must be a real, direct child directory of `builds/`. Symlinked
build directories that resolve outside `builds/` are rejected.

The sorted JSON manifest contains schema/build identifiers, build time, input
version, normalizer and identity versions, entity paths, row counts, normalized
content hashes, parquet byte hashes, warning/quarantine counts, and assumption
status. Fixed inputs/build metadata yield identical rows, ordering, IDs,
reports, content hashes, and parquet bytes. A differing intentional `built_at`
is excluded from row-content comparison.

## Offline CLI

```bash
python -m football_intelligence.ingestion.cli rebuild --source FILE --destination ROOT --build-id ID
python -m football_intelligence.ingestion.cli validate --destination ROOT
python -m football_intelligence.ingestion.cli replay --manifest FILE --destination ROOT
```

Commands accept local files only and exit nonzero on schema, identity,
referential, publication, or replay failure. They never require a token and
cannot select live mode.

## FI-4b portable manifest and distribution contract

Manifest schema v2 replaces the absolute `source_fixture` field with a portable
`source` descriptor: kind, name, version, exact source-byte hash, and an optional
normalized repository-relative path. Replay verifies that hash and confines
implicit resolution beneath the repository root; external snapshots require an
explicit `--source`. Schema-v1 replay fails clearly and is never reinterpreted.
Remote validation does not require the original source snapshot.

Remote keys are generated only as `<prefix>/builds/<build-id>/manifest.json`,
governed canonical/report paths beneath that build, and
`<prefix>/_football_latest.json`. Prefix, ID, and path grammars reject traversal,
absolute/drive/UNC paths, backslashes, controls, empty segments, and ambiguous
separators. Immutable writes are idempotent only for identical bytes.

Publication validates locally, uploads and verifies every artifact, uploads and
verifies the manifest, then conditionally writes the pointer last. Pointer schema
v1 has exactly `schema_version`, `build_id`, `manifest_hash`, `published_at`, and
`publisher_version`. Unknown fields/versions fail. A pointer race preserves the
prior pointer.

Download defaults are 64 KiB pointer, 1 MiB manifest, 1 MiB report, 128 MiB per
parquet, and 512 MiB total. Declared and streamed sizes are enforced. Sync uses
a timeout-bounded stale-recoverable lock, unique staging, complete FI-4a
validation, immutable finalization, and an atomic local pointer swap. Failed
refreshes retain the previous validated build.

Missing `FPL_FOOTBALL_REMOTE_*` configuration is `disabled`; no local build is
`unavailable`; a failed refresh with a valid cache is `degraded`; a validated
sync is `ready`. Startup is fail-soft. Request handling reads the validated local
cache via `RuntimeBuildHandle`, never the remote store. SDK failures become typed,
secret-safe errors. Supported versions are pointer 1, manifest 2, canonical 1,
normalizer `fi4a-v1`, and identity registry
`team-seed-v1/player-precedence-v1`; unknown versions fail before activation.

FI-5 features, recommendations, tools, analysis routes, UI/evidence exposure,
live ingestion, and background polling remain out of scope. Tests use fakes and
no real account, credentials, or network.

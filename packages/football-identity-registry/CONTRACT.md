# Football identity registry contract — FI-2

## Boundary

This package owns offline, deterministic cross-provider crosswalk construction.
It wraps rather than replaces the existing FPL resolver. It performs no HTTP,
R2, serving, Sportmonks, fuzzy, probabilistic, or LLM work.

## Matching

Names use Unicode NFKD, combining-mark removal, case folding, punctuation to
spaces, and whitespace collapse. Tiers are evaluated in order and have fixed
confidence: `manual_override` 1.00, `full_name_birth_date` 0.99,
`full_name_team` 0.95, `full_name_unique` 0.90, `known_name_team` 0.85, and
`surname_birth_date` 0.80. Multiple candidates at the first matching tier,
anything below the configurable threshold (default 0.80), and no candidate all
produce queue entries; no lower tier or fuzzy guess resolves ambiguity.

Canonical player IDs are `player_` plus the first 24 hexadecimal SHA-256
characters of `player|<normalized full name>|<birth date or empty>`. Provider
names and IDs are forbidden inputs. Builders must detect a truncated-hash
collision between different fingerprints and stop for operator review. Build
inputs cannot choose canonical IDs: the builder derives them from the immutable
name/birth-date identity and rejects a caller-supplied identifier.

Missing birth date is an explicitly degraded identity mode. Distinct candidate
records with the same normalized-name/no-DOB fingerprint (including records
distinguished by team or known/web name) fail the entire build with
`IdentityIndistinguishableError` before overrides or mappings are evaluated.
Exact duplicate input rows are deduplicated and do not constitute a collision.
Team alone is never promoted into the permanent canonical fingerprint.

A later authoritative DOB backfill changes the fingerprint and therefore may
change the canonical ID; it is not identity-neutral. Reconciliation must retain
the old historical crosswalk, close its validity range, append the new mapping,
and record an auditable operator reconciliation or override when continuity is
asserted. Silent overwrite is forbidden. FI-9 must revisit canonical-ID
fitness and migration using the identity metadata observed during the live
Sportmonks trial.

## Persistent schemas

`player_identity.parquet` has this exact ordered schema:

`canonical_player_id, provider, provider_id, normalized_name, full_name,
team_provider_id, birth_date, valid_from, valid_to, match_method,
match_confidence, manual_override`.

`team_identity.parquet`: `canonical_team_id, provider, provider_id, name,
valid_from, valid_to`; `fixture_identity.parquet`: `canonical_fixture_id,
provider, provider_id, valid_from, valid_to`; `competition_identity.parquet`:
`canonical_competition_id, provider, provider_id, name, valid_from, valid_to`.

Dates are ISO `YYYY-MM-DD`; null `valid_to` means active. At most one active
canonical mapping may exist per `(provider, provider_id)`. A changed team scope
closes the old row on the day before the new `valid_from` and appends a new row,
preserving transfers, departures, and re-entry history.

All parquet and JSON writes use a sibling temporary file plus `os.replace`.
`_identity_latest.json` is written last with schema version, run provenance,
counts, and caller-supplied UTC timestamp. Repeating identical inputs is
semantically idempotent.

## Overrides and queue

Checked-in `overrides.yaml` requires exactly `version: 1` and an `overrides`
list. Each item requires non-empty `provider`, `provider_id`,
`canonical_player_id`, and `reason`; duplicate sources are invalid. Overrides
always win and write `manual_override=true` at confidence 1.00. The repository
contains no production mapping.

`ambiguity_queue.json` contains schema version and deterministic items. Each
item records the complete source context, reason (`ambiguous`,
`below_threshold`, `no_candidate`, or `invalid_manual_override`), and sorted
candidate evidence including canonical ID, display name, and matched fields.

The offline owned-corpus validation writes a names-only extract and deterministic
report under `corpus/`. Its denominator includes every distinct non-empty source
name/team identity. The report carries source hashes, tier counts, match rates,
and the complete unresolved queue; raw shots and credentials are never copied.

Schema column renames/removals, tier changes, confidence changes, canonical-ID
changes, or queue shape changes are breaking. Additive metadata needs a labelled
plan slice and contract-gate update.

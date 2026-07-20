# football-intelligence

FI-4a provides an offline, mock-driven ingestion layer and deterministic local
canonical parquet store. It consumes provider-owned fixture records, exact
identity crosswalks, and provider-neutral canonical ID helpers.

```bash
python -m football_intelligence.ingestion.cli rebuild \
  --source tests/fixtures/sportmonks_replay_v1.json \
  --destination /tmp/football --build-id fixture-v1
python -m football_intelligence.ingestion.cli validate --destination /tmp/football
```

The checked-in team seed is deliberately minimal and Sportmonks mappings remain
mock-only and `unverified_against_live`. See `CONTRACT.md` for schemas, identity
grammars, replay guarantees, quarantine behavior, and atomic publication.

FI-4b adds portable manifests, immutable S3-compatible publication, bounded
cache synchronization, fail-soft backend capability discovery, and the
`python -m football_intelligence.distribution` operator CLI. Imports and
`--help` need no credentials; tests use an in-memory adapter.

Non-goals remain live Sportmonks ingestion, predictions, recommendations, tools,
analysis routes, UI/evidence exposure, and background polling.

FI-5 adds the offline deterministic feature engine:

```bash
python -m football_intelligence.features build --canonical-root data/football-runtime --feature-root data/football-features --feature-build-id fixture-v1 --built-at 2026-07-01T00:00:00Z
python -m football_intelligence.features validate --canonical-root data/football-runtime --feature-build data/football-features/builds/fixture-v1
```

See `FEATURE_CONTRACT.md` for the exact 13-feature catalog, cutoff/window rules,
missingness, provenance, atomic local layout, and analytical non-goals.
# FI-5b(a) runner

Run `python ../fpl-grounded-assistant/run_phase_fi5ba_tests.py` from this
package's parent directory. The runner executes only the canonical scheduling
context v2 tests and performs no network access.

# FI-5b(b) runner

Run `python ../fpl-grounded-assistant/run_phase_fi5bb_tests.py` from this
package's parent directory. The additive feature-contract-v2 build family is
offline and unused by runtime code; no FI-6 module logic is present.

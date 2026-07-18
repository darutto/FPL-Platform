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

Non-goals remain live Sportmonks ingestion, features, recommendations, tools,
analysis routes, UI/evidence exposure, and background polling.

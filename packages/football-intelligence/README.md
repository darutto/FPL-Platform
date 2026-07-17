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

Non-goals in FI-4a: live requests, tokens, R2, scheduled workflows, server or
assistant imports, tools, UI, features, modules, and all FI-4b integration.

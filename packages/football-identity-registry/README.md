# football-identity-registry

FI-2 provides a deterministic, provider-neutral crosswalk above the existing
FPL query resolver. It does not replace or modify `fpl-player-registry` or
`player_matching.py`, and no runtime consumer uses it yet.

```bash
python -m football_identity_registry.cli build --input identities.json \
  --valid-from 2026-08-01 --run-id preseason-2026 \
  --generated-at 2026-08-01T00:00:00Z
python -m football_identity_registry.cli verify
python -m football_identity_registry.cli queue
```

Build inputs are offline JSON containing `candidates` and `sources`. Commands
never prompt or access the network. The root defaults to
`data/football/identity` and can be changed with `FPL_FOOTBALL_ROOT` or
`--root`.

The checked corpus is deliberately small and sanitized: Understat-shaped
names match 4/4 (100%) and vaastav-shaped historical names match 2/3 (66.7%).
It proves matcher behavior but is not representative enough to claim a ≥95%
rate over the real current-season owned store; that measurement remains open
until such a snapshot is available locally.

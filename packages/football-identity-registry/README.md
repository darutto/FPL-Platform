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

Real owned-store validation is reproducible with:

```bash
python -m football_identity_registry.corpus verify
```

The committed names-only extract is derived from hashed 2025–26 tactical/FPL
stores and the 2024–25 vaastav-imported store. Understat produces 375/461
automatic matches (81.3449%; 86 unmatched, 0 ambiguous), below the ≥95% target.
Vaastav produces 804/804 (100%). See `corpus/report.json` for tier distribution
and the complete unresolved queue. The earlier tiny synthetic corpus remains a
unit fixture only and is not presented as production validation.

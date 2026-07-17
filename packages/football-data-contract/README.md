# football-data-contract

Immutable, provider-neutral football data and structured evidence contracts.
The package uses only the Python standard library and adds no runtime
dependency.

```python
from football_data_contract import (
    EvidenceDirection,
    EvidenceItem,
    SignalBasis,
    SubjectType,
)

item = EvidenceItem(
    code="ROLE_STABLE",
    label="Stable role",
    subject_type=SubjectType.PLAYER,
    subject_id="player_365f648bdd9b01f5504c074e",
    fixture_id=None,
    impact=2.0,
    direction=EvidenceDirection.POSITIVE,
    confidence=0.8,
    basis=SignalBasis.OBSERVED,
    summary="The player started in the same role across recent fixtures.",
    source_features=("role_stability",),
    model_version="tactical-role-v1",
    calculated_at="2026-07-14T18:00:00Z",
)
```

The canonical entities follow the same frozen-dataclass pattern and always
carry `Provenance`.

## Non-goals

- Provider payload models or normalization
- Network clients or API calls
- Identity matching or persistence
- Feature or intelligence computation
- Recommendations or scoring
- `FinalResponse`/HTTP exposure and UI rendering

See `CONTRACT.md` for the complete schemas, vocabularies, versioning rules, and
provider-neutral import boundary.

Canonical ID helpers are provider-neutral and deterministic:

```python
from football_data_contract import canonical_player_id, canonical_team_id

player_id = canonical_player_id("Bukayo Saka", "2001-09-05")
team_id = canonical_team_id("england|arsenal|men|first-team")
```

Team registry keys are governed operator assignments with exactly four
lowercase segments: `jurisdiction|stable_club_key|category|squad_level`.
Segments use ASCII letters, digits, and single hyphens. Display names and
provider labels are invalid keys. `|` is reserved for fingerprint boundaries
and is forbidden inside every free-string component; invalid values fail before
hashing. This package does not match providers, ingest payloads, or persist data.

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
    subject_id="cp_01",
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

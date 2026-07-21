# Football Intelligence Pure-Module Contract

This document governs pure FI-6 evaluators. `CONTRACT.md` retains package and
canonical-build ownership; `FEATURE_CONTRACT.md` retains FI-5 feature-store
ownership. FI-6 modules consume validated features but do not alter FI-5.

## Shared evaluator rules

- Results are frozen dataclasses with immutable tuple collections.
- Status is `ok`, `missing_context`, or `not_implemented`. Absent builds,
  manifests, or governed target rows may degrade to `missing_context`;
  malformed, contradictory, unsupported, or corrupt input must not.
- Unsupported feature families, schemas, registries, mapping versions, and
  unversioned fallback attempts raise `UnsupportedFeatureContractError`.
  Invalid v2 manifests, hashes, bindings, rows, and timestamps raise
  `FeatureV2ValidationError`.
- Replay is deterministic reevaluation: identical validated features, explicit
  inputs, and explicit UTC `calculated_at` produce identical frozen results and
  ordered evidence. No wall clock participates.
- Modules perform no network, provider, tool, response, orchestration, renderer,
  UI, or recommendation work. They create no intelligence store, manifest,
  pointer, or persisted evidence.
- Evidence uses the closed `EvidenceItem` contract. Missing evidence is omitted.
  Ordering is descending `abs(impact) * confidence`, then evidence code.

## Module and input versions

| Module | Model | Additional versions |
|---|---|---|
| M1 expected minutes | `expected-minutes-v1` | `expected-minutes-hand-tuned-v1`, `availability-input-v1` |
| M2 tactical role | `tactical-role-v1` | `role-map-v2`, `fpl-nominal-position-v1`, `nominal-role-distance-v1` |

M1 semantics remain documented in `FEATURE_CONTRACT.md`; moving its existing
package-contract paragraphs here is deferred documentation debt.

## M2 tactical role and stability

`evaluate_tactical_role` consumes only validated FI-5b v2
`player_role_window_summary` and `player_role_distribution` rows for one exact
fixture, team, and player. Required windows are `last_10`, `last_3`, and the
non-overlapping `prior_7`. Raw canonical formation grids are not a fallback.

The closed roles are `goalkeeper`, `center_back`, `full_back`, `wing_back`,
`central_midfield`, `wide_midfield`, `winger`, and `forward`. Governed
`last_10.modal_role` is authoritative and is checked against the identical
count-descending, role-lexical mode calculation.

At least three mapped observations in `last_10` are required. Public role
shares are mapped-conditional (`role_count / total mapped role count`) and sum
approximately to one. Governed `role_share` remains validated against its FI-5
denominator, `role_count / eligible_starts`; unmapped coverage instead reduces
confidence and emits `partial_role_mapping`.

Role stability is primary-role mapped count divided by total mapped count.
`ROLE_STABLE` requires at least five mapped observations and stability at least
`0.75`. Role change first requires governed comparability, then at least two
mapped observations and a modal role in each of `last_3` and `prior_7`.

### Flank and formation-depth bridges

Store flank `left` maps to `Flank.LEFT`, `right` to `Flank.RIGHT`, and `center`
to public `Flank.CENTRAL`. Flank modes use count descending then public enum
value; a left/right tie selects left.

Formation depth is modal only among rows for the authoritative primary role.
Store `goalkeeper` and `defense` collapse to `FormationDepth.DEEP`, `midfield`
to `FormationDepth.MID`, and `attack` to `FormationDepth.ADVANCED`. FI-6b does
not expose a depth distribution. Deployment is never described as average
position.

### Nominal-position distance

The caller supplies `GK`, `DEF`, `MID`, `FWD`, or absence through
`fpl-nominal-position-v1`; M2 performs no hidden crosswalk. Classes are:

- GK: `goalkeeper`
- DEF: `center_back`, `full_back`, `wing_back`
- MID: `central_midfield`, `wide_midfield`, `winger`
- FWD: `forward`

The outfield axis is DEF=1, MID=2, FWD=3. Compatible classes have distance 0;
adjacent outfield classes 1; DEF/FWD 2; every goalkeeper/outfield comparison
2. `MAX_ROLE_DISTANCE=2`, and the public score is distance divided by two.

| Nominal / role | goalkeeper | center_back | full_back | wing_back | central_midfield | wide_midfield | winger | forward |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GK | 0 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| DEF | 2 | 0 | 0 | 0 | 1 | 1 | 1 | 2 |
| MID | 2 | 1 | 1 | 1 | 0 | 0 | 0 | 1 |
| FWD | 2 | 2 | 2 | 2 | 1 | 1 | 1 | 0 |

This is a coarse classification mismatch, not a calibrated fantasy-value
effect. Missing nominal position preserves tactical output, produces no score
or `OUT_OF_POSITION` evidence, and reduces only its confidence component.

### Evidence and basis

M2 evidence is descriptive and neutral (`impact=0.0`, `direction=neutral`):

- `ROLE_STABLE`: five mapped observations and stability at least `0.75`.
- `ROLE_CHANGED`: a valid comparison with different recent and baseline modes.
- `OUT_OF_POSITION`: score at least `2 / MAX_ROLE_DISTANCE`, so only maximum
  distance emits evidence.

The result and evidence use `observed` only when every contributing summary row
is observed. Any `inferred_proxy` row reduces the basis to `inferred_proxy`,
emits `proxy_role_basis`, and lowers confidence. Formation-grid interpretation
is an inferred proxy; directly governed canonical role facts may be observed.

### Confidence and reasons

One confidence value, clamped to `[0,1]`, is:

- 40% sample quality: `min(mapped_starts / 10, 1)`;
- 25% mapped coverage: `mapped_starts / eligible_starts`;
- 15% build freshness: age 0–24h inclusive = 1.0, >24–72h = 0.8,
  >72–168h = 0.5, and >168h = 0.25;
- 10% evidence basis: observed = 1.0, inferred proxy = 0.6;
- 10% nominal-position availability: present = 1.0, absent = 0.0.

A build timestamp later than `calculated_at` is invalid. Reason codes have fixed
order: `sparse_role_history`, `partial_role_mapping`, `stale_feature_build`,
`proxy_role_basis`, `nominal_position_missing`, `role_change_not_comparable`,
`ambiguous_formation_depth`, `unsupported_oop_mapping`. The last two are
defensive: a lexical depth tie is reported while remaining deterministic; an
absent distance mapping would be reported only if a future supported vocabulary
could not be classified. Unknown current vocabulary fails validation.

FI-6c, FI-6d, and FI-7 remain outside this slice.

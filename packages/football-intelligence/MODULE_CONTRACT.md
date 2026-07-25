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
| M3 fixture context | `fixture-context-v1` | `fixture-priority-v1`, `competition-weights-v1` |
| M4 opponent personnel disruption | `opponent-personnel-disruption-v1` | non-operational skeleton |
| M5 flank matchup | `flank-matchup-v1` | non-operational skeleton |

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

## M3 fixture and rotation context

`evaluate_fixture_context` asks: what governed scheduling, recovery,
competition-stage, standings-band, and fixture-priority context applies to this
team for the target fixture?

M3 is a team-fixture evaluator at `(fixture_id, team_id)` grain. It consumes
only the exact `team_fixture_context_v2` row selected from an explicit,
validated FI-5b v2 feature build. It does not consume M1 or M2 results. Future
FI-7 composition may place one M3 team result beside multiple player-scoped M1
and M2 results without duplicating M3 computation; that work is outside FI-6c.

FI-6c requires zero FI-5 changes. It does not alter the feature registry,
engine, store, schemas, manifests, builders, pointers, canonical sources,
cutoff policy, or feature tests. Any requirement for such a change stops FI-6c
for another architecture review.

M3 reports only feature-backed schedule context. It does not produce player
rotation probability, late-cameo risk, manager-tendency inference, opponent
difficulty, FDR, fixture outlook, recommendations, or selection conclusions.
The term rotation context is descriptive; it is not a player-selection model.

### Input and public result

The governed M3 row provides weighted trailing and leading congestion over
their existing 21-day windows; corresponding fixture counts; previous and next
rest days; target competition tier and stage; league-position band; schedule
and standings audit timestamps; `competition-weights-v1`; and feature,
canonical, and context-build provenance.

The frozen result exposes the inherited module status, versions, feature-build
reference, fixture/team IDs, confidence, reasons, and evidence plus:

- explicit UTC `calculated_at`;
- fixture priority and `fixture-priority-v1`;
- combined congestion index and both governed directional weighted values;
- previous and next rest days;
- target competition tier and stage;
- league-position band;
- competition-weight version;
- schedule and standings as-of timestamps.

Cutoff, raw counts, feature `built_at`, and source manifest hashes remain
internal evaluator inputs. The merged dataset has no competition ID, season ID,
standings-table ID, or schedule-snapshot ID, and M3 does not invent them.

### Fixture priority

Priority is a deterministic team-motivation or rotation-incentive context. It
is not fixture difficulty. The closed ordered vocabulary is `normal`, `high`,
and `critical`, plus non-rankable `unknown`; there is no `low`. Competition
tier is descriptive and already affects FI-5 congestion weights, but it never
affects fixture priority.

| League band / stage | league | qualification | group | league_phase | round_of_32 | round_of_16 | quarter_final | semi_final | final | replay | unknown |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `top` | critical | normal | normal | normal | normal | high | high | critical | critical | high | unknown |
| `upper_mid` | normal | normal | normal | normal | normal | high | high | critical | critical | high | unknown |
| `lower_mid` | normal | normal | normal | normal | normal | high | high | critical | critical | high | unknown |
| `bottom` | critical | normal | normal | normal | normal | high | high | critical | critical | high | unknown |
| `unknown` | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown |

Unknown band or stage is not silently treated as ordinary priority; it causes
`missing_context`. A null target tier does likewise. Literal tier `"unknown"`
is valid because it records a selected schedule fact whose tier was unknown.

### Congestion and rest

The public congestion index is:

```text
weighted_trailing_congestion_21d + weighted_leading_congestion_21d
```

Higher values mean more surrounding scheduling load. M3 neither reloads
fixtures nor recomputes weights. Both values are finite and nonnegative, and
for each direction `count <= weighted <= 1.25 * count`; zero count therefore
requires zero weight. No separate global maximum is invented.

Previous and next rest days retain their direction. A non-null value is within
`(0, 365]`. Either or both may be null at a season boundary while the result
remains `ok`; null rest reduces context-completeness confidence but does not
fabricate missing context or opponent-relative advantage.

### Missing context and typed failures

An absent build, absent manifest, or absent exact target row returns
`missing_context`. Unknown league band, unknown stage, or null target tier also
returns `missing_context`. Such a result has confidence zero, exactly one
reason, empty evidence, and no partial priority, congestion, rest, or context
output.

Zero trailing or leading counts and null rest anchors are valid facts.
Malformed supported-v2 artifacts raise `FeatureV2ValidationError`; corruption
never degrades. Unsupported feature family, manifest schema, registry, engine,
cutoff policy, or competition-weight version raises
`UnsupportedFeatureContractError`. The loader performs minimal dispatch,
invokes the complete FI-5b v2 store validator, and then enforces only M3
selection and semantic invariants. It performs no pointer discovery, migration,
canonical/provider fallback, or M1/M2 fallback.

### Context-completeness confidence

Confidence measures context completeness, not predictive or rotation accuracy:

- 50% build freshness: age through 24h = 1.0, over 24h through 72h = 0.8,
  over 72h through 168h = 0.5, and over 168h = 0.25;
- 30% schedule coverage:
  `min((trailing_count + leading_count) / 6, 1)`;
- 10% previous-rest-anchor availability;
- 10% next-rest-anchor availability.

The total is clamped to `[0,1]` and rounded once to four decimal places. A
future feature build is invalid and is never clamped. Six is a hand-tuned v1
full-sample reference across the combined 42-day surrounding windows and must
be backtested before predictive interpretation.

### Reasons and evidence

The exact reason order is:

1. `feature_build_unavailable`
2. `feature_manifest_unavailable`
3. `fixture_context_row_unavailable`
4. `unknown_league_position_band`
5. `unknown_competition_stage`
6. `target_competition_tier_unavailable`
7. `stale_feature_build`
8. `sparse_trailing_schedule`
9. `sparse_leading_schedule`
10. `previous_rest_anchor_unavailable`
11. `next_rest_anchor_unavailable`
12. `fixture_congestion`

Missing-context results emit exactly one of the first six. Operational results
emit applicable later reasons in the listed order. A schedule direction is
sparse at fewer than three fixtures. A build is stale after 72 hours.

`FIXTURE_CONGESTION` is emitted exactly when the combined index is at least
`7.0`. It is a neutral (`impact=0.0`, direction neutral), observed, team-subject
fact for the target fixture. Its ordered source features are trailing then
leading weighted congestion, and its summary says only that the team has a
dense governed schedule surrounding the target fixture. Evidence confidence
equals result confidence. M3 emits no `REST_ADVANTAGE`, because no opponent row
is loaded. The immutable evidence tuple has maximum length one.

Replay is deterministic reevaluation: identical validated FI-5b v2 features
and identical explicit `calculated_at` produce an identical frozen result,
reason order, and evidence. M3 performs no network, provider, tool, response,
orchestration, UI, recommendation, persistence, manifest, or pointer work.

## M4 opponent personnel disruption skeleton

`evaluate_opponent_personnel_disruption` reserves the stable public M4 surface
without implementing opponent-personnel analysis. In FI-6d it is mechanically
non-operational and always returns:

```text
status = not_implemented
model_version = opponent-personnel-disruption-v1
feature_registry_version = null
feature_build_id = null
confidence = 0.0
reason_codes = (not_implemented,)
evidence = ()
```

The frozen `OpponentPersonnelDisruptionInput` contains only `fixture_id`,
`team_id`, and explicit UTC `calculated_at`. The frozen
`OpponentPersonnelDisruptionResult` adds no fields to `ModuleResult`.
In particular, FI-6d exposes no affected-unit, affected-flank, missing-starter,
replacement, formation-change, disruption-score, or benefiting-player output,
even as a null default.

M4 has no feature loader and never returns `missing_context`. It does not read
feature builds, registries, manifests, pointers, stores, parquet, canonical
ingestion, provider data, the network, the filesystem, or a wall clock. It has
no M1, M2, or M3 dependency and makes no FI-5 change. It emits no
`OPPONENT_UNIT_DISRUPTION` evidence, prediction, FDR, recommendation, tool,
response, orchestration, renderer, or UI output.

The filename `opponent_disruption.py` follows the implementation-plan mandate.
The evaluator and types retain the governed product/API term “opponent
personnel disruption” so their public names remain stable if a future active
evaluator graduates. That graduation is a separate, trial-gated architecture
slice and is not part of FI-6d.

## M5 flank matchup skeleton

`evaluate_flank_matchup` reserves the stable player-grain M5 surface without
implementing flank inference, zonal logic, or opponent matching. Model version
`flank-matchup-v1` is mechanically non-operational: every valid input returns
`not_implemented`, confidence `0.0`, feature registry and build metadata set to
null, reason codes `(not_implemented,)`, and empty evidence.

The frozen input contains only `fixture_id`, `team_id`, `player_id`, and an
explicit UTC `calculated_at`. The frozen result adds only `player_id` to
`ModuleResult`. It has no active outputs, including nullable placeholders, and
no feature family, feature loader, provider, predecessor-module, zonal-engine,
network, persistence, or wall-clock dependency.

The reserved `OPPONENT_FLANK_WEAKNESS` evidence code is not imported or emitted.
Graduation to an active evaluator is a separate, trial-gated architecture
slice pending M4 graduation, zonal integration, and Understat/Sportmonks trial.
FI-7 remains blocked and is not begun by this skeleton.

FI-6a through FI-6d are merged and complete. FI-6e implements only the M5
skeleton described above.

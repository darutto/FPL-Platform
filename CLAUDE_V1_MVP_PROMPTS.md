# Claude Prompt Pack — V1 MVP Wave

This file contains ready-to-send Claude prompts for the refined V1 MVP roadmap after Phase 6d.

Recommended execution order:

1. `7a` — Structured transfer metadata
2. `7b` — Structured chip metadata
3. `7c` — Transfer + chip debug/example parity
4. `7f` — Transfer follow-up resolution
5. `7h` — Player fixture run intent
6. `7g` — Differential picks intent
7. `7j` — Validation corpus V2 refresh and final gate

---

## Phase 7a — Structured Transfer Metadata

```text
Feedback on the current state:

Transfer advice is now a real deterministic capability, but it still remains text-first.
That means standalone transfer advice has no structured metadata payload, and multi-intent sub_responses cannot expose transfer metadata either.

Approve the next slice as Phase 7a: Structured Transfer Metadata.

Context:
Captain, ranked captain, and comparison already expose bounded structured metadata.
Transfer advice is the main remaining advice-family gap in the stable response contract.

Goals:
1. Add an optional structured transfer field for successful `transfer_advice` responses only.
2. Keep the change additive and backward-compatible.
3. Expose only bounded deterministic transfer metadata, likely including:
   - player_out identity
   - player_in identity
   - recommendation
   - score_delta
   - price_delta only if already grounded and stable
   - reason phrases only if already stable enough to expose safely
4. Preserve plain-text final_text behavior.
5. Keep non-transfer and unsuccessful turns unchanged.
6. Ensure multi-intent sub_responses can later expose the same transfer metadata through the shared response shape.
7. Keep deterministic backend authority unchanged.
8. Keep LLMs out of transfer reasoning.
9. Do not add auth, persistence, UI work, or broader squad-planning behavior.

Suggested implementation direction:
1. Extend the existing final response contract with an optional TransferMeta rather than inventing a parallel schema.
2. Keep the TransferMeta object small and explicit.
3. Populate it only when intent is `transfer_advice` and outcome is `ok`.
4. Keep it null or absent for non-transfer and unsuccessful turns.
5. Align HTTP ask, session ask, and CLI debug serialization around the same shape.
6. Update contract docs if the stable caller-facing contract changes.

Deliverables:
- files created or modified
- additive structured transfer metadata support
- tests or validator coverage
- validation corpus updates if appropriate
- PACKAGE_STATUS.md update only if caller-facing behavior changed materially
- orchestrator-instructions.md update because capability/contract state will change materially
- short end-of-slice handoff summary

Please report exactly:
- what structured transfer fields are exposed
- whether the final response contract changed, and how
- whether HTTP ask, session ask, and CLI debug changed, and how
- whether multi-intent sub_responses can now expose transfer metadata
- whether CLI non-debug output changed
- what remained intentionally deferred

Success criteria:
- successful transfer-advice turns expose bounded structured metadata
- existing callers remain backward-compatible
- deterministic transfer authority remains unchanged
- no broader squad-planning behavior is introduced
```

---

## Phase 7b — Structured Chip Metadata

```text
Feedback on the current state:

Chip advice is now a deterministic capability, but it still remains text-first like transfer advice.
To make the core advice families coherent for developers, chip advice should expose bounded structured metadata the same way captain, comparison, and transfer do.

Approve the next slice as Phase 7b: Structured Chip Metadata.

Context:
Chip advice now supports triple captain, wildcard, bench boost, and free hit with explicit deterministic recommendation outputs.
The next useful step is to expose those grounded outputs in a stable structured form for programmatic callers.

Goals:
1. Add an optional structured chip field for successful `chip_advice` responses only.
2. Keep the change additive and backward-compatible.
3. Expose only bounded deterministic chip metadata, likely including:
   - chip
   - recommendation
   - current gameweek where relevant
   - a bounded supporting signal appropriate to that chip
4. Preserve plain-text final_text behavior.
5. Keep non-chip and unsuccessful turns unchanged.
6. Keep deterministic backend authority unchanged.
7. Do not imply DGW/BGW support that does not exist yet.
8. Do not add auth, persistence, UI work, or open-ended strategy behavior.

Suggested implementation direction:
1. Extend the existing final response contract with an optional ChipAdviceMeta.
2. Keep the object small and explicit.
3. Populate it only when intent is `chip_advice` and outcome is `ok`.
4. Keep it null or absent for non-chip and unsuccessful turns.
5. Align HTTP ask, session ask, and CLI debug serialization around the same shape.
6. Update contract docs if the stable caller-facing contract changes.

Deliverables:
- files created or modified
- additive structured chip metadata support
- tests or validator coverage
- validation corpus updates if appropriate
- PACKAGE_STATUS.md update only if caller-facing behavior changed materially
- orchestrator-instructions.md update because capability/contract state will change materially
- short end-of-slice handoff summary

Please report exactly:
- what structured chip fields are exposed
- whether the final response contract changed, and how
- whether HTTP ask, session ask, and CLI debug changed, and how
- whether CLI non-debug output changed
- what remained intentionally deferred

Success criteria:
- successful chip-advice turns expose bounded structured metadata
- existing callers remain backward-compatible
- deterministic chip authority remains unchanged
- no unsupported strategic behavior is introduced
```

---

## Phase 7c — Transfer + Chip Debug and Example Parity

```text
Feedback on the current state:

Transfer and chip metadata now exist as structured caller-facing fields.
The next useful step is to give them the same debug/example parity already established for captain and comparison.

Approve the next slice as Phase 7c: Transfer + Chip Debug and Example Parity.

Context:
Captain, ranked captain, comparison, transfer, and chip should now all have coherent structured surfaces.
This slice should close the documentation and example parity loop without changing underlying logic.

Goals:
1. Add transfer and chip example parity across:
   - CLI debug examples
   - stateless HTTP examples
   - session examples
2. Keep default CLI behavior unchanged and text-first.
3. Make absence behavior explicit on non-transfer and non-chip turns.
4. Reuse the real production serialization shape rather than inventing example-only payloads.
5. Avoid production logic changes unless a very small serialization fix is strictly required.

Deliverables:
- files created or modified
- transfer and chip example updates
- tests or validator coverage
- PACKAGE_STATUS.md update only if caller-facing behavior changed materially
- orchestrator-instructions.md update only if capability/contract state changed materially
- short end-of-slice handoff summary

Please report exactly:
- what transfer examples were added or changed
- what chip examples were added or changed
- whether any stable caller-facing contract changed
- whether CLI debug, /ask, and /session examples now all cover transfer and chip behavior
- what remained intentionally deferred

Success criteria:
- transfer and chip behavior are demonstrated consistently across example surfaces
- examples reflect the real product behavior accurately
- no new contract claims are introduced
- no logic regressions are introduced
```

---

## Phase 7f — Transfer Follow-up Resolution

```text
Feedback on the current state:

Comparison follow-up exists, but transfer follow-up does not.
That asymmetry makes the session experience feel incomplete once transfer advice exists as a first-class deterministic capability.

Approve the next slice as Phase 7f: Transfer Follow-up Resolution.

Context:
Transfer advice already supports bounded two-player transfer prompts.
The next useful step is to support narrow deterministic follow-up patterns after a transfer turn, similar in spirit to comparison follow-up but simpler.

Goals:
1. Add deterministic-only transfer follow-up resolution for common patterns such as:
   - what about Palmer instead?
   - how about Palmer?
   - Palmer instead?
2. Preserve deterministic backend authority.
3. Store enough session state to rewrite the follow-up into a canonical transfer query.
4. Keep the resolver bounded and auditable.
5. Do not add LLM fallback in V1.
6. Do not broaden into squad-planning behavior.
7. Keep CLI, stateless HTTP, and session behavior consistent where session context exists.

Suggested implementation direction:
1. Add `last_transfer` session state storing the last `(player_out, player_in)` pair for successful transfer turns.
2. Add a deterministic resolver that rewrites successful follow-ups to a canonical transfer query like `sell {last_transfer_out} for {new_player}`.
3. Expose a clear resolver source for debug or audit surfaces only if consistent with existing patterns.
4. Fall back safely when no transfer context exists or no follow-up pattern matches.

Deliverables:
- files created or modified
- deterministic transfer follow-up resolution
- tests or validator coverage
- validation corpus updates if appropriate
- PACKAGE_STATUS.md update only if caller-facing behavior changed materially
- orchestrator-instructions.md update because capability/contract state will change materially
- short end-of-slice handoff summary

Please report exactly:
- what transfer follow-up patterns are supported
- what session state was added or changed
- whether any stable caller-facing contract changed
- how fallback behaves when no transfer context exists
- what remained intentionally deferred

Success criteria:
- common deterministic transfer follow-ups work in session flows
- no LLM is required for V1 transfer follow-up behavior
- existing comparison and session behavior do not regress
- unsupported follow-ups remain explicit and safe
```

---

## Phase 7h — Player Fixture Run Intent

```text
Feedback on the current state:

The platform still lacks a deterministic answer for a very common developer-facing question: upcoming fixtures for a given player.
This is a good next intent because it is retrieval-oriented, grounded, and lower-risk than a recommendation-heavy expansion.

Approve the next slice as Phase 7h: Player Fixture Run Intent.

Context:
Bootstrap already contains the ingredients needed for a grounded fixture-run response.
This slice should add a deterministic retrieval intent, not an editorial prediction layer.

Goals:
1. Add a new deterministic intent for prompts such as:
   - Haaland fixtures
   - Salah next 5 games
   - upcoming fixtures for Palmer
2. Resolve the player deterministically.
3. Return a bounded upcoming fixture run using already-grounded data.
4. Keep the result explicit and retrieval-oriented.
5. Keep CLI, HTTP, and session flows consistent.
6. Do not broaden into predictive fixture commentary or long-horizon planning.

Suggested implementation direction:
1. Add a new `player_fixture_run` intent.
2. Use existing player resolution and grounded fixture data.
3. Choose a deterministic default horizon, likely 5.
4. If structured metadata is helpful, add a bounded FixtureRunMeta rather than a loose dict.
5. Keep unsupported or not-found behavior explicit.

Deliverables:
- files created or modified
- new deterministic fixture-run capability
- tests or validator coverage
- validation corpus updates if appropriate
- PACKAGE_STATUS.md update if caller-facing capability changed materially
- orchestrator-instructions.md update because capability/contract state will change materially
- short end-of-slice handoff summary

Please report exactly:
- what deterministic fixture data is used
- what default horizon is used
- what prompts are now supported
- whether any stable caller-facing contract changed
- how CLI, stateless HTTP, and session flows were validated
- what remained intentionally deferred

Success criteria:
- common fixture-run prompts are now supported deterministically
- behavior is explicit, grounded, and consistent across surfaces
- no predictive or open-ended reasoning is introduced
```

---

## Phase 7g — Differential Picks Intent

```text
Feedback on the current state:

The platform still lacks a deterministic answer for another common developer-facing question: differential picks.
This is higher-value than many polish slices, but it needs careful grounding so it does not drift into vague recommendation logic.

Approve the next slice as Phase 7g: Differential Picks Intent.

Context:
Bootstrap already contains selected_by_percent and the captain engine already provides a grounded scoring path.
This slice should use those deterministic ingredients to surface a bounded differential-picks capability.

Goals:
1. Add a deterministic intent for prompts such as:
   - good differentials
   - differential options
   - low-ownership picks
2. Define deterministic defaults up front for:
   - ownership threshold
   - top_n
3. Filter candidates by low ownership using grounded bootstrap data.
4. Rank the filtered candidates using an existing grounded scoring path.
5. Return a bounded result with clear reasons or ranking signals where appropriate.
6. Keep CLI, HTTP, and session flows consistent.
7. Do not broaden into open-ended transfer-planning or squad-building behavior.

Suggested implementation direction:
1. Add a new `differential_picks` intent.
2. Use explicit deterministic defaults rather than caller-configurable knobs unless the existing request model supports that cleanly.
3. If structured metadata is useful, expose a bounded DifferentialMeta with entries rather than a loose list.
4. Keep the output concise and grounded.
5. Preserve explicit unsupported behavior for phrasings outside the narrow scope.

Deliverables:
- files created or modified
- new deterministic differential-picks capability
- tests or validator coverage
- validation corpus updates if appropriate
- PACKAGE_STATUS.md update if caller-facing capability changed materially
- orchestrator-instructions.md update because capability/contract state will change materially
- short end-of-slice handoff summary

Please report exactly:
- what ownership threshold and top_n defaults were chosen
- what deterministic signals are used for ranking
- what prompts are now supported
- whether any stable caller-facing contract changed
- how CLI, stateless HTTP, and session flows were validated
- what remained intentionally deferred

Success criteria:
- common differential prompts are now supported deterministically
- ranking logic is explicit and grounded
- behavior is consistent across surfaces
- no broader strategy behavior is introduced
```

---

## Phase 7j — Validation Corpus V2

```text
Feedback on the current state:

The MVP wave adds new structured surfaces, follow-up behavior, and new deterministic intents.
Before calling the wave complete, the validation baseline needs to be refreshed so the platform can be trusted as a coherent developer-facing API.

Approve the next slice as Phase 7j: Validation Corpus V2.

Context:
Validation should be treated as a rolling asset throughout this wave, but this phase is the final sweep and gate for V1.
It should consolidate all added coverage into an updated readable corpus and refreshed artifacts.

Goals:
1. Refresh the validation corpus to cover:
   - structured transfer metadata
   - structured chip metadata
   - transfer follow-up behavior
   - player fixture run intent
   - differential picks intent
2. Keep the corpus readable and inspectable by a human.
3. Keep cross-surface parity checks explicit.
4. Regenerate machine-readable and human-readable validation artifacts.
5. Preserve the existing principle of asserting semantics and contracts, not exact prose.

Suggested implementation direction:
1. Add scenarios incrementally as needed, then use this phase as the normalization and reporting sweep.
2. Keep surface-specific exceptions explicit instead of hiding them.
3. Refresh validation_results.json and validation_report.md.
4. Update any count guards conservatively so they remain additive rather than brittle.

Deliverables:
- files created or modified
- validation corpus V2 refresh
- updated smoke runner support if needed
- updated machine-readable validation artifact
- updated human-readable validation report
- tests or validator coverage
- PACKAGE_STATUS.md update only if caller-facing capability changed materially
- orchestrator-instructions.md update because roadmap and capability state will change materially
- short end-of-slice handoff summary

Please report exactly:
- what new scenario families were added
- what artifacts were refreshed
- what parity rules are enforced
- whether any production code had to change, and why
- what remained intentionally deferred

Success criteria:
- the V2 corpus covers all MVP additions
- the artifacts are useful to a human, not just a pass counter
- cross-surface parity remains trustworthy
- the wave can be treated as a coherent V1 gate
```

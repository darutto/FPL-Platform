# FPL Platform V1 MVP Roadmap

## Purpose

This document defines the refined V1 MVP roadmap after Phase 6d.

For this platform, V1 MVP does **not** mean maximum feature count.
It means:

> The platform is internally consistent, the core deterministic advice intents expose coherent caller-facing contracts, and a developer can build reliably on top of the API without needing to understand the phase history.

The V1 bar is therefore:
- contract coherence
- deterministic grounding
- cross-surface consistency
- bounded follow-up symmetry where users already expect it
- validation evidence that is readable by humans and reliable for regressions

## Current MVP Blockers

Three gaps prevent the platform from feeling coherent to an API caller:

| Gap | Why it blocks V1 |
|---|---|
| Transfer and chip are still text-first | Captain and comparison already expose structured metadata. Transfer and chip should be symmetric for successful turns. |
| Transfer has no follow-up symmetry | Comparison follow-up exists in sessions. Transfer advice still behaves differently for a similar conversational pattern. |
| Common FPL asks still miss deterministic support | Differential picks and player fixture run are common developer-facing needs and currently leave obvious coverage gaps. |

## V1 MVP Scope

### Included slices

The recommended MVP cut is:

1. `7a` — Structured transfer metadata
2. `7b` — Structured chip metadata
3. `7c` — Transfer + chip debug/example parity
4. `7f` — Transfer follow-up resolution
5. `7h` — Player fixture run intent
6. `7g` — Differential picks intent
7. `7j` — Validation corpus V2 refresh and final gate

### Why this order

This order is optimized for V1 coherence rather than raw feature count:

1. `7a -> 7b -> 7c`
Reason: finish metadata and parity for the four core advice families first.

2. `7f`
Reason: close the biggest remaining session UX asymmetry.

3. `7h`
Reason: add a low-risk deterministic retrieval intent before a more recommendation-like one.

4. `7g`
Reason: add a high-value recommendation intent once the contract pattern is already stable.

5. `7j`
Reason: finalize the wave with refreshed validation evidence across all newly added or expanded capabilities.

## Explicitly Deferred Post-MVP

These are valuable, but they are not V1 blockers:

| Slice | Why deferred |
|---|---|
| `7d` Multi-intent conjunction extension | `and` already covers the main path; `also` and `plus` are useful but non-essential. |
| `7e` Multi-intent session state integration | Current behavior is explicit and documented, so it is not a coherence blocker. |
| `7i` DGW/BGW detection | Free hit returning `missing_context` is an acceptable V1 limitation if documented clearly. |

Also still deferred:
- squad context such as ITB, budget, chip availability, or team composition
- multi-transfer planning
- multi-player comparison beyond 2 players
- persistence, auth, or multi-worker-safe session infrastructure
- open-ended football reasoning from model memory
- frontend-heavy work

## V1 Done Criteria

V1 should be considered done when the following are all true:

1. Successful turns for the four main advice families expose coherent structured metadata:
   - captain
   - captain_ranking
   - comparison
   - transfer
   - chip

2. Multi-intent sub-responses expose relevant bounded structured metadata where applicable.

3. Comparison and transfer both support bounded follow-up behavior in session flows.

4. Differential picks and player fixture run are available as deterministic intents.

5. CLI, stateless HTTP, and session HTTP remain contract-consistent.

6. Validation corpus V2 passes and is readable enough to serve as a human inspection gate.

## Slice Notes

### 7a — Structured Transfer Metadata

Add `TransferMeta` to the stable response contract for successful `transfer_advice` turns.

Target shape should stay bounded and likely include:
- player_out identity
- player_in identity
- recommendation
- score_delta
- price_delta if already grounded and stable
- reasons only if they are already stable enough to expose without churn

Key rule:
- no new transfer reasoning logic in this slice

### 7b — Structured Chip Metadata

Add `ChipAdviceMeta` to the stable response contract for successful `chip_advice` turns.

Target shape should stay bounded and likely include:
- chip
- recommendation
- relevant deterministic supporting signal
- current gameweek where appropriate

Key rule:
- do not imply DGW/BGW support that does not yet exist

### 7c — Transfer + Chip Debug And Example Parity

Close the parity loop once metadata exists.

Expected outputs:
- CLI debug examples
- HTTP examples
- session examples
- explicit absence behavior on non-transfer and non-chip turns

Key rule:
- no logic changes unless required for serialization alignment

### 7f — Transfer Follow-up Resolution

Mirror comparison follow-up with a deterministic-only first version.

Likely supported patterns:
- what about Palmer instead?
- how about Palmer?
- Palmer instead?

Expected rewrite shape:
- `sell {last_transfer_out} for {new_player}`

Key rules:
- deterministic-only for V1
- no LLM fallback required for MVP

### 7h — Player Fixture Run Intent

Add a deterministic fixture-run retrieval intent.

Likely prompt families:
- Haaland fixtures
- Salah next 5 games
- upcoming fixtures for Palmer

Likely defaults:
- fixed horizon, probably 5 fixtures or 5 gameweeks

Key rule:
- keep it retrieval-oriented and explicit, not editorial

### 7g — Differential Picks Intent

Add a deterministic differential recommendation intent.

Likely prompt families:
- good differentials
- differential options
- low-ownership picks

Defaults should be decided before implementation:
- ownership threshold
- top_n

Key rule:
- keep the ranking logic simple and explicit so it remains grounded and debatable in a healthy way

### 7j — Validation Corpus V2

Refresh the validation baseline after the MVP slices land.

Recommended approach:
- update the corpus incrementally as 7a, 7b, 7f, 7h, and 7g land
- use 7j as the final normalization and reporting sweep

Expected artifacts:
- updated corpus
- updated machine-readable results
- updated human-readable report

Key rule:
- this should be the final MVP gate, not just another pass counter

## Recommended Working Principles For This Wave

1. Favor additive contract changes.
2. Keep new metadata bounded and explicit.
3. Do not expand deterministic signals casually once a recommendation path exists.
4. Prefer symmetry only where it improves caller trust and consistency.
5. Keep LLMs out of football reasoning.
6. Update the handoff summary as each slice materially changes capability or contract state.

# fpl-grounded-assistant · Final Response Contract

*Phase 3d. Canonical reference for the stable caller-facing ``respond()`` /
``FinalResponse`` surface.*

---

## Purpose

This document defines the **stable public contract** for ``respond()``, the
outermost entrypoint of the fpl-grounded-assistant stack.

External callers (UI layers, API handlers, evaluation harnesses) should rely
only on the fields and invariants described here.  Internal fields in
``FinalResponseDebug`` are explicitly **not** part of this contract.

See ``CONTRACT.md`` for the lower-level ``adapt()`` / ``AdapterResponse``
contract (Phase 2m).

For machine-readable HTTP request/response fixtures (V2 Phase 1f), see
``http_contract_fixtures.json`` at the package root.  That file is the
canonical source of truth for downstream consumers building against the
HTTP API.  It covers ``POST /ask`` and ``POST /session/{id}/ask`` request
shapes, response invariants with stability annotations, and ``intent_hint``
contract invariants in one self-contained artifact.

---

## Interface Hierarchy

```
respond()                    ← caller-facing entrypoint  (Phase 3c)  ← THIS DOCUMENT
  └── ask_llm_safe()         ← review gate               (Phase 3b)
        └── ask_llm()        ← LLM presentation          (Phase 3a)
              └── adapt()    ← deterministic adapter     (Phase 2m)
                    └── dispatch()    ← dispatcher       (Phase 2k/2l)
                          └── ask()  ← grounded harness  (Phase 1h)
```

All routing and scoring is **deterministic** — no LLM calls affect
``outcome``, ``supported``, ``intent``, or the structured ``raw_output``.
The LLM layer is limited to phrasing presentation of the grounded result;
it never alters backend semantics.

---

## `respond()` — Primary Entrypoint

```python
from fpl_grounded_assistant import respond, FinalResponse

response: FinalResponse = respond(
    user_message,              # str        — raw user question
    bootstrap,                 # dict       — FPL bootstrap or assembled context
    *,
    client=None,               # Anthropic|None  — pre-built API client
    model=DEFAULT_MODEL,       # str        — Anthropic model identifier
    candidate_inputs=None,     # dict|None  — scoring overrides for captain_score
    candidates_list=None,      # list|None  — candidates for rank_candidates
    api_key=None,              # str|None   — explicit API key
    include_debug=False,       # bool       — opt-in debug bundle
    squad_context=None,        # dict|None  — optional per-turn squad state (Phase 8e1)
    intent_hint=None,          # str|None   — optional slash-command routing bias (V2 Phase 1c)
)
```

**Guarantees:**
- Never raises — all failure cases return a valid ``FinalResponse``
- ``final_text`` is always non-empty
- ``outcome`` is always one of the six ``OUTCOME_*`` constants
- ``supported`` is always ``(outcome != OUTCOME_UNSUPPORTED_INTENT)``
- ``llm_used=True`` iff an LLM API call was made AND the returned text passed
  the deterministic parity review
- ``debug`` is ``None`` unless ``include_debug=True`` is passed explicitly

---

## `intent_hint` — Optional Routing Bias (V2 Phase 1c)

``intent_hint`` is an optional ``str | None`` parameter that lets callers nudge
the routing layer toward a specific intent when the deterministic router returns
``None`` for the user's question.

### Semantics

| Property | Behaviour |
|----------|-----------|
| **Deterministic router wins** | If ``route(question)`` succeeds, ``intent_hint`` is completely ignored. The hint only fires on router miss. |
| **Allowlisted values** | Only the 7 values in ``INTENT_HINT_ALLOWLIST`` are honoured. Any other value is silently ignored (safe fallback — unsupported intent outcome). |
| **Canonical synthesis** | The hint fires by synthesising a canonical routeable question from a per-intent template (e.g. ``"should I captain {question}"`` for ``captain_score``). The synthesised question is passed to ``route()``; if that also misses, the hint has no effect. |
| **Pre-classifier / provider-neutral** | ``intent_hint`` is a pre-classifier bias — it fires before the LLM classifier without any LLM call. It does not invoke the LLM classifier. No provider identity is part of the public contract. |
| **No new intents** | ``intent_hint`` can only target intents that the deterministic router already understands. It is not a mechanism for adding new intents. |
| **``classification_source``** | Set to ``"intent_hint"`` on the ``DispatchResult`` when the hint fires. ``None`` for deterministic routing. ``"llm_classifier"`` when the LLM fallback fires. |

### Allowlisted values

```
captain_score       differential_picks
rank_candidates     player_fixture_run
compare_players     chip_advice
transfer_advice
```

### Examples

```python
# Valid hint — "Haaland" alone doesn't route; hint synthesises "should I captain Haaland"
r = respond("Haaland", bootstrap, intent_hint="captain_score")
# r.intent == "captain_score", r.outcome == "ok"

# Deterministic router wins — hint is ignored
r = respond("should I captain Salah", bootstrap, intent_hint="compare_players")
# r.intent == "captain_score"  (deterministic route took precedence)

# Invalid hint — silently ignored; question falls through to unsupported_intent
r = respond("Haaland", bootstrap, intent_hint="not_a_real_intent")
# r.supported == False, r.outcome == "unsupported_intent"
```

---

## `FinalResponse` — Stable Caller-Facing Contract

Frozen dataclass.

### Stable caller-facing fields

| Field | Type | Stability | Description |
|-------|------|-----------|-------------|
| `final_text` | `str` | **Stable** | The text to surface to the user. Non-empty. Policy: `llm_text` when `llm_used=True`; `response_text` otherwise. |
| `outcome` | `str` | **Stable** | One of the six `OUTCOME_*` constants. Use for routing decisions. |
| `supported` | `bool` | **Stable** | `True` if intent was within supported scope; `False` only for `unsupported_intent`. |
| `intent` | `str` | **Stable** | One of the `INTENT_*` constants. Useful for logging and analytics. |
| `review_passed` | `bool` | **Stable** | Whether the LLM text passed deterministic parity checks. `False` → `final_text` is the deterministic fallback. |
| `llm_used` | `bool` | **Stable** | Whether LLM-generated text appears in `final_text`. `True` iff `llm_called AND review_passed`. |
| `debug` | `FinalResponseDebug\|None` | **Stable shape; debug-only content** | `None` by default. Opt-in with `include_debug=True`. |
| `comparison` | `ComparisonMeta\|None` | **Stable (Phase 5g)** | Populated for `compare_players` OK turns. `None` for all other intents and non-OK outcomes. Provides structured access to `winner`, `margin`, `label`, `reasons` without parsing `final_text`. |
| `captain` | `CaptainScoreMeta\|None` | **Stable (Phase 5n)** | Populated for `captain_score` OK turns. `None` otherwise. Provides structured access to `web_name`, `team_short`, `captain_score`, `tier`, `role_bonus`, `set_piece_notes`. |
| `captain_ranking` | `tuple[RankedCaptainEntry,...]\|None` | **Stable (Phase 5p)** | Populated for `rank_candidates` OK turns. `None` otherwise. Tuple of ranked entries ordered by captain score descending. |
| `sub_responses` | `tuple[FinalResponse,...]\|None` | **Stable (Phase 6c)** | Populated for `multi_intent` turns. `None` for single-intent turns. Each entry is a full `FinalResponse` for one independently-resolved sub-question. |
| `transfer` | `TransferMeta\|None` | **Stable (Phase 7a)** | Populated for `transfer_advice` OK turns. `None` for all other intents and non-OK outcomes. Provides structured access to `player_out`, `player_in`, `recommendation`, `score_delta`, `price_delta`, `reasons`. |
| `chip` | `ChipAdviceMeta\|None` | **Stable (Phase 7b)** | Populated for `chip_advice` OK turns. `None` for all other intents and non-OK outcomes. Provides structured access to `chip`, `recommendation`, `gw`, `signal_value`, `signal_label`. |
| `fixture_run` | `FixtureRunMeta\|None` | **Stable (Phase 7h)** | Populated for `player_fixture_run` OK turns. `None` for all other intents and non-OK outcomes. Provides structured access to `web_name`, `team_short`, `position`, `horizon`, `current_gameweek`, `fixtures`. |
| `differential` | `DifferentialPicksMeta\|None` | **Stable (Phase 7g)** | Populated for `differential_picks` OK turns. `None` for all other intents and non-OK outcomes. Provides structured access to `ownership_threshold`, `top_n`, `picks`. |
| `orch_outcome` | `str\|None` | **Stable (Orch-4c)** | Orchestration audit field. `None` when orchestration was not attempted (orch flag OFF or `_multi_intent_depth > 0`). `"ok"` when orchestrator succeeded and its answer was used. One of six non-OK strings when orchestrator was attempted but fell back to the deterministic path. **Independent of `outcome`** — `outcome` always reflects the deterministic result, regardless of orch state. |

### Field shape stability commitment

The names and types of all non-debug fields above are considered a
**stable external contract**.  Any future change to their names, types, or
semantics is treated as a **breaking change** and must be documented
explicitly with a phase label.

---

## Phase 8a1 — Position-Aware Heuristic Evaluation (Three-Layer Architecture)

**Added in Phase 8a1.** Replaces the Phase 8a additive `position_bias` with a
cleaner position-aware heuristic layer. This is explicitly a **heuristic
scaffold for future ML**, not a final predictive model.

### Three-layer scoring architecture

| Layer | Name | Purpose | Status |
|-------|------|---------|--------|
| 1 | `captain_score` | Canonical formula — regression baseline, explainable, frozen | Stable (never modified) |
| 2 | `position_score` | Position-aware heuristic — operational scoring for comparisons, transfers, differentials | This phase |
| 3 | Future ML | Learned weights from historical outcome data | Deferred — requires backtesting |

### Layer 1 — `captain_score` (frozen)

```
captain_score = form(40%) + fixture(30%) + xGI/90(20%) + minutes(10%)
```

Computed by `fpl-captain-engine`. Never modified by this or any future phase.

### Layer 2 — `position_score` (this phase)

Position-specific weight profiles over 7 shared normalised components:

| Component | Normalisation | Source |
|-----------|--------------|--------|
| `form_score` | `clamp(form / 10 × 100, 0, 100)` | canonical |
| `fixture_score` | `clamp((6 − FDR) × 20, 0, 100)` | canonical |
| `xgi_score` | `clamp(xgi_per_90 × 50, 0, 100)` | canonical |
| `minutes_score` | `clamp(100 − minutes_risk, 0, 100)` | canonical |
| `saves_score` | `clamp(saves_per_90 / 4.0 × 100, 0, 100)` | Phase 8a |
| `cs_score` | `clamp(cs_per_90 / 0.5 × 100, 0, 100)` | Phase 8a |
| `dc_score` | `clamp(dc_per_90 / 12.0 × 100, 0, 100)` | Experimental — zero weight default |

### Default weight profiles (sum to 1.0)

| Component | GKP | DEF | MID | FWD |
|-----------|-----|-----|-----|-----|
| form | 0.30 | 0.30 | 0.40 | 0.40 |
| fixture | 0.20 | 0.25 | 0.30 | 0.30 |
| xgi | 0.00 | 0.15 | 0.20 | 0.20 |
| minutes | 0.10 | 0.10 | 0.10 | 0.10 |
| saves | 0.25 | 0.00 | 0.00 | 0.00 |
| clean_sheet | 0.15 | 0.20 | 0.00 | 0.00 |
| dc | 0.00 | 0.00 | 0.00 | 0.00 |

**Design rationale:**
- **MID** = canonical formula weights exactly (zero drift by design)
- **FWD** = same as MID (transitional simplification, not final conclusion)
- **GKP** = saves dominant; xgi zeroed (structurally zero for keepers)
- **DEF** = clean sheets primary defensive signal; xgi reduced for attacking fullbacks

### Defensive contributions (`dc_score`) — open modeling question

`dc_per_90` is normalised and tracked at **zero weight** in all default profiles.
It appears in the `components` dict at every surface for auditability. An
experimental DEF profile (`dc_included`, dc=0.10) is defined for backtesting.
Resolution requires outcome backtesting (Layer 3), not assumption.

### Cross-position comparability

Because all components are normalised 0–100 and weights sum to 1.0, `position_score`
is always on a 0–100 scale regardless of position. Scores are **operationally
comparable** for ranking and tooling. However, equal numeric values across
positions do NOT have fully calibrated equivalent predictive meaning. True
predictive calibration requires outcome backtesting (Layer 3).

### Which surfaces expose `position_score`

| Intent / tool | `position_score` exposed | Notes |
|---|---|---|
| `compare_players` | Yes — `ComparisonPlayerContext.position_score`; margin uses `position_score` | — |
| `transfer_advice` | Yes — `TransferMeta.score_delta` uses `position_score` delta | — |
| `differential_picks` | Yes — `DifferentialEntry.position_score`; ranking by `position_score` | — |
| `captain_score` (single query) | Not yet — in `fpl-tool-contract` | Deferred |
| `rank_candidates` | Not yet — in `fpl-tool-contract` | Deferred |

### Auditability

- `captain_score` (Layer 1, canonical) is **always preserved** alongside `position_score`.
- Debug `score_inputs` includes `position_score`, `position_profile`,
  `components` (all 7 normalised scores), and `weights` (profile used).
- MID players have `position_score == captain_score` (identical weights — zero drift).
- `weights_override` parameter on `compute_position_score()` enables future
  ML migration without pipeline changes.

### Field changes from Phase 8a

| Phase 8a | Phase 8a1 |
|----------|-----------|
| `adjusted_captain_score` | `position_score` |
| `position_bias` | removed (implicit in per-position weights) |
| `captain_score` | `captain_score` (preserved, Layer 1) |
| bias_inputs spread | `components` dict (all 7 normalised scores) |

---

## Phase 8b — Home/Away Fixture Factor

**Added in Phase 8b.** Adds venue-aware fixture difficulty to the Layer 2 scoring input. Layer 1 (`captain_score`) is unchanged.

### Design

- `HOME_FDR_ADJUSTMENT = 0.5` — home team gets `raw_fdr − 0.5` (easier at home), away team gets `raw_fdr + 0.5` (harder away), clamped to [1.0, 5.0].
- Net effect: ±10 points on `fixture_score` component in Layer 2 (via `(6 - fdr) * 20`).
- **Layer 1 (`captain_score`)** always uses the raw integer FDR — the canonical formula is frozen.
- **Layer 2 (`position_score`)** uses `effective_fdr` for its `fixture_score` component.
- When `team_fixtures` data is absent or the current GW cannot be resolved, `is_home = None` and `effective_fdr = raw_fdr` (no adjustment).

### New fields propagated to metadata

| Field | Present in | Type | Description |
|-------|-----------|------|-------------|
| `is_home` | `ComparisonPlayerContext`, `DifferentialEntry` | `bool\|None` | `True`=home, `False`=away, `None`=unknown |
| `effective_fdr` | `ComparisonPlayerContext` | `float` | Home/away adjusted FDR used by Layer 2 (1.0–5.0) |

### FDR reason phrases

When the fixture advantage reason is generated in comparisons and transfers, the phrase now includes the venue tag:

```
"easier fixture (FDR 3H vs 4A)"  ← home vs away
"easier fixture (FDR 2H vs 3H)"  ← both home, but lower raw FDR wins
"easier fixture (FDR 2 vs 4)"    ← no venue data (is_home=None)
```

---

## Phase 8e1 — Squad Context and Hard Constraint Overrides

**Added in Phase 8e1.** Adds an optional `squad_context` parameter to `respond()` that enables deterministic hard-constraint overrides for transfer budget and chip availability. Constraints are applied post-processing, after all metadata is assembled. The deterministic backend (`recommendation`) is never changed; only `final_text` and the constraint flag are set.

### `squad_context` parameter

```python
squad_context: dict[str, Any] | None = None
```

Shape (all fields optional):

```json
{
  "itb": 20,
  "chips_remaining": ["wildcard", "bench_boost", "free_hit"],
  "free_transfers": 1
}
```

| Key | Type | Unit | Description |
|-----|------|------|-------------|
| `itb` | `int` | Tenths of £ (same unit as `now_cost`) | Money in the bank. `20` = £2.0m. |
| `chips_remaining` | `list[str]` | — | Chips the manager still has available. Valid values: `"triple_captain"`, `"wildcard"`, `"bench_boost"`, `"free_hit"`. |
| `free_transfers` | `int` | — | **Phase 8e2.** Number of free transfers available this gameweek. `1` triggers `hit_warning` on marginal recommendations. |

**Per-turn only** — `squad_context` is never persisted to `ConversationState`. Each turn is independent. Passing `squad_context=None` (or omitting it) behaves identically to no squad state.

### Transfer budget constraint

When `itb` is present and `transfer.price_delta > itb` (strict `>`):

- `TransferMeta.budget_constraint` is set to `True`
- `final_text` is overridden with: `"Budget constraint: bringing in {player_in} costs +£{price_m:.1f}m but you have £{itb_m:.1f}m in the bank."`
- `TransferMeta.recommendation` is **unchanged** (score-based, not budget-aware)

When `price_delta == itb` the constraint does **not** fire (strict `>` required).

### Free transfer hit warning (Phase 8e2)

When `free_transfers` is present and equals `1`, and `transfer.recommendation == "marginal_transfer_in"`:

- `TransferMeta.hit_warning` is set to `True`
- `final_text` is **NOT overridden** — hit_warning is advisory, not a hard block
- `TransferMeta.recommendation` is **unchanged**

**Rationale:** A marginal transfer is borderline by definition. When the manager has only one free transfer, spending it on a marginal case costs a point (a hit on the next transfer). The flag surfaces this deterministically without suppressing the advice. Does not fire for `transfer_in` (a clear upgrade is worth taking a hit) or `hold` (no transfer recommended at all).

### Chip unavailable constraint

When `chips_remaining` is present and the chip name is not in the list:

- `ChipAdviceMeta.chip_unavailable` is set to `True`
- `final_text` is overridden with: `"Chip unavailable: {chip} is not in your chips remaining."`
- `ChipAdviceMeta.recommendation` is **unchanged** (conditions-based, not availability-aware)

### Multi-intent turns

`squad_context` is forwarded to **every sub-call** in a multi-intent turn. Both constraints apply independently to their respective sub-intents. A combined multi-intent `final_text` will contain both override messages (newline-separated) when both constraints fire.

### CLI and HTTP surfaces

| Surface | How to supply `squad_context` |
|---------|-------------------------------|
| CLI | `--itb £m`, `--chips-remaining "triple_captain,wildcard"`, `--free-transfers N` |
| HTTP `/ask` | `{"squad_context": {"itb": 20, "chips_remaining": [...]}}` in request body |
| HTTP `/session/{id}/ask` | Same as `/ask` — per-turn, not persisted |

### Override application order (Orch-4d)

Squad context overrides are applied **after** all metadata is assembled, in a fixed, deterministic order. The same `_apply_squad_overrides` helper is called on both the deterministic path and the orchestration-success path, guaranteeing identical semantics regardless of which path produced the answer.

| Step | Override | Type | Condition | Effect |
|------|----------|------|-----------|--------|
| 1 | `budget_constraint` | **Hard block** | `transfer.price_delta > itb` | Replaces `final_text` with budget constraint message; sets `TransferMeta.budget_constraint=True`; `recommendation` unchanged. |
| 2 | `hit_warning` | **Advisory** | `free_transfers == 1` AND `recommendation == "marginal_transfer_in"` | Sets `TransferMeta.hit_warning=True`; `final_text` is **not** overridden. Reads `recommendation` from the TransferMeta produced by step 1 (which never changes `recommendation`). |
| 3 | `chip_unavailable` | **Hard block** | chip name not in `chips_remaining` | Replaces `final_text` with chip unavailable message; sets `ChipAdviceMeta.chip_unavailable=True`; `recommendation` unchanged. |

**Combined firing (budget + hit_warning):** Both can fire in the same turn. Budget fires first (step 1), then hit_warning reads the updated TransferMeta (step 2). A budget-blocked transfer (`budget_constraint=True`) still has its original `recommendation`, so if `recommendation == "marginal_transfer_in"` and `free_transfers == 1`, both flags will be set. In practice this means `final_text` is the budget message (hard block wins) and `hit_warning=True` is set as an additional signal.

**Path invariant:** `_apply_squad_overrides` is the single source of truth. Calling it with identical `(transfer, chip, squad_context)` inputs always produces identical outputs, regardless of whether the inputs came from the deterministic path or the orchestrator.

### Scope exclusions (deferred)

- Points-hit calculation — deferred; `hit_warning` only flags the condition, it does not compute expected point loss
- Free transfer accumulation / rollover logic — deferred
- Squad persistence across turns — explicitly out of scope; `squad_context` is per-turn only

---

## `orch_outcome` — Orchestration Audit Field (Orch-4c / Orch-4d)

**Added in Orch-4c.** `FinalResponse.orch_outcome` is a `str | None` audit field that records what the LLM orchestrator returned, independent of the deterministic `outcome` field.

### Semantics table

| `orch_outcome` value | Meaning |
|----------------------|---------|
| `None` | Orchestration was **not attempted** this turn. Either the orch flag is OFF (no API client, orch disabled), or `_multi_intent_depth > 0` (sub-calls inside a multi-intent turn always bypass the orch gate by design). |
| `"ok"` | Orchestrator succeeded and its answer was used to build the `FinalResponse`. Squad context overrides were applied after orch success via `_apply_squad_overrides`. |
| `"no_client"` | Orch was attempted but no Anthropic client was available. Fell back silently to deterministic path. |
| `"llm_error"` | Orch was attempted but the LLM call raised an exception. Fell back silently to deterministic path. |
| `"no_tool"` | Orchestrator returned no tool call in its response. Fell back silently to deterministic path. |
| `"unknown_tool"` | Orchestrator called a tool not in the registered tool set. Fell back silently to deterministic path. |
| `"tool_error"` | The registered tool raised an exception during execution. Fell back silently to deterministic path. |
| `"tool_result_error"` | The tool returned a result that could not be parsed into a valid `FinalResponse`. Fell back silently to deterministic path. |

### Independence from `outcome`

`orch_outcome` and `outcome` are **independent fields** and must be read together to understand a turn's provenance:

| `orch_outcome` | `outcome` | Interpretation |
|----------------|-----------|----------------|
| `None` | any | Orch not attempted; deterministic path produced the answer. |
| `"ok"` | `"ok"` | Orch succeeded; structured answer with metadata returned. |
| `"ok"` | other | Orch succeeded but the tool returned a non-OK outcome (e.g. not_found). |
| non-OK string | any | Orch was attempted, failed silently, and the deterministic path produced the answer. `outcome` reflects the deterministic result. |

**Key invariant:** A non-OK `orch_outcome` never changes `outcome`. When orch falls back, `outcome` is always the deterministic result — callers can rely on `outcome` for all routing decisions without inspecting `orch_outcome`.

### Surface serialization

| Surface | Behaviour |
|---------|-----------|
| CLI JSON (`--json`) | `orch_outcome` key is **omitted** when `None` (orch OFF or depth > 0). Present with its string value when non-None. |
| HTTP `/ask` | `orch_outcome` is **always present** in the JSON response body (as JSON `null` when `None`). |
| HTTP `/session/{id}/ask` | Same as `/ask` — always present. |

### Multi-intent sub-calls (deferred note)

Sub-calls inside a multi-intent turn always have `orch_outcome=None` by design. The orch gate checks `_multi_intent_depth > 0` and bypasses orchestration entirely. This prevents recursive orch calls and avoids latency compounding across sub-intents. The top-level multi-intent response's own `orch_outcome` reflects the orch state of the top-level call only. Future phases may expose per-sub-response orch state via `sub_responses[i].orch_outcome`, but this is explicitly deferred.

---

## `ComparisonMeta` — Structured Comparison Bundle (Phase 5g / 5i)

Frozen dataclass. Populated on `FinalResponse.comparison` when `intent == "compare_players"` and `outcome == "ok"`. `None` for all other turns.

| Field | Type | Description |
|-------|------|-------------|
| `winner` | `str\|None` | Winning player display name. `None` when the two players are tied on captain score. |
| `margin` | `float` | Absolute score difference (winner − loser). Zero on a tie. |
| `label` | `str` | Categorical margin: `"narrow"` (< 3.0), `"moderate"` (3.0–9.99), `"clear"` (≥ 10.0). |
| `reasons` | `tuple[str, ...]` | Deterministic advantage phrases (e.g. `"stronger form (9.5 vs 8.0)"`). Empty tuple when no advantage clears the threshold. |
| `player_a` | `ComparisonPlayerContext\|None` | Bounded per-player context for the first comparison player (Phase 5i). |
| `player_b` | `ComparisonPlayerContext\|None` | Bounded per-player context for the second comparison player (Phase 5i). |

```python
r = respond("compare Haaland and Salah", bootstrap)
if r.comparison:
    print(r.comparison.winner)             # "Salah"
    print(r.comparison.label)             # "moderate"
    print(r.comparison.reasons)           # ("stronger form (9.5 vs 8.0)",)
    print(r.comparison.player_a.position) # "FWD"
    print(r.comparison.player_b.role_bonus) # 5.0
```

---

## `ComparisonPlayerContext` — Per-Player Context (Phase 5i / 8a1 / 8b)

Frozen dataclass. Populated on `ComparisonMeta.player_a` and `ComparisonMeta.player_b` for successful comparison turns. Exposes a bounded, deterministic subset of per-player context — no values are recomputed; all come from the `compare_players()` raw output.

| Field | Type | Description |
|-------|------|-------------|
| `web_name` | `str` | Player display name (e.g. `"Haaland"`). |
| `position` | `str` | FPL position: `"FWD"`, `"MID"`, `"DEF"`, or `"GKP"`. |
| `captain_score` | `float` | **Layer 1.** Canonical deterministic captain score (form 40% / fixture 30% / xGI/90 20% / minutes 10%). Preserved for auditability. Always uses raw integer FDR. |
| `position_score` | `float` | **Phase 8a1 (Layer 2).** Position-aware heuristic score used for comparison ranking. Uses position-specific weight profiles over 7 normalised components. Equal to `captain_score` for MID (identical weights). Uses `effective_fdr` (Phase 8b). |
| `is_home` | `bool\|None` | **Phase 8b.** `True` if home this GW, `False` if away, `None` if venue unknown. |
| `effective_fdr` | `float` | **Phase 8b.** Home/away adjusted FDR (1.0–5.0). Home: `raw_fdr − 0.5`; away: `raw_fdr + 0.5`; clamped. Equals raw FDR when `is_home=None`. Used by Layer 2 only. |
| `role_bonus` | `float` | Numeric contribution to captain score from set-piece involvement. `5.0` for primary penalty taker, `0.5` for secondary free-kick taker, `0.0` for no role. |
| `set_piece_notes` | `tuple[str, ...]` | Role-key strings describing set-piece involvement (e.g. `("penalty_taker_1",)`). Empty tuple when no role is recorded. |

**Scoring model** — `ComparisonMeta.margin` and the comparison winner are computed from `position_score` (Layer 2). `captain_score` (Layer 1, canonical) is preserved alongside for auditability. Debug `score_inputs` includes `position_score`, `position_profile`, `components` (all 7 normalised scores), `weights`, `is_home`, and `effective_fdr`.

```python
r = respond("compare Raya and Haaland", bootstrap)
if r.comparison and r.comparison.player_a:
    ctx = r.comparison.player_a
    print(ctx.web_name)                 # "Raya"
    print(ctx.position)                 # "GKP"
    print(ctx.captain_score)            # e.g. 52.0  (Layer 1 canonical)
    print(ctx.position_score)           # e.g. 66.5  (Layer 2 position-aware)
    print(ctx.is_home)                  # True (home this GW)
    print(ctx.effective_fdr)            # 2.5  (raw 3 − 0.5 home adj)
    print(ctx.role_bonus)               # 0.0
    print(ctx.set_piece_notes)          # ()
```

---

## `TransferMeta` — Structured Transfer Advice Bundle (Phase 7a)

Frozen dataclass. Populated on `FinalResponse.transfer` when `intent == "transfer_advice"` and `outcome == "ok"`. `None` for all other turns.

| Field | Type | Description |
|-------|------|-------------|
| `player_out` | `str` | Web name of the player being sold (e.g. `"Saka"`). |
| `player_in` | `str` | Web name of the player being bought (e.g. `"Salah"`). |
| `recommendation` | `str` | One of `"transfer_in"` (score_delta > 5.0), `"marginal_transfer_in"` (0 < delta ≤ 5.0), or `"hold"` (delta ≤ 0). Score-based; never overridden by `squad_context`. |
| `score_delta` | `float` | `position_score_in − position_score_out` (Phase 8a1). Positive when player_in scores higher on the position-aware heuristic. |
| `price_delta` | `int` | `now_cost_in − now_cost_out` in tenths of £. Positive when player_in is more expensive. Informational only; does not affect the recommendation. |
| `reasons` | `tuple[str, ...]` | Deterministic advantage phrases for player_in (e.g. `("stronger form (9.5 vs 8.0)",)`). Empty tuple when no signal clears its threshold, or for `"hold"` turns where player_in has no clear edge. |
| `budget_constraint` | `bool` | **Phase 8e1.** `True` when `squad_context.itb` is supplied and `price_delta > itb` (player_in unaffordable). `False` by default. When `True`, `final_text` is overridden with a budget constraint message; `recommendation` is unchanged. |
| `hit_warning` | `bool` | **Phase 8e2.** `True` when `squad_context.free_transfers == 1` AND `recommendation == "marginal_transfer_in"`. `False` by default. Advisory only — `final_text` is NOT overridden; use this flag to surface a warning in the UI. Does not fire for `transfer_in` (clear upgrade worth the hit) or `hold`. |

```python
r = respond("should I sell Saka for Salah", bootstrap)
if r.transfer:
    print(r.transfer.player_out)         # "Saka"
    print(r.transfer.player_in)          # "Salah"
    print(r.transfer.recommendation)     # "transfer_in"
    print(r.transfer.score_delta)        # e.g. 25.3
    print(r.transfer.price_delta)        # e.g. 10  (£1.0m more expensive)
    print(r.transfer.reasons)            # ("stronger form (9.5 vs 5.0)",)
    print(r.transfer.budget_constraint)  # False (no squad_context)
```

---

## `ChipAdviceMeta` — Structured Chip Advice Bundle (Phase 7b)

Frozen dataclass. Populated on `FinalResponse.chip` when `intent == "chip_advice"` and `outcome == "ok"`. `None` for all other turns.

| Field | Type | Description |
|-------|------|-------------|
| `chip` | `str` | One of `"triple_captain"`, `"wildcard"`, `"bench_boost"`, `"free_hit"`. |
| `recommendation` | `str` | One of `"conditions_favorable"`, `"conditions_marginal"`, `"conditions_unfavorable"`. Conditions-based; never overridden by `squad_context`. |
| `gw` | `int\|None` | Current gameweek number, or `None` when unavailable. |
| `signal_value` | `float\|None` | The primary signal value driving the recommendation (e.g. top captain score for TC). |
| `signal_label` | `str\|None` | Human-readable label for `signal_value` (e.g. `"top captain score"`). |
| `chip_unavailable` | `bool` | **Phase 8e1.** `True` when `squad_context.chips_remaining` is supplied and the chip name is not in that list. `False` by default. When `True`, `final_text` is overridden with a chip unavailable message; `recommendation` is unchanged. |

```python
r = respond("should I use triple captain this week", bootstrap)
if r.chip:
    print(r.chip.chip)               # "triple_captain"
    print(r.chip.recommendation)     # "conditions_favorable"
    print(r.chip.signal_value)       # e.g. 85.2
    print(r.chip.signal_label)       # "top captain score"
    print(r.chip.chip_unavailable)   # False (no squad_context)
```

---

## `FixtureRunMeta` — Structured Fixture Run Bundle (Phase 7h)

Frozen dataclass. Populated on `FinalResponse.fixture_run` when `intent == "player_fixture_run"` and `outcome == "ok"`. `None` for all other turns.

| Field | Type | Description |
|-------|------|-------------|
| `web_name` | `str` | Player display name (e.g. `"Salah"`). |
| `team_short` | `str` | Three-letter team abbreviation (e.g. `"LIV"`). |
| `position` | `str` | Player position: `"GKP"`, `"DEF"`, `"MID"`, or `"FWD"`. |
| `horizon` | `int` | Number of fixtures returned (default 5). |
| `current_gameweek` | `int` | The GW from which the fixture run starts. |
| `fixtures` | `tuple[FixtureEntry, ...]` | Ordered upcoming fixtures, earliest first. Length ≤ `horizon`. |

### `FixtureEntry`

Each element of `FixtureRunMeta.fixtures` is a frozen dataclass:

| Field | Type | Description |
|-------|------|-------------|
| `gameweek` | `int` | GW number of this fixture. |
| `opponent_short` | `str` | Three-letter abbreviation of the opponent team (e.g. `"MCI"`). |
| `is_home` | `bool` | `True` if the player's team is at home. |
| `difficulty` | `int` | FPL fixture difficulty rating (1–5). |

```python
r = respond("Salah fixtures", bootstrap)
if r.fixture_run:
    print(r.fixture_run.web_name)          # "Salah"
    print(r.fixture_run.team_short)        # "LIV"
    print(r.fixture_run.position)          # "MID"
    print(r.fixture_run.horizon)           # 5
    for fx in r.fixture_run.fixtures:
        print(fx.gameweek, fx.opponent_short, fx.is_home, fx.difficulty)
        # 28 ARS True 4
        # 29 MCI False 4
        # ...
```

---

## `DifferentialPicksMeta` — Structured Differential Picks Bundle (Phase 7g)

Frozen dataclass. Populated on `FinalResponse.differential` when `intent == "differential_picks"` and `outcome == "ok"`. `None` for all other turns.

| Field | Type | Description |
|-------|------|-------------|
| `ownership_threshold` | `float` | Ownership percentage ceiling used for filtering (default 15.0). |
| `top_n` | `int` | Number of picks returned. Equals `len(picks)`. |
| `picks` | `tuple[DifferentialEntry, ...]` | Ranked picks, sorted by `position_score` descending (Phase 8a1). |

### `DifferentialEntry`

Each element of `DifferentialPicksMeta.picks` is a frozen dataclass:

| Field | Type | Description |
|-------|------|-------------|
| `rank` | `int` | 1-based rank by `position_score` descending (Phase 8a1). |
| `web_name` | `str` | Player display name (e.g. `"Palmer"`). |
| `team_short` | `str` | Three-letter team abbreviation (e.g. `"CHE"`). |
| `position` | `str` | Player position: `"GKP"`, `"DEF"`, `"MID"`, or `"FWD"`. |
| `captain_score` | `float` | **Layer 1.** Canonical deterministic captain score. Preserved for auditability. |
| `position_score` | `float` | **Phase 8a1 (Layer 2).** Position-aware heuristic score used for ranking. Uses `effective_fdr` (Phase 8b). Equal to `captain_score` for MID when at home or no venue data. |
| `ownership` | `float` | `selected_by_percent` as a float (e.g. `3.5`). |
| `now_cost` | `int` | Current price in tenths of £ (e.g. `60` = £6.0m). |
| `is_home` | `bool\|None` | **Phase 8b.** `True` if home this GW, `False` if away, `None` if venue unknown. |

**Filtering rules (deterministic, not configurable via prompt):**
- `status == "a"` (available only — doubtful, injured, suspended excluded)
- `selected_by_percent < 15.0` (ownership below threshold)
- `captain_score > 0` (must have a positive score signal)

```python
r = respond("good differentials", bootstrap)
if r.differential:
    print(r.differential.ownership_threshold)  # 15.0
    print(r.differential.top_n)                # number of picks returned
    for p in r.differential.picks:
        print(p.rank, p.web_name, p.team_short, p.position)
        print(p.captain_score, p.ownership, p.now_cost)
        # 1 Palmer CHE MID 55.0 3.5 60
        # 2 Mbeumo MUN FWD 38.0 8.2 75
```

---

## `FinalResponseDebug` — Debug Bundle (Not Part of Contract)

Five fields.  Frozen dataclass.  Only populated when ``include_debug=True``.

| Field | Type | Description |
|-------|------|-------------|
| `llm_text` | `str` | Raw LLM output (or `response_text` when `llm_called=False`). |
| `response_text` | `str` | Deterministic backend text. Equals `final_text` when `llm_used=False`. |
| `violations` | `tuple[str, ...]` | Violation strings from the review layer. Empty when `review_passed=True`. |
| `prompt_used` | `str` | The user-turn prompt sent (or prepared) for the LLM. |
| `model` | `str` | Anthropic model identifier, or `"none"` when deterministic fallback was used. |

**These fields are for diagnostics and regression testing only.**  Callers
should not branch on ``debug`` content in production code.

---

## Final-Text Policy

```
FINAL_TEXT_POLICY = (
    "final_text = review.safe_text: "
    "llm_text when (llm_called AND review_passed), "
    "response_text otherwise"
)
```

Three cases, exactly one always applies:

| Condition | `final_text` | `llm_used` |
|-----------|-------------|-----------|
| LLM called, review passed | `llm_text` | `True` |
| LLM called, review failed | `response_text` | `False` |
| LLM not called (no API key / error) | `response_text` | `False` |

The deterministic backend ``response_text`` is the ultimate recovery path in
all fallback cases, regardless of failure mode.

---

## `llm_used` Semantics

``llm_used=True`` means exactly:

> An Anthropic API call was made **AND** the returned text passed the
> deterministic parity review.

``llm_used=False`` covers all fallback scenarios without distinction:
- No API key set (``ANTHROPIC_API_KEY`` absent and no explicit ``api_key``)
- API error (network failure, rate limit, etc.)
- Review violation (overconfident language, invented numbers, false resolution)
- ``client=None`` and no key

Callers do not need to distinguish between these failure modes — they always
receive a safe, non-empty ``final_text``.

---

## `review_passed` Semantics

``review_passed=True`` means the LLM text (or deterministic fallback) passed
all four deterministic parity checks:

| Check | What it detects |
|-------|----------------|
| Overconfidence on non-ok outcomes | Phrases like "definitely", "guaranteed", "i can confirm" in failure responses |
| Numeric invention | Numbers in `llm_text` absent from `response_text` (non-ok outcomes only) |
| Ambiguous false resolution | Resolution phrases like "the player you're looking for is" in ambiguous responses |
| Empty LLM text | Empty string returned from an actual API call |

The deterministic fallback path always passes (``llm_text == response_text``
when ``llm_called=False`` → numeric check is trivially satisfied).

---

## Outcome Vocabulary

| Constant | Value | `supported` | When to surface `final_text` |
|----------|-------|-------------|------------------------------|
| `OUTCOME_OK` | `"ok"` | `True` | Surface directly as final answer |
| `OUTCOME_NOT_FOUND` | `"not_found"` | `True` | Surface; optionally invite spelling check |
| `OUTCOME_AMBIGUOUS` | `"ambiguous"` | `True` | Surface; prompt user to disambiguate |
| `OUTCOME_MISSING_ARGUMENTS` | `"missing_arguments"` | `True` | Surface (already contains guidance); request missing input |
| `OUTCOME_ERROR` | `"error"` | `True` | Surface; log debug bundle for diagnostics |
| `OUTCOME_UNSUPPORTED_INTENT` | `"unsupported_intent"` | `False` | Surface (safe fallback); optionally route to another system |

---

## Invariants (Always True)

All of the following hold for every ``FinalResponse`` returned by ``respond()``:

1. ``len(response.final_text) > 0`` — ``final_text`` is never empty
2. ``response.supported == (response.outcome != "unsupported_intent")``
3. ``not response.llm_used or response.review_passed`` — ``llm_used=True``
   implies ``review_passed=True``
4. ``response.outcome in {OUTCOME_OK, OUTCOME_NOT_FOUND, OUTCOME_AMBIGUOUS,``
   ``OUTCOME_MISSING_ARGUMENTS, OUTCOME_ERROR, OUTCOME_UNSUPPORTED_INTENT}``
5. When ``include_debug=True``:
   - ``response.debug is not None``
   - ``response.debug.violations == ()`` iff ``response.review_passed``
   - ``not response.llm_used → response.final_text == response.debug.response_text``
6. ``response.debug is None`` when ``include_debug=False`` (default)

---

## Named Scenarios

Six canonical scenarios covering all caller-relevant states.
See ``fpl_grounded_assistant.final_response_fixtures`` for executable versions.

### 1. `supported_ok`
```python
respond("should I captain Haaland", STANDARD_BOOTSTRAP)
# FinalResponse(
#   final_text=<non-empty captain score response>,
#   outcome="ok",
#   supported=True,
#   intent="captain_score",
#   review_passed=True,
#   llm_used=False,   # False in deterministic mode; True when LLM passes review
#   debug=None,
# )
```

### 2. `supported_ambiguous`
```python
respond("who is Doe", AMBIGUOUS_BOOTSTRAP)
# FinalResponse(
#   final_text=<clarification prompt listing both Doe players>,
#   outcome="ambiguous",
#   supported=True,
#   intent="player_resolve",
#   review_passed=True,
#   llm_used=False,
#   debug=None,
# )
```

### 3. `supported_not_found`
```python
respond("should I captain xyznotaplayer999", STANDARD_BOOTSTRAP)
# FinalResponse(
#   final_text=<player not found message>,
#   outcome="not_found",
#   supported=True,
#   intent="captain_score",
#   review_passed=True,
#   llm_used=False,
#   debug=None,
# )
```

### 4. `supported_missing_arguments`
```python
respond("top captains this week", STANDARD_BOOTSTRAP)  # no candidates_list
# FinalResponse(
#   final_text=<missing candidates_list guidance>,
#   outcome="missing_arguments",
#   supported=True,
#   intent="rank_candidates",
#   review_passed=True,
#   llm_used=False,
#   debug=None,
# )
```

### 5. `unsupported_intent`
```python
respond("Is Haaland fit to play?", STANDARD_BOOTSTRAP)
# FinalResponse(
#   final_text=<safe out-of-scope message>,
#   outcome="unsupported_intent",
#   supported=False,
#   intent="unsupported",
#   review_passed=True,
#   llm_used=False,
#   debug=None,
# )
```

### 6. `llm_fallback_to_deterministic`
```python
# No API key set, no explicit client
response = respond("should I captain Salah", STANDARD_BOOTSTRAP,
                   include_debug=True)
# FinalResponse(
#   final_text=<same as debug.response_text>,
#   outcome="ok",
#   supported=True,
#   intent="captain_score",
#   review_passed=True,
#   llm_used=False,                              ← fallback
#   debug=FinalResponseDebug(
#     llm_text=<same as response_text>,          ← fallback sets llm_text=response_text
#     response_text=<deterministic backend text>,
#     violations=(),                             ← no LLM → no violations
#     model="none",                              ← no LLM call
#     ...
#   ),
# )
assert response.final_text == response.debug.response_text  # fallback invariant
```

---

## Bootstrap vs. Assembled Context

``respond()`` accepts either a raw bootstrap dict or a full assembled context
from ``fpl_pipeline.assemble_captain_context()``.  Detection is automatic.

```python
# Raw bootstrap
respond("should I captain Haaland", bootstrap_dict)

# Assembled context — fixture_difficulty_map automatically included
from fpl_pipeline import assemble_captain_context
ctx = assemble_captain_context(gameweek=28, bootstrap=bs, fixtures=fx)
respond("should I captain Haaland", ctx)
```

---

## Stability Commitment

The following are **breaking changes** requiring explicit documentation:
- Renaming or removing any of the six non-debug fields on ``FinalResponse``
- Changing the type of any non-debug field
- Changing the semantics of ``supported``, ``llm_used``, or ``review_passed``
- Adding required parameters to ``respond()``

The following are **non-breaking**:
- Adding new optional parameters to ``respond()`` (keyword-only, with defaults)
- Populating additional fields in ``FinalResponseDebug``
- Adding new ``OUTCOME_*`` constants (callers should handle unknown outcomes
  gracefully by treating them as unsupported)

---

## Out of Scope (Deferred)

| Capability | Status |
|------------|--------|
| Multi-turn conversation memory | Deferred |
| Pronoun resolution | Deferred |
| Combined intents | Deferred |
| UI integration | Deferred |
| Streaming responses | Deferred |
| Model-based (non-deterministic) review | Deferred |
| LLM-based intent classification | Deferred |
| Live FPL API calls (fixtures use injected bootstrap) | Out of scope for grounded layer |
| Per-sub-response `orch_outcome` in multi-intent turns | Deferred (Orch-4c note) — sub-calls always have `orch_outcome=None` by design; future phases may expose this via `sub_responses[i].orch_outcome` |
| Points-hit calculation for `hit_warning` | Deferred — `hit_warning` flags the condition only; does not compute expected point loss |



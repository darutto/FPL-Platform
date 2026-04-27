# FPL Grounded Assistant — Handoff Summary

## Purpose

This project is a **grounded Fantasy Premier League assistant**.

The system must:
- use **deterministic backend logic** for FPL facts and recommendations
- use LLMs only for:
  - phrasing
  - reference resolution
  - limited conversational interpretation
- never let the LLM become the source of football truth

Core principle:

> **Interpret with the LLM, answer with the deterministic backend.**

---

# Current Architectural Intent

The project has evolved from consolidation into a real backend platform.

## What the system is meant to do

Support grounded FPL questions such as:
- Should I captain Haaland?
- Who is Salah?
- Give me a summary for Palmer
- Compare Haaland and Salah
- Follow-up questions like:
  - And Salah?
  - What about him?
  - ¿Y él?
  - ¿Y Salah?

## What the system is NOT meant to do
Not yet:
- broad general chat about football from model memory
- unsupported freeform reasoning
- multi-turn long-term memory
- multi-player comparison
- open-ended debate-style answers
- UI-heavy frontend work

---

# Core Design Principles

## 1. Deterministic backend is authoritative
All FPL facts and recommendations must come from deterministic code:
- player resolution
- current gameweek
- captain score
- ranking
- comparison
- rendered grounded response text

## 2. LLMs are bounded helpers
LLMs may:
- rewrite follow-up questions
- resolve pronouns/references
- produce polished phrasing on top of deterministic output

LLMs must NOT:
- invent scores
- invent player facts
- answer unsupported intents as if they were supported
- override ambiguous/not_found outcomes

## 3. Contracts matter
Stable caller-facing surfaces now exist.
Changes to these should be treated as interface changes, not casual refactors.

---

# Current Package/Capability Map

## Deterministic backend packages
- `fpl-api-client`
- `fpl-player-registry`
- `fpl-data-core`
- `fpl-query-tools`
- `fpl-tool-contract`
- `fpl-tool-runner`
- `fpl-captain-engine`
- `fpl-grounded-assistant`
- `fpl-pipeline`

## Supporting packages (not on critical path)
- `fpl-charts` — TypeScript theme constants (colors, brand, risk levels)

## Key external surfaces
- CLI
- HTTP stateless endpoint
- HTTP session endpoints

---

# Captaincy System Intent

## Current state
Captaincy is implemented as a deterministic, grounded system.
Direct captain score queries and ranked captain candidate outputs now render correctly through the shared response layer across CLI, HTTP, and session flows.

### Captain Score v1
Current score is still a heuristic baseline.

It uses:
- form
- fixture difficulty
- xGI/90
- minutes risk

This formula is preserved as:
- baseline
- regression target
- deterministic engine

### Important note
The captain score is **not the final football model**.
It is currently:
- useful
- explainable
- tested
- good enough for grounded recommendations

But it is still heuristic.

## Additional captain framing added
The system now also supports:
- tier labels
- role-aware framing
- explanation strings
- role/set-piece metadata

Captain framing is now normalized across direct captain and ranked-candidate outputs using deterministic bootstrap-element data rather than hardcoded fallback inputs.
Current tier vocabulary is intentionally bounded and consistent:
- `safe`
- `upside`
- `differential`
- `avoid`

Successful direct captain-score turns can now also carry additive structured captain metadata for programmatic callers, including bounded fields such as player name, team short name, captain score, tier, role bonus, and set-piece notes.
Successful ranked captain turns can also carry additive structured ranking metadata for programmatic callers when the ranking intent succeeds.

These are deterministic editorial layers on top of the score.

---

# Comparison System Intent

Comparison is now a first-class deterministic capability.

It supports:
- direct comparison:
  - compare Haaland and Salah
  - Haaland vs Salah
  - who is better Haaland or Salah
- narrow follow-up comparison:
  - And Salah?
  - What about Saka?
  - Compare him to Salah
  - ¿Y Salah? (Spanish)
  - vs Saka
  - Or Saka?
  - elliptical references resolved via LLM

Comparison follow-up resolution uses a two-tier chain:
1. Deterministic regex-based resolver first (fast, covers common English patterns)
2. LLM-assisted resolver fallback for Spanish and elliptical cases that deterministic patterns cannot catch

Current LLM comparison follow-up behavior is intentionally narrow:
- it extracts only whether the turn is a comparison follow-up and the new player name
- it rewrites successful follow-ups to `compare {last_comparison_a} and {new_player}`
- it is not allowed to invent comparison facts or return football reasoning
- if the LLM is unavailable, raises, returns invalid output, returns low confidence, or says the turn is not a comparison follow-up, the system silently falls through to the broader resolver chain

Comparison outputs include:
- winner
- margin
- recommendation
- `margin_label`
- `comparison_reasons`

Comparison explanations now also support richer deterministic role-aware framing, including more specific set-piece advantage phrases and additive per-player context such as position and role signals in backend comparison payloads.

Successful comparison turns also now carry additive structured comparison metadata in the final response layer for programmatic callers.
That structured metadata can now include bounded per-player comparison context for player A and player B, such as web name, position, captain score, role bonus, and set-piece notes.

Comparison remains:
- strictly two-player only
- deterministic scoring
- grounded in existing score inputs and deterministic player metadata already present in the platform

Not supported yet:
- multi-player comparison
- follow-up targeting player B specifically; v1 still anchors rewrites to player A from the last comparison
- open-ended “debate”
- broad comparison memory

---

# Transfer Advice System Intent

Transfer advice is a deterministic, grounded capability for two-player transfer-style queries.

It supports prompts like:
- should I sell Saka for Salah?
- sell Haaland for Salah
- swap Saka for Palmer
- replace Bruno with Foden
- transfer out Saka for Haaland
- should I transfer Saka for Palmer?

## Recommendation outcomes

Three possible recommendation values:

- `transfer_in` — score_delta > 5.0 (strong case to transfer in)
- `marginal_transfer_in` — score_delta in (0, 5.0] (slight edge to player_in)
- `hold` — score_delta ≤ 0 (player_out is equal or better)

For `hold`, explanation reasons are intentionally phrased from the perspective of keeping the current player, not from the perspective of the incoming player failing to win.

## Deterministic inputs

The recommendation is based solely on:
- captain score delta (player_in minus player_out) as the primary recommendation driver
- form delta for grounded reason phrasing
- fixture difficulty (FDR) delta for grounded reason phrasing
- xGI/90 delta for grounded reason phrasing
- minutes risk delta for grounded reason phrasing
- set-piece role signals as additive grounded reason phrasing

Price delta (player_in cost minus player_out cost) is shown as informational context only — it does not affect the recommendation direction.

## Scope limitations

Transfer advice is strictly:
- two-player only
- deterministic scoring (same captain engine used for captain_score and comparison)
- no squad context, no ITB/budget awareness, no multi-transfer planning
- no long-term fixture view beyond current FDR

Successful transfer-advice turns now carry additive structured transfer metadata in the final response layer for programmatic callers (Phase 7a).
`FinalResponse.transfer: TransferMeta | None` is populated for `transfer_advice` OK turns with bounded fields: `player_out`, `player_in`, `recommendation`, `score_delta`, `price_delta`, `reasons`.
The `transfer` field is serialized in HTTP `/ask`, `/session/{id}/ask`, and CLI debug JSON.
For `multi_intent` turns, `sub_responses` entries can also expose `transfer` when a sub-intent produces a `transfer_advice` OK result.
Plain-text `final_text` behavior is unchanged.

Transfer advice also now supports bounded deterministic follow-up resolution in session flows (Phase 7f).
When a successful transfer turn establishes `last_transfer = (player_out, player_in)`, follow-ups such as:
- `what about Haaland instead?`
- `how about Haaland instead?`
- `what about Haaland?`
- `how about Haaland?`
- `Haaland instead?`
are rewritten deterministically to `sell {player_out} for Haaland` and routed through the existing transfer path.

Current transfer follow-up limitations are intentional:
- deterministic-only for V1
- always anchored to the prior `player_out`
- no Spanish or broader elliptical follow-up patterns yet
- no squad-planning suggestions

---

# Chip Advice System Intent

Chip advice is a deterministic, grounded capability for FPL chip questions.

Supported chips and routing triggers
--------------------------------------

- **triple_captain**: "should I use triple captain this week", "is this a good week for triple captain", etc.
- **wildcard**: "should I wildcard this week", "wildcard this week", etc.
- **bench_boost**: "should I bench boost now", "is this a good week for bench boost", etc.
- **free_hit**: "should I free hit this week", "should I free hit this gameweek", etc.

Routing requires BOTH a chip keyword AND an advisory phrase (e.g. "should I", "this week", "is this a good"). Bare chip mentions without advisory context do not route.
Chip routing is intentionally checked before current-gameweek routing so prompts like "should I free hit this gameweek" do not get swallowed by the standalone gameweek keyword path.

## Recommendation outcomes

| Chip | Possible recommendations |
|---|---|
| triple_captain | `conditions_favorable` (score ≥ 75), `conditions_marginal` (score ≥ 55), `conditions_unfavorable` (score < 55) |
| wildcard | `conditions_unfavorable` (GW ≤ 6 or GW ≥ 29), `conditions_marginal` (GW 7–28) |
| bench_boost | `conditions_favorable` (avg FDR ≤ 2.5), `conditions_marginal` (≤ 3.0), `conditions_unfavorable` (> 3.0) |
| free_hit | Always `missing_context` (no DGW/BGW detection available) |

All recognised chips return `status="ok"` and `outcome=ok`. The `recommendation` field distinguishes quality of conditions.

## Deterministic inputs

| Chip | Signals used |
|---|---|
| triple_captain | Top MID/FWD captain score (same captain engine as captain_score and comparison) |
| wildcard | Current GW number from bootstrap events |
| bench_boost | Average FDR for top 10 MID/FWD players via the same grounded scoring inputs path |
| free_hit | Current GW number (for display only) — no DGW/BGW signals available |

## Scope limitations

Chip advice is strictly:
- grounded in currently available bootstrap signals only
- no squad context (chip availability, bench composition, team layout)
- no DGW/BGW detection (free_hit always returns missing_context)
- no chip combination planning
- no long-horizon fixture view

Successful chip-advice turns now carry additive structured chip metadata in the final response layer for programmatic callers (Phase 7b).
`FinalResponse.chip: ChipAdviceMeta | None` is populated for `chip_advice` OK turns with bounded fields: `chip`, `recommendation`, `gw`, `signal_value`, `signal_label`.
The `chip` field is serialized in HTTP `/ask`, `/session/{id}/ask`, and CLI debug JSON.
For `multi_intent` turns, `sub_responses` entries can also expose `chip` when a sub-intent produces a `chip_advice` OK result.
Plain-text `final_text` behavior is unchanged.

Signal mapping per chip:
- `triple_captain`: `signal_value` = top available MID/FWD captain score (float); `signal_label` = "top captain score"
- `wildcard`: `signal_value` = current gameweek number as float; `signal_label` = "current gameweek"
- `bench_boost`: `signal_value` = average FDR for top 10 outfield players (float); `signal_label` = "average FDR (top 10)"
- `free_hit`: `signal_value` = None; `signal_label` = None (missing_context by design)

`signal_value` and `signal_label` are intentionally either both present or both `None`.

The `advice_text` field explicitly notes these limitations.

---

# Player Fixture Run System Intent

Player fixture run is a deterministic, grounded retrieval capability for upcoming player schedules.

It supports prompts like:
- Salah fixtures
- Haaland's fixtures
- Palmer fixture run
- Saka fixture schedule
- fixtures for Salah
- upcoming fixtures for Haaland
- fixture run for Palmer
- Salah next 5 games
- Haaland next 3 fixtures

## Deterministic inputs

Fixture run uses:
- deterministic player resolution
- current gameweek from bootstrap events
- grounded team fixture data from the fixture data path backing bootstrap

The default horizon is 5 games unless the prompt explicitly requests a supported `next N` form.

## Scope limitations

Fixture run is strictly:
- retrieval-only
- grounded in available fixture data only
- no predictive commentary
- no editorial fixture difficulty summary beyond surfaced grounded difficulty values
- no follow-up resolution yet for prompts like `what about Haaland?`
- no per-request horizon customization beyond supported `next N` phrasing

Successful fixture-run turns now carry additive structured fixture metadata in the final response layer for programmatic callers (Phase 7h).
`FinalResponse.fixture_run: FixtureRunMeta | None` is populated for `player_fixture_run` OK turns with bounded fields: `web_name`, `team_short`, `position`, `horizon`, `current_gameweek`, and `fixtures`.
The `fixture_run` field is serialized in HTTP `/ask`, `/session/{id}/ask`, and CLI debug JSON.
Plain-text `final_text` behavior is unchanged.

---

# Multi-Intent Orchestration System Intent

Multi-intent orchestration is a narrow capability that detects and handles
conjunctive questions containing two independently-resolvable sub-intents.

## Routing triggers

Detection fires in `respond()` BEFORE the single-intent pipeline when:
1. The question contains " and " after trailing punctuation is stripped and detection is lowercased
2. The question is split on the first occurrence only
3. BOTH halves of the split independently route via the deterministic `route()` function

If either half fails to route, the question falls through to the normal single-intent pipeline.
No new deterministic data sources are introduced for multi-intent turns; each half uses exactly the same deterministic inputs it would use as a standalone question.

## False-split guards (by design)

- **"compare Salah and Haaland"** — "compare Salah" alone does not route (comparison requires a two-player connector) → single intent `compare_players` ✓
- **"sell Saka and bring in Salah"** — "sell Saka" alone has no transfer connector → single intent `get_transfer_advice` ✓
- **"Haaland vs Salah"** — no " and " present → single intent ✓

## Response contract

Multi-intent turns return `FinalResponse` with:
- `intent = "multi_intent"` — synthetic intent, not dispatched via the single-intent pipeline
- `outcome = "ok"` when all sub-intents succeed; first non-OK sub-outcome otherwise
- `supported = True` when all sub-intents are within scope
- `final_text` — sub-response texts joined with `"\n\n"` separator
- `sub_responses` — tuple of per-sub-intent `FinalResponse` objects (always 2 in Phase 6c)

Sub-response objects inside `sub_responses` always have `debug=None` (debug opt-in is not surfaced for individual sub-turns).

The `sub_responses` field is additive and defaults to `None` for all single-intent turns (backward-compatible).

## HTTP serialization

`AskResponse` and `SessionAskResponse` have an additive `sub_responses: list[dict] | None` field.
Each sub-response dict always includes: `final_text`, `outcome`, `supported`, `intent`.
When the sub-intent produces structured metadata, the dict also includes:
- `captain` — when sub-intent is `captain_score` and outcome is `ok` (Phase 6d)
- `captain_ranking` — when sub-intent is `rank_candidates` and outcome is `ok` (Phase 6d)
- `comparison` — when sub-intent is `compare_players` and outcome is `ok` (Phase 6d)
`sub_responses` is `null` in JSON for single-intent turns.

## CLI serialization

`run()` debug JSON includes `sub_responses` list when `intent == multi_intent`.
`run_session()` turn dicts include `sub_responses` when the turn is multi-intent (Phase 6d).
Both include bounded structured metadata per sub-response when present (Phase 6d).
Non-debug output is the combined `final_text` (unchanged caller behavior).

## Scope limitations

- Two sub-intents only (Phase 6c). No 3-way multi-intent.
- " and " conjunction only. Other conjunctions ("also", "plus") are deferred.
- Both halves must independently route via deterministic `route()`. LLM classification is not used for split detection.
- Session state (last_player, last_comparison, last_resolver_source) does not update from multi-intent turns.
- No debug bundle inside sub-responses.
- `sub_responses` entries expose bounded structured metadata (captain, comparison, captain_ranking) per sub-intent when present (Phase 6d). Entries without relevant structured output contain only `final_text`, `outcome`, `supported`, `intent`.

---

# Supported Intents (Current)

These are the main supported deterministic intents:

- `captain_score`
- `rank_candidates`
- `current_gameweek`
- `player_summary`
- `player_resolve`
- `compare_players`
- `transfer_advice`
- `chip_advice`
- `multi_intent` (Phase 6c — synthetic intent produced by the orchestrator)
- `player_fixture_run` (Phase 7h — upcoming fixture schedule for a named player)
- `differential_picks` (Phase 7g — top low-ownership players ranked by captain score)

## Important behavior
Unsupported prompts must remain explicit and safe.

Unsupported intent should not become guessed football truth.

---

# Expected Response Semantics

## Internal outcome vocabulary
Outcomes include things like:
- `ok`
- `ambiguous`
- `not_found`
- `missing_arguments`
- `unsupported_intent`

These should remain explicit through the stack.

## Caller-facing response policy
The final caller-facing text is selected through the final response layer.

Core policy:

- safest available text is surfaced
- deterministic backend is the ultimate fallback
- LLM output is allowed only when it passes review/hardening

---

# Current Stable Caller-Facing Contracts

## DispatchResult
Dispatcher-level result with:
- intent
- selected tool
- raw_output
- answer_text
- outcome
- context/debug-related metadata as applicable

## AdapterResponse
Thin model-facing wrapper around dispatch.

Important semantics:
- `supported=False` only when intent is unsupported
- recognized but unsuccessful flows (ambiguous/not_found/etc.) are still `supported=True`

## FinalResponse
This is the main stable caller-facing contract.

It exposes:
- `final_text`
- `outcome`
- `supported`
- `intent`
- `review_passed`
- `llm_used`
- `captain` (optional structured metadata for successful `captain_score` responses only)
- `captain_ranking` (optional structured metadata for successful captain ranking responses only)
- `comparison` (optional structured metadata for successful `compare_players` responses only)
- `transfer` (optional structured metadata for successful `transfer_advice` responses only)
- `chip` (optional structured metadata for successful `chip_advice` responses only)
- `fixture_run` (optional structured metadata for successful `player_fixture_run` responses only)
- `differential` (optional structured metadata for successful `differential_picks` responses only)
- `sub_responses` (optional tuple of per-sub-intent `FinalResponse` objects for `multi_intent` turns only)

The `captain` field is additive and defaults to `None` for non-captain or unsuccessful turns. When present, it contains bounded deterministic captain metadata only.
The `captain_ranking` field is additive and defaults to `None` for non-ranking or unsuccessful turns. When present, it contains bounded deterministic ranking metadata only.
The `comparison` field is additive and defaults to `None` for non-comparison or unsuccessful turns. When present, it contains grounded comparison metadata such as winner, margin, label, and reasons.
It may also include bounded per-player context for successful comparison turns where that deterministic data is available.
The `transfer` field is additive and defaults to `None` for non-transfer or unsuccessful turns. When present, it contains bounded deterministic transfer metadata only.
The `chip` field is additive and defaults to `None` for non-chip or unsuccessful turns. When present, it contains bounded deterministic chip advice metadata only: `chip`, `recommendation`, `gw`, `signal_value`, and `signal_label`. `signal_value` and `signal_label` are `None` for `free_hit` (missing_context by design) and when a chip's signal cannot be computed.
The `fixture_run` field is additive and defaults to `None` for non-fixture or unsuccessful turns. When present, it contains bounded deterministic fixture run metadata: `web_name`, `team_short`, `position`, `horizon`, `current_gameweek`, and `fixtures` (a tuple of `FixtureEntry` objects each with `gameweek`, `opponent_short`, `is_home`, `difficulty`). This field is retrieval-only — no predictive commentary is attached.
The `differential` field is additive and defaults to `None` for non-differential or unsuccessful turns. When present, it contains bounded deterministic differential picks metadata: `ownership_threshold` (15.0), `top_n` (int), and `picks` (tuple of `DifferentialEntry` with `rank`, `web_name`, `team_short`, `position`, `captain_score`, `ownership`, `now_cost`). Players are filtered to `status='a'` and `ownership < threshold`. Ranking uses the canonical captain score engine — same as captain, comparison, and transfer intents.
For `multi_intent` turns, `sub_responses` may expose the same bounded structured metadata per relevant sub-intent, while still excluding per-sub-response debug bundles.

Debug details are opt-in and separate.

---

# LLM Layer Intent

## What already exists
There is now a real LLM integration layer.

It is bounded:
- prompt builder is structured/testable
- LLM output is reviewed
- fallback to deterministic backend always exists

The LLM layer can now also assist with intent classification for natural phrasings, but only as a bounded routing helper.
Current classification behavior is intentionally conservative:
- deterministic routing runs first
- LLM classification only fires on routing miss
- classification is confidence-gated
- classification may only map into already-supported intents
- the resulting canonical question still goes through the deterministic routing and backend path
- invalid, low-confidence, or unroutable classifications degrade safely to unsupported behavior

An additional bounded routing bias, `intent_hint`, exists as a **pre-classifier** option (V2 Phase 1c — complete).
`intent_hint` fires only when deterministic routing returns no match, and before the LLM classifier.
It is strictly bounded:
- deterministic router wins — if `route(question)` succeeds, `intent_hint` is completely ignored
- allowlisted to 7 values: `captain_score`, `rank_candidates`, `compare_players`, `transfer_advice`, `chip_advice`, `player_fixture_run`, `differential_picks`
- invalid or unrecognised hints are silently ignored; the question falls through to unsupported behavior
- provider-neutral — fires without any LLM call; uses only deterministic canonical-question synthesis
- session usage is per-turn only; the hint is not stored in session state and does not affect subsequent turns
`classification_source` on `DispatchResult` is set to `"intent_hint"` when this path fires, `"llm_classifier"` for LLM fallback, and `None` for deterministic routing.
UI slash-command integration (the primary consumer of `intent_hint`) is a separate downstream concern; the backend contract is stable and complete.

## LLM review/hardening already exists
Unsafe LLM outputs are detected via deterministic checks such as:
- invented numbers
- overconfidence on non-ok outcomes
- false ambiguity resolution
- empty LLM output

If review fails:
- safe deterministic text is used instead

## Key principle
> The LLM is a presentation and interpretation layer, not a reasoning authority for football truth.

For intent classification specifically, the LLM may help select an existing deterministic path, but it must not infer football facts, bypass player extraction rules, or override downstream deterministic ambiguity/not-found behavior.

---

# Multi-turn / Reference Resolution Intent

## Resolution chain (innermost → outermost)

Each turn passes through a layered resolver chain before routing:

1. **Deterministic comparison follow-up** — catches narrow comparison references ("what about X?", "the other one", pronouns like "him") using regex; updates `last_comparison` state
2. **LLM-assisted comparison follow-up** — handles Spanish + elliptical comparison references that deterministic patterns miss (e.g. "¿Y Salah?", "vs Saka", "Or Saka?"); uses dedicated comparison context, extracts only a new player name, and falls back if LLM unavailable or confidence < 0.5
3. **Deterministic transfer follow-up** — catches narrow transfer substitutions such as "what about X instead?" after a successful transfer turn; updates `last_transfer` state and rewrites to the existing `sell ... for ...` pattern
4. **Deterministic pronoun resolution** — word-boundary-safe substitution ("him" → last player name)
5. **LLM-assisted reference resolution** — general English/Spanish/elliptical reference rewriting; graceful fallback to step 4 if LLM unavailable

The comparison-specific LLM resolver (step 2) is separate from the general reference resolver (step 5) because comparison follow-ups require `last_comparison` context and different prompt framing.
Comparison intent also remains intentionally excluded from the general reference resolver's intent list.

Examples handled:
- What about him?
- And Salah?
- ¿Y él?
- ¿Y Salah?
- ¿Y Saka?
- ¿Y como capitán?
- ¿Y como delantero? (comparison context)
- vs Saka
- Or Saka?

If steps 2 or 3 do not produce a valid rewrite, the failure is never surfaced directly to the user; resolution simply continues through the remaining resolver path and then the deterministic fallback layers.

For debug-oriented session flows, resolver auditability now preserves comparison-specific and transfer-specific follow-up sources distinctly, so direct questions, deterministic comparison follow-up, LLM-assisted comparison follow-up, and deterministic transfer follow-up can be told apart without changing default caller behavior.

## Important architectural rule
The LLM may resolve the reference and rewrite the question,
but the rewritten question still goes through the deterministic backend.

---

# Session Intent

## HTTP session support exists
There is now explicit in-memory session support over HTTP.

Lifecycle:
- create
- ask within session
- inspect
- clear

## Session limitations
This is still:
- in-memory only
- single-instance only
- not persistent
- not load-balancer safe
- not multi-worker shared state

TTL/cap/session hygiene have already been added.

Session ask debug flows can expose bounded resolver metadata for auditability.
Session inspect now also exposes a bounded snapshot of recent session state, such as last intent, last player, last comparison, last transfer, and last resolver source, while still avoiding full transcript or replay behavior.

`POST /session/{id}/ask` also accepts an optional `intent_hint` field in the request body (V2 Phase 1c — complete).
The bias is per-turn: it is not stored in session state and does not affect subsequent turns.
All `intent_hint` invariants described in the LLM Layer Intent section apply identically to session ask requests.

---

# External Interfaces That Exist

## CLI
Thin CLI exists.
- default: print final text
- debug: print structured response/debug info

An interactive live-data REPL shell also exists for manual acceptance testing.
It preserves session context in-process, supports slash commands such as `/help`, `/debug`, `/reset`, `/gw`, and `/quit`, and is now the primary operator-facing UAT surface before any post-MVP expansion.

CLI flows can now optionally use LLM-assisted intent classification when a classifier client is provided, and debug output can expose bounded classification-source metadata.
For successful captain turns, CLI debug output can now surface the same structured `captain` payload used by programmatic interfaces, while non-debug CLI output remains text-only.
For successful comparison turns, CLI debug output can now surface the same structured `comparison` payload used by programmatic interfaces, while non-debug CLI output remains text-only.

## HTTP
Endpoints include:
- stateless ask
- health
- session create
- session ask
- session inspect
- session clear

For comparison turns, stateless and session ask responses can now include additive structured `comparison` data alongside the existing final text fields.
That comparison data can include bounded player A and player B sub-objects for programmatic consumers.
Session-oriented structured outputs now also preserve that comparison payload per successful comparison turn.
The session inspect endpoint can now expose a concise operational summary of the most recent session state without changing ask-flow response contracts.

For successful direct captain-score turns, stateless and session ask responses can now also include additive structured `captain` data alongside the existing final text fields.
For successful ranked captain turns, stateless and session ask responses can also include additive structured `captain_ranking` data alongside the existing final text fields.
HTTP and session ask flows can now also use LLM-assisted intent classification when a classifier client is provided, while preserving deterministic-first routing and safe fallback behavior.

`POST /ask` and `POST /session/{id}/ask` also accept an optional `intent_hint: str | None` field (V2 Phase 1c — complete).
The hint is a bounded, pre-classifier routing bias: deterministic router wins; allowlisted to 7 values; invalid hints ignored safely.
`classification_source` in the debug bundle indicates whether deterministic routing, `intent_hint`, or the LLM classifier resolved the intent.
The Anthropic classifier client is now safely initialized at server startup via `_try_init_classifier_from_env()` when `ANTHROPIC_API_KEY` is set; it stays `None` silently on missing key, missing package, or construction error (V2 Phase 1b — complete).
The server is now containerized with a production-safe `Dockerfile` and `.dockerignore` at the repo root; build context includes all sibling packages (V2 Phase 1a — complete).

## Examples/docs
There are executable examples and contract docs for:
- stateless usage
- session lifecycle
- CLI/HTTP flows
- comparison exposure

There are now also explicit UAT artifacts for human manual testing:
- `UAT_RUNBOOK.md`
- `UAT_CHECKLIST.md`
- `UAT_FINDINGS_TEMPLATE.md`

Examples now also demonstrate structured comparison payloads, including bounded per-player comparison context in CLI debug, HTTP, and session flows.
Examples now also demonstrate structured captain payloads in CLI debug, stateless HTTP, and session flows, with explicit absence on non-captain turns.
Examples now also demonstrate ranked captain behavior across CLI debug, stateless HTTP, and session flows. Phase 5 example parity is now complete for comparison, direct captain score, and ranked captain outputs.
Examples now also demonstrate structured transfer and chip payloads across CLI debug, stateless HTTP, and session flows, including multi-intent sub_response exposure and explicit absence behavior on non-transfer and non-chip turns. The structured-metadata parity wave is now complete for captain, ranked captain, comparison, transfer, and chip.
The project now also has frozen validation artifacts: a readable scenario corpus, a cross-surface smoke runner, a machine-readable results baseline, and a human-readable validation report. Validation Corpus V2 now checks structured metadata presence/absence parity across all current metadata families and serves as the MVP closeout gate.

---

# What “Good Responses” Should Look Like

## For supported successful queries
Responses should be:
- grounded
- concise
- consistent with backend signals
- clear about captain/comparison framing

Example qualities:
- mention tier where relevant
- mention comparison reasons where relevant
- preserve deterministic semantics
- avoid overclaiming

## For ambiguous/not_found/missing cases
Responses should:
- stay explicit
- not invent player facts
- not silently choose a player
- remain helpful but bounded

## For unsupported queries
Responses should:
- say the system does not support that intent yet
- not fake an answer
- avoid pretending broader coverage than exists

---

# Current Development Philosophy

## What to preserve
- deterministic backend authority
- explicit contracts
- narrow scope per slice
- additive changes
- test-first / validator-heavy approach
- independent validation evidence across surfaces, not only slice-local green tests
- interface consistency across CLI / HTTP / sessions

## What to avoid
- broadening scope too fast
- bypassing the tool/contract architecture
- making LLMs authoritative
- unbounded memory
- hidden orchestration paths
- casual contract changes

---

# Current State of the Roadmap

The system has already completed major work in these areas:
- consolidation into shared packages
- deterministic captain flow
- captain tier framing consistency across rendered direct and ranked outputs
- bounded structured captain metadata exposure for successful direct captain-score turns
- debug/example parity for structured captain data without changing default caller behavior
- bounded structured ranked captain metadata exposure for successful ranking turns
- debug/example parity for ranked captain data without changing default caller behavior
- deterministic comparison flow
- context assembly
- tool contracts and runner
- grounded assistant harness
- LLM layer
- LLM safety review
- final response policy
- CLI
- HTTP
- sessions
- comparison normalization
- comparison explainability
- comparison exposure consistency
- comparison follow-up explainability parity across direct, stateless, and session flows
- role-aware comparison context and richer deterministic set-piece phrasing
- bounded structured comparison player context exposure for programmatic callers
- debug/example parity for structured comparison data without changing default caller behavior
- comparison resolver-source auditability in debug-oriented session surfaces
- bounded session inspect audit snapshot for recent session state
- multilingual reference resolution
- LLM-assisted comparison follow-up resolution for narrow comparison turns, including Spanish and elliptical English patterns
- resolver auditability
- session hygiene/docs/examples
- frozen validation corpus for realistic grounded scenarios
- cross-surface smoke runner and validation artifacts baseline
- LLM-assisted intent classification on deterministic routing miss, validated against the frozen baseline
- classifier parity across CLI, stateless HTTP, and session ask surfaces
- deterministic transfer advice for two-player transfer-style prompts
- validation corpus coverage for direct and not-found transfer scenarios across CLI and HTTP
- deterministic chip advice for triple captain, wildcard, bench boost, and free hit
- validation corpus coverage for chip advice scenarios across CLI and HTTP
- multi-intent orchestration for conjunctive questions splitting on " and " into two independently-routable sub-intents
- validation corpus coverage for multi-intent scenarios across CLI and HTTP
- structured sub-response metadata (captain, comparison, captain_ranking) exposed per sub-intent in multi-intent turns across CLI debug, HTTP ask, and session ask surfaces
- bounded structured transfer metadata (TransferMeta) exposed for transfer_advice OK turns across CLI debug, HTTP ask, and session ask surfaces; sub_responses entries also expose transfer when a sub-intent is transfer_advice OK
- bounded structured chip advice metadata (ChipAdviceMeta) exposed for chip_advice OK turns across CLI debug, HTTP ask, and session ask surfaces; sub_responses entries also expose chip when a sub-intent is chip_advice OK; signal_value/signal_label expose chip-specific deterministic signal per chip type
- debug/example parity for transfer and chip metadata across CLI debug, HTTP ask, session ask, and multi-intent sub_response examples
- deterministic transfer follow-up resolution with `last_transfer` session state and `transfer_followup` resolver-source auditability
- deterministic `player_fixture_run` intent for upcoming fixture schedules; resolves player deterministically, returns bounded `FixtureRunMeta` (web_name, team_short, position, horizon, current_gameweek, fixtures); supports suffix ("Salah fixtures", "Haaland's fixtures"), prefix ("fixtures for Salah", "upcoming fixtures for Haaland"), and next-N forms ("Salah next 5 games"); horizon defaults to 5; no predictive commentary
- `FixtureEntry` / `FixtureRunMeta` frozen dataclasses in `final_response.py`; `FinalResponse.fixture_run` field; exposed across CLI debug, HTTP `/ask`, and session `/session/{id}/ask`; validation corpus scenarios `fixture_run_direct` and `fixture_run_not_found`
- deterministic `differential_picks` intent for low-ownership player recommendations; filters `status='a'` players with `selected_by_percent < 15.0` and ranks by canonical captain score (same engine as captain/comparison/transfer); defaults: threshold=15.0%, top_n=5; supported prompts: "good differentials", "differential options", "low ownership picks", "best differentials this week", "differentials", "low owned players"
- `DifferentialEntry` / `DifferentialPicksMeta` frozen dataclasses in `final_response.py`; `FinalResponse.differential` field; exposed across CLI debug, HTTP `/ask`, and session `/session/{id}/ask`; validation corpus scenarios `differential_picks_direct` and `differential_picks_low_ownership`
- **Phase 7j: Validation Corpus V2** — V2 sweep and gate for the MVP wave. Added 4 new `expect_*` fields to `ValidationScenario` (expect_transfer, expect_chip, expect_fixture_run, expect_differential). Updated scenarios 17/25/26 to assert structured metadata. Added scenario #30 (`transfer_followup_det`, session surfaces, resolver_source=transfer_followup) and #31 (`differential_picks_structured`, DIFFERENTIAL_BOOTSTRAP ok-path). Added `DIFFERENTIAL_BOOTSTRAP` to `conversation_fixtures.py` and `__init__.py`. Fixed CLI surface gap: `_serial_differential()` added to `fpl_cli.py`, wired into `run()` and `run_session()`. Smoke runner extended: all 4 surface runners extract transfer/chip/fixture_run/differential; `_check_scenario_result()` asserts presence and structural correctness; `_check_cross_surface_parity()` checks null/non-null presence consistency across surfaces. `write_markdown_artifact()` renders new structured fields in per-surface table. 31/31 scenarios PASS. `validation_results.json` and `validation_report.md` regenerated. V1 gate closed.
- **UAT Readiness Phase** — Feature expansion is intentionally paused pending manual acceptance. The existing live-data REPL (`fpl_repl.py`) is the primary UAT surface; single-turn CLI and HTTP/session flows are secondary verification paths. Human-facing artifacts now exist for execution and evidence capture: `UAT_RUNBOOK.md`, `UAT_CHECKLIST.md`, `UAT_FINDINGS_TEMPLATE.md`, and the current pass record `UAT_FINDINGS.md`. The current gate is confidence and defect discovery, not new capability. The previously identified live `player_fixture_run` blocker is now fixed: assembled live bootstrap now injects `team_fixtures`, and focused retesting passed across REPL, CLI debug, and HTTP `/ask`. Explicit unsupported injury prompts remain correct non-blocking behavior, and team fixture prompts remain out of scope.
- **V2 Phase 1a — Container** — Production-safe `Dockerfile` for `fpl_server.py` (FastAPI + uvicorn). Build context is repo root; copies all sibling packages into `/app/packages/`. CMD uses `${PORT:-8000}` for Railway compatibility. `.dockerignore` added at repo root. `requirements.txt` pinned. Complete.
- **V2 Phase 1b — Classifier Startup Wiring** — `_try_init_classifier_from_env()` added to `fpl_server.py`. Called in lifespan when `_classifier_client is None`. Builds Anthropic client from `ANTHROPIC_API_KEY` silently; stays `None` on any failure. `if _classifier_client is None` guard preserves test-injected stubs. `anthropic>=0.40.0` added to `requirements.txt`. Complete.
- **V2 Phase 1c — `intent_hint` Implementation** — Optional `intent_hint: str | None` threaded through `dispatch()` → `adapt()` → `ask_llm()` → `ask_llm_safe()` → `respond()` → `/ask` and `/session/{id}/ask`. Fires only on deterministic router miss, before LLM classifier. Allowlisted to 7 values via `INTENT_HINT_ALLOWLIST`. Uses `_HINT_CANONICAL_TEMPLATES` to synthesize routeable canonical questions. `classification_source="intent_hint"` on `DispatchResult` when hint fires. 69/69 tests pass. Complete.
- **V2 Phase 1d — `intent_hint` Documentation Parity** — `FINAL_RESPONSE_CONTRACT.md` updated with `intent_hint` signature entry and dedicated semantics section. `SESSION_CONTRACT.md` updated with per-turn session note. Three HTTP examples added (`intent_hint_valid`, `intent_hint_no_change`, `intent_hint_invalid_safe`) and one session flow (`intent_hint_session`) added to examples modules. `run_session_flow()` extended to forward `intent_hint` and `debug` per turn. `run_phase_v2_intent_hint_examples_tests.py` created (22/22 pass). Complete.
- **V2 Phase 1e — Architecture Doc Parity** — `orchestrator-instructions.md` and `HANDOFF.md` updated to reflect V2 backend completions. `intent_hint` invariants, LLM-classifier status, V2 roadmap entries, and next-step guidance all brought into parity. `run_phase_v2_doc_parity_tests.py` created (44/44 pass). Complete.
- **V2 Phase 1f — HTTP Contract Fixtures** — `http_contract_fixtures.json` created as the canonical machine-readable HTTP contract for downstream consumers. Covers `POST /ask` and `POST /session/{id}/ask` request shapes, response invariants with `stable`/`conditional`/`debug_only` stability annotations, `intent_hint` contract invariants, and `http_status_contract` table. `run_phase_v2_http_contract_tests.py` verifier created (126/126 pass). `FINAL_RESPONSE_CONTRACT.md` updated with pointer to the JSON artifact. Complete.

---

# Recommended Next-Step Direction

## Current V2 backend status (as of 2026-04-01)

V2 Phase 1 backend is **complete**:
- V2 Phase 1a — Container (Dockerfile, .dockerignore, requirements.txt)
- V2 Phase 1b — Classifier startup wiring (`_try_init_classifier_from_env()`)
- V2 Phase 1c — `intent_hint` implementation (full stack threading, 69/69 tests)
- V2 Phase 1d — `intent_hint` documentation parity (22/22 tests; contract docs and examples updated)
- V2 Phase 1e — Architecture doc parity (44/44 checks; `orchestrator-instructions.md` + `HANDOFF.md`)
- V2 Phase 1f — HTTP contract fixtures (126/126 pass; `http_contract_fixtures.json` + verifier)

The backend now supports slash-command routing bias (`intent_hint`) as a stable, provider-neutral, pre-classifier mechanism.
`http_contract_fixtures.json` is the canonical machine-readable HTTP contract for downstream consumers — it encodes request shapes, response invariants with stability annotations, and the `intent_hint` contract in one self-contained JSON artifact.
UI slash-command integration is the next downstream consumer; that work lives in the UI layer, not in this package.

## Next directions

Backend is stable. Remaining work falls into two tracks:

**UI/product track (deferred — do not open in this package):**
- `fpl-ui` slash-command surface that passes `intent_hint` to the backend
- Spanish-first UI per V2 MVP roadmap
- Patreon-gated session management

**Backend stabilization (permitted if UAT surfaces gaps):**
- DGW/BGW detection for `free_hit` if live usage shows it is the highest-value gap
- Fixture-run or differential follow-up resolution only if real usage demonstrates a clear need
- Carefully scoped session refinements if manual testing shows friction

Avoid immediately jumping to:
- broad open chat
- multi-intent reasoning beyond current "and"-split
- persistence/auth-heavy infra
- large frontend build-outs in this package
- uncontrolled memory features

---

# Instructions for Any New Chat / Agent

When continuing work on this project:

1. Assume the current architecture is intentional.
2. Do not bypass the deterministic backend.
3. Do not replace stable contracts casually.
4. Treat LLMs as bounded helpers only.
5. Keep new slices narrow and testable.
6. Preserve interface consistency across:
   - internal contracts
   - CLI
   - HTTP
   - sessions
7. Prefer additive changes over refactors unless architectural cleanup is explicitly needed.
8. If adding a new capability, ensure it fits the existing path:
   - route
   - tool/contract
   - runner
   - renderer/explainer
   - dispatch
   - adapter
   - final response

---

# Short “One-Paragraph” Summary

This project is a grounded FPL assistant where the deterministic backend is the source of truth and the LLM is only allowed to interpret references or improve phrasing. It supports captaincy, player lookup, summaries, current gameweek, two-player comparison, transfer advice, chip advice, multi-intent orchestration, player fixture run, differential picks, HTTP/CLI access, and in-memory conversational sessions. Stable response contracts exist, LLM outputs are reviewed and can fall back safely to deterministic text, and all intent responses include structured reasoning, editorial framing, and additive metadata for programmatic callers. Every intent that produces structured output — captain, comparison, captain_ranking, transfer, chip, fixture_run, differential — exposes a frozen dataclass on FinalResponse, serialized identically across CLI debug, HTTP /ask, and session /session/{id}/ask. Transfer follow-ups are resolved deterministically via last_transfer session state; comparison follow-ups via a two-tier resolver (deterministic, then LLM-assisted). The MVP wave (Phases 6a–7j) is complete and automated validation is green at 31/31 scenarios. V2 Phase 1 is also complete (Phases 1a–1f): the server is containerized (1a), the Anthropic classifier client is safely initialized at startup (1b), `intent_hint` — a bounded pre-classifier routing bias for slash-command integration — is implemented and documented across the full stack (1c–1d), architecture docs are in parity (1e), and a machine-readable JSON HTTP contract fixture artifact (`http_contract_fixtures.json`) now provides downstream consumers with request shapes, response invariants annotated with stability levels, and the full `intent_hint` contract in one self-contained file (1f). `intent_hint` is allowlisted to 7 values, fires only on deterministic router miss, is ignored safely when invalid, is per-turn in session flows, and is provider-neutral. The backend contract is stable and ready for UI slash-command consumption.
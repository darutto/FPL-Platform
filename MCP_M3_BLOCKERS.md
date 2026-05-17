# MCP_architecture — M3 Mandatory Blockers

**Status:** OPEN. M3 (Orchestrator Wiring) MUST NOT begin until every item below is resolved.
**Established:** 2026-05-11, end of M0 (Lead Orchestrator review + Adversarial Architecture Reviewer pass).
**Owner at resolution time:** Orchestrator Wiring Agent (M3), Opus-tier.

This file is the single source of truth for M3 pre-requisites. The Lead Orchestrator gates M3 kick-off on every item here being CLOSED. Items are not optional improvements — they are deterministic-safety prerequisites identified during M0 review.

---

## Blocker B1 — `tool_schema_registry._ALL_SCHEMAS` is missing 7 of 17 grounded tools

**Source:** `MCP_INTENT_AUDIT.md` §3 drift note + §9 item 2; `MCP_INTENT_AUDIT_REVIEW.md` Action 2.

**Detail:** `packages/fpl-grounded-assistant/fpl_grounded_assistant/tool_schema_registry.py` registers only the original 10 grounded tools. The 7 Phase-2.6 tools are absent from the registry:

1. `get_player_form`
2. `get_injury_list`
3. `get_price_changes`
4. `get_team_fixture_calendar`
5. `get_team_schedule`
6. `get_position_fixture_run`
7. `get_transfer_suggestion`

**Why this blocks M3:** `ask_orchestrated()` can only call tools whose schemas are registered. Wiring the orchestrator as the open-prose fallback without extending the registry would silently expose only 10 of the 17 capabilities — the orchestrator would fail to answer questions whose deterministic surface depends on the 7 missing tools.

**Resolution required before M3 begins:** Extend `tool_schema_registry._ALL_SCHEMAS` with JSON schemas for all 7 Phase-2.6 tools, including `to_openai()` / `to_anthropic()` parity. Add a parity test that asserts `len(_ALL_SCHEMAS) == 17` and that each `INTENT_*` constant in `SUPPORTED_INTENTS` has at least one tool whose schema is in the registry.

**Evidence of resolution (M3 preflight, pending Lead + Independent Verifier confirmation):**
`packages/fpl-grounded-assistant/fpl_grounded_assistant/tool_schema_registry.py` now registers all 17 tools (GET_PLAYER_FORM_SCHEMA, GET_INJURY_LIST_SCHEMA, GET_PRICE_CHANGES_SCHEMA, GET_TEAM_FIXTURE_CALENDAR_SCHEMA, GET_TEAM_SCHEDULE_SCHEMA, GET_POSITION_FIXTURE_RUN_SCHEMA, GET_TRANSFER_SUGGESTION_SCHEMA added).
`packages/fpl-grounded-assistant/run_phase_m3_preflight_tests.py` asserts `len(_ALL_SCHEMAS) == 17`, OpenAI/Anthropic/Gemini serialisation shape for each, and full SUPPORTED_INTENTS coverage via `_TOOL_TO_INTENT`.

Verified by: M3 preflight runner — `run_phase_m3_preflight_tests.py` (B1.* assertions PASS). Lead Orchestrator + Independent Verifier confirm.

---

## Blocker B2 — `intent_classifier.CLASSIFIER_SYSTEM_PROMPT` omits 3 supported intents

**Source:** `MCP_INTENT_AUDIT_ADVERSARIAL_REVIEW.md` (the genuinely-new finding the Lead missed).

**Detail:** The classifier system prompt in `packages/fpl-grounded-assistant/fpl_grounded_assistant/intent_classifier.py` enumerates ~15 intents but omits:

1. `differential_picks`
2. `position_fixture_run`
3. `multi_intent`

**Why this blocks M3:** The classifier is the **second** deterministic fallback (router → classifier → orchestrator). If the classifier prompt does not know an intent exists, it cannot rewrite ambiguous user prose into a canonical form for that intent — meaning those intents fall through to the orchestrator with no classifier-rewrite opportunity, and (for `position_fixture_run`, which is also absent from the schema registry per B1) the orchestrator has no tool to call. The audit's §5/§10 claim "every supported intent has a deterministic primary surface, no orchestrator-only intents" presumes both fallbacks are intent-aware. They are not, today.

**Resolution required before M3 begins:** Extend the classifier system prompt to enumerate all 17 supported intents, with canonical-question examples in both English and Spanish for the three missing intents. Add a test that asserts the prompt string contains each `INTENT_*` constant name.

**Evidence of resolution (M3 preflight, pending Lead + Independent Verifier confirmation):**
`packages/fpl-grounded-assistant/fpl_grounded_assistant/intent_classifier.py` extends `CLASSIFIER_SYSTEM_PROMPT` with three new labelled sections (`differential_picks:`, `position_fixture_run:`, `multi_intent:`) each carrying English AND Spanish canonical-question examples. `_CONFIDENCE_THRESHOLD` remains `0.7` and `IntentClassification` is untouched.
`run_phase_m3_preflight_tests.py` asserts every member of `SUPPORTED_INTENTS` (17) plus `multi_intent` appears in the prompt and that the three previously-missing intents have their own labelled sections with Spanish phrasings.

Verified by: M3 preflight runner — `run_phase_m3_preflight_tests.py` (B2.* assertions PASS). Lead Orchestrator + Independent Verifier confirm.

---

## Status table

| ID | Blocker | Owner | Status |
|---|---|---|---|
| B1 | `tool_schema_registry` missing 7 of 17 tools | M3 Orchestrator Wiring Agent | CLOSED (pending Lead confirm) |
| B2 | `classifier system prompt` missing 3 of 18 intents | M3 Orchestrator Wiring Agent | CLOSED (pending Lead confirm) |

**Count semantics (Lead-approved 2026-05-14):** "17+1" — `SUPPORTED_INTENTS` (frozenset in `dispatcher.py`) holds the 17 deterministic intents; `multi_intent` is a classifier-recognised meta-intent that composes sub-intents and lives outside the frozenset. The classifier-visible universe is therefore 17 + 1 = 18. Tests and the prompt enumerate all 18; tool schemas cover only the 17 deterministic ones (multi_intent is composition, not a tool).

The Lead Orchestrator will close items here only after they are verified in-code with passing tests. M3 phase kick-off is gated on `OPEN → CLOSED` for every row.

**Preflight regression status (recorded by M3 preflight agent):**
- `run_phase_m1_tests.py`: 49/49 PASS (unchanged).
- `run_phase_m2_tests.py`: 58/58 PASS (unchanged).
- `run_validation.py`: 106/106 scenarios PASS (unchanged).
- `run_phase_m3_preflight_tests.py`: 130/130 PASS.

---

## Downstream contract notes (logged at end of M3, 2026-05-17)

These are not blockers for M3 itself (the slice is approved by the Independent Verifier and conditionally cleared by the Adversarial Architecture Reviewer). They are hand-off contracts the next two phases must honor. They were surfaced by the Adversarial Architecture Reviewer at end-of-M3 and recorded here so they cannot be lost.

### M4 hand-off — D-suite Spanish phrase contract (Adversarial finding F7)

The M3 test runner `run_phase_m3_tests.py` exercises the orchestrator branch using one deliberately-unroutable Spanish phrase:

> `"darme un consejo holistico sobre mi banco esta semana segun el calendario"`

This phrase must remain unroutable for the D-suite to actually exercise step 3 (orchestrator) rather than silently being absorbed by step 1 (deterministic `route()`). M3 added a one-line guard at `run_phase_m3_tests.py:296-300` that fails fast if `route()` ever absorbs the phrase.

**M4 (Spanish Hardening) contract:** before removing any Spanish alias coverage *for `banco` or fixture-related vocabulary that could absorb this phrase*, the M4 agent MUST either:

1. Verify the D-suite guard still passes against the new alias tables, OR
2. Supply a fresh unroutable Spanish phrase for the M3 runner AND update the `_D_QUESTION` constant + guard message.

Failing to honor this contract means the M3 strict-ordering tests will silently start exercising the wrong code path (step 1 instead of step 3) under future M4 alias expansion. The guard prevents the silent-pass mode, but the M4 agent must take ownership of replacement.

### M5 hand-off — telemetry contract for attempted-vs-grounded tool calls (Adversarial finding R5)

The `routing_trace.orchestrator_tool_calls` field is populated whenever the orchestrator *names* a tool, even when the resulting `grounded` flag is `False` (e.g. tool execution errored, `OUTCOME_NO_TOOL`, or `OUTCOME_TOOL_ERROR`). This means:

> **`orchestrator_tool_calls` records *attempted* tool calls, not *grounded* tool calls.**

**M5 (Telemetry & Rollout) contract:** the per-branch counters added on the health surface MUST distinguish:

- `orchestrator_attempted` — tool was named (`tool_chosen is not None`).
- `orchestrator_grounded` — tool was named AND `outcome == OUTCOME_OK` AND `grounded == True`.

The two are NOT interchangeable. The graduation criteria in plan §M5 line 321 ("orchestrator handles the long tail") must be evaluated against `orchestrator_grounded`, not `orchestrator_attempted`, otherwise the rollout decision will overstate orchestrator reliability.

### routing_trace tier discipline (Adversarial finding F4)

For the M3–M4 window, `routing_trace` is a **debug-tier** field — additive, optional, observable from server-side tests and traffic shaping, but **not** part of the stable response contract. UI and external consumers must not depend on its schema. Promotion to stable-tier is an explicit M5 graduation step, not a silent relabel. The docstrings on `harness.ask_v2()` and `fpl_server.AskOrchestratedResponse` record this constraint inline.

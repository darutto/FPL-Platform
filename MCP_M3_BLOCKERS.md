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

---

## Blocker B2 — `intent_classifier.CLASSIFIER_SYSTEM_PROMPT` omits 3 supported intents

**Source:** `MCP_INTENT_AUDIT_ADVERSARIAL_REVIEW.md` (the genuinely-new finding the Lead missed).

**Detail:** The classifier system prompt in `packages/fpl-grounded-assistant/fpl_grounded_assistant/intent_classifier.py` enumerates ~15 intents but omits:

1. `differential_picks`
2. `position_fixture_run`
3. `multi_intent`

**Why this blocks M3:** The classifier is the **second** deterministic fallback (router → classifier → orchestrator). If the classifier prompt does not know an intent exists, it cannot rewrite ambiguous user prose into a canonical form for that intent — meaning those intents fall through to the orchestrator with no classifier-rewrite opportunity, and (for `position_fixture_run`, which is also absent from the schema registry per B1) the orchestrator has no tool to call. The audit's §5/§10 claim "every supported intent has a deterministic primary surface, no orchestrator-only intents" presumes both fallbacks are intent-aware. They are not, today.

**Resolution required before M3 begins:** Extend the classifier system prompt to enumerate all 17 supported intents, with canonical-question examples in both English and Spanish for the three missing intents. Add a test that asserts the prompt string contains each `INTENT_*` constant name.

---

## Status table

| ID | Blocker | Owner | Status |
|---|---|---|---|
| B1 | `tool_schema_registry` missing 7 of 17 tools | M3 Orchestrator Wiring Agent | OPEN |
| B2 | `classifier system prompt` missing 3 of 18 intents | M3 Orchestrator Wiring Agent | OPEN |

The Lead Orchestrator will close items here only after they are verified in-code with passing tests. M3 phase kick-off is gated on `OPEN → CLOSED` for every row.

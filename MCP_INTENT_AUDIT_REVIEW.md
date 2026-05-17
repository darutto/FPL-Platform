# MCP_INTENT_AUDIT — Lead Orchestrator Review

**Reviewer:** Lead Orchestrator (acting inline; persistent agent at `.claude/agents/lead-orchestrator.md`)
**Reviewed doc:** [`MCP_INTENT_AUDIT.md`](MCP_INTENT_AUDIT.md)
**Date:** 2026-05-11
**Phase:** M0 (Intent Audit and Capability Mapping)
**Branch:** `MCP_architecture`

---

## Per-section verdicts

| Section | Verdict | Notes |
|---|---|---|
| §1 Context / §2 Methodology | PASS | Cites file:line evidence sources. Methodology section names the inputs that were inspected and acknowledges the read-only constraint. |
| §3 Intent inventory | PASS | All 18 intents covered. Stability/Spanish/frequency/user-job/surface columns populated. File:line citations present. |
| §4 User-job clusters (A–I) | PASS with note | Nine clusters vs. the plan's hypothesized six. Extra granularity (separating "comparativas" from "capitanía"; splitting "identidad y meta" out) is defensible and improves resolution. No rework. |
| §5 Surface-assignment table | PASS | All four surface-selection rules applied. Reasoning is explicit per intent. |
| §6 M1 resource verdict | PASS with required pre-implementation step | All six confirmed. `@injuries` recency-field caveat is the only open item (see Action 1 below). |
| §7 Ambiguity hot spots / Spanish fragility | PASS | Concrete phrasings, owner = M4 explicitly named. Cross-collision in §7.3 (`team_schedule` vs `player_fixture_run`) is a real disambiguator for M4. |
| §8 Confidence section | PASS | Honest about what was not verifiable from a static read. |
| §9 Out-of-scope notes | PASS, escalated | Items 1–3 require Lead decisions before M3 can start (see Action 2 below). |
| §10 Primary-surface summary | PASS | Matches §5 row-for-row. |

## Judgment calls reviewed

- **`transfer_suggestion` → `text+route()` instead of `/fichar`.** Defended on grounds of well-tested Spanish prose corpus (12 scenarios). Accept. A future `/fichar` is still possible but not for M2.
- **`@prices` and `@differentials` deferred** out of the M1 resource set. Consistent with plan discipline (plan lines 206–208). Accept.
- **`/clasificacion` not yet in the UI slash-commands registry.** Flagged correctly for M2. Accept.

## Drift / scope-creep check

No drift detected. The audit did not propose new backend tools, did not redesign routing, did not promote anything from fallback to primary. All recommendations are additive within the approved scope.

---

## Verdict

**APPROVE the M0 audit document**, conditional on the following actions before the phase is marked complete:

### Required next step (per plan): Adversarial Architecture Reviewer pass on M0

The plan explicitly requires an Adversarial Architecture Reviewer pass on M0 surface-assignment decisions before M1 may start. Do not mark M0 complete until that review returns CLEAR or CONDITIONAL-with-resolved-items.

### Actions absorbed into downstream phases

1. **M1 pre-implementation check (Resource Surface Agent):** before implementing `@injuries` ranking, fetch one live `bootstrap-static` payload and verify `news_added` is populated on the majority of elements with `status != "a"`. If sparse, fall back to `chance_of_playing_this_round` ascending as the primary sort. Cite the verification in the M1 PR/commit. (Audit §6 + §8.)

2. **M3 pre-requisite (Orchestrator Wiring Agent):** the `tool_schema_registry._ALL_SCHEMAS` currently exposes only the original 10 grounded tools; the 7 Phase-2.6 tools (player_form, injury_list, price_changes, team_fixture_calendar, team_schedule, position_fixture_run, transfer_suggestion) are missing. M3 wiring **must** extend the registry to cover all 17 tools before connecting `ask_orchestrated()`. This is now an M3 pre-req, not an optional improvement. (Audit §9 item 2.)

3. **M4 owner-handoff (Spanish Hardening Agent):** ingest §7's three high-risk items verbatim as M4 work:
   - Spanish transfer-advice prose (`_TRANSFER_PREFIXES` / `_TRANSFER_CONNECTORS` extension)
   - Spanish player-fixture-run prose (`_FIXTURE_RUN_PREFIXES` / `_FIXTURE_RUN_SUFFIXES` extension)
   - `team_schedule` vs `player_fixture_run` collision on `"calendario de X"`

4. **Manifest cleanup (not blocking; recorded for a future docs/manifest phase):**
   - `INTENT_MANIFEST` stale by 7 intents.
   - `packages/fpl-ui/lib/types.ts` `SUPPORTED_INTENT_VALUES` lists only 11. The plan's `ResourceResult` shape sidesteps this for M1, but UI work in later phases should reconcile.
   - `INTENT_MULTI_INTENT` declared but not in `SUPPORTED_INTENTS`. Likely intentional — flag for a one-line clarifying comment in `dispatcher.py`.

### Not adopted

- No changes requested to the six-resource M1 set. The audit's confirmation stands.
- No changes requested to the surface-assignment table.
- No changes requested to the user-job clustering.

---

## Phase gate status

- M0 audit: **conditionally approved by Lead, pending Adversarial Architecture Reviewer pass.**
- M0 phase complete: **NO.** Will be set by Lead after the adversarial pass returns CLEAR (or after CONDITIONAL items are resolved).
- M1 may begin: **NOT YET.** Blocked on M0 phase-complete sign-off.

# MCP_INTENT_AUDIT — Adversarial Architecture Review

**Reviewer:** Adversarial Architecture Reviewer (per `.claude/agents/adversarial-architecture-reviewer.md`)
**Reviewed docs:** [`MCP_INTENT_AUDIT.md`](MCP_INTENT_AUDIT.md), [`MCP_INTENT_AUDIT_REVIEW.md`](MCP_INTENT_AUDIT_REVIEW.md)
**Plan held against:** `C:\Users\thera\.claude\plans\in-this-project-we-proud-milner.md`
**Date:** 2026-05-11
**Phase:** M0 (Intent Audit and Capability Mapping)
**Branch:** `MCP_architecture`
**Disposition:** Read-only. Independent of Lead.

---

## Scope of this review

The agent definition lists ten "lines of attack." Several of them are M3- or pre-merge-specific (ask_orchestrated reimplementation, `/ask-orchestrated` becoming product, intent_hint vs prompt_registry parallel routing without transition, deterministic-vs-LLM ordering inside `ask_v2`, contract-vs-smoke testing of code, premature stability-tier promotion of fields, malicious-prompt regression of deterministic answers). M0 has no code, so those attacks are not actionable here and I record them for the M3 / pre-merge passes.

The attacks that *do* apply to a document-only phase are:

1. Has the audit silently invented capabilities (drift between plan and code)?
2. Did a "prompt" or "resource" recommendation creep into "tool call in disguise"?
3. Is `text→orchestrator` quietly carrying weight that the audit denies?
4. Is the four-surface taxonomy (`@resource` / `/prompt` / `text+route()` / `text→orchestrator`) being applied honestly, or is it papering over a real fallback need?
5. Did the audit verify the load-bearing claims about the code or did it copy plan language back?

I independently re-read `dispatcher.py:60-180`, `tool_schema_registry.py:380-391`, `injury_list.py` (whole file), `router.py:700-825`, `intent_classifier.py:40-266`, and `packages/fpl-ui/lib/types.ts:60-115`.

---

## 1. Architectural findings

### 1.1 — Verified: the 7-intent / 7-tool / 7-UI-type drift is real, and the Lead has under-stated its M3 consequence

Independently confirmed:

- `dispatcher.SUPPORTED_INTENTS` (lines 92–110): **17 intents.**
- `dispatcher.INTENT_MANIFEST` (lines 183–316): **10 entries** (only the originals). The 7 Phase-2.6 intents are absent.
- `tool_schema_registry._ALL_SCHEMAS` (lines 380–391): **10 schemas**. The 7 newer tools (`get_player_form`, `get_injury_list`, `get_price_changes`, `get_team_fixture_calendar`, `get_team_schedule`, `get_position_fixture_run`, `get_transfer_suggestion`) are not exposed to the orchestrator at all.
- `packages/fpl-ui/lib/types.ts::SUPPORTED_INTENT_VALUES` (lines 65–77): **11 values** (10 + `multi_intent`).
- `intent_classifier.py` system prompt (lines 94–266): the classifier knows about ~15 intents — but **does not include `differential_picks`, `position_fixture_run`, or `multi_intent`** in its allowlist. The audit's "14 intents" count in §2 is approximately right but blurs which seven are missing where — the three surfaces (manifest / schema / classifier / UI types) each have a *different* missing set, and the audit collapses them into one number.

The audit caught (a) and (c) and the Lead Review absorbed (c) into an M3 pre-req. **Neither caught (e):** the classifier fallback has zero ability to rewrite Spanish prose into `differential_picks` or `position_fixture_run`. This is architecturally material for the audit's central decision artifact in §10:

- `differential_picks` primary surface = `/prompt` (`/diferenciales`). Fine when the slash menu is used. But for **bare-text** Spanish ("diferenciales esta semana", "jugadores diferenciales para esta jornada"), §7.6 itself observed that `_DIFFERENTIAL_KEYWORDS` has no Spanish synonym — so `route()` misses. The classifier *also* cannot rewrite into `differential_picks` (not in its allowlist). So bare-text Spanish differentials questions fall straight through to `ask_orchestrated()`, whose schema registry does not register `get_differential_picks` either — wait, it does: `GET_DIFFERENTIAL_PICKS_SCHEMA` is in `_ALL_SCHEMAS` (line 390). So the orchestrator path can recover this case **but only when `FPL_ORCH_ENABLED` is on**. With the flag off, the bare-text Spanish phrasing for a §10-claimed-primary-surface intent has no deterministic exit.
- `position_fixture_run` primary surface = `text+route()`. §3 row 16 marks Spanish coverage "good" via `_POSITION_*` prefix tables — that's accurate. But the classifier prompt does not list `position_fixture_run` (verified by Grep against `intent_classifier.py`), so when router prefixes miss, the classifier silently routes the question to some adjacent intent or `unsupported`. The orchestrator path also has no schema for `get_position_fixture_run`. So **position_fixture_run is the one supported intent in the system that has no fallback at all** — router miss is terminal.

These are not theoretical. The audit's claim in §5 that "**Orchestrator-only intents: None. Every supported intent has a deterministic primary surface**" is *technically* true but elides the dual property: every intent has a primary surface, **but two intents (`differential_picks`, `position_fixture_run`) have only one path and no working fallback**. This is the kind of boundary mistake the agent definition tells me to look for. The Lead's review did not flag this.

**Severity:** Medium. Not blocking for M1 (M1 only ships `@injuries` + five `@top_*` resources). It becomes blocking for M3 (orchestrator wiring) — the M3 plan must extend both the schema registry **and** the classifier prompt's intent list to cover all 17, and the audit's "every intent has a primary surface" line should be amended to "every intent has a primary surface; two have no fallback today."

### 1.2 — `IntentClassification` dataclass docstring is stale ("six supported INTENT_* constants" at `intent_classifier.py:73`)

The classifier prompt now enumerates ~15 intents but the dataclass docstring still says "one of the six supported INTENT_* constants or 'unsupported'." Cosmetic by itself, but evidence that the classifier was extended without updating its contract documentation — and the audit cited the classifier as a stability witness without noticing this. Not blocking.

### 1.3 — The `transfer_suggestion → text+route()` judgment call is defensible but the audit's defense is incomplete

The audit (§3 row 17, §5, §8) chooses `text+route()` over `/fichar` on the grounds that "12 corpus scenarios" prove Spanish prose handles the multi-arg shape better than a prompt could. Lead accepted.

I push back partially. The argument confuses *test coverage* with *user-facing ergonomics*. Twelve corpus scenarios prove the existing router does not regress on the *specific* phrasings the corpus author chose; they do not prove that an open-ended Spanish user typing "necesito un delantero del Liverpool por menos de 7 millones que tenga buen calendario" will route — that's a 4-argument compound (`position`, `team`, `price_ceiling`, `horizon`) and `_TRANSFER_SUGGESTION_PREFIXES` is a finite prefix set. The honest framing is: "promotion to `/fichar` is a future option; for M2 it is out of scope and would duplicate well-tested router phrasings." That framing keeps the option open for M4/M5 if telemetry shows misses. The audit's framing ("text routing is the *better* primary") prematurely closes the door.

**Severity:** Low. Not blocking. Recommend the audit add a one-line note in §5 row `transfer_suggestion` reframing the rationale, or have the Lead absorb it as "revisit in M5 telemetry."

### 1.4 — `team_schedule` vs `player_fixture_run` collision on "calendario de X" (audit §7.3)

The audit identifies the collision and proposes a disambiguator: `_extract_team_token` first, then fall through to `player_fixture_run`. I independently verified `_extract_team_token` exists (`router.py:765-786`) and is already used inside `_try_route_transfer_suggestion`. The proposal is sound — same primitive, new caller. **No finding here.** The Lead correctly handed this to M4.

### 1.5 — `news_added` field absence and the `@injuries` recency recommendation (audit §6)

Independently verified: `injury_list.py` reads `el.get("status")` and `el.get("chance_of_playing_this_round")`. No `news_added` reference anywhere in `injury_list.py`. The audit's recommendation (sort by `news_added` ISO-8601 desc; tie-break by `chance_of_playing_this_round` asc; preserve element order as last fallback; explicitly rule out `cost_change_event`) is technically correct and the explicit "verify against a live bootstrap" gate the audit and Lead both name is the right safety. **No finding here.**

One small reinforcement: the M1 verification step the Lead listed should also confirm that `news_added` is **monotonic** with reality (i.e. an injury reported via a new `news` blurb actually bumps `news_added` rather than stays null) — without that, "most recent status change" is not the property `news_added` carries, regardless of how populated it is. Not blocking.

### 1.6 — `differential_picks` outcome=error scenarios (audit §9 item 5)

The audit notes that two corpus scenarios for `differential_picks` produce `outcome="error"`. The current `text+route()` surface can return error; a hypothetical `@differentials` resource shape should not. The audit defers `@differentials` past M1, so this is correctly out of scope. The note is good. **No finding.**

### 1.7 — Surface taxonomy is being applied honestly

I tested the four-surface rules against the more debatable rows in §5:

- `rank_candidates → text+route()` instead of `@top_captains` — defensible (zero-arg but score-computed, not a static bootstrap-field sort). A `@top_captains` resource would need to call `rank_captain_candidates` internally and would blur the "argument-free static read" contract; deferring is correct.
- `injury_list → @injuries` (not `/lesionados` prompt) — correct: zero-arg, list-shaped, read-only.
- `chip_advice → /chips` — correct: enum-bounded arg.
- `multi_intent → text+route()` — correct: composition, cannot be a leaf surface.

No taxonomy abuse detected. The audit is not promoting anything from fallback to primary; the Lead's "no scope creep" verdict holds on this axis.

### 1.8 — No pseudo-MCP runtime creep detected in M0

M0 is a document. No FastMCP, no stdio, no new process boundaries proposed. Resources stay "thin wrappers over bootstrap or existing tool functions" (audit §6). **No finding.**

### 1.9 — `/ask-orchestrated` is correctly described as rollout-isolation only

The audit does not propose any UI binding to `/ask-orchestrated`. The plan's "single user-facing logical ask surface" invariant is not eroded by anything in the audit. **No finding.** (This will be the central question of the M3 adversarial pass; flagging now so M3 reviewer revisits.)

---

## 2. Risk surface

Post-M0 risks I do not see reflected anywhere in either the audit or the Lead's review:

### 2.1 — Two intents will have no fallback when M3 ships

Per §1.1: `differential_picks` and `position_fixture_run` are absent from the classifier's intent allowlist, and `position_fixture_run` is also absent from the schema registry. If M3 wires the orchestrator without (a) extending the classifier prompt to enumerate the full supported intent set, and (b) registering `get_position_fixture_run` (and the other six) in `tool_schema_registry`, then router misses on those intents will not route through *either* fallback path. The Lead Review caught (b); neither caught (a). **Add to M3 pre-reqs: extend `intent_classifier.py`'s `CLASSIFIER_SYSTEM_PROMPT` to include all 17 supported intents (or document why specific intents are deliberately excluded).**

### 2.2 — Slash-command "expansion mode" vs "direct-dispatch" decision is not stress-tested in M0

The plan (lines 169–179) lists which prompts expand to canonical text vs dispatch directly. The audit §5 rows mention this in passing ("Direct-dispatch prompt — plan line 174") but does not name which prompts in the M2 set are at risk if the expansion-mode plan is wrong. Specifically: `/comparar a=Salah b=Palmer` expands to `"compare Salah and Palmer"` — but if the user types `/comparar` with names containing spaces or accents ("De Bruyne"), the expansion-mode path re-enters `route()` and the compare-connector logic (`_COMPARE_CONNECTORS`) may not parse cleanly. The audit does not flag compare-mode expansion fragility. Not M0-blocking — it is M2 work — but the audit's confidence section §8 should have flagged it as a "could not determine."

### 2.3 — The orchestrator's tool list will silently shrink for already-shipped intents

If M3 extends the schema registry to include the 7 new tools, the orchestrator gains coverage. But if anyone in M3 *also* adds new tool schemas with subtly different parameter shapes from `TOOL_REGISTRY` specs, the orchestrator will call them with malformed args. Not M0-actionable; flagging for M3 reviewer.

### 2.4 — `intent_hint` deprecation path is not anchored in the audit

The plan's transition table (lines 326–334) says `intent_hint` is "frozen for the duration of this branch" and "reduced to a legacy fallback" at exit. The audit does not touch this. That's fine for M0, but the M2 reviewer should check that the new `prompt_registry` path does not silently double-dip with the existing `INTENT_HINT_ALLOWLIST` path — i.e., we should not end up with two parallel routing-bias mechanisms inside one request.

### 2.5 — "Yellow stability" semantics are non-standard

The audit's legend (after §3) says yellow means "well-tested in router/corpus but invisible to one or more downstream layers (manifest/orch schema/UI types). Routing is not the problem; surface visibility is." This is sensible for the audit's purposes but conflicts with the plan's lead-language "yellow = known failure modes" (plan §M0 spec column). A future reader of the audit who maps "yellow" onto the conventional "fragile" semantics will misread §3. Recommend the audit add a one-line explicit definition at the top of §3.

---

## 3. Verdict

**CONDITIONAL — CLEAR.**

The audit is honest, evidence-cited, and does not invent capabilities. The four core load-bearing claims I spot-checked all hold:

1. The 7-intent / 7-tool / 7-UI-type drift is real and material (confirmed against `dispatcher.py`, `tool_schema_registry.py`, `types.ts`).
2. `news_added` is genuinely absent from `injury_list.py`; the recency recommendation is sound.
3. The `team_schedule` vs `player_fixture_run` collision is a real ambiguity and the proposed `_extract_team_token` disambiguator is correct.
4. The `transfer_suggestion → text+route()` judgment call is defensible (with the §1.3 caveat about framing).

The Lead Review absorbed the right items into downstream phases (M1 `news_added` verification; M3 schema registry extension; M4 Spanish-fragility ingestion).

**One genuinely new finding the Lead missed (§1.1):** the audit's "every supported intent has a deterministic primary surface" line in §5 conceals that `differential_picks` and `position_fixture_run` have no working fallback when their primary surface misses — because the classifier prompt does not enumerate them and (for `position_fixture_run`) the schema registry does not register the tool. This must be reflected in M3's pre-reqs before that phase opens, alongside the schema-registry extension the Lead already named.

**Conditions to satisfy before marking M0 complete and opening M1:**

- **C1 (M3 pre-req addition, not M1 blocker):** Extend the M3 pre-requisites in the Lead Review to include: "M3 must extend `intent_classifier.py::CLASSIFIER_SYSTEM_PROMPT` to enumerate all 17 supported intents (or explicitly document any deliberate exclusions). Without this, the classifier fallback silently strands `differential_picks`, `position_fixture_run`, and `multi_intent`." This pairs with the schema-registry extension the Lead already required.

- **C2 (M0 audit amendment, one-line):** Add a clarifying note to §5 / §10 of `MCP_INTENT_AUDIT.md` stating that while every intent has a deterministic primary surface, two intents (`differential_picks`, `position_fixture_run`) currently have no working classifier or orchestrator fallback path, and that this is being addressed as part of M3's pre-requisites.

- **C3 (low-priority audit hygiene):** Add an explicit one-line definition of the audit's "yellow" stability semantics at the top of §3 (per §2.5 above), so the legend does not collide with the plan's conventional reading.

None of C1–C3 require M0 to redo work. C1 is a one-bullet addition to the Lead Review's "Actions absorbed into downstream phases." C2 is a one-sentence edit to the audit document. C3 is a one-sentence edit to the audit document. M1 may proceed in parallel with C2/C3 since neither affects the M1 surface set, but **C1 must be in writing before M3 starts** to avoid re-discovering the gap at integration time.

If C1–C3 are accepted as written, this review converts to **CLEAR**. No fundamental drift detected. The audit is fit for purpose and the architecture holds.

---

End of adversarial review.

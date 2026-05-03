# FPL Platform — Full Project Roadmap Summary

**Last updated:** May 2026  
**Purpose:** Complete historical reference of all work completed and planned, organized by phase, for use as a milestone baseline for future feature planning.

---

## What This Project Is

A Python platform that wraps FPL (Fantasy Premier League) data and logic into a **grounded assistant**. The assistant accepts a natural-language question and returns a structured `FinalResponse` — deterministic routing and scoring with an optional LLM presentation layer on top.

**Core design principle:** the LLM is subordinate to the deterministic backend. Routing, scoring, outcome classification, and safety fallbacks are all deterministic. The LLM only phrases the grounded result; it never alters backend semantics.

---

## Architecture Overview

```
fpl-platform/
├── packages/
│   ├── fpl-captain-engine/      ← Scoring formula (TypeScript + Python)
│   ├── fpl-data-core/           ← Season registry, analytics, schemas
│   ├── fpl-api-client/          ← FPL bootstrap + fixtures HTTP client
│   ├── fpl-player-registry/     ← Player identity + nickname resolution
│   ├── fpl-query-tools/         ← Player lookup composition layer
│   ├── fpl-tool-contract/       ← Structured tools (resolve, summary, gw, captain, rank)
│   ├── fpl-tool-runner/         ← ToolSpec/ToolRegistry, in-process dispatch
│   ├── fpl-pipeline/            ← Context assembly (bootstrap + fixtures + FDR in one call)
│   ├── fpl-grounded-assistant/  ← PRIMARY PACKAGE — full end-to-end stack
│   ├── fpl-charts/              ← TypeScript theme constants (colors, brand, risk levels)
│   └── fpl-ui/                  ← Next.js frontend (App Router + shadcn/ui)
```

---

## Phase 0 — Package Consolidation and Platform Bootstrap

**Goal:** Extract captain engine and core data logic from existing projects (captaincy-showdown, captaincy-ml) into a unified platform monorepo.

**What was built:**
- `fpl-captain-engine` (TypeScript): verbatim copy of `captainScore.ts` from captaincy-showdown; exports `calculateCaptainScore`, `updateCaptainScores`, `CaptainCandidate`, `MatchupData`
- `fpl-captain-engine` (Python): cross-language parity port; exports `calculate_captain_score`, `CaptainTier`, `get_captain_tier`, `evaluate_role_signals`
- `fpl-data-core`: season registry, analytics (`compute_rolling_xgi_per_90`), and column schemas ported from captaincy-ml
- `fpl-api-client`: FPL bootstrap HTTP client (`get_bootstrap`, `get_players`, `get_teams`, `get_current_gameweek`)
- `fpl-player-registry`: player identity resolution with nickname support (KDB, Salah, etc.)
- `fpl-query-tools`: composition layer bridging player registry with bootstrap element lookup
- Import alias wiring in captaincy-showdown (vite.config, vitest.config, tsconfig)

**Validation:** 14/14 parity tests, 11/11 compatibility checks, 29/29 captaincy-showdown tests passing. Path aliasing bug found and fixed.

**Status:** ✅ Complete

---

## Phase 1 — Core Tool Infrastructure

**Goal:** Build the structured tool layer that deterministic advice intents are built on.

| Slice | Description | Tests |
|---|---|---|
| 1c | API client smoke tests + validation | ~40 |
| 1d | Player registry parity tests | ~30 |
| 1e | Query tools composition tests | ~30 |
| 1f | Tool contract — 5 structured tools (resolve_player, player_summary, current_gameweek, captain_score, rank_candidates) | phase1f |
| 1g | Tool runner — ToolSpec/ToolRegistry, in-process dispatch via `run_tool()` | phase1g |
| 1h | End-to-end harness wiring all tools together | 47 |

**Key outputs:**
- `run_tool(name, args, bootstrap) → dict` — universal dispatch interface
- `TOOL_REGISTRY` containing all five registered tools
- Full tool chain from question → bootstrap → tool → result

**Status:** ✅ Complete

---

## Phase 2 — Captain Engine and Grounded Advice Core

**Goal:** Build the deterministic scoring, ranking, rendering, and dispatch layers on top of the tool infrastructure.

| Slice | Description | Tests |
|---|---|---|
| 2a | Captain score tool integration | 78 |
| 2b | Rank candidates | 112 |
| 2c | Auto-derivation of scoring inputs from bootstrap elements | 133 |
| 2d | Fixture difficulty (FDR) integration | 132 |
| 2e | `fpl-pipeline`: `assemble_captain_context()` — single call for bootstrap + fixtures + FDR | ~90 |
| 2f | Assembled context contract tests | 106 |
| 2g | Tier labels (`safe`, `upside`, `differential`, `avoid`) | 160 |
| 2h | Role signals — set-piece, penalty taker, penalty area role metadata | 165 |
| 2i | Renderer — human-readable grounded response text for CLI output | 172 |
| 2j | Explainer — deterministic explanation strings per score | 184 |
| 2k | Dispatcher — routes question text to the correct tool intent | 132 |
| 2l | Outcomes — `OUTCOME_OK`, `OUTCOME_NOT_FOUND`, `OUTCOME_AMBIGUOUS`, `OUTCOME_MISSING_ARGUMENTS`, `OUTCOME_ERROR`, `OUTCOME_UNSUPPORTED_INTENT` | 211 |
| 2m | Adapter — `adapt()` → `AdapterResponse` (normalised contract over DispatchResult) | 118 |
| 2n | Contract fixtures — `STANDARD_BOOTSTRAP`, `AMBIGUOUS_BOOTSTRAP`, fixture definitions | 261 |

**Key outputs:**
- `DispatchResult` — internal dispatch contract
- `AdapterResponse` — normalised adapter contract
- `INTENT_MANIFEST` — supported intent registry
- `SUPPORTED_INTENTS` — enumerated intent names
- `assemble_captain_context()` — pipeline entry point for real data

**Status:** ✅ Complete

---

## Phase 3 — LLM Layer and Final Response Contract

**Goal:** Add a bounded LLM phrasing layer on top of deterministic output; define the stable caller-facing `FinalResponse` surface.

| Slice | Description | Tests |
|---|---|---|
| 3a | LLM layer — `ask_llm()`, provider abstraction, fake/real LLM client, prompt construction | 269 |
| 3b | LLM review — `ask_llm_safe()`, automated parity review: LLM output validated against deterministic backend | 355 |
| 3c | Final response — `respond()` → `FinalResponse`, `FinalResponseDebug`, `FINAL_TEXT_POLICY` | 328 |
| 3d | Contract hardening — edge cases, unsupported intent safety, review bypass prevention | 248 |

**Key outputs:**
- `FinalResponse` — stable caller-facing surface; contains `intent`, `outcome`, `final_text`, `supported`, `llm_used`, `debug`
- `FINAL_RESPONSE_CONTRACT.md` — reference document for all callers and UI developers
- Automated parity review: LLM phrasing is rejected if it contradicts deterministic facts

**Status:** ✅ Complete

---

## Phase 4 — Multi-Turn Sessions, HTTP Exposure, and Hardening

**Goal:** Add conversational state, HTTP endpoints, multi-turn follow-up resolution, and a full governance and documentation hardening wave.

| Slice | Description | Tests |
|---|---|---|
| 4a | Live fixtures endpoint — `get_fixtures()`, `get_fixture_difficulty_map()` added to fpl-api-client; live E2E integration tests (E1–E13) | ~50 |
| 4b–4c | Governance hardening (contract alignment, intent manifest docs) | — |
| 4d | Integration examples — reference usage for all surfaces | 115 |
| 4e | Multi-turn state — `ConversationSession`, `ConversationState`, pronoun resolution (`resolve_pronouns`) via regex | 120 |
| 4f | LLM reference resolver — `resolve_reference_llm()` for Spanish and elliptical follow-ups; structured JSON extraction | 151 |
| 4g | Resolver auditability — `ResolverDebug` bundle; `resolver_source`, `fallback_reason` exposed | 161 |
| 4h | HTTP session exposure — `POST /session`, `POST /session/{id}/ask`, `GET /session/{id}` | 184 |
| 4i | Session hygiene — `clear()`, expiry, isolation between sessions | 149 |
| 4j | Session examples and operational docs | 86 |
| 4k–4k5 | Full governance/documentation hardening wave (CONTRACT_GATE.md, UAT runbook, UAT checklist, UAT findings template, http_contract_fixtures) | — |

**Key outputs:**
- `ConversationSession.respond()` — multi-turn entry point
- `ConversationState` — tracks `last_player`, `last_comparison_a/b`, `last_resolver_source`
- `ResolverDebug` — auditable resolver chain trace in every response
- HTTP endpoints: `POST /ask`, `POST /session`, `POST /session/{id}/ask`, `GET /session/{id}`, `GET /ready`
- `UAT_RUNBOOK.md`, `UAT_CHECKLIST.md`, `UAT_FINDINGS_TEMPLATE.md`
- `http_contract_fixtures.json` — machine-readable HTTP surface contract

**Status:** ✅ Complete (4a–4k5 declared the Hardening & Governance phase complete)

---

## Phase 5 — Comparison Intent

**Goal:** Add a first-class deterministic two-player comparison capability.

| Slice | Description | Tests |
|---|---|---|
| 5a | Two-player captain comparison — `compare_players` intent, winner, margin, reasons, `margin_label` | 98 |
| 5b | Comparison contract normalization — structured `ComparisonMeta`, `comparison_reasons`, role-aware framing, set-piece phrases | 61 |

**Key outputs:**
- `compare_players` intent: supports "compare X and Y", "X vs Y", "who is better X or Y"
- Structured `ComparisonMeta`: winner, margin, margin_label, recommendation, per-player context
- Comparison follow-up resolution: "And Salah?", "What about Saka?", "¿Y Salah?" resolved via two-tier chain (regex → LLM)
- `FinalResponse.comparison: ComparisonMeta | None`

**Status:** ✅ Complete

---

## Phase 6 — Transfer Advice Intent and Real Integration

**Goal:** Add deterministic transfer advice and connect the platform to real LLM provider APIs.

| Slice | Description |
|---|---|
| 6a–6c | Transfer advisor core — `get_transfer_advice` intent, `transfer_in` / `marginal_transfer_in` / `hold` recommendations |
| 6d | Multi-provider LLM connectivity — Gemini (primary), Anthropic, OpenAI; `DEFAULT_PROVIDER` env var; retry logic hardening (`HTTPError`/`ConnectionError` retried; `ConnectTimeout` handled upstream as `missing_context` fallback) |
| 2.6.x | Additional hardening slices (decimal naming to avoid roadmap collision) |

**Key outputs:**
- `get_transfer_advice` intent: "should I sell Saka for Salah?", "swap X for Y", "transfer out X for Y"
- `TransferMeta` (later promoted in Phase 7a): player_out, player_in, recommendation, score_delta, price_delta, reasons
- Real LLM provider wiring via `llm_layer.py`; `dev-backend.sh` startup script
- `.env.template` for provider key management

**Status:** ✅ Complete

---

## Phase 7 — V1 MVP Slices

**Goal:** Achieve V1 coherence: structured metadata symmetry across all four advice families, transfer follow-up parity, and two new deterministic retrieval intents.

| Slice | Description |
|---|---|
| 7a | Structured transfer metadata — `FinalResponse.transfer: TransferMeta | None`; serialized in HTTP + CLI debug |
| 7b | Structured chip metadata — `FinalResponse.chip: ChipAdviceMeta | None`; `signal_value`, `signal_label` per chip |
| 7c | Transfer + chip debug/example parity — CLI, HTTP, session examples aligned |
| 7f | Transfer follow-up resolution — "what about Haaland instead?", "how about X?" → `sell {player_out} for X` (deterministic-only, anchored to prior player_out) |
| 7g | Differential picks intent — `differential_picks`; low-ownership high-upside candidates ranked by adjusted score |
| 7h | Player fixture run intent — `player_fixture_run`; 5-game horizon; `FixtureRunMeta` with `fixtures[]`, `horizon`, `current_gameweek`, team + position |
| 7j | Validation corpus V2 refresh and final gate — 31 corpus scenarios all passing |

**Chip routing coverage:**
- `triple_captain`: score ≥ 75 → favorable, ≥ 55 → marginal, < 55 → unfavorable
- `wildcard`: GW 7–28 → marginal, outside → unfavorable
- `bench_boost`: avg FDR ≤ 2.5 → favorable, ≤ 3.0 → marginal
- `free_hit`: always `missing_context` (no DGW/BGW detection yet — addressed in V1.5)

**V1 done criteria met:**
1. Four advice families expose structured metadata: captain, captain_ranking, comparison, transfer, chip ✅
2. Multi-intent sub-responses expose bounded structured metadata ✅
3. Comparison and transfer both support bounded follow-up in session flows ✅
4. Differential picks and player fixture run available as deterministic intents ✅
5. CLI, stateless HTTP, and session HTTP contract-consistent ✅
6. Validation corpus V2 passes ✅

**Status:** ✅ Complete — V1 MVP declared

---

## Phase 8 (V1.5) — Stabilisation Wave

**Goal:** Raise advice accuracy to a level where real FPL players can argue with the answers, not the infrastructure. Prerequisite to handing the backend to a UI developer.

| Slice | Title | Status |
|---|---|---|
| 8a | Position-aware scoring — `adjusted_captain_score` adds position bias; GKP uses `saves_per_90` + `clean_sheets_per_90`; DEF uses `clean_sheets_per_90`; canonical score preserved | Planned |
| 8b | Home/away fixture factor — `effective_fdr = fdr ± 0.5` based on `is_home`; `fixture_difficulty_map` extended; `(H)`/`(A)` labels in fixture run | Planned |
| 8c | DGW/BGW detection and free hit unblock — `gameweek_type` field; free hit now returns `conditions_favorable` for DGW, `conditions_marginal` for BGW, `conditions_unfavorable` for normal | Planned |
| 8d | Follow-up resolution completeness — fixture run follow-up (`last_fixture_run_player`); differential follow-up (routes to captain score) | Planned |
| 8e | Squad context layer — optional `squad_context` on `/ask`; `budget_constraint`, `chip_unavailable`, `hit_warning` modifiers; CLI `--itb`, `--chips`, `--free-transfers` flags | Planned |
| 8f | Validation corpus V3 and gate — 36 corpus scenarios passing; closes V1.5 wave | Planned |

**V1.5 done criteria:**
- Advice is correct enough to be argued with by real FPL players
- All 36 corpus scenarios pass
- Squad context wired on all three surfaces (CLI, HTTP, session)
- Backend stable enough to be handed to a UI developer

**Status:** Planned — not yet started

---

## V2 Phase 1 — UI Chat Shell (Next.js)

**Goal:** Build a working chat interface connected to the live backend. `final_text` only in Phase 1.

| Sub-slice | Description | Status |
|---|---|---|
| 1a | Scaffold `packages/fpl-ui/` with `create-next-app` + shadcn/ui; `lib/types.ts`; `ChatShell`, `InputBar`, `MessageList`, `StarterPrompts` | ✅ Complete |
| 1b | Session mode toggle; stateless vs session HTTP path | ✅ Complete |
| 1c | `intent_hint` — `POST /ask` accepts `intent_hint` for slash command routing; allowlist enforced | ✅ Complete |
| 1d–1f | HTTP contract fixtures; `http_contract_fixtures.json`; backend ready for UI consumption | ✅ Complete |

**Status:** ✅ Complete

---

## V2 Phase 2 — Intent Components, Squad Context, Slash Commands

**Goal:** Render structured metadata below `final_text`; add squad context panel; add Spanish-first slash commands.

**What was built:**
- `CaptainCard` — score meter, tier badge (safe=emerald, upside=amber, differential=violet, avoid=red), set-piece tags
- `ComparisonCard` — two-column layout, winner highlight, margin label badge, reasons list
- `RankingTable` — sortable table, tier badge per row
- `TransferCard` — out→in arrow layout, score delta bar, recommendation badge, `budget_constraint`/`hit_warning` banners
- `ChipCard` — chip icon, recommendation badge, signal metric, "chip unavailable" greyed state
- `FixtureRunTable` — 5-column fixture grid, FDR colour scale, H/A tags
- `DifferentialTable` — ranked table, ownership % bar, cost display
- `MultiIntentView` — stacked cards, one per sub-response
- `SquadContextPanel` — FPL team ID input → auto-fetch ITB, chips, free transfers from public FPL API
- `SlashMenu` — Spanish-first slash commands (`/capitan`, `/comparar`, `/transferencia`, `/calendarios`, `/diferenciales`, `/chips`); keyboard nav; ARIA accessible; wires `intent_hint`

**Validation:** 216 tests passing, clean build

**Status:** ✅ Complete

---

## V2 Phase 2.5 — Integration and Live Engine Connectivity

**Goal:** Connect the UI to a running Python backend with a live LLM engine.

**What was built:**
- Multi-provider LLM layer: Gemini (primary), Anthropic and OpenAI as fallbacks; controlled via `DEFAULT_PROVIDER` env var
- `dev-backend.sh` — exports full `PYTHONPATH` for all internal packages; starts Uvicorn on localhost:8000
- `.env.template` — provider key placeholders (`GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)
- `packages/fpl-ui/.env.local.template` — frontend backend URL placeholder
- Verified `assemble_captain_context()` fetches live FPL bootstrap data with PYTHONPATH set

**Status:** ✅ Complete

---

## V2 Phase 3 — Auth and Subscriber Gating

**Goal:** Patreon-gated access behind Clerk OAuth.

**Planned work:**
- Clerk setup with custom Patreon OAuth2 provider (non-native — requires manual endpoint config)
- `middleware.ts` protecting `/chat` via `subscription_tier` metadata
- Paywall page at `/subscribe` with Patreon link
- Patreon webhook handler `POST /api/webhooks/patreon` → updates Clerk user metadata on tier change
- Stripe as future alternate payment path (same Clerk metadata pattern)

**Status:** Planned

---

## V2 Phase 4 — Hardening and Production Deployment

**Goal:** Deploy backend to Railway and frontend to Vercel; secure environment variables; add rate limiting.

| Sub-slice | Description | Status |
|---|---|---|
| 4.1 | Railway backend deployment — Dockerfile, environment variables, `/ready` endpoint verified | ✅ Complete |
| 4.2 | Vercel frontend deployment — Next.js 15 build; server-side proxy boundary; Railway URL not in browser bundle | ✅ Complete |
| 4.x | Domain + SSL on Vercel; rate limiting on proxy route; error states for all intent components | Planned |

**Production state (as of 2026-04-30):**
- Backend: `https://fpl-backend-production-4151.up.railway.app`
- Frontend: `https://fpl-rjhsi6f8d-leo-gonzalezs-projects-fe3d4b93.vercel.app`
- LLM: `gemini-2.5-flash` via `classification_source=llm_classifier`, `llm_used=true`
- Grounded output verified: Salah (61.85) over Haaland (56.58)

**Status:** Partially complete (4.1 and 4.2 done; domain/SSL/rate limiting planned)

---

## Supported Intents — Current State

| Intent | Route trigger | Structured metadata | Follow-up support |
|---|---|---|---|
| `captain_score` | "should I captain X", "captain Haaland" | `FinalResponse.captain` | Yes — pronoun + LLM resolver |
| `rank_candidates` | "who should I captain", "best captain options" | `FinalResponse.captain_ranking[]` | Yes — pronoun resolver |
| `player_summary` | "tell me about X", "who is Salah" | — | Yes — pronoun resolver |
| `player_resolve` | "who is KDB" | — | Yes — pronoun resolver |
| `current_gameweek` | "what gameweek is it" | — | No |
| `compare_players` | "compare X and Y", "X vs Y" | `FinalResponse.comparison` | Yes — regex + LLM (Spanish) |
| `get_transfer_advice` | "should I sell X for Y", "swap X for Y" | `FinalResponse.transfer` | Yes — deterministic anchor to player_out |
| `chip_advice` | "should I use triple captain", "should I wildcard" | `FinalResponse.chip` | No |
| `player_fixture_run` | "X fixtures", "fixture run for X" | `FinalResponse.fixture_run` | No (planned: V1.5 8d) |
| `differential_picks` | "differential picks", "low ownership options" | `FinalResponse.differential` | No (planned: V1.5 8d) |
| `multi_intent` | "X and Y" (two independently routable halves) | `FinalResponse.sub_responses[]` | Partial — per sub-intent rules apply |

---

## Key Contracts

| Contract | Location | Description |
|---|---|---|
| `FinalResponse` | `fpl_grounded_assistant/final_response.py` | Stable caller-facing surface for all intents |
| `AdapterResponse` | `fpl_grounded_assistant/adapter.py` | Normalised adapter contract over DispatchResult |
| `DispatchResult` | `fpl_grounded_assistant/dispatcher.py` | Internal dispatch output |
| `FINAL_RESPONSE_CONTRACT.md` | `packages/fpl-grounded-assistant/` | Human-readable reference for all callers |
| `CONTRACT.md` | `packages/fpl-grounded-assistant/` | Lower-level adapter contract |
| `http_contract_fixtures.json` | `packages/fpl-grounded-assistant/` | Machine-readable HTTP surface contract |

---

## Test Coverage Summary

| Phase | Tests |
|---|---|
| Phase 1h (harness) | 47 |
| Phase 2a–2n (core engine) | ~1,800 cumulative |
| Phase 3a–3d (LLM + final response) | 1,200 |
| Phase 4a–4j (sessions + HTTP) | ~900 |
| Phase 5a–5b (comparison) | 159 |
| V1 corpus scenarios | 31 (Corpus V2) |
| V2 UI (Next.js) | 216 |

---

## Deferred — Not Yet Started

| Feature | Why deferred |
|---|---|
| Multi-player comparison (>2) | Two-player comparison sufficient for V1; N-player adds routing complexity |
| Multi-intent `also` / `plus` conjunctions | `and` covers the main path; `also`/`plus` are non-essential (Phase 7d) |
| Multi-intent session state integration | Current explicit behavior documented; not a coherence blocker (Phase 7e) |
| Squad composition context | No bench players, lineup, or net hit cost yet — V1.5 adds ITB/chips/FT only |
| Multi-transfer planning | Outside V1/V1.5 scope |
| Long-term conversation memory / persistence | No multi-worker-safe session infrastructure yet |
| Open-ended football reasoning | LLM must not invent football facts — explicit policy |
| Injury data / availability | Not available from bootstrap; requires per-player API calls |
| Patreon auth gate | V2 Phase 3 — planned |
| Custom domain + SSL | V2 Phase 4.x — planned |
| Rate limiting on proxy | V2 Phase 4.x — planned |
| Stripe as alternate payment path | Post-Patreon gate |
| Form recency weighting (exponential decay) | V1.5 or later — form spikes diluted by older weeks |

---

## Future Milestone Ideas

These are areas the roadmap does not yet address, suitable for planning future increments:

- **V1.5 completion** — finish slices 8a–8f (position scoring, home/away FDR, DGW/BGW, follow-up completeness, squad context)
- **V2 Phase 3** — Patreon + Clerk auth gate, subscriber-only `/chat`
- **V2 Phase 4 completion** — domain, SSL, rate limiting, error states
- **Score model V2** — exponential form decay, injury availability signal, expected minutes
- **Fixture run follow-up** — session follow-up for fixture run and differential intents (8d)
- **Multi-transfer planning** — "who should I bring in for my two free transfers?"
- **Squad composition context** — inject bench players, team layout for smarter advice
- **Injury / availability layer** — flag missing players before captain or transfer advice
- **Gameweek preview intent** — summarise the week's key fixtures and captaincy context
- **Team-level analysis** — "how do Arsenal look this week?" as a grounded retrieval intent
- **Season-long planning intents** — chip strategy across the remaining gameweeks
- **Mobile-responsive UI polish** — progressive enhancement on small screens
- **Analytics / telemetry** — track which intents are used most; identify coverage gaps
- **Internationalisation beyond Spanish** — Portuguese, Arabic as high-value FPL markets

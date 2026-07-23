# FPL Platform — Full Roadmap

**Last updated:** 2026-07-23 — 2026-27 season launched; added Season Launch block (top of pipeline)
**Current state:** Architectural pivot merged to main. Backend fully production-capable (25 tools, LLM-primary orchestrator, quota/audit, 126/126 validation scenarios). UI deployed on Railway + Vercel. Phase 3 auth is the remaining blocker for Patreon launch.

---

## 🚀 Season Launch — 2026-27 (added 2026-07-23) — TOP OF PIPELINE

The 2026-27 FPL API went live 2026-07-23. Reviewed `bootstrap-static` + `fixtures`
against our client/schemas: **no breaking structural changes** — every field
`fpl_client.py` and `schemas.py` depend on is still present. Actions below fall
out of that review, ordered by urgency.

**Done 2026-07-23:** `/fixtures` ticker regenerated from the live 2026-27
schedule + FDR (`export_real_season_fixture_outlook.py --season-start` →
`fixture-outlook-2026-27.json`; seam + disclaimer updated). Both axes = FDR at
launch; defence axis re-separates once results exist (see next item).

**Also done 2026-07-23 (compare-card + season-launch data bugs):** three
season-launch data bugs found while eyeballing `/comparar` — all the same
`.get(key, default)`-doesn't-fire-when-`key:null` trap: (a) `team["strength"]`
present-but-null broke ALL backend startup (`context.py::_build_team_fixtures`),
forcing a ~53-day-stale fallback; (b) `fixture_difficulty_map` was all-null
because `get_fixture_difficulty_map` read the null aggregate `strength` instead
of each fixture's `team_h/a_difficulty` (the real FDR the calendar already uses)
— so compare treated every fixture as neutral FDR=3; (c) GW1 venue never
resolved because three byte-identical `_get_current_gw` copies only checked
`is_current` (GW1 is `is_next` pre-kickoff), no-op'ing home/away on the most
important GW — fixed by delegating all three to canonical `get_current_gameweek`.
Compare card also now shows `position_score` (the value that decides the winner)
instead of `captain_score`, branded **Bendito Fantasy /100**. Duplicate-resolver
sprawl (≥9 current-GW impls) deferred to a dedicated cleanup track.

| # | Item | Severity | Notes |
|---|---|---|---|
| 1 | **Zero-minutes / fresh-season safety** — verify per-90 & ratio consumers don't divide-by-zero or rank on empty stats before GW1 is played | High | All cumulative stats/xG are 0 until GW1 completes; audit `PER_90_COLS` consumers + any form/value ranking |
| 2 | **Chip logic → two-window aware** — API exposes 8 chip entries: 2× each chip, split GW1–19 / GW20–38; **wildcard & free hit are NOT available in GW1** (`start_event=2`) | Medium | `chip_advisor.py` reasons over 4 chip names statically; make it window-aware (chips remaining, GW1 WC/FH unavailability). Honors `feedback_chip_advice_meta_7b` |
| 3 | **Defence-axis form upgrade** — re-run the default (non-`--season-start`) fixture export once enough GWs are played, to re-separate defence from attack via the validated FDR+form recipe | Medium | Blocked on real results accumulating (`compute_rolling_strength` needs played GWs) |
| 4 | **Partial-schedule refresh** — launch schedule is partial (320 fixtures, events 1–33 of 38); re-run `--season-start` export to pick up newly-scheduled tail GWs | Low | Idempotent; safe to re-run anytime |
| 5 | **New elements signals** — `scout_risks` + `scout_news_link` are new 2026-27 fields (official injury/rotation scout flags); `opta_code` is a clean cross-source join key | Low | Additive — nothing breaks; evaluate for availability grounding + historical join |

---

## What Is Complete

### Backend Core (Phases 1–7j) — MVP wave closed
- 14 intents, 25 tools (10 original + 8 atomic + 7 from pivot), `respond()` contract, session layer, resolver chain
- Structured metadata on `FinalResponse`: captain, comparison, transfer, chip, fixture run, differential
- 126/126 validation corpus scenarios, ~8,000 assertions

### MCP Architecture (M0–M5) — Merged 2026-05-18
- `@resource` normalizer + `DecisionRouter` + `PromptRegistry` + `ask_v2()` as production routing path
- `/healthz` telemetry counters on real traffic
- Spanish hardening + paraphrase corpus
- Rollout-isolation surface retired; `POST /ask` routes through `ask_v2() → harness_adapter`

### Architectural Pivot (P0–P6) — Merged 2026-05-24
- LLM orchestrator is now the **primary reasoner** for plain text (not a fallback)
- 8 new atomic tools: `find_players`, `get_player_snapshot`, `get_player_history`, `get_fixtures_for_gw`, `get_gameweek_context`, `get_team_snapshot`, `web_fetch`, `rank_players_by_metric`
- Source-discipline compressed system prompt (~480 tokens), multi-tool batching across 3 providers
- Second-layer evaluator (GROUNDED / COMPLETE / SAFE axes, 1-retry, fail-open)
- 4-layer off-topic defense (URL allowlist → prompt classification → output framing → heuristic + evaluator SAFE override)
- `quota.py` + `audit.py`: per-user 24h/30d rolling windows, 3 tiers, NDJSON audit, SHA256-hashed user IDs
- `GET /quota` endpoint + `QuotaIndicator.tsx` footer widget
- `@resource` UI renderers (`ResourceRankingTable`, `InjuriesTable`)

### Graduation Debt-D (D1–D3+A2) — Merged 2026-05-25
- D1: Dockerfile bakes `FPL_ORCH_ENABLED` + `FPL_SESSION_ENABLED` + `--workers 1` defaults
- D2: Quota exception observability + frontend intent contract-sync
- D3: `GET /quota` auth guard + session token observability via `logger.warning`
- A2: `X-Internal-Token` header name documented in `.env.template`

### UI — V2 Phases 1–4 live in production
- Railway backend + Vercel frontend deployed end-to-end (Gemini Flash, `llm_used=true` confirmed)
- All 8 intent components, session, squad context, slash menu, ARIA hardening, 216 tests
- Next.js 15.5.15, shadcn/ui, Spanish-first slash commands

---

## Open Debt (carry forward)

| Item | Severity | Notes |
|---|---|---|
| **Sessions token observability** — `ConversationSession.respond()` records `tokens=0` | High | Session quota enforces message cap only; `FPL_SESSION_ENABLED=false` recommended until fixed |
| **Multi-intent HTTP carve-out** — `POST /ask` returns only first sub-intent for multi-intent queries | Medium | CLI still correct; 3 validation scenarios skipped on HTTP surface |
| **F7 per-turn token ceiling** — no max-per-turn cap | Medium | Orchestrator loop can burn unbounded tokens within daily quota |
| **Clerk + Patreon auth (Phase 3)** | **Launch blocker** | Paywall not yet wired |
| `_orch_result_to_final_response` dead code | Low | Kept for 45 test assertions; can be retired together |
| `intent_hint` deprecation | Low | Pre-processed in `fpl_server.py:630-635`; orthogonal to ask_v2 path |
| `_record_turn` silent failure | Low | Bare `pass` on quota counter write |
| F6 Accept-Language detection | Low | Quota messages always Spanish regardless of user language |
| Bench-boost truncation deeper fix | Low | Doubles cost (2nd LLM synthesis call); defer to post-cost-model decision |
| Mismatch fixture tool | Low | `get_fixture_mismatches(gw)` or `largest_fdr_delta_fixture` extension |
| `lib/types.ts` contract-sync | Low | 2 pre-existing frontend test failures |

---

## Near-term Sprint (week of 2026-05-26)

| Day | Work |
|---|---|
| Mon 26 | Phase 3 auth scaffold — Clerk install, `middleware.ts`, `/login` redirect |
| Tue 27 | Patreon tier gating — custom OAuth2 provider, `X-User-Id`/`X-User-Tier` headers, quota E2E |
| Wed 28 | Sessions token observability — fix `record_turn(tokens=0)` in `ConversationSession.respond()` |
| Thu 29 | Multi-intent HTTP carve-out — lift 3 skipped validation scenarios |
| Fri 30 | Dead code cleanup, `_record_turn` silent failure, F7 per-turn token ceiling, Railway deploy |

---

## Track A — Historical Data Pipeline

**Priority: most urgent long-horizon track.** The FPL API resets at end of season — once GW38 closes all per-GW player data is gone. The project started by referencing `olbauday/FPL-Core-Insights` (community historical data repo) but the goal is an **owned pipeline independent of any third-party cadence, quality, or schema**.

**Target:** Pull directly from the FPL API, store in our own schema, and make historical data queryable without hitting the live API. Feeds ML training data long-term.

| Phase | Work |
|---|---|
| H1 | Schema design — storage format (parquet on disk initially, Postgres on Railway long-term). Tables: `players`, `gameweeks`, `player_gw_stats`, `fixtures`, `teams` mirroring FPL API shape |
| H2 | Incremental puller — script or Railway cron that pulls from `https://fantasy.premierleague.com/api/` after each GW deadline and appends to the store. Idempotent re-runs |
| H3 | End-of-season capture — one-shot script to pull full current-season history before the FPL reset (~June 2026). Run before season close |
| H4 | Bootstrap hot-swap — make `fpl_server.py` load from local store when FPL API is unavailable (off-season), rather than failing |
| H5 | Prior-season seed import — use `olbauday/FPL-Core-Insights` for 2016–2024 seasons as a one-time seed import, normalized to our own schema |

---

## Track B — ML / Metrics Hardening

**Depends on Track A** (backtesting needs historical GW data). Design can begin in parallel.

**Current state:** All scoring algorithms (captain, transfer, differential, chip) use hand-tuned coefficients with no outcome calibration and no time-series awareness. Each GW is treated independently.

**Direction:** Deterministic scoring layer stays authoritative. ML produces calibration multipliers and confidence scores on top — not a full replacement.

| Phase | Work |
|---|---|
| ML0 | Backtest framework — given historical GW data, run current algorithms against past decisions and compare predicted vs. actual GW points. Establishes calibration error baseline |
| ML1 | Captain score calibration — fit coefficient weights using historical captain vs. actual-return data. Replace hand-tuned values with data-derived ones |
| ML2 | Form / time-series signals — rolling N-GW weighted averages (form decay) fed into transfer and differential engines |
| ML3 | Differential expected-return model — replace blunt ownership threshold with EV-over-ownership model |
| ML4 | Position-aware subscores — GKP: saves+CS, DEF: CS+bonus, MID/FWD: xG+xA; replaces flat scoring input |
| ML5 | Provider cost study — once Patreon usage data exists, evaluate Gemini Flash vs. Haiku 4.5 vs. GPT-4o-mini with capability/cost scoring |

---

## Track C — UI Redesign from Stitch

**Stitch project:** `019dd722-9393-7d31-8a09-9f2e13f9b67c` — File: `FPL Chat Hi-Fi.html`
**Approach:** Incremental. One component at a time, verified against existing tests before moving on. First integration — go slow.

| Phase | Work |
|---|---|
| UI0 | Review design together — use "Handoff to Claude Code" button in Stitch. Map each screen to `packages/fpl-ui/components/` |
| UI1 | Port chat shell / message layout — drop-in replacement for `components/chat/ChatShell.tsx`. Visual only; keep all prop/API contracts |
| UI2 | Port intent cards (CaptainCard, ComparisonCard, etc.) to new design language. One card at a time |
| UI3 | Replace `InputBar` and `StarterPrompts` with Stitch-designed equivalents |
| UI4 | Port `QuotaIndicator` and nav/header; wire shadcn/ui tokens to Stitch palette |
| UI5 | Full E2E visual pass — deploy to Vercel preview, compare against Stitch screens |

---

## Track D — Fixture Intelligence (Calendar Outlook)

**Next slice of work.** Borrows the strongest ideas from NextXI's fixture ticker (reverse-engineered 2026-06-27) and adapts them to a **chat-first** product with a complementary **browse-first** surface. NextXI is grid-only; BF runs both: the run-detection logic is a *narrative generator* (the assistant **speaks** the outlook), AND a standalone grid page lets users scan fixtures without prompting. Evolves the existing single-axis FDR engine (`team_fixture_calendar.py`), the card pipeline (`FixtureRunTable.tsx` + intent→renderer), and the scoring engine (`position_score.py`) — not greenfield.

**Two-surface model (the intended user flow):**
1. **Browse — standalone Fixtures page.** User opens the grid, scans color-coded fixtures, forms a hunch. Zero tokens spent; the baseline analysis is free and always available.
2. **Deepen — chat.** From that hunch the user jumps to chat to interrogate a specific team or player — pros/cons, tendencies, "should I get him." The grid is the cheap entry point that funnels into (paid, token-spending) conversation only when the user wants depth.

The same engine (FI0–FI3) powers both surfaces; the visual ticker + sparkline also render **inline as static cards inside chat answers** when a query is fixture- or player-shaped.

**Locked decisions (2026-06-27):**
- Difficulty source = FPL team strength ratings first (Poisson deferred to FI6).
- Band granularity = **5 bands** (parity with existing FDR), not NextXI's 7.
- Standalone Fixtures page (FI7) is **free / outside the paywall** — it is the top-of-funnel acquisition lure; chat depth is the paid surface.
- Default horizon = **10 GWs** (long enough to surface genuine runs; run detection needs length to be meaningful). The existing 5-GW default stays for narrow in-chat queries.
- **No buy/sell language anywhere in this track.** The engine highlights good/bad *runs* (schedule reads only — "calendario verde J34–38"); the user decides what to do with it. Advice/transfer framing stays owned by the transfer/captain/differential engines (FI3), preserving the `team_fixture_calendar` invariant.

**Three things borrowed, in priority order:** (1) two-axis difficulty — attack vs. clean-sheet, replacing one flat FDR number; (2) run/tendency detection — find ≥3-GW good/bad streaks, label intensity by length; (3) visual ticker + tendency sparkline.

**Data foundation:** FPL bootstrap already ships per-team strength ratings (`strength_attack_home/away`, `strength_defence_home/away`). v1 derives per-fixture attack difficulty (our attack vs their defence) and defence difficulty (their attack vs our defence) directly from those — deterministic, no model, ships immediately. The Poisson layer (strengths → expected goals λ → P(2+ goals), P(clean sheet)) is a later calibration upgrade that ties into Track B.

| Phase | Work |
|---|---|
| FI0 | **Two-axis difficulty model (deterministic).** Extend the fixture data layer to compute per fixture `attack_difficulty` and `defence_difficulty` from FPL team strength ratings, home/away aware, bucketed into **5 bands**. Backwards-compatible with existing `f.difficulty`. Pure deterministic, no LLM, no new live calls beyond bootstrap. Unit-tested against known fixtures |
| FI1 | **Run/tendency detection.** Given a team's difficulty sequence over a horizon (default **10 GWs**), classify each GW good/bad vs thresholds, find consecutive runs ≥3, grade intensity (strong ≥5 / mild 3–4) by length, combine DGW fixtures, pin BGW to worst. Emit a structured `runs` summary + a one-line Spanish verdict per team. **Schedule-only language** — highlights runs ("calendario verde J34–38"), never buy/sell. This is the narrative engine |
| FI2 | **Backend tool `get_fixture_outlook`.** Wrap FI0+FI1 as an orchestrator tool returning structured outlook (grid cells + runs + verdict) for a team or set of teams. Register in `tool_schema_registry` so the LLM can call it from plain-text questions |
| FI3a | **Player-aware integration — additive context (the "intelligence engine on a player prompt").** Resolve player → club → outlook on the position-relevant axis (attacker → attack, DEF/GKP → clean-sheet; axis auto-selected, no manual toggle). **Dynamic defensive-midfielder detection:** a MID at/above the league's defensive-contribution threshold (`defensive_contribution_per_90`, top ~30%) reads the *defence* axis instead of attack — so a Caicedo-type is evaluated for defensive returns, not just goals. Surface the two-axis outlook + run verdict in the **explanation/metadata** of the engines that already consume fixtures (`captain`, `compare_players`, `transfer_advisor`, `differential_picks`, `chip_advisor`) and use it only as a **tiebreaker**. The hand-tuned FDR scoring inputs stay authoritative — this is purely additive, so no recalibration and no corpus churn. See surface map below |
| FI3b | **Input replacement (gated on Track B).** Replace each engine's flat single-axis FDR input with the two-axis difficulty as the *scoring* signal (not just context). Changes tuned behaviour (`_FDR_ADV_THRESHOLD`, `HOME_FDR_ADJUSTMENT`, Bench-Boost FDR cutoffs) → requires re-validation against the 126-scenario corpus and is only justified once FI6/Track B backtesting exists. **Do not start before Track B.** |
| FI4 | **Visual: Fixture Ticker card (in-chat).** New `fixture_outlook` intent + card rendering the color-coded grid (rows=teams, cols=GWs) with attack⇄defence toggle and per-team verdict chip. Embedded as a **static card inside chat answers**, Bendito Fantasy design language, mobile-first. Reuses intent→renderer pipeline. Add `/calendario` slash command |
| FI5 | **Visual: Tendency trend.** Per-team mini trend (reversed-axis line, good=up, green/red run bands ≥3 GW). Compact sparkline inline as part of answer rendering, full chart on tap. Tap a cell → that fixture's projected goal/CS probability |
| FI7 | **Standalone Fixtures page (free, browse-first surface).** A dedicated full-page grid — the zero-token entry point, **outside the paywall** as the acquisition lure. Renders the full-league ticker over a **10-GW default horizon** with attack⇄defence toggle, horizon selector, and per-team tendency bands. Each team/cell links into chat pre-seeded with the relevant question ("deepen X's outlook") so the browse→chat funnel is one tap. Reuses the FI4/FI5 components at page scale. Independent of the chat embed; same FI0–FI3 engine |
| FI6 | **Poisson upgrade (Track B tie-in).** Replace strength-ratio difficulty with calibrated Poisson: team strengths → λ → P(2+ goals) / P(clean sheet), bucketed into difficulty bands. Backtested against historical outcomes (**depends on Track A** historical data). Turns the engine from heuristic to genuinely predictive |

**Surfaces it touches (the integration is broad, not siloed).** Fixture difficulty is *already* cross-cutting: the pipeline injects `fixture_difficulty_map` + `team_fixtures` into the bootstrap every engine receives (`fpl-pipeline/.../context.py`), and the decision engines already consume it — as **flat single-axis raw FDR**. FI does not "add fixtures to more places"; it **upgrades the existing signal** at points that already exist, plus exposes it as a first-class queryable surface.

| Surface (command) | Uses fixtures today | FI upgrade |
|---|---|---|
| captain_score `/capitan` | `fixture_difficulty_map` injected | attack-axis + run awareness |
| compare_players `/comparar` | `fixture_difficulty` score input | position-mapped axis per player |
| transfer_advice `/transferencia` | effective FDR + home/away adj (8b), in-vs-out | two-axis delta + easier-run detection |
| differential_picks `/diferenciales` | blank-GW filter, `fixture_difficulty` input, DGW overlay | richer run/tendency signal |
| chip_advice `/chips` | Bench-Boost avg-FDR thresholds, DGW/BGW | run-aware chip windows |
| player_fixture_run `/calendarios` | raw FDR calendar (dedicated) | native two-axis surface |
| rank_candidates `/clasificacion` | captain fixture context | attack-axis ranking |

**Two connection mechanisms, different risk profiles:**
- **Via the FI2 tool (LLM orchestrator).** The moment FI2 lands, the engine reaches *every* fixture-shaped question (captaincy, transfers, "should I get Saka") because the orchestrator calls the tool. No deterministic-engine changes, **zero recalibration risk** — this is where most of the broad reach lands.
- **Via the deterministic engines (FI3a/FI3b).** FI3a is additive (context/tiebreaker, tuned scores untouched). FI3b swaps the scoring input and is recalibration-sensitive → gated on Track B.

**Sequencing:** FI0–FI2 (engine + narrative + tool) deliver broad reach with no UI and no recalibration. FI3a adds additive per-engine context. FI4–FI5 add the in-chat static visuals; FI7 reuses them as the standalone free browse-first page. FI6 is the predictive Poisson upgrade (gated on Track A); FI3b is input replacement (gated on Track B). Each phase is independently shippable; FI7 can land any time after FI4–FI5.

---

## Track E — Bendito Fantasy Score Leaderboard (added 2026-07-23)

**Origin:** came out of the compare-card work. The card now surfaces
`position_score` as the branded **Bendito Fantasy score (X/100)** — our own
0–100 heuristic rating (`position_score.py`, Layer 2). Natural next question from
the user: *"can we show a ranking of players by our score?"* Yes — the score is
already computed per player; this is a **read/surface** feature, not a scoring
change. Mostly additive: new (or extended) tool + new card + optional page.

**What already exists (reuse, don't rebuild):**
- `differential_picks` already ranks by `position_score` (filtered by ownership).
- A `rank_candidates` / `/clasificacion` surface is referenced in Track D
  (captain fixture context) — confirm its current state and whether the
  leaderboard should extend it rather than add a parallel tool. **This is
  exactly the duplicate-resolver trap (see the duplicate-resolver cleanup track) —
  check before writing a new ranking path.**

**Scope (v1):**
| Phase | Work |
|---|---|
| E1 | **Reuse/extend an existing ranking tool — do NOT add a third.** Candidates already in the tree: `rank_players_by_metric` (atomic tool, P0–P6 pivot), `rank_candidates` / `/clasificacion` (Track D surface), and `differential_picks` (already ranks by `position_score`). First task is to audit these three and decide whether `position_score` is just another `metric` value for `rank_players_by_metric` (likely the cleanest) or warrants a thin dedicated path. Then: input filters — `position` (GKP/DEF/MID/FWD), `max_price`, `min_minutes`, `top_n` (default 15); output ranked `{rank, web_name, team_short, position, position_score, captain_score, now_cost, ownership, is_home, effective_fdr}` sorted by `position_score` desc. Pure deterministic; reuses `_score_one`/`compute_position_score`. |
| E2 | **Leaderboard card** (`ranking` intent + renderer). Ranked rows with the Bendito Fantasy score `/100` shown prominently (the honest place to expose the scale — users see the whole distribution). Position/price filter chips. Bendito Fantasy design language, mobile-first, reuses intent→renderer pipeline. Add `/ranking` (or reuse `/clasificacion`) slash command. |
| E3 | **Standalone leaderboard page (optional, browse-first).** Full-table version behind or beside the Fixtures page (Track D FI7). Same engine; page scale. Gate/paywall decision TBD alongside FI7. |

**Design notes / open questions:**
- **Scale honesty (season-start artifact).** `form` is 40% of the MID/FWD weight
  and is **0 for every player until GW1 is played**, so the reachable ceiling is
  ~60 right now and premiums sit ~40/100. Scores rise into the 70s–80s once form
  accrues. 100 is near-asymptotic (needs form≈10 + FDR-1 + elite xGI + secure
  minutes simultaneously). The leaderboard makes this visible, which is good —
  but consider a short pre-GW1 disclaimer ("las puntuaciones suben cuando arranca
  la forma"). Ties into the Layer-3 calibration work in `position_score.py`.
- **Cross-position comparability caveat** already documented in
  `position_score.py`: scores are operationally rankable across positions but not
  fully calibrated to equal predictive meaning — a single mixed leaderboard is
  fine for v1 but a per-position default view is safer. Relates to
  the Phase 8a modeling-direction notes.
- No buy/sell language (product-wide rule): the leaderboard *rates*, it doesn't
  instruct. Positive framing only.

---

## Data & Intelligence Vision

Beyond FPL: the long-term product direction is a **holistic football intelligence platform** — not just FPL-specific advice but broader player intelligence, form tracking, fixture analysis, and market signals. Track A (historical data) and Track B (ML) are the foundation for this. The FPL framing is the initial surface; the underlying data and model layer should be designed to generalize.

# Football Intelligence Expansion — Implementation Plan

**Repository:** `darutto/FPL-Platform`
**Produced by:** Claude Code repository audit, 2026-07-13
**Input brief:** `FOOTBALL_INTELLIGENCE_PLANNING_BRIEF.md`
**Executor:** Codex, one approved phase/slice at a time
**Status:** IMPLEMENTATION REVIEW — FI-5b(a)/(b) merged; FI-6a implemented and under review; FI-6b/c/d blocked

---

## 0. Executive Recommendation

**Build before the Sportmonks trial (provider-independent, ~4 weeks, target completion 2026-08-08):**

1. `football-data-contract` — provider-neutral canonical models + the structured evidence contract (Python + TypeScript mirror).
2. `football-identity-registry` — cross-provider identity crosswalk that **wraps** (never modifies) `fpl-player-registry` and generalises the existing `player_matching.resolve_fpl_player` tiered matcher; validated pre-trial against the two external sources we already own (Understat names in the tactical store, vaastav historical imports).
3. `sportmonks-client` — full client skeleton (auth, transport abstraction, pagination, rate-limit, retries, raw-snapshot persistence) tested entirely against checked-in mock payloads built from Sportmonks' public documentation.
4. Raw→canonical ingestion pipeline + owned-store landing (parquet + R2), mirroring the proven `fpl-historical` / `fpl-tactical` pattern.
5. `football-intelligence` package — feature engine v1 + the first intelligence modules coded against canonical models and mock data, including everything computable **today** from FPL + Understat + owned history (congestion/rest-days, minutes-confidence inputs from FPL history, flank-matchup proxy reusing the zonal store).
6. Additive `FinalResponse.evidence` field + TS mirror + `EvidenceChip`/`EvidenceList`/`ConfidenceBadge` UI components, demonstrated end-to-end with mock data behind flags (all OFF by default).

**Must wait for live access (trial, 2026-08-10 → ~2026-08-24):**

- Real Sportmonks payload shape validation (formation grids, detailed positions, substitution linkage, injury feed latency).
- Identity mapping of the actual 2026-27 player pool (≥95% auto-match target + ambiguity queue burn-down).
- Calibration of role/flank inference from real lineup coordinates.
- Data-update-timing observations (pre/during/post match) and post-match corrections.
- Licensing confirmation (persistence, derived scores, subscriber display).
- Subscription go/no-go decision.

**Three intelligence modules to demonstrate first (during the trial):**

1. **Starting & minutes confidence** (`evaluate_expected_minutes`) — highest product value; upgrades the weakest input of the frozen captain formula (`minutes_risk`) without touching Layer 1.
2. **Tactical role & role stability** (`evaluate_tactical_role`) — unlocks the out-of-position and deployment-history stories; feeds the flank matchup proxy.
3. **Fixture & rotation context** (`evaluate_fixture_context`) — cross-competition congestion; builds directly on Track D's fixture engine and is partially demonstrable pre-trial with PL-only data.

(Opponent personnel disruption is phase-next: it depends on injury-feed quality + usual-starter inference that can only be validated live.)

**Conditions before activating the trial (gate, §14):** all pre-trial phases FI-1…FI-7 merged and green; acceptance scripts runnable with one env var; mock end-to-end demo recorded; licensing question list ready to send on day 1; go/no-go rubric agreed.

---

## 1. Current-State Architecture Map

This section records what actually exists as of `main@c5950d0` (2026-07-13). It supersedes the dated snapshot in `HANDOFF.md` (2026-04-01) where they differ.

### 1.1 Runtime request path

```
POST /ask ──► ask_v2() (harness.py)                      [mcp-graduation, 2026-05-18]
                ├── "@<resource>"  → resource_registry (deterministic, no LLM)
                ├── "/<prompt>"    → prompt_registry (deterministic dispatch/expansion)
                └── plain text     → ask_orchestrated() (orchestrator-PRIMARY since
                                     architectural-pivot P1.a; FPL_ORCH_ENABLED gate)
                                       ├── build_system_prompt(bootstrap context)
                                       ├── LLM chooses tools (multi-tool batching,
                                       │    Anthropic/OpenAI/Gemini via
                                       │    llm-orchestrator-core provider_client)
                                       ├── run_tool() — ALWAYS deterministic
                                       ├── evaluator (cheap-model GROUNDED/COMPLETE/SAFE
                                       │    judge, fail-open, 1 retry)
                                       └── renderer → answer text + structured meta
              → harness_adapter.py (pure mapping) → AskResponse

POST /session/{id}/ask ──► ConversationSession.respond() (legacy respond() path,
                           retains LLM-review semantics; FPL_SESSION_ENABLED kill switch)
```

Key invariant preserved everywhere: **the LLM chooses tools and phrases output; it never produces football facts.** Tool execution is deterministic; every failure path returns a valid response.

### 1.2 Tool surface (29 registered tools)

`tool_schema_registry.py` is the single source of tool definitions. Categories:

- **Intent tools (10):** captain score, rank candidates, compare, transfer advice, chip advice, fixture run, differentials, summary, resolve, current GW.
- **Retrieval tools (7, Phase 2.6):** player form, injury list, price changes, team fixture calendar, team schedule, position fixture run, transfer suggestion.
- **Track D:** `get_fixture_outlook` (two-axis FDR-first engine, `fixture_outlook.py`, real 2025-26 data).
- **Tactical track:** `get_zonal_weakness` / `get_zonal_opportunity` (Understat owned store, relative-to-baseline zonal engine, live in prod).
- **Atomic tools (8, pivot P2):** `find_players`, `get_player_snapshot`, `get_player_history`, `get_fixtures_for_gw`, `get_gameweek_context`, `get_team_snapshot`, `web_fetch` (allowlisted), `rank_players_by_metric`.

The established extension pattern (used by Track D and the zonal track, to be reused verbatim):

```
pure engine module (no registry import, no network)
  → thin *_tool.py wrapper (registers in TOOL_REGISTRY)
  → schema entry in tool_schema_registry.py
  → renderer entry
  → UI card + lib/types.ts mirror
```

### 1.3 Scoring layers (frozen semantics)

| Layer | What | Status |
|---|---|---|
| 1 | `captain_score` = form 40% + fixture 30% + xGI/90 20% + minutes 10% (`fpl-captain-engine`) | **Frozen** — baseline + regression target; never modified |
| 2 | `position_score` — position-aware weight profiles over 7 normalised components; venue-adjusted `effective_fdr` (Phase 8a1/8b) | Operational for compare/transfer/differentials |
| 3 | Future ML | Deferred, requires backtesting |

`minutes_risk` (Layer 1 input) is currently a heuristic derived from bootstrap minutes/status. This is the sanctioned insertion point for the minutes-confidence module (brief §6.1: "improve the existing minutes-risk component rather than breaking it").

### 1.4 Data & persistence (no database anywhere)

| Store | Owner | Layout | Delivery |
|---|---|---|---|
| Live FPL API | `fpl-api-client` → `fpl-pipeline` | in-memory bootstrap + fixtures | request-time |
| Owned FPL history | `fpl-historical` | gzipped raw JSON snapshots + manifests → `parquet/` (players, teams, events, fixtures, player_gw_stats) → `parquet_merged/` overlay; `_latest.json` / `_owned_latest.json` pointers | weekly GH Actions → R2; server startup sync (`owned_store_sync.py`, fail-soft, `OWNED_STORE_SYNC_ENABLED`) |
| Owned tactical (Understat shots) | `fpl-tactical` | `understat_shots.parquet` + `_tactical_latest.json` per season | weekly GH Actions → R2 under `tactical/` prefix; fail-soft sync; `soccerdata` is workflow-only, never shipped to server |
| Multi-season seed | vaastav import (H6) | prior seasons into `parquet_merged/` | one-shot operator runbook |

Established persistence invariants: atomic temp-write → `os.replace`; provenance pointer JSON rewritten on every ingest; raw snapshots immutable; baseline trees never mutated by overlays; idempotent re-runs; network only in CLI/workflow paths, **never in request handlers**; server degrades to `missing_context` when a store is absent.

### 1.5 Identity resolution (two existing mechanisms)

1. `fpl-player-registry` — user-query → FPL element (nicknames, aliases, accent handling); consumed by every intent. **Stable, do not modify.**
2. `fpl_grounded_assistant/player_matching.py` — external-source name → FPL element (`resolve_fpl_player`): NFKD-accent-strip, tiered (full name → web_name → second_name), **never guesses on ambiguity**, no fuzzy matching. Regression-pinned by PR #14 (team resolver aliases + 20-team three-way pins).

There is no cross-season, cross-provider, persistent identity store. Understat joins are name-based at query time.

### 1.6 Contracts

- `FinalResponse` frozen dataclass — stable fields + **additive optional metadata** per intent (`captain`, `comparison`, `transfer`, `chip`, `fixture_run`, `differential`, `sub_responses`, `orch_outcome`). The additive-bounded-metadata pattern is the sanctioned way to extend it.
- `http_contract_fixtures.json` — machine-readable HTTP contract; CI contract-drift gate (`scripts/run_contract_gate.sh`, `CONTRACT_GATE.md`).
- `routing_trace` — stable (graduated M5) audit schema on every `ask_v2` result.
- TS mirror: `packages/fpl-ui/lib/types.ts`; the two former P2 intent-drift failures were repaired and regression-pinned in FI-0(a).
- Per-package `CONTRACT.md` in `fpl-historical` and `fpl-tactical` freeze storage layouts.

### 1.7 UI

Next.js 15 card-based chat (`components/chat/IntentRenderer.tsx` maps intent/meta → card). 18 intent cards exist including `FixtureOutlookCard`, `DefensiveZonesCard` (zonal pitch shading), `InjuriesTable`, `ResourceRankingTable`, `QuotaIndicator`. Spanish-first; product-wide framing rule: **opportunity-positive language only** (turquoise highlight, never red-danger, no buy/sell in tactical/fixture surfaces).

### 1.8 Cost/observability infrastructure

`quota.py` (per-user rolling windows, 3 tiers), `audit.py` (append-only NDJSON + USD cost per turn), `telemetry.py` (per-branch routing counters on health surface), evaluator, off-topic Layer A–D. Deploy constraints: `--workers 1`, Gemini Flash default provider (`FPL_ORCH_PROVIDER`/`FPL_ORCH_MODEL` env).

---

## 2. Gap Analysis

| Brief requirement | Repo today | Gap |
|---|---|---|
| Canonical football data layer | FPL bootstrap shapes everywhere; Understat shots parquet; no provider-neutral entities | **New** — no canonical player/team/fixture/appearance model exists |
| Provider adapter (Sportmonks) | `fpl-api-client`, `worldcup-api-client` precedents; no Sportmonks code (`football_data_client.py` is a dormant audit copy of a football-data.org client — ignore, do not extend) | **New package** |
| Cross-provider identity | Query-time name matching only (§1.5) | **New** — persistent crosswalk, confidence, ambiguity queue, season validity |
| Derived feature layer | `position_score` components; zonal player profiles; `rolling_strength.py` in fpl-historical | Partial — no role/minutes/congestion features, no versioned feature store |
| Intelligence modules | `fixture_outlook` (schedule), `zonal_weakness` (finish-zone) | Partial — no availability/minutes/role/disruption modules |
| Structured evidence | Per-intent bounded meta dataclasses; `reasons: tuple[str,...]` phrases | **New** — no typed, versioned, confidence-carrying evidence objects |
| Cross-competition fixtures | PL only (FPL API) | **New** — needs Sportmonks (UCL/UEL/UECL/FA Cup/EFL Cup) |
| Availability/injury data | `get_injury_list` from FPL bootstrap `status`/`news` (coarse, no return dates, no opponent-unit view) | Partial — needs richer provider feed |
| Lineups/formations/roles | none | **New** — Sportmonks only |
| Minutes model | `minutes_risk` heuristic | Upgrade path defined (§1.3) |
| Flank matchup | Zonal engine = defence-side finish-zone weakness; T3 (FotMob buildup-flank) unbuilt | Partial — attacker-flank side needs tactical-role feature; proxy possible now |
| UI evidence components | Cards exist; no EvidenceChip/ConfidenceBadge | **New components**, existing pipeline |

**What is already solved and must be reused, not rebuilt:** owned-store ingestion pattern, R2 publish/sync, engine/tool/renderer/card pipeline, additive FinalResponse metadata pattern, provider-neutral LLM core, accent-robust matching, contract gate, env-flag convention, opportunity-framing language rule.

---

## 3. Proposed Target Architecture

```
Official FPL API ─────────────► fpl-api-client ──┐
Understat shots ──────────────► fpl-tactical ────┤
Owned FPL history ────────────► fpl-historical ──┤          (existing, unchanged)
Sportmonks API ───────────────► sportmonks-client ┤ (NEW: adapter + raw snapshots)
                                                  ▼
                    football-data-contract (NEW: canonical models, enums,
                    evidence contract — pure, provider-neutral, import-light)
                                                  ▼
                    football-identity-registry (NEW: crosswalk store,
                    wraps fpl-player-registry + player_matching patterns)
                                                  ▼
                    football-intelligence (NEW)
                      ├── features/   (feature engine: role, flank, minutes
                      │               inputs, congestion, availability…)
                      └── modules/    (evaluate_* — bounded questions →
                                      scores + EvidenceItem lists)
                                                  ▼
                    fpl-grounded-assistant (existing)
                      ├── *_tool.py wrappers → TOOL_REGISTRY
                      ├── tool_schema_registry entries
                      ├── renderers
                      └── FinalResponse.evidence (additive)
                                                  ▼
                    fpl-ui (existing) — EvidenceChip/EvidenceList/
                    ConfidenceBadge inside existing cards; new cards later
```

Layer separation (raw → canonical → derived → evidence → presentation) maps onto: `sportmonks-client` raw snapshots → canonical parquet (provider adapter and build orchestration in `football_intelligence.ingestion`, canonical models from `football-data-contract`) → feature parquet (`football-intelligence/features`) → evidence objects (`football-intelligence/modules`, computed at request time) → `FinalResponse.evidence` → cards.

**Provider-replacement guarantee:** only `sportmonks-client` and the explicit FI-4a provider adapter inside `football_intelligence.ingestion` may consume Sportmonks payload fields. Canonical contracts, canonical parquet columns, runtime, features, tools, evidence, and UI may not. Enforced by contamination tests in the FI-4a gate.

---

## 4. Package and Module Decisions

The brief proposes five packages. Audit-grounded decision: **four new packages** — the feature engine and intelligence modules ship as two subpackages of one `football-intelligence` package.

| Brief proposal | Decision | Justification from repo |
|---|---|---|
| `football-data-contract` | **New package** `packages/football-data-contract/` | Nothing existing fits: `fpl-data-core` is Tier-B FPL-schema-tracking (drift risk), `fpl-tool-contract` is the FPL tool surface. Must be import-light (pure dataclasses/enums + pydantic-optional) so every package can depend on it — same contamination rule as `llm-orchestrator-core`: MUST NOT import `fpl_*`, `sportmonks_*`, or any provider client. |
| `sportmonks-client` | **New package** `packages/sportmonks-client/` | Mirrors `fpl-api-client`/`worldcup-api-client` precedent (URL constants + thin wrappers). Owns network, provider payload models, envelopes, and raw snapshots. FI-4a keeps canonical persistence out of this package and places the explicit provider adapter in neutral ingestion orchestration. |
| `football-identity-registry` | **New package** `packages/football-identity-registry/` | Wraps, never modifies, `fpl-player-registry` (parity-validated, consumed by every intent — too load-bearing to touch). Generalises `player_matching.py`'s normalization + never-guess tiers into a persistent, season-versioned crosswalk. Separate package because both `sportmonks-client` ingestion and `football-intelligence` consume it, and its store has its own lifecycle. |
| `football-feature-engine` | **Merged** into `football-intelligence/features/` | Features and modules ship together in every phase, share fixtures and test harness, and have no independent consumer. Package count matters here: packages are wired by `PYTHONPATH`/sys.path shims (no pip install), so each one adds cost to the Dockerfile, test runners, and contract gate. Splitting later is cheap because both sides only speak canonical contracts. |
| `football-intelligence` | **New package** `packages/football-intelligence/` with `features/` and `modules/` subpackages | Pure + deterministic + import-light at request time (pandas/pyarrow allowed, matching `zonal_weakness.py`). Tool wrappers stay in `fpl-grounded-assistant` per the established Track D / zonal pattern. |

New-package conventions (all four): `CONTRACT.md`, `README.md`, `pytest.ini`, `requirements.txt`, `tests/` (pytest, matching `fpl-tactical`/`fpl-historical` — not the legacy standalone-runner style), added to the Dockerfile package copy list and the contract-gate PYTHONPATH.

---

## 5. Canonical Data Contracts (`football-data-contract`)

### 5.1 Entities (Python frozen dataclasses; pydantic models only at HTTP edges)

```
CanonicalPlayer      player_id (`player_` + 24 hex deterministic hash), full_name, known_name,
                     birth_date|None, nationality|None, positions_nominal
CanonicalTeam        team_id (`team_` + 24 hex deterministic hash), name, short_code
CanonicalCompetition competition_id (`competition_` + 24 hex), name, tier (league|domestic_cup|
                     continental), country|None
CanonicalSeason      season_id, label ("2026-2027"), competition_id
CanonicalFixture     fixture_id (`fixture_` + 24 hex), season_id, competition_id, kickoff_utc,
                     home_team_id, away_team_id, status, gameweek|None (PL only)
PlayerMatchAppearance fixture_id, player_id, team_id, started, minutes,
                     sub_on_minute|None, sub_off_minute|None, replaced_by|None
PlayerMatchRole      fixture_id, player_id, formation, grid_slot|None,
                     detailed_position|None, derived_flank (left|central|right|None),
                     derived_depth (deep|mid|advanced|None)
Formation            fixture_id, team_id, formation_string, source_timestamp
AvailabilityStatus   player_id, as_of_utc, state (available|doubtful|injured|
                     suspended|unregistered|unknown), detail|None,
                     expected_return|None
InjuryRecord / SuspensionRecord / Substitution / TeamMatchStats / PlayerMatchStats
ProviderRef          provider (fpl|understat|sportmonks|vaastav), provider_id (str),
                     valid_from, valid_to|None
Provenance           source_provider, ingested_at, source_timestamp|None,
                     ingestion_run_id, model_version|None
```

Rules:
- Every canonical record carries `Provenance`.
- Enums are closed vocabularies defined in this package; normalizers must map provider values into them or emit a normalization warning (never pass provider strings through).
- **Language discipline encoded in the contract:** role fields are named `derived_flank`, `formation_depth`, `starting_role` — there is no field named anything like `average_position` (brief §6.2 limitation: lineup coordinates are tactical deployment, not true operating position).
- Confirmed-fact vs inferred-proxy is a first-class distinction: shared enum `SignalBasis = observed | inferred_proxy`, carried by features and evidence.

### 5.2 TypeScript parity

Only types that reach the UI get TS mirrors (evidence types in FI-1; others as they surface). Mirror lives in `packages/fpl-ui/lib/types.ts` extensions plus a new `lib/evidence.ts`; parity is pinned by the existing lib/types contract tests. FI-0(a) confirmed that the two expected `SUPPORTED_INTENT_VALUES` drift failures had already been repaired on `main`; the actual remaining gate-trust issue was the stale Orch-4a K1 exact tool-count pin, which FI-0(a) refreshed from 10 to 29.

---

## 6. Identity Strategy (`football-identity-registry`)

**Decision (brief Q2): wrap, don't extend.** `fpl-player-registry` stays the query→FPL-element resolver. The new registry is the provider crosswalk above it.

### 6.1 Crosswalk store (parquet + JSON overrides, owned-store pattern)

`player_identity.parquet` columns: `canonical_player_id, provider, provider_id, normalized_name, full_name, team_provider_id|None, birth_date|None, valid_from, valid_to, match_method, match_confidence, manual_override(bool)`. Analogous `team_identity.parquet`, `fixture_identity.parquet`, `competition_identity.parquet` (competitions/teams are small enough to seed by checked-in YAML with manual confirmation).

- `data/football/identity/` root, `_identity_latest.json` provenance pointer, atomic replace, R2 publish under `football/identity/` prefix — all mirroring `fpl-tactical` CONTRACT §4–§6.
- `overrides.yaml` checked into the package: operator-confirmed mappings that always win (`match_method="manual_override"`, confidence 1.0).
- `ambiguity_queue.json` artifact produced by every matching run: unmatched + multi-candidate cases with the evidence for each candidate, for operator review.

### 6.2 Matching algorithm (deterministic, tiered, never-guess)

Reuses `player_matching._norm` normalization (NFKD accent-strip, casefold, whitespace collapse). Tiers, each producing `match_method` + fixed `match_confidence`:

1. Existing manual override → 1.00
2. Exact normalized full name + birth date → 0.99
3. Exact normalized full name + same team → 0.95
4. Exact normalized full name, unique league-wide → 0.90
5. web_name/known_name + same team → 0.85
6. Surname + birth date → 0.80
7. Anything ambiguous or below threshold (default 0.80, configurable) → **ambiguity queue, no mapping written**

Transfers/season changes (brief Q13): mappings are validity-ranged; a new season run re-verifies team-scoped matches and closes (`valid_to`) rows that no longer hold, rather than mutating them.

### 6.3 Pre-trial validation

The matcher is exercised before any Sportmonks data exists against: (a) Understat player names in `understat_shots.parquet` (replacing nothing — `zonal_weakness_tool` keeps its current query-time join until FI-6 optionally consumes the crosswalk), and (b) vaastav historical names. FI-2 establishes the reproducible owned-store baseline: Understat 2025/26 matched 375/461 eligible source name/team identities automatically (81.3449%), with 86 unmatched and 0 ambiguous; vaastav 2024/25 matched 804/804 (100%). Every unresolved identity remains in the committed ambiguity queue. The mandatory ≥95% automatic-match target is transferred—not waived—to the §14.1/FI-9 trial-readiness identity gate, after canonical team-crosswalk population, sanctioned Sportmonks identity metadata, audited overrides, operator queue burn-down, and upstream data-quality repair. Fuzzy or speculative matching remains prohibited.

Canonical player IDs currently hash normalized full name plus DOB. Missing DOB is a degraded mode: distinct candidate records sharing a no-DOB fingerprint fail closed before matching or overrides. A later DOB backfill changes the fingerprint and can change the canonical ID; migration must preserve and close historical rows, append the corrected mapping, and use an auditable reconciliation/override when continuity is asserted. FI-9 must revisit this strategy against live Sportmonks identity metadata.

---

## 7. Persistence Strategy

**Decision (brief Q3): no database.** Continue the proven parquet + gzipped-raw-JSON + R2 owned-store architecture. Rationale: workloads are batch (weekly/daily cron ingests) + read-only request serving; `fpl-historical`/`fpl-tactical` already solved atomicity, provenance, idempotency, R2 delivery, and fail-soft startup sync; Railway's ephemeral FS is already handled by startup sync; introducing Postgres/SQLite now adds infra the brief tells us to avoid. **Revisit trigger** (documented, not built): if ingestion becomes intra-day (live lineups ~1h before kickoff) and R2 round-trips become the bottleneck, promote the canonical layer to SQLite-on-volume first, Postgres only if multi-writer.

### 7.1 Layout

```
data/football/
├── raw/sportmonks/{endpoint}/{capture_ts}/payload.json.gz + _manifest.json
│      (immutable; manifest schema mirrors fpl-historical CONTRACT §2/§9.2:
│       schema_version, kind, endpoint, params, status, captured_at, run_id)
├── canonical/{season}/
│      players.parquet, teams.parquet, competitions.parquet, fixtures.parquet,
│      appearances.parquet, roles.parquet, formations.parquet,
│      availability_snapshots.parquet, injuries.parquet, suspensions.parquet,
│      substitutions.parquet, team_match_stats.parquet, player_match_stats.parquet
├── identity/   (§6.1)
├── features/{season}/
│      player_match_features.parquet, player_fixture_features.parquet,
│      team_match_features.parquet, fixture_context.parquet
│      (each row: feature_version column)
└── _football_latest.json   (provenance pointer per layer)
```

- Root override env: `FPL_FOOTBALL_ROOT` (mirrors `FPL_HISTORICAL_ROOT`/`FPL_TACTICAL_ROOT`).
- R2 prefix `football/` (distinct namespace, same `OWNED_STORE_R2_*` credentials); publish loud, sync fail-soft, wired into `owned_store_sync`-style startup (extend `fpl_server` lifespan the same way tactical sync was added).
- **Upsert keys:** raw = (endpoint, params, captured_at) — append-only; canonical = natural keys (`fixture_id`, `(fixture_id, player_id)` …) with most-recent-capture-wins dedup (the fpl-historical §10.4 rule); features = (entity keys, feature_version).
- **Reprocessing:** canonical and feature layers are always rebuildable from raw snapshots; a `rebuild` CLI subcommand replays raw → canonical for a season. Model-version bumps write new rows keyed by version; no destructive migration.
- **Raw retention / deletion:** raw payloads kept indefinitely by default; a `purge --provider sportmonks` CLI exists from day 1 in case licensing requires deletion on cancellation (trial question §14.3-Q8).
- **Schema migration:** parquet schemas are frozen in `sportmonks-client/CONTRACT.md`; additive columns allowed, renames are breaking and need a phase label (same rule as everywhere else in this repo).
- Evidence is **not persisted** in v1 — computed at request time from features (cheap, deterministic, versioned). An optional `intelligence_evidence.parquet` materialisation is deferred until a backtesting phase needs it.

---

## 8. Structured Evidence Contract

### 8.1 `EvidenceItem` (in `football-data-contract`; frozen dataclass + TS mirror)

```python
@dataclass(frozen=True)
class EvidenceItem:
    code: str                 # closed vocabulary, EVIDENCE_CODES registry
    label: str                # short human label (Spanish-first at UI, EN in contract)
    subject_type: str         # "player" | "team" | "fixture"
    subject_id: str           # canonical id
    fixture_id: str | None
    impact: float             # bounded [-10.0, +10.0]; sign = direction
    direction: str            # "positive" | "negative" | "neutral" (derived from impact,
                              #  kept explicit for renderers)
    confidence: float         # [0.0, 1.0] — see conventions below
    basis: str                # "observed" | "inferred_proxy"   (brief §6.4 requirement)
    summary: str              # one sentence, grounded, no advice verbs
    source_features: tuple[str, ...]   # feature names that produced it
    model_version: str        # e.g. "flank-matchup-v1"
    calculated_at: str        # UTC ISO
```

Initial `EVIDENCE_CODES` (closed; additions are contract changes): `MINUTES_CONFIDENCE_HIGH/LOW`, `ROTATION_RISK`, `CAMEO_RISK`, `ROLE_STABLE`, `ROLE_CHANGED`, `OUT_OF_POSITION`, `OPPONENT_FLANK_WEAKNESS`, `OPPONENT_UNIT_DISRUPTION`, `FIXTURE_CONGESTION`, `REST_ADVANTAGE`, `SET_PIECE_ROLE`, `AVAILABILITY_DOUBT`.

**Conventions:**
- *Impact* is on the same 0–100-score-relative scale as Layer-2 components: |impact| 0–2 minor, 2–5 meaningful, 5–10 major. Modules must document their mapping.
- *Confidence* is deterministic and rule-derived (data freshness, sample size, observed-vs-proxy), never LLM-assigned. Bands for UI: ≥0.75 High, 0.5–0.75 Medium, <0.5 Low. Incomplete inputs ⇒ confidence decreases (brief §16); missing inputs ⇒ the evidence item is **omitted**, never fabricated.
- *Versioning:* `model_version` = `<module-slug>-v<N>`; bump on any behaviour change; pinned in tests.
- *Serialization:* dataclass → dict via the existing `_to_dict` path in `harness_adapter`; stable JSON field names identical to the dataclass.

### 8.2 Exposure in `FinalResponse` (brief Q6)

- New additive field `FinalResponse.evidence: tuple[EvidenceItem, ...] | None = None` — exactly the pattern of `transfer`/`chip`/`fixture_run`. Default `None`; populated only when a football-intelligence module ran and `FOOTBALL_INTELLIGENCE_ENABLED` is on.
- **Bound: max 8 items**, ranked by |impact|·confidence; enforced at assembly.
- Multi-intent: `sub_responses[i].evidence` per sub-intent (same as other meta); top-level stays `None`.
- HTTP: additive `evidence: list[dict] | null` on `AskResponse`/`SessionAskResponse`; `http_contract_fixtures.json` gains entries with `conditional` stability; CLI debug JSON serialises it like other meta.
- Existing clients remain compatible: field is additive-optional everywhere; contract gate proves old fixtures still validate.

Traceability chain (brief §7): `EvidenceItem.source_features` → feature parquet rows (with `feature_version` + provenance) → canonical rows → raw snapshot manifests. Debug bundle gains an optional `intelligence` section listing modules run, feature versions, and data-freshness timestamps (§14 observability).

---

## 9. Intelligence Module Definitions (`football-intelligence/modules`)

All modules: pure functions over canonical/feature frames + FPL bootstrap; return a typed result (scores + `tuple[EvidenceItem, ...]` + `confidence` + `reason_codes`); `status="missing_context"` when stores are absent (never raise) — the zonal-engine degradation contract.

### 9.1 First release (build pre-trial on mocks, validate in trial)

**M1 `evaluate_expected_minutes` — Starting & minutes confidence** (brief §6.1)
- Inputs: owned FPL history (`player_gw_stats` — starts, minutes, sub timing already in the merged store), FPL `status`/`news`/`chance_of_playing`, canonical appearances + availability when Sportmonks lands, fixture congestion feature (M4).
- Outputs: `start_probability, expected_minutes, cameo_probability, rotation_risk, confidence, reason_codes` + evidence (`MINUTES_CONFIDENCE_*`, `ROTATION_RISK`, `CAMEO_RISK`).
- Deterministic v1 algorithm (placeholder logic, documented as heuristic): weighted recent-start share (last 6 PL matches, recency-weighted) × availability multiplier (state-based table) × congestion damping; expected_minutes = start_prob·E[min|start] + cameo_prob·E[min|cameo] from the player's own history. Coefficients live in one constants block, marked for post-trial calibration (FI-10) — same discipline as the 8a memory: hand-tuned v1, backtest before trusting.
- **Integration rule:** exposes `minutes_risk_v2` (0–100). Layer 1 `captain_score` is untouched. Layer 2 may consume `minutes_risk_v2` for its `minutes_score` component **only** behind `EXPECTED_MINUTES_V2_ENABLED` and only in a dedicated slice with side-by-side old/new comparison fixtures.
- Pre-trial buildable: **yes** (FPL-history-only inputs real; availability/lineups mocked).

**M2 `evaluate_tactical_role` — role & stability** (brief §6.2)
- Inputs: canonical `roles` (formation, grid_slot, detailed_position), appearances, FPL nominal position.
- Outputs: `primary_role, role_distribution, flank, flank_distribution, formation_depth, role_stability, role_change_detected, out_of_position_score, confidence` + evidence (`ROLE_STABLE`, `ROLE_CHANGED`, `OUT_OF_POSITION`).
- v1: grid-slot → (flank, depth) lookup tables per formation string (checked-in, unit-tested); distributions over last N starts; stability = share of modal role; change = modal role over last 3 ≠ modal over prior 7; OOP = mapping distance between FPL nominal position and modal derived role.
- Language rule enforced in code: outputs use only starting-role/deployment vocabulary; grid tables are `inferred_proxy` basis until trial confirms grid semantics.
- Pre-trial: **yes, fully mock-driven** (formation grids from Sportmonks docs).

**M3 `evaluate_fixture_context` — fixture & rotation context** (brief §6.5)
- Inputs: canonical cross-competition fixtures (PL from FPL API today; UCL/UEL/UECL/FA Cup/EFL Cup from Sportmonks later), rest days, M1's rotation tendency inputs.
- Outputs: `rest_days, congestion_index, rotation_probability, fixture_priority, late_cameo_risk, confidence` + evidence (`FIXTURE_CONGESTION`, `REST_ADVANTAGE`).
- v1: congestion_index = matches within trailing/leading 21-day window weighted by competition tier; fixture_priority = deterministic table (league position band × competition stage). Builds on Track D: `fixture_outlook` remains the difficulty engine; this module adds the scheduling/rotation axis and must not duplicate FDR logic.
- Pre-trial: **partially real** (PL schedule real; other competitions mocked).

### 9.2 Second wave (build pre-trial as far as mocks allow; graduate during/after trial)

**M4 `evaluate_opponent_personnel_disruption`** (brief §6.3) — usual-starter inference from appearance history; missing-starter → affected unit/flank via M2 roles; replacement experience from appearances. Outputs per brief. Blocked on live injury-feed quality → demo target during trial, not before.

**M5 `evaluate_flank_matchup` (proxy)** (brief §6.4) — join of: attacker flank (M2; pre-trial fallback = zonal `compute_player_zone_shares` finish-zone profile, explicitly `inferred_proxy`), opponent zonal weakness (existing `zonal_weakness` deltas — **reused, not reimplemented**), opponent defensive availability (M4 outputs). Every output carries `supporting_signals` + `limitations`; the finish-zone-vs-buildup-flank caveat from `fpl-tactical` CONTRACT §8 applies verbatim. True buildup-flank stays in the tactical roadmap's T3 (FotMob Tier-2) — this plan does not absorb it.

`evaluate_player_availability` folds into M1 (availability multiplier + `AVAILABILITY_DOUBT` evidence) rather than shipping as a separate module; `evaluate_role_change` folds into M2. `evaluate_team_defensive_stability` and `evaluate_player_matchup` are explicitly **out of first release**.

---

## 10. Orchestration Changes

**Decision (brief Q9, Q8): no new intent types, no new orchestration manifest.** The orchestrator-primary architecture already decomposes vague questions via multi-tool batching. Changes are bounded:

1. **New grounded tools** (thin wrappers in `fpl-grounded-assistant`, engine in `football-intelligence`), registered in `TOOL_REGISTRY` + `tool_schema_registry` + renderer, exactly like `get_fixture_outlook`:
   - `get_player_intelligence(player, modules=None)` — **the deterministic investigation runner**: resolves the player, runs the enabled module set (default: all enabled flags), returns merged evidence bundle + per-module scores. One tool call answers "Is Saka a good pick this week?" without the LLM sequencing 5 calls — keeps token cost flat (this matters: quota/audit infra bills Patreon users per token; see also `internet-ideas/2026-06-07-agentic-rag-ed-donner.md` on cheap-path routing).
   - `get_expected_minutes(player)`, `get_tactical_role(player)`, `get_fixture_context(team)` — atomic variants for narrow questions.
   - Registry grows 29 → 33. Note: `run_phase_orch3a` O6a/O6b/O6c token-budget baselines will need their documented registry-growth adjustment.
2. **System prompt:** one added SOURCE→TOOL mapping block entry ("player context / minutes / role / matchup questions → get_player_intelligence"). No change to source-discipline classification.
3. **The LLM may select modules only by choosing tools/args** from the allowlist; module internals are invisible to it. The evaluator's GROUNDED axis applies unchanged.
4. **Existing intents receiving evidence first (Q7):** `captain_score`, `compare_players`, `transfer_advice` — an FI-7 slice enriches their OK-turn assembly with evidence from M1/M3 (flag-gated). Deterministic recommendations (tiers, deltas, recommendations) are **not** changed by evidence in this plan — evidence explains; a later approved phase may let it score (that phase would define weighting profiles per brief §8).
5. **Scoring strategy (brief §8):** no universal score. Module scores are Layer-2-adjacent component scores; the only sanctioned coupling in this plan is `minutes_risk_v2` → Layer 2 minutes component behind its flag (§9.1-M1). Intent-specific weighting profiles are designed (constants + version string per profile) but **not applied** to recommendations until FI-10 backtesting exists.
6. `@resource` surface: add `@minutes <player>`, `@role <player>` resource entries in `resource_registry` (deterministic, quota-free) in FI-7 — cheap parity with the resource browse model.

Session path (`respond()`) is untouched except that `get_player_intelligence` is reachable through it like any registered tool.

---

## 11. UI Integration Plan

Phase 1 (FI-7, this plan): shared primitives inside existing cards —
- `EvidenceChip.tsx` (code-mapped icon + label + `ConfidenceBadge`), `EvidenceList.tsx` (≤8, ranked), `ConfidenceBadge.tsx` (High/Medium/Low bands).
- Wired into `CaptainCard`, `ComparisonCard`, `TransferCard` under the meta section when `evidence` present; absent → cards render exactly as today (snapshot-tested).
- Styling: Bendito Fantasy system; opportunity-positive framing — positive evidence turquoise highlight, negative evidence neutral/informational (never red-danger), Spanish-first labels from a `EVIDENCE_LABELS_ES` map.

Phase 2 (later, out of this plan's first release): `TacticalRoleBadge`, `FlankIndicator`, `AvailabilityIndicator`, `FixtureContextStrip`, `OpponentDisruptionCard`, `MatchupEvidenceCard`, `RoleHistoryMiniChart`. No pitch heatmaps from formation coordinates (would misrepresent deployment as position — prohibited by brief §13).

Renderer plumbing: `IntentRenderer` passes `evidence` through; `intent-renderer.ts` mapping updated; TS types per §5.2.

---

## 12. Security and Configuration Plan

- `SPORTMONKS_API_TOKEN` env var; added to `.env.template`; never committed; server-side only (token never reaches the browser — UI talks only to our backend).
- Client behaviour without token: offline construction is explicit; live construction without required configuration raises `SportmonksConfigurationError`. Future request-time runtime integration must use capability discovery and may expose unavailable/disabled status without constructing a live client; no undefined `ProviderUnavailable` transport result is required.
- Transport: `requests`, redirects disabled, 15s timeout default, bounded idempotent-GET retries, secret-safe typed errors, and numeric `Retry-After` capped at 60 seconds. A streaming response-size cap is a hard FI-4a prerequisite before any live ingestion call; an after-download length check is insufficient.
- Rate-limit strategy: controlled serialized ingestion scheduling plus sanitized rate-header observation and reactive bounded 429 handling. A proactive token bucket is not required before offline FI-4a; revisit only if live trial measurements show controlled pacing is insufficient.
- Cache: raw snapshot store *is* the cache (replay via `rebuild`); no separate HTTP cache layer.
- Secret rotation: documented procedure in `sportmonks-client/README.md` (Railway env update + restart; no code change).
- Feature flags (env vars, matching `orch_config.py` truthy-parse convention, all default OFF), read via a new `football_intelligence/config.py`:
  `FOOTBALL_INTELLIGENCE_ENABLED` (master), `SPORTMONKS_ENABLED` (client+sync), `TACTICAL_ROLE_ENABLED`, `EXPECTED_MINUTES_V2_ENABLED`, `OPPONENT_DISRUPTION_ENABLED`, `FLANK_MATCHUP_ENABLED`, `FOOTBALL_STORE_SYNC_ENABLED` (startup R2 sync).
  Capability registry considered and rejected: env flags are the established repo mechanism (`FPL_ORCH_ENABLED`, `OWNED_STORE_SYNC_ENABLED`, `FPL_SESSION_ENABLED`) and per-module granularity needs nothing richer.
- Graceful degradation matrix (tested): flag off → field absent; store missing → `missing_context`; partial data → reduced confidence; stale data → freshness timestamp in debug + confidence penalty.

---

## 13. Testing Strategy

Philosophy preserved: no network, no API key, deterministic, checked-in sanitized fixtures; contract gate must stay green at every slice.

| Layer | Tests (per brief §12, mapped to packages) |
|---|---|
| `sportmonks-client` | auth config, include/query construction, pagination (multi-page mock), retry/rate-limit/timeout behaviour (injected fake transport), malformed payloads, empty results, snapshot manifest writing, no-token degradation |
| Normalizers | one test module per entity (fixtures, players, teams, lineups, formations, grid positions, detailed roles, subs, injuries, suspensions, stats); closed-enum mapping; normalization-warning emission; provenance stamping |
| `football-identity-registry` | tier-by-tier matching, accents/unicode, nicknames, duplicate surnames, name+DOB, name+team, club changes (validity ranges), manual overrides win, confidence thresholds, ambiguity queue contents; live-shaped corpus from Understat + vaastav names |
| `football-intelligence` | per-module: golden fixture frames → expected scores/evidence (pinned `model_version`); role-stability, flank-distribution, formation-depth tables; OOP vs nominal position; expected-minutes inputs; congestion; disruption; evidence generation bounds (≤8, impact/confidence ranges); `missing_context` degradation |
| Contract | `FinalResponse.evidence` additive (old fixtures unchanged); TS↔Python evidence parity; multi-intent serialization; **provider-leak gate**: grep-based test that no `sportmonks` identifier appears outside `sportmonks-client` (and no `EvidenceItem` field carries a provider id) |
| Integration | mock raw payloads → canonical parquet → features → evidence → `respond()`/`ask_v2()` metadata → renderer output; flags-off regression sweep (full existing validation corpus green with all FI flags unset) |
| Live (trial only) | FI-8 acceptance scripts — explicitly excluded from CI; keyed, network-touching, operator-run |

Runner conventions: new packages use pytest (`fpl-tactical` precedent); grounded-assistant slices add `run_phase_fi*_tests.py` runners and get appended to `scripts/run_contract_gate.sh` where they pin contracts. Codex must run the contract gate before completing any slice.

---

## 14. Trial-Readiness Checklist

### 14.1 Gate — do not activate the trial until all boxes tick

- [ ] FI-1…FI-7 merged to main; contract gate + full validation corpus green with flags off **and** with flags on over mocks
- [ ] Mock end-to-end demo recorded: question → `get_player_intelligence` → evidence in `AskResponse` → EvidenceChips rendered
- [ ] `SPORTMONKS_API_TOKEN` wiring proven with token absent (degradation) and dummy-token (auth-failure path)
- [ ] FI-8 acceptance scripts (`packages/sportmonks-client/scripts/trial_*.py`) runnable end-to-end against mocks via `--mock`
- [ ] Identity matcher reaches ≥95% automatic matching on the current-season Understat corpus after canonical team-crosswalk population and sanctioned Sportmonks identity metadata are applied. FI-2 baseline: 375/461 (81.3449%), with an 86-item unresolved queue. Before this gate passes, unresolved identities must be reduced below 5% through canonical team-crosswalk alignment, richer sanctioned identity metadata, audited manual overrides, and upstream encoding/data-quality fixes. Fuzzy matching, speculative aliases, and unsafe fall-through matching are prohibited.
- [ ] Licensing question list (§14.3) ready to send to Sportmonks support on day 1
- [ ] Go/no-go rubric (§14.4) agreed
- [ ] Trial dashboard artifact: `TRIAL_STATUS.md` template with the 20 acceptance objectives from brief §11.3 as a checklist, updated daily during the trial

### 14.2 Trial execution outline (FI-9, ~Aug 10–24)

Day 1–2: auth live; competition/season id discovery; entity availability sweep → record every payload as raw snapshot. Day 2–5: full PL squads + players ingest; populate canonical team crosswalks; apply licensed Sportmonks birth dates and richer player names where available; re-run the real current-season identity corpus; review and burn down the FI-2 unresolved queue; and verify that no fuzzy, speculative, or unsafe matching tier was introduced. The identity trial gate cannot pass below ≥95% automatic matching. Day 5–10: lineups/formations/injuries for preseason + opening fixtures; validate grid semantics against known deployments (e.g. Saka right, Mitoma left — same known-flank pinning trick as the zonal fix). Aug 22–24: opening weekend live observation — update timing pre/during/post match, corrections, stat completeness; run M1–M3 on real data; produce three-module demo + subscription recommendation.

### 14.3 Questions for Sportmonks support (send day 1)

The twelve questions from brief §11.5 verbatim, plus two audit-derived additions:
13. Are formation-grid coordinates documented semantics (slot indices vs pitch coordinates), and are they stable across competitions?
14. What is the actual per-hour/per-entity rate limit on the trial vs the Starter plan?

### 14.4 Subscription go/no-go rubric (brief Q17)

**GO requires all:** (a) ≥95% PL player auto-map (post-queue ≥99%); (b) confirmed lineups available pre-kickoff with formation + grid for ≥90% of PL fixtures observed; (c) injuries/suspensions update within 48h of public news for sampled cases; (d) licensing answers permit raw storage + derived scores + subscriber display; (e) Starter+1 plan covers PL + UCL + FA Cup + EFL Cup at minimum; (f) M1–M3 produce sensible evidence on opening weekend (spot-check ≥20 players).
**NO-GO / defer if:** grid data absent or undocumented (M2 collapses to detailed_position only — re-evaluate value), licensing blocks derived display, or mapping <90% auto.
**Partial fallback:** if only lineups are weak, a lineups-only cheaper source may be reconsidered — decision recorded in `TRIAL_STATUS.md`.

---

## 15. Phased Codex Execution Plan

> **Phase-label disambiguation:** Track D (fixture intelligence) already used unhyphenated `FI0`–`FI7` labels in commits and in `tool_schema_registry.py` ("Track D/FI2"). This plan's phases are the **hyphenated `FI-0`…`FI-10`** from the brief and are unrelated to Track D's. Codex: when a repo artifact says `FI<digit>` without a hyphen, it refers to Track D, not this plan.

Global rules for every phase (brief §18 — Codex MUST): work one approved slice at a time; read `FINAL_RESPONSE_CONTRACT.md`, `CONTRACT_GATE.md`, and the relevant package `CONTRACT.md` before edits; tests before/alongside code; no network in unit tests; provider-neutral models outside the adapter; no unapproved features; document deviations; update `PACKAGE_STATUS.md` + this plan's phase table after each slice; run the contract gate before completion; produce a completion report (files, tests, risks); **stop and request plan revision if the repo contradicts this plan**. Codex MUST NOT: put provider calls in prompts, let the LLM infer football facts, expose credentials to the frontend, couple recommendation code to provider payloads, replace deterministic scoring, rename stable fields, present lineup coordinates as average position, or add infrastructure (DBs, queues) without written justification.

Phase table (each phase = one or more PR-sized slices; "Trial-dep" = requires live Sportmonks):

### FI-0 — Audit closure & scaffolding *(complete)*
- **Purpose:** this document is the FI-0 audit outcome. Both mechanical slices are complete.
- **Slices:** (a) close intent-contract gate drift so the TS/Python gate is trustworthy. The two expected `lib/types.ts` `SUPPORTED_INTENT_VALUES` failures were already repaired on `main`; the accepted review widened FI-0(a) to refresh the actual remaining stale Python Orch-4a K1 exact-count pin from 10 to 29. (b) scaffold the four packages (dirs, CONTRACT.md stubs, pytest.ini, requirements, Dockerfile copy list, contract-gate PYTHONPATH) with zero logic.
- **Tests:** existing UI contract tests green; empty-package import smoke.
- **DoD:** `npm test` contract suite green; `bash scripts/run_contract_gate.sh` green; packages importable.
- **Trial-dep:** none. **Pre-trial:** yes.

### FI-1 — Provider-neutral contracts + evidence contract
- **Files new:** `packages/football-data-contract/football_data_contract/{entities.py, enums.py, evidence.py, provenance.py, __init__.py}`; `packages/fpl-ui/lib/evidence.ts`; contract parity test.
- **Contracts added:** everything in §5 + §8.1 (`EvidenceItem`, `EVIDENCE_CODES`, `SignalBasis`). No existing contract changes.
- **Tests:** dataclass shape pins; enum closure; TS↔Py parity; contamination test (package imports nothing beyond stdlib/pydantic).
- **Docs:** `football-data-contract/CONTRACT.md` (field-by-field, versioning rules).
- **DoD:** parity test green both sides; contract gate green. **Trial-dep:** none. **Pre-trial:** yes.

### FI-2 — Identity & mapping foundation
- **Files new:** `packages/football-identity-registry/…` (matcher, store I/O, overrides.yaml, ambiguity queue, CLI `python -m football_identity_registry.cli {build,verify,queue}`).
- **Existing touched:** none (`player_matching.py` copied/generalised, original left in place for zonal until FI-6).
- **Contracts:** crosswalk parquet schemas frozen in package CONTRACT.md.
- **Algorithms:** §6.2 tiers.
- **Tests:** §13 identity row; Understat + vaastav corpus report committed as test artifact.
- **FI-2 identity corpus DoD (formally amended after Fable re-review):** duplicate-fingerprint and collision handling fail closed; real owned-store corpus validation is measured and committed with reproducible provenance; Understat 2025/26 baseline is 375/461 automatically matched (81.3449%), with 86 unmatched and 0 ambiguous; vaastav 2024/25 is 804/804 (100%); all unresolved identities are retained in the committed ambiguity queue; idempotent rebuild and canonical-ID stability are proven. The mandatory ≥95% target moves to the §14.1/FI-9 trial-readiness identity gate and is expected to be reached through populated team crosswalks, sanctioned Sportmonks birth dates/richer names, audited manual overrides, operator queue burn-down, and upstream encoding repair. Fuzzy or speculative matching remains prohibited. **Trial-dep:** none. **Pre-trial:** yes.

### FI-3 — Sportmonks client skeleton
- **Files new:** `packages/sportmonks-client/sportmonks_client/{config.py, transport.py, client.py, models.py, endpoints/*.py}`; `tests/fixtures/*.json` (sanitized doc-derived payloads for: fixtures, seasons/competitions, teams+squads, players, lineups+formations+detailed positions, substitutions, injuries, suspensions, coaches, referees, team/player match stats).
- **Contracts:** client public API (typed methods per endpoint family returning provider models); `SportmonksConfigurationError` for missing live configuration; snapshot manifest schema.
- **Algorithms:** pagination iterator, controlled scheduling plus reactive bounded 429 handling, retry policy (§12).
- **Tests:** §13 client row via injected fake transport.
- **Docs:** README (auth, includes, rate limits as documented — flagged UNVERIFIED until trial).
- **DoD:** all client tests green with no network; `SportmonksClient.offline(...)` demonstrated. **Trial-dep:** payload shapes are doc-derived — every fixture carries governed `_fixture` provenance until FI-9 validation. **Pre-trial:** yes.
- **FI-3 implementation discrepancies (recorded after Fable review and resolved by the pre-FI-4 checkpoint):** `ProviderUnavailable` was not added; missing-token live construction uses `SportmonksConfigurationError`, now the blessed operator-facing policy. Controlled scheduling plus reactive bounded HTTP 429 handling is the approved pre-live strategy; a proactive token bucket is conditional on trial measurements. No response-size cap exists; a streaming cap is a hard FI-4a prerequisite before the first live request. JSON fixture provenance uses governed `_fixture` metadata because JSON has no comments. Endpoint modules are represented by one governed endpoint table. `SportmonksClient.offline(...)` replaces the planned `--mock` surface.

### Pre-FI-4 canonical-contract reconciliation checkpoint *(complete)*
- Canonical formats are provider-neutral deterministic hashes owned by `football-data-contract`: `player_`, `team_`, `competition_`, `season_`, and `fixture_`, each followed by 24 lowercase hex characters. FI-2 player IDs remain unchanged; the former `cp_`/`ct_`/`cc_`/`cf_` text was never a stored implementation.
- Player fingerprints use the owned FPL registry/history full name plus DOB under canonical normalization. Corrections require historical close-and-append migration; missing DOB remains degraded/fail-closed; FI-9 reassesses authority with live-validated richer identity data.
- Teams use seeded immutable registry keys, never display-name-only minting. Competition keys include governing body/category. Fixture keys exclude kickoff so rescheduling preserves identity and use explicit replay discriminators.
- Fingerprint components reject empty/whitespace-only values, leading/trailing whitespace, and the reserved `|` separator before hashing. Team keys use exactly `jurisdiction|stable_club_key|category|squad_level` with lowercase ASCII letters, digits, and single hyphens. Full literal IDs for all five entity types independently pin the format; valid existing IDs are unchanged.
- `ProviderIdentifier` is the sole persisted provider vocabulary; FI-2 strings remain read-compatible and unknown values fail.
- Cross-contract consistency tests delegate through the existing FI-2 package runner; no checkpoint runner was added.
- Evidence `details` is rejected for v1 because quantitative values belong to canonical/feature stores; FI-6 uses bounded impact/confidence/summary/source-feature references.
- `ProviderUnavailable` is rejected as a transport result; missing live configuration raises `SportmonksConfigurationError`, while future runtime capability discovery degrades without constructing the client.
- Redirects are disabled; snapshot headers use a secret-safe allowlist; malformed `meta` is typed. Controlled scheduling plus reactive 429 handling is sufficient pending measurements. A streaming response cap is mandatory in FI-4a before any live request.
- No normalizer, canonical store, persistence, R2, workflow, server, feature, tool, UI, or runtime integration was added.

### FI-4a — Normalizers and canonical store
- **Implemented location:** provider-specific normalization orchestration lives in neutral `football_intelligence.ingestion`, while `sportmonks-client` retains provider records/transport only. This is an intentional dependency-boundary correction from the earlier illustrative `sportmonks_client/normalize` path.
- **First deliverable:** governed team-registry/crosswalk seed before player or fixture normalization.
- **Contracts:** canonical parquet schemas and `_football_latest.json`; provider mocks/raw snapshots → canonical records; deterministic byte-stable replay and rebuild CLI.
- **Safety prerequisite:** streaming response-size cap is implemented at the transport boundary and tested without live calls. It does not authorize live ingestion. Ordinary FI-4a tests remain offline.
- **DoD:** mocks → full canonical parquet set; idempotent atomic local writes; replay proven byte-stable. No production server integration.

### FI-4b — Distribution and runtime integration
- **Files new/touched:** R2 publishing/synchronization, disabled scheduled workflow, server lifespan hook behind `FOOTBALL_STORE_SYNC_ENABLED`, and production deployment validation.
- **DoD:** fail-soft startup and store-absent behavior, scheduled delivery, synchronization, and deployment checks. No feature computation.

### FI-5 — Feature engine v1
- **Files new:** `packages/football-intelligence/football_intelligence/{config.py, features/{roles.py, minutes.py, congestion.py, availability.py, io.py}}`.
- **Outputs:** feature parquet tables (§7.1) with `feature_version`; features per brief §5.4 subset: `primary_role, role_stability, flank, flank_distribution, formation_depth, out_of_position_score, start_probability inputs, expected_minutes inputs, cameo inputs, rotation tendency, fixture_congestion_index, rest_days, availability multiplier`.
- **Algorithms:** formation-grid lookup tables; recency-weighted start shares; 21-day congestion window.
- **Tests:** §13 feature rows; golden frames.
- **DoD:** features computable from (a) pure mocks and (b) real owned FPL history where inputs exist today. **Trial-dep:** role features mock-only until live. **Pre-trial:** yes.

### FI-5b — Approved module-enablement prerequisite *(merged and complete)*
- **Reason:** validated `fi5-registry-v1` summaries cannot reproduce M1's last-six conditional-minute procedure, M2's last-three versus prior-seven role comparison, or M3's as-of stage/standing/leading-schedule context. The module formulas must not be weakened and FI-6 must not bypass the validated feature boundary.
- **Decision:** Option A, split into (a) provider-neutral canonical scheduling context v2 and (b) module-enablement feature registry/schema v2. Existing canonical schema v1, feature schema 1, and `fi5-registry-v1` remain immutable and readable by their existing tooling.
- **FI-5b(a):** add governed `CompetitionStage`, as-known-at-cutoff fixture schedule snapshots, and team standing snapshots. Historical bands use one latest complete standings table identity strictly before cutoff and recompute rank with a literal points/goal-difference/goals-scored/wins/canonical-team-ID chain. Active teams come exclusively from the storage-neutral canonical competition-membership contract effective at `as_of_utc`; standings rows cannot establish participation and provider-observed position is audit-only. Both snapshot contracts govern primary keys, equal-timestamp conflicts, strict as-of selection, join cardinality, stable ordering, and deterministic replay. The definition of done includes the field-level proof obligations in `FOOTBALL_INTELLIGENCE_FI5B_RECONCILIATION.md`; unavailable stage/standing/schedule context remains unknown rather than using current state.
- **FI-5b(b):** mint `fi5-registry-v2`, `fi5-engine-v2`, feature manifest schema 2, and `strictly-before-kickoff-v2`. Add last-six weighted start/cameo conditional-minute sufficient statistics; normalized last-10/last-3/prior-7 role-window summaries and distributions; and team-fixture trailing/leading scheduling plus as-of standing context. Intelligence probabilities, expected minutes, risk, confidence, fixture priority, recommendations, and evidence remain FI-6 outputs.
- **Compatibility:** FI-6 accepts v2 exclusively and fails typed on v1; migration is an explicit offline rebuild from a validated canonical-v2 build. No runtime reinterpretation or in-place mutation.
- **M3 policy:** complete prerequisites before FI-6. M3 is active and produces golden output with complete mocks; individual dependent outputs may return deterministic `missing_context` when stage, standings, or as-of schedule context is unavailable. All M1-M3 implementations are required for FI-6 completion.
- **Inherited hardening:** causally pin strict same-time exclusion with a completed candidate and team-scoped congestion with an unrelated third-team fixture. Do not change FI-5 formulas.
- **Full contract:** `FOOTBALL_INTELLIGENCE_FI5B_RECONCILIATION.md` owns the approved field-level delta, grains, dtypes, units, windows, provenance, replay, risks, and per-slice definitions of done.
- **Authorization:** FI-5b(a)/(b) are merged and complete. FI-6a is authorized, implemented, and under review. FI-6b/c/d remain blocked; FI-7(a) is merged (PR #45), FI-7(b)–(e) have not started.

### FI-6 — Intelligence modules v1 (M1, M2, M3; M4/M5 skeletons)
- **Prerequisite:** approved and completed FI-5b(a)/(b); FI-6 consumes validated v2 feature builds exclusively.
- **Files new:** `football_intelligence/modules/{expected_minutes.py, tactical_role.py, fixture_context.py, opponent_disruption.py (skeleton), flank_matchup.py (skeleton, consumes existing zonal deltas via its public functions)}`.
- **Contracts:** per-module result dataclasses + evidence emission per §9; `model_version` strings minted.
- **Replay/non-persistence:** replay means deterministic reevaluation from an identical validated FI-5b v2 build with an identical explicit `calculated_at`. Results and evidence are frozen but are not persisted; FI-6 adds no intelligence build family, manifest, or pointer. Optional `intelligence_evidence.parquet` remains deferred to backtesting.
- **FI-6a explicit inputs:** availability state/chance-of-playing and nominal position are versioned evaluator inputs, not resurrected FI-5 v1 features. M1 coefficients live in the `expected-minutes-hand-tuned-v1` constants block and must be backtested before they are treated as calibrated.
- **Skeleton boundary:** M4/M5 expose metadata and a typed non-operational `not_implemented` response only, with no scores, defaults, evidence, or rows eligible for an intelligence build. They never return `missing_context`, which is reserved for implemented modules lacking governed row context. Their active execution path must fail explicitly.
- **Tests:** §13 module rows; evidence bounds; degradation matrix.
- **DoD:** M1–M3 produce pinned evidence on golden fixtures; M4/M5 return `not_implemented` cleanly. **Trial-dep:** M4 graduation; M2 grid-semantics confirmation. **Pre-trial:** yes (mocks).

### FI-7 — Response and UI integration
- **Slices:** (a) `FinalResponse.evidence` + serialization + `http_contract_fixtures.json` additions + CLI debug; (b) tools `get_player_intelligence`, `get_expected_minutes`, `get_tactical_role`, `get_fixture_context` + schemas + renderers (registry 29→33; adjust documented orch3a token baselines); (c) evidence enrichment of `captain_score`/`compare_players`/`transfer_advice` OK turns behind master flag; (d) UI `EvidenceChip/EvidenceList/ConfidenceBadge` + card wiring + `@minutes`/`@role` resources; (e) end-to-end mock demo script + recording.
- **Existing files touched:** `final_response.py`, `harness_adapter.py`, `tool_schema_registry.py`, renderer module, `resource_registry.py`, `fpl_server.py` (serialization only), `IntentRenderer.tsx`, three cards, `lib/types.ts`.
- **Compatibility:** all additive; flags-off sweep of the full validation corpus is the slice-(c) gate.
- **Tests:** contract additivity; renderer snapshots with/without evidence; tool schema validation; Jest card tests.
- **DoD:** demo recorded; contract gate + validation corpus + `npm run build`/tests green. **Trial-dep:** none. **Pre-trial:** yes — completing FI-7 IS the trial-readiness bar.
- **Status (2026-07-26):** slice **(a) complete — merged in PR #45** (approved head `7de77b2`): additive optional immutable `FinalResponse.evidence`, recursive adapter serialization, `AskResponse`/`SessionAskResponse` omit-when-None, `lib/types.ts` mirror, `http_contract_fixtures.json` evidence fixtures, FI-1 gate graduated from deferred. Slices **(b)–(e) not started**; **(b) is the next engineering task**. Carry-forward (F2): add a session-level end-to-end evidence test in slice (b) once an assembler can produce top-level evidence — the `session_ask` top-level path is an equivalent-mutant until then. **Not a slice:** PR #48 (`fix(ui): mirror player season points intent`, merged to main `03bac5697d087e1dba636ef8c4f534edc63d978a`) was a **post-merge cleanup associated with PR #47** — a one-file, two-line TypeScript intent-mirror parity fix, not an FI-7 roadmap slice.

### FI-7b — detailed slice specification (source of truth for b1–b3)

**Status:** planned; next engineering task. Supersedes the one-line FI-7(b) summary in the §15 FI-7 block for implementation detail. Delivered as three sequential, independently-reviewed sub-slices (b1 → b2 → b3), each its own draft PR.

#### Verified module dependencies (confirmed merged on main)
FI-7b exposes already-merged, fully-implemented FI-6 modules — no module work occurs in FI-7b:
- **M1 `expected_minutes`** — FI-6a, PR #31 (implemented).
- **M2 `tactical_role`** — FI-6b, PR #32 (implemented).
- **M3 `fixture_context`** — FI-6c, PR #40 (implemented); this is the FI-6c `football-intelligence` `fixture_context` module, not the separate Track-D `fpl_grounded_assistant` fixture-context helper.

#### Explicit exclusions
- **M4 `opponent_disruption`** (FI-6d, PR #42) and **M5 `flank_matchup`** (FI-6e, PR #43) are merged as **skeletons** returning `not_implemented`. FI-7b exposes **no** tool for M4/M5. They gain tools only after their modules graduate under a future FI-6 slice.

#### Master flag
`FOOTBALL_INTELLIGENCE_ENABLED`, defined in `orch_config.py` mirroring the `FPL_ORCH_ENABLED` pattern (env constant, truthy parse helper, **default OFF**, value snapshotted into the harness debug/audit bundle beside `feature_flag_orch_enabled`). When OFF: the FI-7b tools are excluded from the offered LLM tool set, and no FI-6 module is imported on the request path. The flag governs all of b1–b3.

#### Tool set, schemas, registry transition
Four tools, schemas added to `tool_schema_registry.py`. Two distinct counts, not to be conflated:
- **Static schema registry:** 29 → **33** in **b1** (the four schema definitions exist once registered), and remains 33 through b2–b3.
- **Offered LLM tool set:** flag-gated — **29** when `FOOTBALL_INTELLIGENCE_ENABLED` is OFF (byte-identical to the pre-FI-7b offered set), **33** when ON.

| Tool | Backing | Returns |
|---|---|---|
| `get_expected_minutes(player)` | M1 | minutes result dataclass + evidence |
| `get_tactical_role(player)` | M2 | role result dataclass + evidence |
| `get_fixture_context(team, fixture)` | FI-6c `football-intelligence` M3 `fixture_context` | fixture-context result dataclass + evidence, using resolved `team_id`, selected `fixture_id`, explicit UTC `calculated_at`, and a validated v2 build |
| `get_player_intelligence(player)` | M1+M2+M3 composite | merged result + merged evidence (default investigation, Q8/Q9) |

In **b2**, `get_player_intelligence(player)` resolves the player to the canonical `player_id` and `team_id`, selects the applicable fixture deterministically to obtain `fixture_id`, acquires the validated v2 build and explicit UTC `calculated_at`, and constructs the exact public M1/M2/M3 input types before invoking the modules. M3 does not consume `player_id`.

Implementers must verify the live static pre-count is 29 before adding; if it differs, stop and reconcile rather than hardcoding. The documented orch3a token baselines are updated in **b2**.

#### Evidence propagation and the ≤8 bound
FI-7a already delivered the `FinalResponse.evidence` field and generic serialization (`Enum→.value`, tuple→array, omit-when-None at the HTTP boundary). Serialization exists; population does not yet exist. In **b2**, orchestrator-answered results from the four new FI-7b tools will populate `FinalResponse.evidence` through new bounded stateless assembly wiring. That wiring does not enrich any existing intent; existing-intent enrichment remains FI-7c. In **b3**, session-path integration will populate top-level and nested evidence as required for the end-to-end `/session/{id}/ask` test that retires F2.

The **≤8-item evidence bound (brief §8.2 / Q6)** — deliberately *not* implemented in FI-7a — is owned **here**. It is deterministic selection/truncation, not a newly scored ranking model:
1. The composite preserves module order: M1 `expected_minutes`, then M2 `tactical_role`, then M3 `fixture_context`.
2. Within each module, preserve the evidence order emitted by that module.
3. Deduplicate only exact duplicate `EvidenceItem`s using their fully serialized canonical value.
4. Take the first eight remaining items.
5. Do not use an LLM, relevance score, confidence guess, or nondeterministic ordering.
6. Single-module tools apply the same exact deduplication and first-eight truncation while preserving their native emitted order.

#### Cross-slice invariants (apply to b1, b2, and b3)
1. **Additive only.** No change to deterministic recommendations, tiers, deltas, routing, classification, rendering of existing intents, or HTTP-contract semantics.
2. **Flag-off byte-identity.** With `FOOTBALL_INTELLIGENCE_ENABLED` OFF, the full validation corpus and contract gate are byte-identical to pre-FI-7b main; no FI-6 import on the request path.
3. **Honest degradation.** Tools surface each module's `missing_context` / `not_implemented` verbatim — never fabricated scores, defaults, or evidence.
4. **No LLM-sourced evidence.** Evidence derives only from deterministic module output, consistent with the FI-6 grounding invariant.
5. **Scope isolation.** No existing-intent evidence enrichment (FI-7c), no UI (FI-7d), no M4/M5, no new intent.
6. **Registry vs. allowlist.** The static registry reaches exactly 33 in b1 and remains 33 through b2–b3. The flag controls whether the four FI-7b tools are included in the offered LLM tool set.

#### Sub-slice boundaries
- **b1 — flag + schemas + wiring (zero module risk).** Add the flag to `orch_config.py`; add the four tool schemas to `tool_schema_registry.py`; add placeholder handlers returning `not_implemented`; and gate the four tools into the orchestrator's offered allowlist only when the flag is ON. No FI-6 import. The static registry reaches 33, while the flag-OFF offered tool set remains byte-identical to the pre-FI-7b set of 29.
- **b2 — real handlers + stateless evidence assembly.** Replace the four placeholder handlers with implementations that resolve the requested player through the existing football identity registry to canonical `player_id` and `team_id`; select the applicable fixture deterministically to obtain `fixture_id`; acquire the validated v2 build and explicit UTC `calculated_at` required by the FI-6 public APIs; construct the exact public M1, M2, and M3 input types; and call the unchanged M1/M2/M3 modules, returning result dataclasses and deterministic evidence. This is new FI-7b identity-resolution, fixture-selection, build-loading, and input-construction wiring, not FI-6 module implementation. The composite bundles M1+M2+M3 evidence in module/native order, performs exact serialized-value deduplication, and takes the first eight; single-module tools use the same native-order exact-deduplication and first-eight rule. Add bounded stateless orchestrator-answered assembly that copies evidence from only these four new tools into `FinalResponse.evidence`. Update the documented orch3a token baselines in this slice. Adds no schemas, renderers, session integration, existing-intent enrichment, UI, M4/M5, or FI-6 logic changes.
- **b3 — renderers + session integration + F2 test.** Add tool-output text renderers for the orchestrator-answered path and session-path evidence assembly/integration as required; add the `/session/{id}/ask` end-to-end test asserting top-level and nested evidence and retiring F2 (below). No card/chip work.

#### Cumulative acceptance criteria
Every sub-slice must leave the tree green on **both** configurations:

| Gate | Flag OFF | Flag ON (over mocks) |
|---|---|---|
| Full validation corpus | byte-identical to pre-FI-7b main | passes; tools offered & callable |
| Contract gate (`run_contract_gate.sh`) | 16/0, unchanged | 16/0 |
| Static schema registry | 33 valid schemas | 33 valid schemas |
| Offered LLM tool set | 29, byte-identical | 33, including four FI tools |
| Handler behavior | tools unreachable | four tools callable over mocks |
| `npm run build` / Jest | green, unchanged | green |
| FI-1 gate | 22/0 | 22/0 |

Any deviation between the two configurations not explained by the flag is a blocker. After b1 the static-registry row is 33 under both flag states; the flag-OFF offered set stays 29.

#### F2 retirement condition
The FI-7a review left finding **F2** open: the `session_ask` top-level `evidence` path is an equivalent-mutant (structurally always `None`) until an assembler can produce top-level evidence. **b3 retires F2** by adding the required session-path evidence assembly/integration and a session-level end-to-end test asserting top-level **and** nested `evidence` serialization on `/session/{id}/ask` once `get_player_intelligence` populates it. F2 is considered closed only when that test exists and passes with the flag ON.

#### Explicit non-goals (deferred to later FI-7 slices)
- **FI-7c:** evidence enrichment of `captain_score` / `compare_players` / `transfer_advice` OK-turn assembly behind the master flag. FI-7b adds **no** evidence to any existing intent.
- **FI-7d:** `EvidenceChip` / `EvidenceList` / `ConfidenceBadge` UI, card wiring, and `@minutes` / `@role` resources. FI-7b touches **no** `lib/types.ts` and no UI.
- **FI-7e:** the recorded mock end-to-end demo.
- Out entirely: `player_recommendation` intent (Q8, post-calibration), M4/M5 tools, any change to FI-6 module logic or deterministic scoring.

#### Files touched (union across b1–b3)
`orch_config.py` (flag); `tool_schema_registry.py` (4 schemas, static 29→33); a tools/handlers module (confirm existing home vs new); renderer module (tool-output text); `harness.py` / orchestrator allowlist wiring (flag-gated); bounded stateless `FinalResponse.evidence` assembly for the four new tools; session-path evidence assembly/integration; tests. **Not touched:** `final_response.py` field set (FI-7a already added `evidence`), `lib/types.ts`, any existing-intent assembly, FI-6 modules.

### FI-8 — Trial readiness gate
- **Files new:** `sportmonks-client/scripts/trial_{auth,entities,fixtures,squads,lineups,injuries,stats,mapping}.py` (each: live call → raw snapshot → normalize → report; `--mock` mode for CI-less rehearsal); `TRIAL_STATUS.md` template; licensing checklist doc; go/no-go rubric doc (§14.4).
- **DoD:** §14.1 checklist fully ticked. **Trial-dep:** none to build; exists to spend the trial well. **Pre-trial:** yes.

### FI-9 — Live trial execution *(operator + Codex support)*
- Per §14.2. Deliverables (brief §11.4): working connector; raw+canonical ingestion of real payloads; M1–M3 on real data; one end-to-end visual example; go/no-go decision documented. Identity work must re-run the real current-season corpus after populated canonical team crosswalks and licensed Sportmonks birth dates/richer player names are applied; review and burn down the FI-2 86-item unresolved queue; prove no fuzzy, speculative, or unsafe tier was introduced; and demonstrate ≥95% automatic matching before the identity trial gate passes. Payload-shape mismatches found here are handled as plan-revision requests, fixed in `sportmonks-client` only.
- **Trial-dep:** entirely. **Pre-trial:** no.

### FI-10 — Post-trial calibration
- Compare predicted vs actual minutes (owned history now includes trial GWs); validate role tables; adjust confidence rules and M1 coefficients (version bumps); document limitations; decide paid add-ons; decide whether `EXPECTED_MINUTES_V2_ENABLED` and evidence-informed weighting profiles (brief §8) get their own approved follow-on plan.
- **Trial-dep:** requires trial data + ≥2 gameweeks of season. **Pre-trial:** no.

---

## 16. Answers to the Brief's §19 Questions

1. **Contracts owner:** new `football-data-contract` (§4) — no existing package is provider-neutral and import-light.
2. **fpl-player-registry:** wrapped by `football-identity-registry`, never modified (§6).
3. **Storage:** owned parquet + raw gzip JSON + R2; no DB; revisit trigger documented (§7).
4. **Raw caching/replay:** immutable snapshots + manifests; `rebuild` CLI replays raw→canonical (§7.1).
5. **Versions:** `feature_version` columns; `model_version` on evidence; profile version strings; bump-on-change, pinned in tests (§8.1).
6. **Evidence in FinalResponse:** additive optional `evidence` field, ≤8 items, same pattern as existing meta (§8.2).
7. **First intents:** captain_score, compare_players, transfer_advice (§10.4).
8. **`player_recommendation` intent:** later. `get_player_intelligence` + orchestrator covers the vague-question case now; a deterministic intent can graduate post-calibration (§10).
9. **Module selection:** LLM chooses allowlisted tools; composite tool bundles the default investigation; flags gate modules (§10).
10. **Pre-trial computable:** congestion/rest (PL), minutes-confidence inputs (owned history), finish-zone flank proxy (zonal store), identity for Understat/vaastav, everything else on mocks (§9, §15).
11. **Blocked until live:** grid semantics, injury latency, usual-starter inference (M4), stat completeness, mapping of real pool, update timing (§0, §14.2).
12. **Current vs historical separation:** per-season directories + validity-ranged identity rows; baseline/overlay never mutated (§6.2, §7.1).
13. **Transfers across seasons/clubs:** validity ranges (`valid_from`/`valid_to`), re-verification runs close stale rows (§6.2).
14. **Stale injury data:** freshness timestamps in provenance → deterministic confidence penalty → below threshold, evidence omitted (§8.1, §12 degradation matrix).
15. **Confirmed vs inferred:** `SignalBasis` enum on features and `basis` on every evidence item (§5.1, §8.1).
16. **Minimum pre-trial demo:** the FI-7(e) recorded mock end-to-end (question → evidence → chips) (§14.1).
17. **Go/no-go rubric:** §14.4.

---

## 17. Risks and Open Questions

| Risk | Mitigation |
|---|---|
| Sportmonks docs ≠ live payloads (grid fields especially) | All fixtures flagged `UNVERIFIED_VS_LIVE`; FI-9 day-1 shape sweep; mismatches fixed only inside the adapter |
| Grid coordinates unusable/undocumented | M2 degrades to detailed_position-only roles; go/no-go criterion (b)/(NO-GO) covers it |
| Licensing blocks storage or derived display | Question list day 1; `purge` CLI exists; derived-only exposure (no raw fields in contracts) is already the design |
| Identity mapping under 95% on real pool | Ambiguity queue + overrides.yaml workflow sized for operator triage during trial |
| Understat mojibake/encoding defects reduce identity matches | **Tracked debt:** repair encoding in the `fpl-tactical` ingestion path before the FI-9 identity gate; do not compensate with speculative aliases |
| Canonical team labels are not yet aligned across providers | **Tracked debt:** seed and populate canonical team-label crosswalks before the FI-9 identity trial-readiness check |
| Trial window misses (season start slips / trial starts late) | Everything through FI-8 is provider-independent; trial can shift without waste |
| Token-cost creep from new tools | Composite tool keeps typical investigations to 1 call; schemas compressed per P1.e conventions; quota/audit already meter |
| Evidence misread as advice | Framing rules encoded: no advice verbs in `summary`, opportunity-positive UI, deterministic recommendations unchanged by evidence in v1 |
| Intent-contract drift can mask future registry changes | FI-0(a) verified the two expected TS mirror repairs already existed, added explicit regression pins, and refreshed the stale independent Orch-4a exact tool-count assertion to 29. |
| Hand-tuned v1 coefficients trusted too much | Explicit heuristic labels, FI-10 backtest gate before any recommendation coupling (8a lesson) |
| Package sprawl / PYTHONPATH breakage | Only 4 new packages; FI-0(b) wires Dockerfile + gate once; import-smoke tests |

Open questions requiring trial validation are enumerated in §14.2/§14.3 and must not be answered by assumption in code (Codex rule: stop and ask).

---

## 18. Explicit Non-Goals (this plan)

- No ML/learned weights (Layer 3) — FI-10 only decides whether to plan it.
- No modification of Layer 1 `captain_score`, existing tier vocabulary, or any existing recommendation logic.
- No buildup-flank (FotMob Tier-2) ingestion — remains `TACTICAL_ASSISTANT_ROADMAP.md` T3.
- No pitch heatmaps from formation coordinates; no "average position" language anywhere.
- No database, queue, or new hosted infrastructure.
- No new user-facing intents; no changes to routing-ladder ordering, quota tiers, or session semantics.
- No tracking data, no additional paid providers (Sportmonks decision itself waits for the trial rubric).
- No removal or rewrite of the existing zonal/fixture-outlook engines — FI reuses their public functions.
- No live Sportmonks calls before FI-9, anywhere, including tests.

---

## Appendix A — Per-phase status table (Codex updates after every slice)

| Phase | Slice | Status | Tests | Notes |
|---|---|---|---|---|
| FI-0 | a — intent contract-drift repair | complete | UI contract 27/27; Orch-4a 217/217; contract gate 7/7 | Backend `dispatcher.py` is authoritative for response intents. The expected `fixture_outlook`/`zonal_opportunity` TypeScript mirror repairs already existed on `main` via `a630104`; FI-0(a) added explicit regression pins and, per accepted review, widened scope to refresh the stale independent Orch-4a K1 literal tool-count pin from 10 to 29. FI-0(b) was not started. |
| FI-0 | b — package scaffold | complete | pytest import smoke 4/4; UI contract 27/27; TypeScript check green; FI-0(b) runner 16/16; Orch-4i 74/74; contract gate 8/8 | Added the four import-light, dependency-free package scaffolds and wired their paths into the backend image, local/CI contract gate, and package inventories. Docker COPY wiring is statically pinned; a local image build was unavailable because the Docker daemon was not running. No FI-1 contracts, provider logic, features, modules, or runtime behavior were added. FI-1 was not started. |
| FI-1 | contracts + evidence | complete | football-data-contract pytest 47/47; Python/TS evidence parity 7/7; UI contract 27/27; TypeScript check green; FI-0(b) 16/16; FI-1 gate 22/22; Orch-4i 78/78; contract gate 9/9 | Added frozen provider-neutral canonical entities, closed enums, provenance, the 13-code bounded `EvidenceItem` contract, and a UI-only TypeScript mirror. Fable review hardening made parity parsing CRLF-safe and documented lineup-entry/timestamp validation boundaries. No dependencies or runtime/HTTP/FinalResponse fields were added. Carry-forward hardening refreshed Docker COPY matching, FI-7 registry growth, and verified Orch-4a/4b counts. FI-2 was not started. |
| FI-2 | identity registry | complete — amended DoD | identity pytest 34/34; FI-2 gate 5/5; FI-0(b) 16/16; FI-1 22/22; Orch-4i 82/82; contract gate 10/10 | B1 pins pytest in CI and a seeded failure proved propagation; B2 makes distinct no-DOB candidate collisions fail closed before overrides; B3 commits the reproducible real owned-store measurement. Understat: 375/461 (81.3449%), 86 unmatched, 0 ambiguous; vaastav: 804/804 (100%). Fable formally transferred the mandatory ≥95% identity target to the §14.1/FI-9 trial-readiness gate. The 86-item unresolved queue remains a tracked blocker and was not waived. Existing runtime joins remain unchanged and FI-3 was not started. |
| FI-3 | sportmonks client | complete | sportmonks-client pytest 49/49; FI-3 gate 5/5; FI-0(b)/FI-1/FI-2 green; Orch-4i 86/86; contract gate 11/11 | Added offline-only configuration/auth plumbing, injected transport, 15 endpoint families, provider-owned immutable models, envelopes/snapshots, bounded GET retry/rate-limit handling, pagination guards, secret-safe errors, documentation-derived fixtures, assumption registry, and a one-request guarded live smoke CLI. Fable hardening suppresses raw request causes and clamps numeric Retry-After to 60 seconds. All live assumptions remain unverified; no account/token/network was used. Former ProviderUnavailable/token-bucket/response-cap discrepancies are resolved by the checkpoint row below. No FI-4 normalization began. |
| Pre-FI-4 | canonical-contract reconciliation checkpoint | complete | football-data-contract 76/76; identity/cross-contract 40/40; Sportmonks 53/53; FI-0(b) 16/16; FI-1 22/22; FI-2 5/5; FI-3 5/5; Orch-4i 86/86; contract gate 11/11 | Blessed deterministic canonical IDs and ownership, governed FPL fingerprint authority/migration, seeded team and scheduling identities, closed provider compatibility, rejected EvidenceItem details v1, settled ProviderUnavailable and pre-live transport policies, and split FI-4a/FI-4b. Fable hardening validates every free-string component, enforces the four-segment team-key grammar, and independently pins all five full ID formats. Valid existing IDs are unchanged. No FI-4 implementation began. |
| FI-4 | a — normalizers and canonical store | complete | football-intelligence 77 passed/2 platform skips; sportmonks-client 67/67; FI-4a runner 5/5; Orch-4i 90/90; contract gate 12/12 | Added a governed two-team seed and four-provider exact crosswalks, owned-player precedence, season/fixture key grammars, offline mock normalizers for all 15 approved families, explicit deterministic parquet schemas, safe quarantine, content/byte-hashed manifests, atomic pointer publication, replay/validate/rebuild CLI, and a 4 MiB streaming transport cap. Fable remediation additionally types and sanitizes mid-stream request failures, confines manifest entity paths after resolution, and governs active build IDs with `[a-z0-9]+(?:-[a-z0-9]+)*`; symlink escapes fail closed. Orchestration is in the neutral ingestion layer rather than the plan's illustrative provider-package path. All Sportmonks assumptions remain unverified; no token/account/network, R2, workflow, server, runtime, feature, tool, UI, or FI-4b work was used. |
| FI-4 | b — distribution and runtime integration | complete | football-intelligence 94 passed/2 platform skips; FI-4b runner 5/5; Orch-4i 94/94; contract gate 13/13 | Replaced absolute source paths with portable manifest-v2 descriptors and explicit schema-v1 rejection. Added governed S3-compatible keys/configuration, secret-safe store abstraction, immutable pointer-last publication, strict pointer schema, bounded streaming downloads, validated atomic local-cache activation/rollback, synchronization locking, fail-soft backend capability discovery, read-only runtime handle, operator CLI, and strong in-memory tests. No real account/credential/network or Sportmonks request was used; no feature, tool, analysis route, UI, or FI-5 work started. |
| FI-5 | feature engine v1 | complete | feature tests 20/20; football-intelligence 120 passed/2 platform skips; FI-5 runner 5/5; Orch-4i 98/98; contract gate 14/14 | Added the closed 13-feature provider-neutral registry, strict pre-kickoff historical windows, deterministic player-as-of-fixture computation, row/build provenance, immutable atomic local feature builds, strict manifest/source-hash validation, offline build/validate/replay/status CLI, leakage/determinism/path/rollback tests, and bounded FI-4b hygiene. Post-review hardening pins exact registry dataset/column dependencies plus same-time exclusion, governed row-universe, exact 21-day endpoints, cross-competition/season isolation, grouping, null-history, and deterministic tie behavior. No network/provider call, prediction, recommendation, tool, route, UI, evidence, remote feature publication, or FI-6 work. |
| FI-5b | a — canonical scheduling context v2 | merged; complete | measured totals recorded by PR #29 | Added provider-neutral stage, effective competition membership, as-known schedule snapshots, complete historical standings selection, deterministic rank/bands, immutable canonical-v2 build/replay, and mutation-resistant boundary/tie-break tests. FI-5b(b) carries the approved non-blocking hardening. |
| FI-5b | b — module-enablement features v2 | merged; complete | FI-5b(b) 36/36; FI-5b(a) 29/29; combined FI-5 85/85; full package 185 passed/2 platform skips; Orch-4i 106/106; contract gate 16/16 | Added closed 30-field `fi5-registry-v2` with stable manifest-bound hash, parallel engine/manifest/cutoff v2, normalized M1 start/cameo, M2 role-window, and M3 schedule/standing sufficient statistics, immutable dual-source-bound builds/replay, and explicit v1/v2 rejection. Review remediation decouples nearest-fixture rest from 21-day congestion, total-orders same-kickoff fixtures, and rejects deterministic cross-source fixture contradictions before output. PR #30 merged at `7c45292c126b76fce0a6323723bb8acb1ad9a4cc`. |
| FI-6 | a — shared contracts, strict v2 input, and M1 | implemented; under review | focused FI-6a 11/11; full football-intelligence 196 passed/2 platform skips; contract gate 16/16 | Added frozen module/result contracts, strict validated v2 row loading, explicit `availability-input-v1`, pure `expected-minutes-v1` evaluation, hand-tuned-v1 coefficient versioning, deterministic evidence/replay, and corruption-versus-absence degradation tests. No persistence, tool, response, orchestration, recommendation, UI, FI-6b/c/d, or FI-7 work. |
| FI-7 | a — `FinalResponse.evidence` + serialization + TS mirror + fixtures + FI-1 gate graduation | complete — merged PR #45 | FI-7a focused 6/6; FI-1 gate 22/22; TS evidence-contract 8/8; contract gate 16/0 | Additive optional immutable `evidence` on `FinalResponse`; recursive adapter serialization (`Enum→.value`, dataclass walk, tuple→array, None→absent at HTTP boundary); `AskResponse`/`SessionAskResponse` omit-when-None; `lib/types.ts` mirror; `http_contract_fixtures.json` evidence fixtures; FI-1 gate graduated from deferred. Approved head `7de77b2`. Carry-forward (F2): add a session-level end-to-end evidence test in FI-7b once an assembler can produce top-level evidence (`session_ask` top-level path is an equivalent-mutant until then). No flag, tool, intent enrichment, or UI work — those are FI-7b+. |
| — | post-merge cleanup — PR #47 intent drift (NOT a roadmap slice) | complete — merged PR #48 | UI contract 27/27; evidence-contract 8/8; full Jest 406/25 suites; contract gate 16/0; FI-1 22/22; PR-47 Python 15/15 | **Not an FI-7 slice** — recorded here only to explain the extra PR between FI-7a and FI-7b. Two-line TypeScript intent-mirror parity fix (`packages/fpl-ui/lib/types.ts` only): added `player_season_points` to the `Intent` union and `SUPPORTED_INTENT_VALUES`, restoring parity with `dispatcher.py` after PR #47 shipped the backend intent without the UI mirror. Merged to main `03bac5697d087e1dba636ef8c4f534edc63d978a`. FI-7a untouched. |
| FI-7 | b–e response/UI integration | not started | — | (b) tools + schemas + renderers is the next engineering task |
| FI-8 | trial gate artifacts | not started | — | |
| FI-9 | live trial | blocked until ~2026-08-10 | — | |
| FI-10 | calibration | blocked on FI-9 | — | |

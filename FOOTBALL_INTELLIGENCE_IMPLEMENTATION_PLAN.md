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
4. **Existing intents receiving evidence first (Q7):** `captain_score`, `compare_players`, `transfer_advice` — FI-7c enriches their OK-turn assembly, behind the master flag, by reusing the governed `get_player_intelligence` M1 → M2 → M3 composite and its already-bounded evidence. This supersedes this section's earlier M1/M3-only phrasing; FI-7c must not filter M2 or reconstruct/re-bound an M1/M3 subset. Deterministic recommendations (tiers, deltas, recommendations) are **not** changed by evidence in this plan — evidence explains; a later approved phase may let it score (that phase would define weighting profiles per brief §8).
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
- **Status (2026-08-01):** slices **(a) and (b) complete**. FI-7a merged in PR #45. FI-7b1/b2/b3 merged in PRs #51/#53/#55; b3 closed F2 through deterministic FI rendering plus real single- and multi-intent session evidence propagation. **FI-7c documentation is the active slice; implementation has not started.** FI-7d/FI-7e remain unstarted. **Not a slice:** PR #48 (`fix(ui): mirror player season points intent`, merged to main `03bac5697d087e1dba636ef8c4f534edc63d978a`) was a **post-merge cleanup associated with PR #47** — a one-file, two-line TypeScript intent-mirror parity fix, not an FI-7 roadmap slice.

### FI-7b — detailed slice specification (source of truth for b1–b3)

**Status:** complete. FI-7b1, FI-7b2, and FI-7b3 merged in PRs #51, #53, and #55. Supersedes the one-line FI-7(b) summary in the §15 FI-7 block for implementation detail.

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

### FI-7b2 — deterministic Football Intelligence runtime integration

**Status:** complete — merged in PR #53. This subsection remains the
authoritative FI-7b2 runtime contract; FI-7b3 subsequently merged in PR #55.

#### Runtime responsibilities and ownership

FI-7b2 owns only the stateless adapter between the four FI-7b1 tool shells and
the already-merged FI-6 M1–M3 APIs. Its responsibilities are:

1. resolve a tool argument through the existing FPL query resolver, then map
   the resolved FPL provider identity through the owned
   `football-identity-registry` crosswalks;
2. resolve the canonical player and team IDs without minting, guessing, fuzzy
   matching, or modifying identity data;
3. select or validate one canonical target fixture under the deterministic
   rule below;
4. acquire one validated `module-enablement-features-v2` build and its exact
   validated canonical-v1 and `canonical-context-v2` source bindings;
5. capture or receive one explicit UTC `calculated_at` for the tool invocation
   and pass that same value to every invoked module;
6. construct the existing frozen M1, M2, and M3 input dataclasses through their
   public v2 loaders;
7. evaluate M1, M2, and M3 in the fixed order M1 → M2 → M3 when the composite
   tool requests all three;
8. serialize module results without changing their statuses, reasons, model
   versions, confidence, or evidence; and
9. assemble bounded evidence under the native-order, exact-deduplication,
   first-eight rule already governed by the FI-7b source-of-truth section.

FI-7b2 does not own identity matching policy, canonical-ID generation, feature
calculation, module formulas, feature-build publication, pointer mutation,
rendering, or recommendation logic. It delegates those responsibilities to the
existing resolver, `football-identity-registry`, FI-5b v2 validation, and FI-6
module contracts respectively.

#### Deterministic fixture selection

The governing sources are:

- `football_intelligence.ingestion.context_v2.select_schedule`, which selects
  independently per fixture the latest schedule snapshot whose
  `observed_at_utc` is strictly before the supplied cutoff;
- `football_intelligence.features.engine_v2`, which treats a next fixture as
  eligible only when its governed status is exactly `scheduled` and its kickoff
  is strictly after the cutoff; and
- `FEATURE_CONTRACT.md`, which makes `fixture_id` the deterministic secondary
  ordering key for same-kickoff fixtures.

FI-7b2 therefore pins this player-tool target-selection algorithm:

1. Use the invocation's explicit UTC `calculated_at` as the selection cutoff.
2. Validate the selected feature build and both source bindings before using
   any row. Corrupt, contradictory, unsupported, or unversioned artifacts fail
   with their existing typed validation/unsupported-contract error and are
   never treated as missing context.
3. From the validated `canonical-context-v2` source, select the latest schedule
   snapshot for each fixture with `observed_at_utc < calculated_at`, exactly as
   `select_schedule` does.
4. Join those schedule facts to validated canonical fixtures involving the
   resolved canonical `team_id`.
5. Retain only fixtures whose selected status is exactly `scheduled` and whose
   `scheduled_kickoff_utc` is strictly greater than `calculated_at`.
6. Retain only fixtures represented as target rows for that team in the
   selected validated FI-5b v2 build. This prevents the runtime from evaluating
   a fixture outside the immutable build it has loaded.
7. Sort candidates by `(scheduled_kickoff_utc, fixture_id)` ascending and select
   the first.

The boundary cases are fixed:

| Case | Required result |
|---|---|
| Multiple future fixtures | Earliest kickoff wins; canonical `fixture_id` breaks an exact-kickoff tie. |
| Postponed fixture | Excluded because its selected status is not `scheduled`; it may become eligible only through a later as-known `scheduled` snapshot in a later validated build/invocation. |
| Completed fixture | Excluded. |
| Live fixture | Excluded. |
| Kickoff equal to `calculated_at` | Excluded by the strict-future boundary. |
| Missing kickoff | Invalid canonical/context artifact; typed validation failure, never sorting fallback. |
| Duplicate fixture ID or duplicate target key | Invalid validated artifact; typed validation failure, never first-row-wins. |
| Missing/empty fixture ID | Invalid canonical/context artifact; typed validation failure. |
| No eligible fixture | Deterministic `missing_context`; no module is invoked. |

`player_fixture_run.py` and `get_team_snapshot.py` are not authoritative for
this selection. Their gameweek-oriented FPL display helpers neither consume the
validated canonical v2 schedule nor govern status/as-known semantics.

For `get_fixture_context(team, fixture)`, the caller supplies a fixture
reference. FI-7b2 resolves that reference through the existing identity
crosswalk, verifies that the resolved canonical team participates in the
resolved canonical fixture, and requires the exact `(fixture_id, team_id)`
target row in the validated v2 build. It does not silently replace an explicit
fixture with the next fixture.

#### Identity lifecycle

The player-tool input is the existing FI-7b1 `player` argument. FI-7b2 first
delegates query parsing and unique FPL element resolution to the existing FPL
resolver. `not_found` and `ambiguous` remain deterministic terminal tool
results; FI-7b2 must not choose among ambiguous candidates.

For a unique FPL element, FI-7b2 uses the active FPL-provider row in the owned
identity store to obtain `canonical_player_id`, and the active FPL team
crosswalk to obtain `canonical_team_id`. Exactly one active mapping must exist
for each resolved provider identity. No mapping yields `missing_context`;
multiple active mappings, invalid validity intervals, an unknown provider, or
a player/team mapping contradiction is a typed identity-validation failure.
The FPL nominal position and availability inputs remain explicit,
versioned evaluator inputs sourced from the resolved FPL element; they do not
become FI-5 features.

The identity registry owns matching tiers, overrides, canonical ID generation,
validity history, and ambiguity policy. FI-7b2 owns only the read-only runtime
adapter that composes the existing FPL resolver with validated active
crosswalks. It performs no crosswalk writes and never creates an identity.
`football-identity-registry/README.md` currently states that the package has no
runtime consumer; FI-7b2 is the first authorized consumer, not evidence that a
runtime adapter already exists.

Team-only fixture-context input follows the same lifecycle through the existing
exact FPL team data and active team crosswalk. The repository does not govern a
new fuzzy team/fixture resolver. A canonical ID may be used directly; otherwise
the reference must identify exactly one active provider row (an exact governed
team name/provider ID for a team, or provider fixture ID for a fixture).
The explicit fixture reference is resolved through the governed fixture
crosswalk. An unresolved or ambiguous team/fixture reference is deterministic
`not_found`/`ambiguous`; absent governed crosswalk context is
`missing_context`.

#### Build loading and module invocation

One tool invocation uses one immutable feature build, its bound validated
canonical sources, and one `calculated_at`. The handler resolves the configured
local runtime handle once, resolves the v2 pointer once if a pointer is the
configured entry point, and validates the resulting build before module
loading. It must not fall back to FI-5 v1 or an unversioned feature root.

Loading and evaluation order is fixed:

| Tool | Load/evaluate order |
|---|---|
| `get_expected_minutes` | Load M1 input (including governed M3 congestion columns used by M1), then evaluate M1. |
| `get_tactical_role` | Load M2 input, then evaluate M2. |
| `get_fixture_context` | Load M3 input, then evaluate M3. |
| `get_player_intelligence` | Load/evaluate M1, then M2, then M3 against the same build, bindings, fixture, team, player where applicable, and `calculated_at`. |

Lazy import/loading is permitted only after
`FOOTBALL_INTELLIGENCE_ENABLED` is ON and the tool has been selected. It must
not change results or ordering, and the OFF path must retain the FI-7b1
no-FI-6-import guarantee. There are no retries, remote reads, pointer refreshes,
fallback builds, or wall-clock reads inside the adapter or modules. A caller
may retry a whole request as a new invocation, but FI-7b2 itself evaluates each
module at most once.

Absent build, manifest, or exact governed row degrades only as already allowed
by the relevant FI-6 loader. Unsupported families/versions raise
`UnsupportedFeatureContractError`; malformed, contradictory, non-finite, or
corrupt supported-v2 input raises `FeatureV2ValidationError` (or the existing
typed identity validation error before module loading). FI-7b2 must not catch
those failures and relabel them `missing_context`.

#### Aggregation and partial-module contract

Single-module tools return the serialized frozen result of their backing
module, including its native `status`, reason codes, confidence, model/build
versions, identifiers, and bounded evidence. `missing_context` remains an
honest module result and is not replaced with defaults.

The composite returns an ordered module mapping with keys
`expected_minutes`, `tactical_role`, and `fixture_context` in that order. Every
successfully evaluated module result is present, including a native
`missing_context` result. Composite status is derived without prediction:

- `ok` when all three module statuses are `ok`;
- `partial` when at least one is `ok` and at least one is
  `missing_context`; and
- `missing_context` when none is `ok`.

The composite records each native module status and reason codes so the
top-level status never hides which context is absent. Its evidence is assembled
M1 then M2 then M3, preserving native order, removing only fully serialized
exact duplicates, and taking the first eight.

A native `missing_context` result does not prevent later modules from being
evaluated. For example, M1 `ok`, M2 `missing_context`, and M3
`missing_context` produces composite `partial` with the M1 result/evidence and
both missing-context results/reasons intact. M1 `missing_context`, M2 `ok`, and
M3 `ok` is likewise `partial`.

Typed identity, fixture, unsupported-contract, or validation failures are
request-level failures because they invalidate the shared identity/build
premise. They abort the invocation deterministically; the composite must not
return a misleading partial bundle from modules evaluated before the failure.
Unexpected exceptions also fail the tool through the existing tool-runner
error boundary and do not trigger fallback values, retries, an LLM-generated
answer, or partial evidence.

For identical validated identity/build inputs, explicit tool arguments, and
explicit `calculated_at`, serialization is byte-stable: fixed module order,
fixed mapping order, immutable tuples, canonical enum values, exact evidence
deduplication, and no process-global accumulation.

#### Per-tool contract

| Tool | Inputs and resolution | Output | Deterministic failures |
|---|---|---|---|
| `get_expected_minutes` | FI-7b1 `player`; resolve canonical player/team, select target fixture, load M1 with explicit availability and `calculated_at`. | Serialized `ExpectedMinutesResult` plus native bounded evidence. | `not_found`/`ambiguous`, identity/build validation error, or native M1 `missing_context`. |
| `get_tactical_role` | FI-7b1 `player`; resolve canonical player/team and nominal FPL position, select target fixture, load M2. | Serialized `TacticalRoleResult` plus native bounded evidence. | `not_found`/`ambiguous`, identity/build validation error, or native M2 `missing_context`. |
| `get_fixture_context` | FI-7b1 `team` and `fixture`; resolve both canonical identities, verify participation, load exact M3 row. | Serialized `FixtureContextResult` plus native bounded evidence. | `not_found`/`ambiguous`, team-fixture mismatch, identity/build validation error, or native M3 `missing_context`. |
| `get_player_intelligence` | FI-7b1 `player`; one canonical identity, one selected fixture, one validated build/binding set, one `calculated_at`; invoke M1→M2→M3. | Ordered three-module bundle, derived composite status, native reasons, and merged evidence capped at eight. | Shared identity/fixture/build failures abort; native module `missing_context` values aggregate under the partial-module rules above. |

No tool calls M4 or M5. No tool selects an opponent, ranks a player, changes a
recommendation, or describes module confidence as predictive certainty.

#### Explicit FI-7b2 non-goals

FI-7b2 does not implement or change:

- text/card renderers or FI-7b3 session integration;
- UI, TypeScript response types, evidence chips, or evidence formatting;
- evidence for existing intents;
- recommendation generation or ranking;
- M1–M5 formulas, FI-5 features, schemas, registries, manifests, or pointers;
- new intelligence modules, M4/M5 tools, or b3 behavior;
- network/provider calls, remote refresh, persistence, or intelligence builds;
- tool schemas, the 33-entry static registry, the 29/33 offered-set gate, or
  the default-OFF master flag.

#### FI-7b2 acceptance matrix

| Area | Required acceptance |
|---|---|
| Fixture selection | Latest as-known facts strictly before `calculated_at`; only strict-future `scheduled` targets; `(kickoff, fixture_id)` order; explicit tests for multiple, same-time, postponed, live, completed, missing kickoff/ID, duplicate ID/key, and no candidate. |
| Deterministic identity | Existing resolver + active owned crosswalks only; unique player/team/fixture mappings; ambiguity never guessed; no writes or ID minting. |
| Build loading | One validated FI-5b v2 build and exact source bindings per invocation; no v1/unversioned fallback, retries, remote reads, or pointer mutation. |
| Module invocation | M1/M2/M3 use existing public loaders/evaluators and one shared `calculated_at`; composite order is M1→M2→M3; each module evaluated at most once. |
| Partial results | All combinations of `ok`/`missing_context` pin composite status, native result retention, native reason retention, and evidence order; typed corruption/unsupported/identity failures abort rather than degrade. |
| Reproducibility | Reversed source-row order, repeated evaluation, lazy-vs-eager import, and fresh-process replay produce identical selected fixture, results, reasons, evidence, and serialization. |
| Flag behavior | OFF retains 29 offered tools and no FI-6 request-path imports; ON retains 33 static/offered tools and enables only the four governed handlers. |
| Runtime isolation | No wall clock inside modules/adapter, network/provider import, LLM fallback, mutable global cache, session state, renderer, UI, recommendation, M4/M5, FI-5 behavior, or persisted intelligence. |
| Regression | Focused FI-7b2 tests, FI-6 M1/M2/M3 suites, FI-7b1 flag/registry tests, full grounded-assistant suite, football-intelligence suite, contract gate, Jest, and production build preserve their governed baselines. |

### FI-7b3 — deterministic rendering, response evidence, and session F2 closure

**Status:** complete — merged in PR #55 at merge commit
`9e36795adbffcf361274565a6f8868fb8f71d25c`. FI-7c, FI-7d, and FI-7e remain
separate and unstarted.

#### Verified current state and exact remaining gap

The merged FI-7b2 runtime returns deterministic structured dictionaries for
`get_expected_minutes`, `get_tactical_role`, `get_fixture_context`, and
`get_player_intelligence`. Each dictionary contains native status/reasons and
the already-bounded evidence list; the composite preserves M1 → M2 → M3 order,
exact-value deduplication, and the first-eight bound.

On the stateless orchestrator-answered path, `harness.ask_v2()` currently copies
the tool dictionary into `raw_output` but uses the orchestrator's existing
`answer_text` unchanged and does not copy `raw_output["evidence"]` into the
top-level `evidence` key consumed by `harness_adapter.to_ask_response()`.
Consequently FI-7b2 does **not** yet populate stateless
`FinalResponse.evidence`/`AskResponse.evidence`; the b2 source-of-truth wording
describes the intended ownership, while this b3 subsection governs the
remaining implementation.

`SessionAskResponse` already has the optional evidence field. `session_ask()`
already converts `r.evidence` through the generic recursive serializer and
passes it to that top-level field, and `_sub_response_dict()` already serializes
and includes a nested response's evidence when non-`None`. Therefore nested
evidence can serialize today when injected. The remaining F2 gap is production:
`ConversationSession.respond()` reuses the legacy `FinalResponse` path, which
does not yet produce FI tool evidence, so session top-level evidence remains
`None` and ordinary nested FI evidence is likewise unreachable. FI-7b3 must
connect the existing FI orchestrator result to `FinalResponse` on both the
stateless and session paths, then prove the real HTTP path end to end.

#### Renderer ownership and prohibitions

A new bounded FI renderer module in `fpl_grounded_assistant` owns deterministic
text rendering for exactly the four FI tools. It exposes one dispatcher over
four tool-specific pure renderers (or equivalently four pure public functions
behind one bounded dispatcher). Each renderer consumes only the serialized
structured FI-7b2 tool result and returns text. The harness/orchestrator response
assembly selects that renderer only after a successful call to one of the four
FI tools; generic and existing-intent rendering remain unchanged.

Renderers must not reinvoke M1/M2/M3, reload builds, resolve identities, select
fixtures, recalculate confidence, reorder or create evidence, generate
recommendations, invent explanations, call an LLM, read the network, use the
wall clock, or mutate request/global state. Native status, reason codes, model
values, and canonical serialized numbers remain authoritative. Where the
repository has no existing numeric-formatting precedent, render the canonical
serialized value without introducing a new rounding policy.

#### Deterministic per-tool text contracts

All labels and sections below have fixed order. Every rendered line uses the
literal `Label: value` form. Status is the first line (`Status: <native-status>`),
reasons are the last line when non-empty (`Reasons: <code-1>, <code-2>, ...`),
and a governed null value is rendered as the literal `unavailable`. Repeated
evaluation of the same structured result produces identical text. Native
reason-code order is preserved; an empty reason list adds no fabricated reason.

| Tool | Fixed text contract |
|---|---|
| `get_expected_minutes` | After status, fixed labels are `Expected minutes`, `Start probability`, `Cameo probability`, `Rotation risk`, `Minutes risk v2`, and `Confidence`, followed by reasons when present. Values are the canonical serialized FI-7b2 values. `missing_context` therefore renders each unavailable native value as `unavailable` plus native reasons; it never prints invented minutes or start/bench/buy advice. |
| `get_tactical_role` | After status, fixed labels are `Primary role`, `Role distribution`, `Primary flank`, `Flank distribution`, `Formation depth`, `Role stability`, `Role change detected`, `Out-of-position score`, and `Confidence`, followed by reasons when present. Distributions preserve their governed serialized order and values. `missing_context` uses `unavailable`/the governed empty distribution plus native reasons and never converts role facts into strategy. |
| `get_fixture_context` | After status, fixed labels are `Fixture priority`, `Congestion index`, `Weighted trailing congestion 21d`, `Weighted leading congestion 21d`, `Previous rest days`, `Next rest days`, `Competition tier`, `Competition stage`, `League position band`, and `Confidence`, followed by reasons when present. `missing_context` preserves unavailable fields/reasons and never invents FDR, opponent difficulty, rotation implications, or advice. |
| `get_player_intelligence` | Render fixed sections `Expected minutes`, `Tactical role`, `Fixture context` in M1 → M2 → M3 order. `ok` renders all three native sections. `partial` renders available sections and a deterministic unavailable marker with native reasons for every missing section. When all modules are `missing_context`, retain all three section headings and unavailable markers. |

Typed identity, fixture, build, validation, and unsupported-contract failures
remain request-level failures and must not be rendered as successful prose.
Unexpected exceptions remain governed by the existing tool/orchestrator failure
boundary; no broad catch may fabricate a successful answer. A renderer does not
change the structured status or failure outcome.

#### Stateless evidence-copy ownership

FI-7a owns the immutable optional `FinalResponse.evidence` contract and generic
HTTP serialization. FI-7b2 owns deterministic structured evidence assembly in
each FI tool result. FI-7b3 owns the narrow bridge in the successful
orchestrator-answered FI path: copy the selected FI tool's structured
`evidence` unchanged into the top-level harness response consumed by
`to_ask_response()`, and let the existing adapter/HTTP serialization carry it
to `FinalResponse.evidence`/`AskResponse.evidence`.

All four individual tools and the composite populate evidence through this same
copy path. FI-7b3 performs no reranking, rededuplication, new evidence creation,
or LLM-authored evidence. The FI-7b2 order and first-eight bound are preserved.
`None` remains omitted at the HTTP boundary. An FI tool's governed empty
evidence list remains empty rather than being rewritten as fabricated evidence.
Pre-existing non-FI intents are not enriched; that remains FI-7c.

#### Session integration and storage semantics

The smallest session change must reuse the existing `ConversationSession` and
`FinalResponse` architecture rather than create a second intelligence runtime.
The session path must route an enabled FI request through the same successful FI
tool execution, renderer, and unchanged evidence-copy rules as the stateless
path, then return that `FinalResponse` through the existing `session_ask()`
projection. The existing top-level `_to_dict(r.evidence)` and nested
`_sub_response_dict()` serializers remain the wire-format owners.

Evidence ownership follows the existing response hierarchy. A single-intent FI
turn owns evidence on its top-level `FinalResponse`. In a multi-intent turn, the
FI sub-response owns its evidence and the multi-intent parent keeps
`evidence=None`; FI-7b3 must not aggregate sub-response evidence onto that
parent. `ConversationSession` wraps and transports the resulting responses, and
`fpl_server.py` performs their HTTP projection.

Session state stores its existing conversation/reference state and retains the
existing `FinalResponse` objects where the architecture already does so; FI-7b3
adds no evidence store, manifest, pointer, persistence family, or reduced
parallel response model. Evidence is transported with the response, not
persisted as intelligence data. Identical controlled inputs and evidence tuples
must replay to byte-identical evidence arrays. `evidence=None` remains absent;
nested sub-responses preserve each response's own evidence independently.

#### F2 retirement tests

F2 closes only through two distinct real HTTP scenarios. Both enable
`FOOTBALL_INTELLIGENCE_ENABLED`, use controlled deterministic mocks or validated
local test builds, create a real session, and invoke `POST /session/{id}/ask`.

**Scenario A — single-intent top-level evidence.** Submit the controlled query
`player intelligence for Saka`, with the existing FI tool-selection seam pinned
to `get_player_intelligence`. The response is a single-intent response:
`SessionAskResponse.evidence` is present and exactly matches the bounded FI-7b2
composite evidence, while `sub_responses` is absent or empty. This scenario must
kill mutations that stop `session_ask()` assigning top-level evidence, remove
`SessionAskResponse.evidence`, or drop the top-level FI evidence copy.

**Scenario B — multi-intent nested evidence.** Use the exact fixture
`player intelligence for Saka and what gameweek is it?`. It reuses the existing
deterministic multi-intent convention: split on the first `" and "`, execute two
ordered sub-questions independently, and retain ordered sub-responses. Because
the FI phrase intentionally has no deterministic-router rule, the test controls
the existing multi-intent detection/tool-selection seams rather than adding a
new intent or classifier rule: sub-response index 0 is routed through
`get_player_intelligence`, and index 1 uses the already-supported deterministic
`get_current_gameweek` intent for `what gameweek is it?`.

The Scenario B parent has `evidence` absent/`None` and has `sub_responses`.
Sub-response index 0 contains the unchanged bounded FI evidence; index 1 remains
the existing non-FI response with unchanged evidence behavior. This scenario
must kill mutations where `_sub_response_dict()` drops nested evidence, the FI
sub-response evidence copy is removed, or nested evidence is copied only to the
top level. It must also causally reject any implementation that aggregates FI
sub-response evidence onto the multi-intent parent.

Across both scenarios, enum values serialize as strings, `source_features`
serialize as JSON arrays, evidence order and FI-7b2's first-eight bound are
preserved, `evidence=None` remains omitted where applicable, and repeated
controlled requests produce identical wire values.

**F2 CLOSED** requires all of the following:

1. Scenario A passes through the real session HTTP endpoint, its top-level FI
   evidence assertion passes, and the `session_ask` top-level evidence mutation
   is killed.
2. Scenario B passes through the real session HTTP endpoint, its nested FI
   evidence assertion passes, the `_sub_response_dict` nested-evidence mutation
   is killed, and the multi-intent parent's evidence remains absent.
3. The serialization, ordering, bound, omission, and replay assertions above
   pass in their applicable scenarios.

Serializer-only tests and direct helper-only tests are insufficient. Both real
HTTP session scenarios are required; no single response is required or allowed
to carry evidence at both parent and nested levels.

#### Determinism and feature flag

- Same structured FI result → identical text; same evidence tuple → identical
  wire output.
- Field and composite-section order is explicit and independent of uncontrolled
  dictionary insertion order.
- Rendering and propagation use no wall clock, locale-dependent formatting,
  randomness, network, provider, or LLM.
- The static registry remains 33 with the flag OFF and ON; the offered set
  remains 29 OFF and 33 ON. No second FI-7b3 flag is added.
- With the flag OFF, FI renderers are unreachable through FI dispatch, no FI
  runtime/module import occurs, existing responses remain byte-identical, and
  FI-7b3 causes no evidence field to appear.
- With the flag ON, successful FI tool results use the deterministic renderer,
  populate `FinalResponse.evidence` from the structured result, and serialize
  that evidence through stateless and session HTTP paths.

#### Error and degradation behavior

| Input/result condition | Required behavior |
|---|---|
| Native module `missing_context` | Render deterministic unavailable/context text, preserve native structured status and reasons, and never fabricate values/evidence. |
| Composite `partial` | Render all three fixed sections, available native content, and deterministic unavailable markers for missing sections. |
| All modules `missing_context` | Render all three unavailable sections with native reasons; composite status remains `missing_context`. |
| Typed identity/build/fixture/contract failure | Preserve request-level failure; do not render as successful FI output or emit partial evidence. |
| Unexpected exception | Use the existing tool/orchestrator failure boundary; no retry or fabricated prose. |

#### Explicit FI-7b3 non-goals

FI-7b3 does not implement FI-7c existing-intent evidence enrichment; FI-7d
`EvidenceChip`, `EvidenceList`, `ConfidenceBadge`, cards, resources, or other UI;
FI-7e demo recording; new tool schemas/names; new runtime adapters or module
calls; new build loading, fixture selection, or identity behavior; evidence
ranking; recommendations or `player_recommendation`; M4/M5 tools; formula or
confidence changes; HTTP field changes; TypeScript changes; session persistence
expansion; or provider/network/LLM behavior. FI-7a already supplies the required
HTTP and TypeScript evidence fields, so no contract expansion is required.

#### Bounded implementation homes

The expected smallest implementation union, to be reconfirmed against main at
implementation time, is:

- a bounded FI tool-output renderer module under
  `packages/fpl-grounded-assistant/fpl_grounded_assistant/`;
- `harness.py` and/or `harness_adapter.py` for successful FI render/evidence
  response assembly;
- the existing session orchestration/response path (`conversation_state.py`
  and/or `fpl_server.py`) only where needed to reuse the same FI response;
- bounded `final_response.py` `respond()`/assembly work where the actual session
  path must create the evidence-bearing `FinalResponse`;
- focused FI-7b3 renderer/evidence tests and real session HTTP tests; and
- governance runner counts only when an existing asserted corpus requires new
  tests to be enumerated.

Explicitly excluded are FI-7b2 `football_intelligence_runtime.py` module logic,
all FI-6 module implementations, `tool_schema_registry.py`, `orch_config.py`
flag semantics, `lib/types.ts`, UI components, the identity registry, build
engine, and `FEATURE_CONTRACT.md`. Implementation must use the smallest feasible
subset of the candidate homes and stop if it appears to require a governed
exclusion.

#### FI-7b3 cumulative acceptance matrix

| Area | Required acceptance |
|---|---|
| Rendering | Each individual tool renders deterministically; composite order is M1 → M2 → M3; `ok`/`partial`/`missing_context` are exact; typed failures never render as success; no advice or recommendations appear. |
| Evidence | Stateless `FinalResponse.evidence` is copied from individual/composite FI structured results; no evidence is generated or reordered; exact FI-7b2 deduplication and ≤8 bound remain unchanged; `None` omission remains intact. |
| Session and F2 | Scenario A: real single-intent `/session/{id}/ask` has top-level FI evidence, no nested response, and kills the top-level assignment/copy mutants. Scenario B: real multi-intent `/session/{id}/ask` keeps parent evidence absent, places FI evidence only in sub-response index 0, leaves the index-1 `get_current_gameweek` response unchanged, and kills the nested serializer/copy mutants. Both pin string enums, array `source_features`, stable order/bound, and `None` omission. FI-7b3 never aggregates sub-response evidence into the multi-intent parent. |
| Flag | OFF responses and import isolation remain byte-identical; ON renderer/evidence paths work; static/offered counts remain 33/33 and 29/33 respectively. |
| Determinism | Repeated and fresh-process rendering/serialization over identical controlled input is identical; no uncontrolled mapping order, locale, clock, randomness, network, or LLM participates. |
| Regression | FI-7b1, FI-7b2, FI runtime, FI-1, HTTP contract tests, full governed validation corpus, and contract gate remain green; Jest/build remain green with no UI change. |

The dormant M3 preflight findings B1.12, B2.1, and B2.1b, plus the three
pre-existing router player-extraction failures and one owned-store fallback
failure, remain recorded as pre-existing and outside FI-7b3. FI-7b3 does not
authorize their correction.

### FI-7c — deterministic evidence enrichment of existing intents

**Status:** specification draft; documentation only. FI-7b3 is merged and
closed. FI-7c implementation is not authorized by this subsection. FI-7d and
FI-7e remain separate and unstarted.

#### Purpose, ownership, and invariants

FI-7c enriches exactly three existing successful deterministic intents with
already-governed Football Intelligence evidence. It does not create an intent,
tool, schema, recommendation, score, renderer, module, or evidence item.

FI-7c supersedes the earlier §10.4/Q7 M1/M3 phrasing. Existing-intent
enrichment reuses the already-governed M1 → M2 → M3 composite and must not
filter or reconstruct its bounded evidence.

The existing intent implementation remains the sole owner of routing, entity
arguments, recommendation calculation, outcome, structured metadata, and
rendered text. The FI-7b2 runtime remains the sole owner of identity crosswalk
validation, fixture selection, v2 build loading, explicit `calculated_at`,
M1 → M2 → M3 evaluation, and bounded evidence construction. FI-7c owns only a
bounded post-success enrichment adapter and the copy into the existing
`FinalResponse.evidence` field. FI-7a/FI-7b3 serializers remain the only wire
format owners.

All FI-7b invariants continue unchanged:

- master flag `FOOTBALL_INTELLIGENCE_ENABLED`, default OFF; no second flag;
- static registry 33 in both states; offered tools 29 OFF and 33 ON; no global
  registry mutation;
- strict-future fixture selection from the latest known schedule ordered by
  `scheduled_kickoff_utc`, then `fixture_id`;
- one canonical identity policy, one validated v2 build, and no v1 or
  unversioned fallback;
- M1 → M2 → M3 order, each module at most once for each enriched player;
- exact serialized duplicate removal, first occurrence retained, then the
  first eight evidence items;
- no LLM-, router-, renderer-, or serializer-generated evidence; and
- native `missing_context`, statuses, reasons, confidence, model versions, and
  evidence remain unmodified.

#### Eligible intent matrix

Eligibility is closed, not pattern-based. Only an `OUTCOME_OK` result from one
of these exact intents may enter enrichment:

| Intent / existing tool | Why eligible and entity context | FI entry point and maximum execution | Text and evidence ownership | Fallback |
|---|---|---|---|---|
| `captain_score` / `get_captain_score` | The successful raw output identifies one uniquely resolved player through its existing player result. | Invoke the existing `get_player_intelligence` runtime entry point once for that player. It evaluates M1, M2, and M3 once each. | Existing captain text, score, tier, reasons, and metadata are unchanged. The successful `FinalResponse` receives the unchanged bounded composite evidence at top level. | Any enrichment identity, fixture, build, module, or renderer-independent adapter failure leaves the original captain response successful with `evidence=None`. |
| `compare_players` / `compare_players` | The successful raw output contains the two resolved comparison players in existing argument order. | Invoke `get_player_intelligence` once per player, first player then second. Each player's M1/M2/M3 executes at most once. Merge the two already-bounded bundles in player order, exact-deduplicate by canonical serialized value, then retain the first eight. | Existing winner, deltas, recommendation-neutral comparison text, and metadata are unchanged. Only top-level evidence is added. | A failed player enrichment contributes no evidence; a successful other player may still contribute its honest native evidence. If neither contributes, evidence is `None`. |
| `transfer_advice` / `get_transfer_advice` | The successful raw output contains resolved `player_out` and `player_in` identities and preserves that semantic order. | Invoke `get_player_intelligence` once for `player_out`, then once for `player_in`. Each player's M1/M2/M3 executes at most once. Merge in out-then-in order, exact-deduplicate, then retain the first eight. | Existing recommendation, score delta, tier, reasons, text, squad overrides, and transfer metadata are unchanged. Only top-level evidence is added. | A failed side contributes no evidence; the other side may still contribute. If neither contributes, evidence is `None`; the original transfer result stays successful. |

The composite entry point is required because it is the existing governed
single-execution pipeline that preserves M1 → M2 → M3 ordering and shared
identity/build/fixture semantics. FI-7c must not call the three atomic tools in
sequence or independently reconstruct their inputs. For two-player intents,
the final cross-player bound repeats FI-7b2's exact canonical serialized-value
deduplication and first-eight operation; it does not score, rank, reinterpret,
or alternate between players.

When an eligible raw intent result exposes its already-resolved FPL element or
player ID, the adapter passes that ID to the existing FI identity path. It
falls back to the existing deterministic identity resolver only when no such ID
is available. This introduces no new identity or matching policy; an ambiguous
fallback resolution skips that player.

#### Explicit exclusions

All other intent constants and categories remain unchanged, including:

- `rank_candidates`, `current_gameweek`, `player_summary`, `player_resolve`,
  `chip_advice`, `player_fixture_run`, `differential_picks`, `player_form`,
  `player_season_points`, `injury_list`, `price_changes`,
  `team_fixture_calendar`, `team_schedule`, `position_fixture_run`,
  `transfer_suggestion`, `fixture_outlook`, `zonal_opportunity`,
  `unsupported`, and the `multi_intent` parent;
- the four native FI tool turns, whose evidence is already owned by FI-7b3;
- non-OK eligible-intent outcomes (`not_found`, `ambiguous`,
  `missing_arguments`, `needs_clarification`, `error`, `quota_exceeded`, or
  unsupported); and
- any future intent unless a later reviewed contract adds it by exact name.

Player/team/fixture context in an excluded intent is not implicit permission to
enrich it. FI-7c does not widen eligibility based on text, metadata shape,
router guesses, or LLM tool selection.

#### Enrichment and rendering semantics

Enrichment is **evidence-only** for all three eligible intents. Existing
`final_text`, renderer selection, structured metadata, recommendation language,
scores, tiers, deltas, reasons, `supported`, `outcome`, review fields, routing
audit fields, suggestions, and squad overrides must remain contract-equivalent
to the pre-FI-7c result.

No FI section is appended and no FI renderer replaces existing intent text.
`renderer.py` and `football_intelligence_renderer.py` remain unchanged. The
bounded adapter runs only after the existing deterministic result is known to
be OK and consumes the canonical resolved player values already present in
that successful raw output; it does not reroute or re-resolve the user's prose.

#### Feature-flag and import behavior

With `FOOTBALL_INTELLIGENCE_ENABLED=OFF`:

- the enrichment adapter returns without importing the FI runtime or modules;
- all three eligible paths are contract-equivalent to current `main`, including
  `evidence=None` and omission at HTTP boundaries;
- FI modules are unreachable and execute zero times; and
- schema registry and offered-tool counts remain 33 static / 29 offered.

With the flag ON, only the exact eligible OK results above are enriched. An
unrelated or non-OK turn must not execute FI. Existing FI-native requests keep
their FI-7b3 behavior and must not be enriched a second time. Static/offered
counts remain 33/33.

#### Evidence construction, copy, and serialization

FI-6 modules construct immutable `EvidenceItem`s. The FI-7b2 runtime serializes
and bounds each composite. FI-7c may only concatenate eligible per-player
bundles in the governed player order, exact-deduplicate canonical serialized
items, take the first eight, restore the existing immutable evidence tuple, and
assign it to the same successful response. It may not alter any field or
synthesize a summary.

The first player may consume all eight evidence slots. The cap is global across
the ordered request, not reserved or balanced per player.

For a single-intent stateless or session response, the response owns evidence
at top level. In a multi-intent turn, each eligible child independently owns
its evidence; the `multi_intent` parent remains `evidence=None` and never
aggregates child evidence. Non-FI children retain `evidence=None`. Existing
recursive adapter and HTTP projection code owns Enum-to-string, tuple-to-array,
and omit-when-`None` behavior. A governed empty bundle remains empty; total
enrichment failure uses `None` so absence is omitted.

#### Failure and honest degradation matrix

| Condition | Required result |
|---|---|
| Eligible intent is non-OK | Skip enrichment; return the existing response unchanged. |
| Existing intent player resolution is absent or contradictory | Skip that player; do not attempt a new matching policy. |
| FI identity is unresolved or ambiguous | Skip that player's enrichment; preserve the normal intent success and existing text. |
| No strict-future fixture | Preserve the runtime's honest unavailable/missing-context result and any native evidence it actually emits; if the runtime produces no evidence, contribute none. |
| Native M1/M2/M3 `missing_context` or composite `partial` | Preserve native statuses/reasons and copy only native evidence; do not fabricate replacement evidence. |
| Typed build/fixture/contract validation failure | Treat enrichment as unavailable for that player; never convert the original successful intent to failure and never hide corruption behind fabricated `missing_context`. |
| Unexpected FI runtime or adapter failure | Contain it at the enrichment boundary, emit no evidence for that player, and preserve the original response. No retry or alternate provider path. |
| FI renderer failure | Impossible by design because FI-7c does not render FI text; no FI renderer is invoked. |
| Multi-intent child failure | Affects only that child under existing response semantics; parent evidence remains absent. |

Degradation containment must be observable in deterministic test seams without
adding user-visible advice, fallback prose, or a persisted intelligence log.

#### Determinism, execution count, and the existing double-`ask_v2` finding

For identical bootstrap/build data, explicit controlled `calculated_at`, raw
eligible tool output, and flag state, enrichment returns byte-identical
evidence arrays. No wall clock, locale, randomness, network, provider refresh,
LLM output, unordered set iteration, mutable global cache, or session history
may affect evidence selection.

Maximum FI composite executions are one for `captain_score` and two for
`compare_players`/`transfer_advice`; each entity executes at most once and each
M1/M2/M3 module at most once within that composite. There are no retries. The
implementation must expose a request-scoped cache keyed by canonical player
identity only if the same eligible entity is repeated within one intent; this
prevents duplicate execution without persisting results across requests.

The accepted informational finding that some non-FI requests can invoke
`ask_v2` twice when the FI flag is ON predates FI-7c. Correcting that routing
architecture is explicitly outside FI-7c because it changes shared request
routing beyond evidence enrichment. FI-7c must not call `ask_v2`, the
orchestrator, or a tool-selection LLM for enrichment, and causal spies must
prove the count is not increased relative to the same request on pre-FI-7c
main. The existing finding remains tracked; FI-7c neither fixes nor worsens it.

#### Stateless, session, multi-intent, and replay behavior

- Stateless HTTP `POST /ask` follows `fpl_server.py` → `harness.ask_v2()` →
  `harness_adapter.to_ask_response()`. A narrow copy-only seam in `harness.py`
  attaches the adapter's finalized evidence bundle to the successful existing-
  intent harness result; the existing adapter then exposes it at top level and
  omits it when unavailable. `harness.py` does not extract players, execute FI,
  cache results, order players, deduplicate, truncate, degrade, or render.
- A single-intent `ConversationSession.respond()` and HTTP session response
  carry top-level evidence through the existing `final_response.py` successful
  assembly seam. Session assembly does not reuse the stateless copy seam.
- Multi-intent execution enriches eligible children independently in existing
  child order. Parent evidence remains absent; excluded children are unchanged.
- Replayed session requests over identical controlled inputs produce identical
  response-local evidence. FI-7c adds no intelligence persistence, manifest,
  pointer, session evidence store, or cross-request cache.

The enrichment adapter executes before either response assembly projection.
Stateless and session seams copy its finalized result only. Replay,
`harness_adapter.py`, `fpl_server.py`, and all serializers transport existing
values and must never trigger enrichment or FI execution.

These rules extend FI-7b3 Scenario A/B ownership to eligible existing-intent
children without changing the native FI scenarios or response schema.

#### Bounded implementation homes

The expected smallest implementation union, to be reverified against merged
`main`, is:

- a new bounded evidence-enrichment adapter under
  `packages/fpl-grounded-assistant/fpl_grounded_assistant/`;
- `final_response.py` only at the existing successful deterministic
  `FinalResponse` assembly seam, including the existing recursive multi-intent
  child path; and
- `harness.py` only at the successful stateless existing-intent response seam,
  where it copies the finalized adapter evidence into the existing harness
  result for `harness_adapter.to_ask_response()`, only for the three eligible
  intents, only while the master flag is ON, and only while the original intent
  result remains successful. This seam performs no player extraction, FI
  execution, caching, ordering, filtering, deduplication, truncation,
  degradation decision, or rendering; and
- focused FI-7c tests plus runner-count updates only where repository gates
  explicitly enumerate test totals.

No change is authorized to `renderer.py`, `football_intelligence_renderer.py`,
`football_intelligence_runtime.py`, FI-6 modules, `harness_adapter.py`,
`fpl_server.py`, `conversation_state.py`, schemas,
registries, flags, TypeScript, UI, persistence, lockfiles, or generated files.
If implementation appears to require one of those homes, stop for a contract
revision rather than expanding scope.

#### Causal test and acceptance matrix

| Area | Required acceptance |
|---|---|
| Eligible set | Each of the three exact OK intents enriches when ON; every enumerated excluded category and each non-OK outcome remains unchanged. Mutating any eligibility constant causes a focused failure. |
| Flag OFF | Existing response dictionaries/text are contract-equivalent, evidence is absent, FI runtime/modules are not imported or invoked, and the full flags-off regression corpus stays at its governed baseline. |
| Identity input | A resolved FPL element/player ID in existing raw output is passed through preferentially; name resolution occurs only when that ID is absent; ambiguity skips the player. Mutations that discard an available ID or guess an ambiguous fallback must fail. |
| Evidence | Single-player and ordered two-player golden cases pin the governed composite's unchanged M1→M2→M3 evidence, cross-player order, exact duplicate removal, first-occurrence retention, global first-eight truncation, immutable result shape, and no synthesized fields. Tests pin that M2 is not filtered, no M1/M3 subset is reconstructed or re-bounded, and the first player may consume all eight slots. Mutations that filter M2, reorder, retain duplicates, balance slots, or take nine must fail. |
| Recommendations | Golden captain, comparison, and transfer text, scores, tiers, deltas, winners/recommendations, reasons, metadata, and squad overrides are identical with the flag OFF and ON; only evidence may differ. |
| Execution | Spies prove one composite execution for captain, two maximum for distinct compare/transfer players, one for a repeated canonical player, M1/M2/M3 exactly once per executed composite, no M4/M5, no atomic-tool fan-out, no retry, and no enrichment-originated `ask_v2`/orchestrator call. Stateless and session assembly over their respective request each copy one finalized bundle and never duplicate FI execution; adapters, serializers, and replay execute none. |
| Failure/degradation | Identity failure, no fixture, native missing context, partial modules, typed corruption, and unexpected failure each preserve the normal successful intent and contribute only honest native evidence or none. |
| HTTP/session ownership | A real stateless HTTP `POST /ask` parameterized over `captain_score`, `compare_players`, and `transfer_advice` pins top-level evidence while intent, outcome, supported state, text, and recommendation values remain unchanged. Removing the `harness.py` copy must fail this test. A single-intent session test pins top-level evidence and fails when the `final_response.py` copy is removed. Eligible multi-intent children own nested evidence; parent evidence remains absent; non-FI children and omission behavior remain unchanged. |
| Determinism | Input-row reversal where supported, repeated evaluation, reversed test order, and fresh-process replay produce identical evidence and execution order; no clock/network/LLM access occurs. |
| Registry/contracts | Static schemas remain 33; offered tools remain 29 OFF / 33 ON; no schema, intent, tool name, response field, serializer, renderer, or TypeScript mirror changes. |
| Regression | Focused FI-7c, FI-7b1/b2/b3, relevant captain/compare/transfer, multi-intent/session/HTTP, full grounded-assistant, football-intelligence, FI-1, Orch-4a/4i, contract gate, Jest, and production build retain governed results. Accepted legacy failures remain exactly unchanged and are not opportunistically corrected. |

#### Definition of done and explicit non-goals

FI-7c is complete only when the three eligible OK intents satisfy the matrix in
both flag states, evidence is deterministic and response-local, recommendation
behavior is unchanged, all required mutation targets are killed, and the
documentation-review → merge → implementation-review workflow is complete.

FI-7c does not add FI text, UI, evidence formatting, cards/resources, tools,
schemas, intents, registry entries, recommendation logic, confidence
recalculation, FI algorithms, M4/M5, persistence, provider/network access, LLM
evidence, FI-7d, FI-7e, or the separately tracked double-`ask_v2` correction.
The dormant M3 findings, three accepted router extraction failures, owned-store
fallback failure, and atomic-tool-ranking work remain untouched.

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
7. **First intents:** captain_score, compare_players, transfer_advice (§10.4 as superseded and locked by FI-7c's governed M1 → M2 → M3 composite rule).
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
| FI-7 | b — FI tools/runtime/rendering/evidence propagation | complete — merged PRs #51/#53/#55 | FI-7b3 focused/session mutation coverage; contract drift gate green on approved PR #55 head | Static registry 33; offered set 29 OFF/33 ON; deterministic M1→M2→M3 runtime, rendering, and stateless/session evidence transport; F2 closed. |
| FI-7 | c — existing-intent evidence enrichment | specification draft; implementation not started | documentation review pending | Exact eligible set: `captain_score`, `compare_players`, `transfer_advice`; evidence-only, master-flag gated, no recommendation or renderer change. |
| FI-7 | d–e UI and demo | not started | — | Remain blocked behind the separately reviewed FI-7c workflow. |
| FI-8 | trial gate artifacts | not started | — | |
| FI-9 | live trial | blocked until ~2026-08-10 | — | |
| FI-10 | calibration | blocked on FI-9 | — | |

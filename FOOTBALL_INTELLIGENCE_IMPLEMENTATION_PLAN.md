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
6. **`@resource` surface:** `@minutes <player>` and `@role <player>` entries in `resource_registry` are deterministic and quota-free, and remain outside FI-7d/FI-7e. The separately reviewed **FI-7f — resource-surface parity** contract below now governs their future implementation.

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
- **Slices:** (a) `FinalResponse.evidence` + serialization + `http_contract_fixtures.json` additions + CLI debug; (b) tools `get_player_intelligence`, `get_expected_minutes`, `get_tactical_role`, `get_fixture_context` + schemas + renderers (registry 29→33; adjust documented orch3a token baselines); (c) evidence enrichment of `captain_score`/`compare_players`/`transfer_advice` OK turns behind master flag; (d) UI `EvidenceChip/EvidenceList/ConfidenceBadge` + card wiring only; (e) end-to-end mock demo script + recording only; (f) separately reviewed deterministic, quota-free `@minutes`/`@role` `resource_registry` parity.
- **Existing files touched:** `final_response.py`, `harness_adapter.py`, `tool_schema_registry.py`, renderer module, `resource_registry.py`, `fpl_server.py` (serialization only), `IntentRenderer.tsx`, three cards, `lib/types.ts`.
- **Compatibility:** all additive; flags-off sweep of the full validation corpus is the slice-(c) gate.
- **Tests:** contract additivity; renderer snapshots with/without evidence; tool schema validation; Jest card tests.
- **DoD:** demo recorded; contract gate + validation corpus + `npm run build`/tests green. **Trial-dep:** none. **Pre-trial:** yes — completing FI-7 IS the trial-readiness bar.
- **Status (2026-08-08):** slices **(a), (b), (c), (d), (e), and (f) complete — FI-7 is closed.** The **Pre-trial** bar above ("completing FI-7 IS the trial-readiness bar") is therefore **satisfied**; FI-8 is unblocked. FI-7a merged in PR #45. FI-7b1/b2/b3 merged in PRs #51/#53/#55; b3 closed F2 through deterministic FI rendering plus real single- and multi-intent session evidence propagation. FI-7c merged in PR #57 at `49435bd004d4314567bb934e8f353db92d43130d`. FI-7d merged in PR #59 and was independently post-merge verified on `main@239bc8137358eeeb5aad137f53a9b0b66a22d0f2`. FI-7e documentation and artifact production are complete; PR #61 merged and merge integrity was independently verified at `main@5e57a40b76bb9478abc5358ca6de700c4c8f6493`. **FI-7f resource-surface parity is complete**, merged in PR #65 at `main@e12c8b9179a90624e6a3cf089022522c9f592283` (reviewed head `0ea9f6cb5b65059f1110acacec60b4f34e7bc19c`, a direct parent of the merge commit). It was **independently reviewed and approved** against this contract by a reviewer with no involvement in its implementation: **no blockers and no required changes**, with two informational findings recorded in the FI-7f closeout note below. Both required checks (`Contract and fixture drift check`, `Package test suites`) pass on the resulting `main`. **Not a slice:** PR #48 (`fix(ui): mirror player season points intent`, merged to main `03bac5697d087e1dba636ef8c4f534edc63d978a`) was a **post-merge cleanup associated with PR #47** — a one-file, two-line TypeScript intent-mirror parity fix, not an FI-7 roadmap slice.

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
- **FI-7d:** `EvidenceChip` / `EvidenceList` / `ConfidenceBadge` UI and card wiring only. `@minutes` / `@role` resources are not part of FI-7d; they are deferred to FI-7f resource-surface parity. FI-7b touches **no** `lib/types.ts` and no UI.
- **FI-7e:** the recorded mock end-to-end demo only.
- **FI-7f:** deterministic, quota-free `@minutes` / `@role` `resource_registry` parity. **Complete** — merged in PR #65 at `main@e12c8b9179a90624e6a3cf089022522c9f592283`; see the FI-7f closeout note below.
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
`EvidenceChip`, `EvidenceList`, `ConfidenceBadge`, cards, or other UI; FI-7e
demo recording; FI-7f `@minutes` / `@role` resources; new tool schemas/names; new runtime adapters or module
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

**Status:** complete — merged in PR #57 at merge commit
`49435bd004d4314567bb934e8f353db92d43130d`. FI-7d is complete and merged in
PR #59. FI-7e is complete and merged in PR #61 at
`main@5e57a40b76bb9478abc5358ca6de700c4c8f6493`.

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

### FI-7d — governed evidence presentation in the existing UI

**Status:** complete; merged in PR #59 and independently verified on
`main@239bc8137358eeeb5aad137f53a9b0b66a22d0f2`. FI-7e is complete and merged
in PR #61. FI-7f resource-surface parity is complete and merged in PR #65 at
`main@e12c8b9179a90624e6a3cf089022522c9f592283`, closing FI-7.

#### Purpose, repository facts, and ownership

FI-7d is a presentation-only consumer of the optional `evidence` already
carried by `AskResponse` and recursively by each `sub_responses` entry. The
current frontend is a Next.js 15 / React 19 / TypeScript application under
`packages/fpl-ui`. Both stateless `ask()` and session `sessionAsk()` return the
same `AskResponse` shape. `ChatShell` stores that response on the assistant
message; `MessageList` renders either an intent card through `IntentRenderer`
or a text bubble; `MultiIntentView` renders each child in its own bounded
sub-card. Replayed controlled responses traverse those same component seams.

The Python `football-data-contract` remains authoritative. Its existing
TypeScript mirror in `lib/evidence.ts` defines a closed `EvidenceItem` with
`code`, `label`, `subject_type`, `subject_id`, nullable `fixture_id`, `impact`,
`direction`, `confidence`, `basis`, `summary`, `source_features`,
`model_version`, and `calculated_at`. Confidence exists per evidence item only,
in the inclusive domain `[0.0, 1.0]`; there is no response-level or module-level
confidence on the UI response contract. An evidence item has no module,
status, reason, or `missing_context` field.

Backend ownership is final: M1 → M2 → M3 order, exact serialized duplicate
removal, first-occurrence retention, and the maximum-eight bound happen before
the response reaches React. FI-7d must not construct, infer, fetch, translate
semantics, reorder, deduplicate, filter valid items, or truncate evidence. It
must not reuse the FI-7b3 text renderer or append duplicate FI prose. Existing
recommendation text and cards remain their current owners.

#### Exact UI surfaces and response ownership

Evidence presentation is ownership-based, not intent-detection-based. A
successful non-parent response renders one `EvidenceList` whenever it owns a
non-empty array containing at least one structurally valid item:

| Surface | Required placement and behavior |
|---|---|
| Stateless text response | Inside the assistant bubble, immediately after `final_text`. This includes FI-native text-only results and any future response that legitimately owns evidence. |
| Stateless structured response | In the same assistant message block, immediately after the bespoke/generic intent card and before share/origin/follow-up controls. Captain, comparison, and transfer cards are not modified internally. |
| Single-intent session response | The identical top-level placement because `sessionAsk()` is structurally the same `AskResponse` renderer input. |
| Multi-intent response | The parent never renders evidence, even if an invalid upstream payload supplies it. Each eligible child renders its own list inside its existing `MultiIntentView` sub-card, after the child's text and structured child view. |
| Replayed response | The same response-local placement and byte-equivalent field mapping; replay performs no FI call and creates no UI state derived from time. |
| Mobile and desktop | The same content and order. Layout adapts only through existing responsive utilities; neither viewport changes evidence selection. |

Non-eligible children remain visually unchanged. Child order remains the wire
order. Lists are never merged across children, and identical serialized items
in different children remain independently visible because response ownership
differs. Share-image/export rendering is unchanged in FI-7d and is not a new
evidence surface.

#### Component contracts and bounded implementation homes

Implementation is expected to add only these bounded presentation components
under `packages/fpl-ui/components/intelligence/`, subject to re-verification
against authoritative main at implementation time:

- `EvidenceList.tsx` accepts `readonly EvidenceItem[] | null | undefined`,
  validates items independently at the UI trust boundary, and renders every
  valid received item in original order as semantic `<ul>` / `<li>` markup.
  It owns no sorting, semantic eligibility, deduplication, cap, collapse, or
  network activity. `null`, `undefined`, an empty array, or an array with no
  valid items renders `null` rather than an empty heading or placeholder.
- `EvidenceChip.tsx` represents exactly one validated item. Despite its name,
  it is a presentational evidence row, not a button, link, checkbox, tooltip
  trigger, or recommendation. It shows the supplied human label and summary,
  then deterministic basis, direction, confidence, and source-feature text.
  It has no `tabIndex`, click handler, hover-only content, or button semantics.
- `ConfidenceBadge.tsx` accepts only one evidence item's numeric confidence.
  It displays `Confianza N%`, where `N = Math.round(confidence * 100)`, including
  `0%` and `100%`. It defines no low/medium/high categories or thresholds,
  performs no recalculation, and uses neutral styling plus visible text so
  meaning never depends on color.
- `EvidenceBoundary.tsx` is a narrow React error boundary around only the
  evidence subtree. Its fallback is `null`: unexpected evidence-rendering
  failure removes the evidence section while the main response/card remains.
  It performs no retry, network request, analytics expansion, or fallback copy.

The response-placement changes are bounded to `MessageList.tsx` for top-level
text/card messages and `MultiIntentView.tsx` for child-owned evidence. A small
pure `lib/evidence-presentation.ts` helper may own structural validation,
deterministic labels/formatting, and stable-key construction. Focused component
and ownership tests may add one new Jest test file and evidence fixtures; an
existing fixture/test file may be modified only where integration coverage
requires it. No individual recommendation card needs FI-specific logic.

#### Deterministic field-to-presentation mapping

The mapping is local, closed, and contains no LLM, locale API, network lookup,
or wall-clock formatting:

| Evidence field | FI-7d treatment |
|---|---|
| `label` | Visible primary text verbatim. It is the contract's human label; the UI does not replace it from `code`. |
| `summary` | Visible secondary factual text verbatim and allowed to wrap fully. It is never rewritten as advice. |
| `confidence` | Visible through the per-item `ConfidenceBadge` numeric percentage. Zero is rendered, not treated as absent. |
| `basis` | Visible deterministic Spanish map: `observed` → `Observado`; `inferred_proxy` → `Proxy inferido`. Proxy status must remain explicit. |
| `direction` | Visible deterministic Spanish map: `positive` → `Positivo`; `negative` → `Negativo`; `neutral` → `Neutral`. Styling may reinforce but never replace this text. |
| `source_features` | Visible traceability line `Fuentes: <values in received order>`. These are provider-neutral evidence feature identifiers and are shown verbatim unless this same contract later defines a closed presentation map. An empty tuple renders `Fuentes: no indicadas`; values are not localized, sorted, or inferred, and no secret, provider credential, or internal subject ID may be displayed. |
| `code` | Not user-facing prose. Used only as one stable-key input and permitted in test-only/data attributes; never displayed as the label. |
| `subject_type` | Internal routing metadata; not visibly rendered. It may participate in stable keys and runtime validation. |
| `subject_id`, `fixture_id` | Canonical internal identifiers. Prohibited from visible, tooltip, accessible-label, title, or copied UI text; may participate only in stable keys. |
| `impact` | Governed machine-readable scale without an approved user interpretation. Validated but hidden; direction text supplies the approved qualitative presentation. |
| `model_version`, `calculated_at` | Internal provenance. Validated and usable for stable keys, but hidden; FI-7d adds no relative-time or model copy. |

Stable React keys must not delete duplicates. Construct a deterministic
canonical serialization of the full received item plus that serialization's
zero-based occurrence ordinal in the current list. This keeps exact duplicates
separate, avoids array-index-only identity, exposes no identifier to users, and
remains stable for identical input.

#### Ordering, completeness, and interaction

The list is expanded by default and displays all valid received items. Because
the backend supplies at most eight, FI-7d adds no fixed-count hiding, “show
more”, disclosure, carousel, pagination, tooltip, or collapse state. There is
therefore no hydration-sensitive client state and no silent evidence loss.
Backend order is semantic and preserved exactly on every viewport and replay.

Chips are noninteractive. They must not receive keyboard focus or interactive
ARIA roles. Full label, summary, and traceability text remain in the document;
long content wraps instead of becoming hover-only or being visually truncated.

#### Missing context, partial evidence, and malformed input

The authoritative evidence contract says missing inputs omit evidence rather
than fabricate it. Since `EvidenceItem` contains no status/reason field or
`missing_context` code, FI-7d must not infer missing context from an intent,
module, absent code, confidence, summary, empty feature list, or other payload
field. The exact policies are:

| Input condition | Presentation |
|---|---|
| No `evidence` property, `null`, or `[]` | Render no evidence section and no invented “insufficient data” message. |
| Partial backend module result with a non-empty evidence array | Render every received valid item unchanged; do not announce or guess which module is absent. |
| Zero confidence | Render `Confianza 0%`; zero is a valid governed value. |
| Empty `source_features` | Render the neutral literal `Fuentes: no indicadas`; do not invent a source. |
| Structurally malformed item | Skip only that item; continue rendering valid siblings in original order. If none remain, render no section. |
| Unsupported enum, non-finite/out-of-range confidence or impact, non-array feature list, missing required field, or invalid UTC string | Treat that item as malformed under the same isolation rule. |

“Dropping missing-context items” is not a valid FI-7d mutation target because
no such item exists in the closed wire contract. The causal replacement is a
test proving that partial-result evidence is not filtered by code, basis,
direction, zero confidence, or empty sources, alongside a test proving that
absence never produces a fabricated item.

#### Feature flag, renderer, and runtime isolation

The UI does not read `FOOTBALL_INTELLIGENCE_ENABLED`, add a client flag, or
reconstruct backend eligibility. It renders only response-owned evidence.
When the backend master flag is OFF, the backend supplies no FI evidence and
the component renders nothing, preserving the existing UI. No evidence
component calls `ask`, `sessionAsk`, `fetch`, an FI tool, or any backend route.

Backend deterministic FI renderers remain backend-owned. Frontend components
render the structured `EvidenceItem` fields only. Existing `final_text`,
recommendation cards, recommendations, confidence calculations, and renderer
copy remain unchanged; no duplicate FI prose is appended.

The `@minutes` and `@role` resources are outside the FI-7d UI-only boundary and
outside FI-7e. The FI-7f subsection below is now their authoritative proposed
contract; implementation remains prohibited until that documentation is
independently approved and merged.

#### Accessibility and responsive behavior

- `EvidenceList` uses a visible section heading and semantic `<ul>` / `<li>`
  structure. The heading is associated with the list by `aria-labelledby`.
- Confidence, basis, and direction are always written as text. Color is
  redundant decoration only, and existing `hc:` high-contrast tokens must
  retain readable borders/text.
- Decorative icons, if any are later selected from the existing set, are
  `aria-hidden`; no icon is required for meaning.
- Noninteractive chips are absent from the tab order. Because there is no
  disclosure or tooltip, FI-7d introduces no new keyboard/focus state or ARIA
  expanded relationship.
- No motion is required. If existing transitions are reused, they must honor
  reduced motion; evidence never animates on replay/hydration.
- Full content remains screen-reader accessible. No `title`-only explanation,
  clipped accessible name, or identifier leakage is allowed.
- The list remains inside the existing `max-w-prose` response width.
  `EvidenceList` renders as exactly one column below the existing `sm`
  breakpoint and exactly two columns at and above `sm`, with backend order
  preserved by row-major placement. Every evidence row uses `min-w-0`; long
  text wraps, and no hidden overflow may contain meaningful content. There is
  no horizontal scroll, fixed pixel width, viewport-dependent filtering,
  truncation, reordering, balancing, or item removal. Identical evidence
  content remains available at every viewport size, and SSR and hydration
  render the same item set.
- Dense multi-intent child lists stay within each existing child sub-card and
  never overlap or merge. Badge/content rows wrap or stack on narrow screens.

#### Failure isolation and logging

Structural validation happens per item before rendering. A malformed item
cannot suppress valid siblings. `EvidenceBoundary` is the repository's first
evidence-specific React error boundary and must use React's supported
class-component error-boundary contract, or an already-supported equivalent if
the repository adopts one before implementation. It catches unexpected render
exceptions only in the evidence subtree and returns `null`; server rendering
must not replace or hide the primary response. The main recommendation
text/card, origin badge, sharing, and follow-up controls remain available.
FI-7d adds no custom telemetry event, analytics, persistence,
console payload dump, retry, or network fallback; in particular it must never
log canonical subject or fixture IDs from malformed evidence.

#### Causal test and acceptance matrix

Tests follow the existing Jest 29 / Testing Library / `@jest-environment jsdom`
component convention, plus the existing pure TypeScript contract tests.

| Area | Required acceptance |
|---|---|
| Component contract | `EvidenceList` preserves exact input order, renders exact duplicates separately, performs no frontend truncation, shows all eight governed items, renders `null`/absent/empty as nothing, skips only malformed items, and retains valid zero-confidence/empty-source/proxy/neutral items. |
| `EvidenceChip` mapping | Label and summary are verbatim; basis/direction/source mappings are deterministic; source-feature order is preserved; code and every internal ID/provenance field are absent from visible and accessible text; long content remains fully available. |
| Confidence | `0`, representative fractional input, and `1` render `0%`, the repository-pinned rounded integer, and `100%`; no thresholds/categories exist; visible confidence text remains when color classes are removed. |
| Top-level ownership | Stateless and single-intent session-shaped responses render top-level evidence on both structured-card and text-only paths. Recommendation/card text is unchanged when evidence is added. |
| Multi-intent ownership | Parent evidence never renders; eligible child evidence renders inside that child; non-eligible child remains unchanged; child order and separate lists remain; identical cross-child items do not merge. |
| Replay/determinism | Re-render and replay of an identical response produce the same item text/order/keys with no network, clock, random, locale, or hydration-dependent branch. |
| Flag/isolation | Absent evidence produces no FI UI; components do not import API clients, reconstruct eligible intents, inspect a client flag, invoke `fetch`, or change tools/registry behavior. |
| Accessibility | Heading/list association, semantic list/listitem roles, nonfocusable chips, complete text, color-independent confidence/basis/direction, high-contrast classes, and no inaccessible tooltip/disclosure are pinned. |
| Responsive | Tests pin exact `grid-cols-1 sm:grid-cols-2` classes, row-major DOM order, `min-w-0`, long-label/source wrapping, and containment inside dense child cards without hidden meaningful overflow. No conditional JavaScript viewport rendering is allowed; below `sm` is exactly one column, at and above `sm` is exactly two, and SSR/hydration retain the identical item set. |
| Failure containment | Mixed valid/malformed arrays keep valid siblings; all-malformed arrays show no section; a deliberately throwing evidence child is contained while the main response remains visible; no identifier is logged. |
| Regression | Existing MessageList/IntentRenderer/MultiIntentView behavior without evidence is unchanged; Jest, TypeScript type-check, production build, contract/evidence parity, backend governed suites, and contract gate remain green. Snapshots change only if intentionally introduced. |

Mutation checks must causally fail when an implementation reverses evidence,
deduplicates exact duplicates, caps below the received length, removes a valid
partial/zero-confidence item, turns zero into absence, renders parent evidence,
merges child lists, exposes `subject_id`/`fixture_id`, hides source features,
uses color without text, gives a presentational chip button/tab semantics,
hides items after a fixed count, or invokes a client FI/network path.

#### Exact exclusions and definition of done

FI-7d changes presentation only. It explicitly excludes backend runtime and
enrichment changes; M1/M2/M3 algorithms; M4/M5; evidence construction,
ordering, deduplication, truncation, schemas, or confidence; new tools,
resources, registry entries, and flags; recommendation, identity, fixture, or
backend renderer changes; HTTP/Python contracts; LLM use; network requests from
evidence components; analytics expansion; persistence; share-image redesign;
recorded-demo assets; and all FI-7e work. A schema mismatch discovered during
implementation stops the slice for separate contract review rather than being
silently widened.

FI-7f resource-surface parity is also excluded. This section records its
deferral only and does not begin its contract or implementation.

FI-7d is complete only after the documentation is independently reviewed and
merged, a separately authorized bounded implementation satisfies the full
matrix, realistic mutations are killed, the implementation receives
independent review, and the final merge is independently verified. This
documentation PR does not authorize or begin that implementation.

### FI-7e — deterministic end-to-end demo and verification evidence

**Status:** complete — documentation and artifact production merged in PR #61;
merge integrity was independently verified at
`main@5e57a40b76bb9478abc5358ca6de700c4c8f6493`. The retained contract below
records the completed evidence boundary. FI-7f and the `@minutes` / `@role`
resources remain unstarted until their documentation is independently approved
and merged.

#### Purpose, repository facts, and evidence model

FI-7e produces a reproducible evidence and communication package for the
completed FI-7a–FI-7d vertical. It adds no product behavior. The package must
prove the runtime and UI claims with machine-readable assertions rather than
asking reviewers to infer correctness from a video.

Repository inspection found checked-in UAT runbooks, dated capture/findings
records, immutable completed passes, machine-readable validation JSON, HTTP
session examples, FastAPI `TestClient` fixtures, and Jest/Testing Library UI
tests. It found no Playwright, Cypress, browser screenshot runner, established
video directory, or binary-video retention convention. The existing FI tests
already provide deterministic controlled inputs, explicit `calculated_at`,
module-call spies, session HTTP transport, response replay, recommendation
equality, malformed-evidence containment, and responsive-class assertions.
The UI runs locally with `npm run dev` and proxies sessions to
`FPL_BACKEND_URL` (default `http://localhost:8000`); the backend runs locally
with `python fpl_server.py` on `127.0.0.1:8000`.

The locked format is therefore a **combined evidence package**:

1. a test-only deterministic capture command exercises the existing backend
   harness/session seams against frozen canonical/mock inputs and emits raw and
   normalized JSON plus a structured runtime trace;
2. the exact normalized `AskResponse` payloads emitted by that command are
   served by a demo-only local fixture server to the unchanged UI, so the UI
   recording consumes the same canonical-JSON SHA-256 payload hashes reviewed
   in the backend trace;
3. checked-in desktop/mobile screenshots, a transcript, manifests, checksums,
   and test summaries make every visual claim independently reviewable; and
4. one short externally hosted silent browser recording is referenced by URL
   and SHA-256 in the manifest. Binary video is not committed to Git.

The fixture server and capture command are later **demo/test tooling**, never a
production route or runtime fallback. A browser-only recording is not runtime
proof, and a backend-only trace is not FI-7d proof. Both halves must name the
same scenario IDs and canonical-JSON response SHA-256 values. If this linkage cannot be
implemented without modifying production code, FI-7e stops as a blocker for
separate review.

#### Exact later artifact boundary and inventory

The separately authorized artifact-production slice may add only these paths;
the current documentation slice adds none of them:

| Path | Class | Retention and purpose |
|---|---|---|
| `packages/fpl-grounded-assistant/FI7E_DEMO_RUNBOOK.md` | hand-authored documentation | Checked in; exact clean-checkout setup, capture, review, rerun, and cleanup procedure. |
| `packages/fpl-grounded-assistant/scripts/capture_fi7e_demo.py` | demo/test tooling | Checked in; offline deterministic capture and assertion runner. It may import existing public/test helpers but may not change production state or call a provider. |
| `packages/fpl-grounded-assistant/scripts/serve_fi7e_demo.py` | demo/test tooling | Checked in; localhost-only fixture server for the exact captured response payloads. It must fail closed outside loopback and is not imported by production. |
| `packages/fpl-grounded-assistant/tests/fixtures/fi7e_demo_inputs.json` | frozen test-only fixture | Checked in; canonical player/fixture/build identifiers, explicit prompts, flag states, and fixed `calculated_at`. |
| `packages/fpl-grounded-assistant/fi7e_evidence/README.md` | hand-authored index | Checked in; SHA, completion state, artifact map, reviewer commands, and external video link. Uses an `IN PROGRESS` marker until every acceptance item passes. |
| `packages/fpl-grounded-assistant/fi7e_evidence/environment.json` | deterministic generated artifact | Checked in; repository SHA, OS family, Python/Node/npm versions, viewport/browser versions, fixture version, and flag state. No environment dump or absolute paths. |
| `packages/fpl-grounded-assistant/fi7e_evidence/manifest.json` | deterministic generated manifest | Checked in; schema version, scenario IDs, artifact paths, canonical-JSON SHA-256 hashes, ordinary non-JSON checksums, generation command, and external video metadata/hash. |
| `packages/fpl-grounded-assistant/fi7e_evidence/backend-trace.json` | deterministic generated artifact | Checked in; module/tool/import/network counters, module order, evidence ownership/count/order, and canonical-JSON response hashes. |
| `packages/fpl-grounded-assistant/fi7e_evidence/responses.json` | deterministic generated artifact | Checked in; raw fixture-backed HTTP responses with allowed volatile fields removed or frozen as specified below. |
| `packages/fpl-grounded-assistant/fi7e_evidence/recommendation-equality.json` | deterministic generated artifact | Checked in; OFF/ON normalized comparison and exact differing-field allowlist. |
| `packages/fpl-grounded-assistant/fi7e_evidence/test-summary.txt` | deterministic generated artifact | Checked in; exact commands, exit codes, and pass totals for focused/full UI, backend FI suites, TypeScript, build, and contract gate. |
| `packages/fpl-grounded-assistant/fi7e_evidence/transcript.md` | hand-authored capture record | Checked in; scenario-by-scenario visible actions/captions tied to manifest IDs and screenshot names. No narration is required. |
| `packages/fpl-grounded-assistant/fi7e_evidence/redaction-statement.md` | hand-authored attestation | Checked in; secret/privacy scan scope and result. |
| `packages/fpl-grounded-assistant/fi7e_evidence/known-issues.md` | hand-authored status | Checked in; Railway caveat and any accepted recording-only limitations, clearly separated from product acceptance. |
| `packages/fpl-grounded-assistant/fi7e_evidence/screenshots/{A-off-desktop,B-native-desktop,B-native-mobile,C-compare-desktop,D-multi-desktop,E-replay-desktop,F-failure-desktop}.png` | deterministic visual captures | Checked in; lossless captures of the exact named fixture payload. No additional screenshots are required unless review finds a missing claim. |
| `packages/fpl-grounded-assistant/fi7e_evidence/SHA256SUMS` | deterministic checksum file | Checked in; relative POSIX paths and SHA-256 for every evidence file except itself and the external video. |

The external recording filename is
`fi7e-demo-<40-char-main-sha>.webm`. It is hosted as a review-accessible GitHub
PR/release attachment or another independently accessible immutable object;
`manifest.json` records its URL, byte length, ordinary byte-level SHA-256,
media type, duration, codec, width, height, and frame rate when the container
reports frame rate reliably. URL, byte length, SHA-256, media type, duration,
codec, width, and height are mandatory; frame rate may be `null` only with the
inspection command and reason recorded. A URL without a downloadable object
and matching hash blocks completion. No binary video, credential, cookie, or
personal data enters Git.

Completed evidence is immutable. A rerun creates a new directory named
`fi7e_evidence_rerun_<YYYYMMDD>_<short-sha>` only after separate review; it
does not overwrite the accepted package. During capture the index begins with
`<!-- IN PROGRESS — not a completed evidence record -->`, following the UAT
archive convention, and removes it only at closeout.

#### Frozen deterministic data and environment

Every scenario uses `fi7e-demo-input-v1`, derived from the already governed
canonical/mock and FI-7 test fixtures. It uses canonical Saka and Palmer
identities, one fixed scheduled fixture, validated FI-5b v2 feature/context
bindings, and `calculated_at = 2026-08-01T12:00:00Z`. Fixture IDs, kickoff,
module inputs, evidence, and responses are committed. Row reversal and repeated
evaluation must produce identical normalized results.

No live FPL, Sportmonks, Understat, LLM/provider, Railway, Vercel, wall clock,
production session, user account, or network response is a demo input. The
capture runner fails if a non-loopback socket is attempted. Browser recording
uses the demo-only localhost fixture server and unchanged frontend proxy. No
credentials are required. A clean checkout plus repository dependencies must
be sufficient on Windows PowerShell (authoritative) and should also work on a
POSIX shell; OS-specific command spelling may differ but normalized artifacts
must not.

`environment.json` pins the exact repository SHA and records, rather than
silently assumes, runtime versions. The later runbook must use the versions in
the repository lockfiles/current CI and commands already supported by the
repository; it may not install a new browser-automation dependency merely for
FI-7e.

#### Scenario and assertion matrix

| ID | Input and capture | Machine-checkable acceptance |
|---|---|---|
| A — flag OFF baseline | Default/unset `FOOTBALL_INTELLIGENCE_ENABLED`; prompt `captain score for Saka`; desktop UI capture. | Static schemas = 33; offered tools = 29; no FI imports, tool calls, module calls, or evidence field; normalized recommendation equals the frozen pre-FI value; UI has no Evidence heading. |
| B — flag ON FI-native | Flag ON; prompt `player intelligence for Saka`; desktop and mobile captures. | Offered tools = 33; one composite invocation; call order exactly `M1,M2,M3`, each once; no M4/M5; the demo payload proves its own bounded native-order M1→M2→M3 evidence output (`0..8`). Exact duplicate collapse, first-occurrence retention, and the eight-item boundary are causally proven by `test_evidence_exact_dedup_first_occurrence_order_and_first_eight`; the screenshot need not show an over-eight pre-truncation input. UI shows `Evidencia`, visible label/summary/basis/direction/confidence/sources, hidden IDs, and no UI FI/network request. |
| C — eligible existing intent | OFF and ON executions of `compare Saka and Palmer`; desktop ON capture. | Intent remains `compare_players`; player order is Saka then Palmer; every response field except `evidence` has identical canonical UTF-8 JSON bytes; ON adds bounded per-player evidence in player order; runtime cache invokes a repeated canonical player at most once in the separate duplicate-input assertion. |
| D — multi-intent ownership | Flag ON; `player intelligence for Saka and what gameweek is it?`; desktop capture. | Parent intent is `multi_intent`, parent evidence absent; child 0 owns FI evidence; child 1 remains unchanged with no evidence; lists do not merge; child order remains fixed; identical cross-child evidence stays independently owned in the adversarial fixture. |
| E — session and replay | Flag ON; create local fixture session, ask `player intelligence for Saka`, persist the returned response, then replay that exact stored object through the same UI path; desktop capture. | Original top-level evidence and stored/replayed evidence have identical canonical UTF-8 JSON bytes and SHA-256; original executes M1→M2→M3 once; replay module/tool/enrichment/UI-request counters are all zero; no sub-response is introduced. |
| F — deterministic degradation | Existing test-only enrichment adapter is made to raise for an eligible `captain score for Saka` response; separately render a fixture with a throwing evidence subtree. | Primary recommendation text/values equal the no-enrichment control; evidence is absent, never fabricated; main UI response remains visible; boundary fallback is null; no retry, provider call, logging of payload IDs, or production failure hook. |

Additional assertions apply across the matrix: flag OFF is the default; no M4
or M5 executes; no LLM creates evidence; no frontend sorting, deduplication,
truncation, or collapse occurs; zero-confidence evidence remains visible;
response ownership is unchanged; and FI-7f resources are absent.

#### Runtime trace and replay proof

`capture_fi7e_demo.py` must produce a closed `backend-trace-v1` record per
scenario with: scenario ID; canonical-JSON input SHA-256; flag state;
static/offered tool counts;
selected tool/intent; canonical identity/fixture IDs (machine artifact only);
M1/M2/M3 load/evaluate counts and order; M4/M5 counts; FI import count on OFF;
enrichment/composite counts; UI-request count; evidence canonical-JSON SHA-256
values and owners; replay count; canonical-JSON response SHA-256; and assertion
results.

Counters come from existing injected test seams/spies, not new production
logging. The trace command must run the existing focused FI-7b2, FI-7b3,
FI-7c, and FI-7d tests as causal corroboration. Replay proof requires the
original response object to be serialized once, stored in `responses.json`,
deserialized without modification, and rendered again while all FI execution
counters remain zero. Merely issuing the same prompt twice is reevaluation,
not replay, and fails Scenario E.

#### Recommendation equality

All normalized hashes, including backend-trace, responses,
recommendation-equality, and manifest hashes, use one canonical serialization:
UTF-8 JSON produced with Python `json.dumps` using `sort_keys=True`,
`separators=(",", ":")`, `ensure_ascii=False`, LF semantics, and no trailing
newline. This is the same compact canonical form already used by
`packages/fpl-grounded-assistant/fpl_grounded_assistant/existing_intent_evidence.py`.
Array order, strings, `null` values, and member omission semantics are
preserved. Numbers use Python's shortest round-trip representation; therefore
all confidence, impact, score, and other floating-point values used by FI-7e
must originate from the frozen fixture and must not be recomputed or
reformatted by shell tools, JavaScript, `jq`, PowerShell, spreadsheet software,
or manual editing before hashing. The only permitted response difference in
Scenario C is the top-level `evidence` member on the eligible successful
response.

Canonical JSON files contain those exact bytes: Unicode is written directly
as UTF-8 rather than `\uXXXX`, JSON is not pretty-printed, omitted members stay
omitted, and `null` remains distinct from omission. SHA-256 is calculated over
the exact canonical UTF-8 bytes. No shell or JavaScript serializer may
regenerate a hashed JSON artifact. Scenario C compares this canonical form for
OFF and ON. No text, intent,
supported/outcome value, comparison player order/value, recommendation,
score, tier, reason, routing trace, or other metadata may differ.

`recommendation-equality.json` records both canonical-JSON SHA-256 values after removing
only `evidence`, the exact JSON Pointer allowlist (`/evidence`), and an empty
unexpected-diff array. Visual similarity or hand-selected field comparisons
are insufficient. The duplicate-player cache assertion is test-only and
records canonical player-resolution/runtime call counts without altering the
user-facing compare request.

#### UI capture and recording protocol

Use Chromium from the locally installed supported browser, 100% zoom, dark
theme, no browser extensions, a fresh unauthenticated local session, and no
open developer-tools panes containing secrets. Desktop captures use
`1440×900`; mobile captures use `390×844`, both at device pixel ratio 1. The
desktop width proves two columns at/above `sm`; the mobile width proves one
column below `sm`. Both Scenario B captures must contain the identical item
labels in identical DOM/backend order, and the manifest records their common
canonical-JSON response SHA-256.

The recording is silent; `transcript.md` supplies captions. It starts with a
title card showing the full repository SHA, scenario ID, flag state, fixture
version, viewport, and expected assertion, then shows A through F in order. It
ends with the manifest/checksum verification result. Permitted editing is
limited to trimming idle time and concatenating whole scenario segments.
Overlays may add scenario titles only. Cutting within a request/response,
reordering scenarios, replacing payloads, changing visible values, hiding an
error, or compositing evidence is prohibited. Raw segment hashes are retained
in the manifest if editing occurs.

Required visual views are: OFF/no-evidence; FI-native desktop; FI-native
mobile; eligible structured comparison; child-owned multi-intent evidence;
session replay; and failure containment. Empty/all-invalid presentation is
machine-tested and may share the failure segment; no fabricated empty-state
copy is shown. The screenshots must demonstrate `grid-cols-1 sm:grid-cols-2`,
`Confianza 0%` in at least one governed fixture, source text including
`Fuentes: no indicadas`, noninteractive rows, and absence of visible internal
subject/fixture IDs.

#### Setup, execution, capture, and rerun contract

The later runbook must provide literal PowerShell and POSIX equivalents for:

1. clone/fetch and checkout the exact accepted artifact-production SHA;
2. verify `git status --porcelain` is empty and record the SHA;
3. create/use the repository Python environment and install only existing
   requirements;
4. run `npm ci` under `packages/fpl-ui`;
5. run the offline capture command with a clean output directory and expect
   exit code 0;
6. start `serve_fi7e_demo.py` on loopback, set the existing
   `FPL_BACKEND_URL=http://127.0.0.1:<documented-port>`, and run `npm run dev`;
7. execute A–F in order, capture the pinned viewports, and stop both processes;
8. run focused FI tests, FI-7d Jest, full UI, TypeScript, production build,
   football-intelligence/grounded-assistant governed suites, and contract gate;
9. run normalization, manifest validation, secret scan, and SHA-256 verification;
10. confirm no tracked file outside the approved artifact boundary changed,
    then remove only documented temporary output/processes.

The canonical PowerShell sequence (with `<accepted-sha>` replaced by the
reviewed artifact-production SHA) is:

```powershell
git fetch origin --prune
git checkout --detach <accepted-sha>
git status --porcelain=v1 --untracked-files=all
git rev-parse HEAD
$fi7eOutput='C:\tmp\fi7e-rerun-<short-sha>'
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r packages\fpl-grounded-assistant\requirements.txt -r packages\football-intelligence\requirements.txt
Push-Location packages\fpl-ui
npm ci
Pop-Location
.\.venv\Scripts\python.exe packages\fpl-grounded-assistant\scripts\capture_fi7e_demo.py --fixture packages\fpl-grounded-assistant\tests\fixtures\fi7e_demo_inputs.json --output $fi7eOutput
```

Then keep the fixture server running in terminal 1:

```powershell
$fi7eOutput='C:\tmp\fi7e-rerun-<short-sha>'
.\.venv\Scripts\python.exe packages\fpl-grounded-assistant\scripts\serve_fi7e_demo.py --responses "$fi7eOutput\responses.json" --host 127.0.0.1 --port 8765
```

After its readiness check passes, keep the UI running separately in terminal
2:

```powershell
$env:FPL_BACKEND_URL='http://127.0.0.1:8765'
Push-Location packages\fpl-ui
npm run dev
Pop-Location
```

The server and UI therefore cannot be pasted as sequential foreground commands
in one terminal. After A–F capture, stop both with
their foreground `Ctrl+C`; do not kill unrelated processes. The verification
sequence is:

```powershell
Push-Location packages\fpl-grounded-assistant
..\..\.venv\Scripts\python.exe -m pytest tests\test_fi7b1_tool_shells.py tests\test_fi7b2_runtime_integration.py tests\test_fi7b3_rendering_session_evidence.py tests\test_fi7c_existing_intent_evidence.py
Pop-Location
Push-Location packages\fpl-ui
npm test -- --runInBand __tests__\fi7d-evidence-ui.test.tsx
npm test -- --runInBand
npx tsc --noEmit
npm run build
Pop-Location
& 'C:\Program Files\Git\bin\bash.exe' 'scripts/run_contract_gate.sh'
git diff --check
git status --porcelain=v1 --untracked-files=all
```

The POSIX runbook first runs `python3 -m venv .venv`, then uses the same
arguments with `.venv/bin/python`, `/` path separators, `pushd`/`popd`, and
`FPL_BACKEND_URL=http://127.0.0.1:8765 npm run dev`; it must not change any
scenario input, output path, or assertion. Every command's expected exit code
is zero. The two long-lived servers are the only exceptions and are considered
successful after their documented loopback readiness checks and clean stop.

The capture command must refuse a dirty tracked or full worktree, stale SHA,
wrong fixture version, pre-existing nonempty output directory, live-provider
configuration, or non-loopback target. It must be idempotent into a fresh
directory. Reviewers rerun into a temporary directory and compare normalized
JSON and canonical-JSON SHA-256 values to the committed package; committed file modification times are
not evidence and are excluded.

#### Timestamps, normalization, privacy, and secrets

All governed `calculated_at`, kickoff, response, and scenario timestamps are
frozen fixture values. Session UUIDs, process IDs, durations, local ports,
absolute paths, file modification times, and recording creation timestamps are
volatile: they may appear only in a raw temporary capture, are removed from
committed normalized JSON, and never participate in canonical hashes. Manifest
`generated_at` is the fixed fixture timestamp, not the wall clock.

JSON semantic hashing and ordinary artifact checksums are distinct. Every
normalized JSON payload uses the compact Python canonical serialization above,
has no trailing newline, and is SHA-256 hashed over those exact UTF-8 bytes.
Every non-JSON artifact is hashed as ordinary final bytes and is never passed
through the JSON canonicalizer: PNG metadata is stripped first and the
resulting PNG bytes are hashed; Markdown is normalized to UTF-8/LF with no
other semantic rewrite and those text bytes are hashed; WebM is hashed over
the downloadable finalized container bytes; and other non-JSON artifacts are
hashed over their final stored bytes. The external video's container metadata
may vary only before finalization; the committed manifest pins the accepted
bytes.

No artifact may contain real user/player-account data beyond public frozen
football fixture names, API/provider keys, auth headers, cookies, tokens,
emails, IPs other than loopback, personal session IDs, environment dumps,
home-directory paths, Railway/Vercel credentials, or provider payloads outside
licensed checked-in mocks. All text/JSON is UTF-8 with LF and relative POSIX
paths. Before closeout, run the repository's available secret scan if present
and an explicit case-insensitive search for token/key/auth/cookie/email and
absolute-path patterns; record the command and zero findings in
`redaction-statement.md`. Potential matches are reviewed, not blindly deleted.

#### Failure policy and Railway caveat

Never edit output to appear successful. On a failed scenario, retain the raw
temporary failure evidence outside the accepted directory, mark the package
`IN PROGRESS`, and classify the failure as product regression, fixture drift,
environment issue, or recording-only issue. Record the failed command, exit
code, SHA, and classification before rerun. Product regression, fixture drift,
machine assertion failure, canonical response/hash mismatch, secret/privacy finding,
missing scenario, missing video access/hash, dirty/stale capture, production
delta, or visual/machine contradiction blocks FI-7e. A recording-only failure
may be rerun from unchanged machine artifacts; an environment issue may be
rerun after documenting the environment correction. Hand-written claims never
replace machine evidence.

Railway `fpl-backend` deployment failure is a separate operational caveat. It
predates FI-7d, FI-7d changed no backend file, and backend tests/contract gates
pass. FI-7e uses the local deterministic backend/fixture server, does not fix
or configure Railway, does not hide its status, and does not treat Railway as
proof. Successful FI-7e does not resolve that issue; Railway requires a
separate operational ticket/runbook outside this roadmap slice. Railway health
is not an FI-7e completion gate when local deterministic validation passes.

#### Review, acceptance, and adversarial mutations

FI-7e is complete only when all A–F scenarios pass; raw/normalized JSON is
linked by canonical-JSON SHA-256 and non-JSON artifacts by ordinary byte-level
SHA-256; visual evidence matches machine evidence; OFF and ON are both
shown; exact tool counts and M1→M2→M3-once are proven; replay has zero FI
execution; parent anti-aggregation and child separation are proven;
recommendation equality has no unexpected diff; desktop/mobile show identical
items and order with the governed responsive layout; failure degradation keeps
the primary response; no M4/M5, LLM evidence, FI network from UI, FI-7f,
`@minutes`, or `@role` appears; privacy/secret checks pass; every checksum and
external link verifies; the package reruns from a clean checkout; all governed
test/build/gate commands pass; and the artifact PR contains no production code.

Independent review must attempt at least these misleading mutations and prove
the manifest/assertions or review procedure rejects each one: ON-only capture;
omitted OFF baseline; live/changing data; stale or dirty SHA; edited JSON after
capture; evidence shown without module-order/count proof; prompt reevaluation
mislabelled as replay; replay with enrichment; child evidence while hiding a
parent payload; merged cross-child lists; recommendation comparison that
ignores fields beyond `/evidence`; changed recommendation text/value; exposed
internal IDs; desktop-only capture; item reordering/dedup/truncation; omitted
zero-confidence evidence; hidden malformed/failure behavior; M4/M5 execution;
LLM-authored evidence; UI FI fetch; missing/altered checksums; inaccessible or
unhashed video; committed secret/path/personal data; reliance on failed
Railway; and accidental FI-7f/resource inclusion.

The later `FI7E_DEMO_RUNBOOK.md` must include an adversarial detection matrix
with exactly four columns: misleading mutation, detecting artifact, detecting
command or assertion, and expected failure. Every mutation named above must
have at least one causal detecting assertion; a prose claim without a failing
command/assertion does not satisfy review.

#### Explicit exclusions and next gate

FI-7e does not authorize changes to production backend/frontend behavior,
runtime, M1/M2/M3 algorithms, fixture/identity selection, evidence semantics,
response ownership, recommendations, rendering, schemas, registry, flags,
deployment, persistence, analytics, or external provider integration. It adds
no product failure hook. FI-7f, `@minutes`, and `@role` remain outside FI-7e;
their separately reviewed contract follows below.

After this documentation is independently reviewed, corrected if required,
merged, and post-merge verified, a separate bounded prompt may authorize only
the listed demo/test tooling and evidence artifacts. This documentation PR
does not create those artifacts or derive that production prompt.

### FI-7f — deterministic resource-surface parity

**Status:** specification active; implementation unstarted. This subsection is
the authoritative contract for the separately reviewed FI-7f implementation.
It does not authorize production changes until this documentation is
independently approved, merged, and post-merge verified.

#### Objective and definition of parity

FI-7f adds deterministic, quota-free player detail commands:

- `@minutes <player>` returns the resolved player's accumulated FPL minutes;
- `@role <player>` returns the resolved player's **nominal FPL position**.

Resource-surface parity means that both commands are registered and
discoverable beside the existing `@resource` surface; use the same deterministic
player resolver as existing tools; return one stable structured resource
payload through the existing stateless transport; distinguish
success, ambiguity, absence, and invalid input honestly; produce identical
serialized output for identical bootstrap bytes and input; use no LLM-authored
facts; and perform no provider or network call during command execution.

Parity does **not** mean exposing FI-6 M1 expected minutes or M2 tactical role.
The repository already has quota-free player facts in the loaded FPL bootstrap:
`elements[].minutes` and `elements[].element_type`. FI-7f exposes those facts
without changing or invoking FI models.

#### Repository-grounded ownership and data sources

| Concern | Existing owner/source | FI-7f contract |
|---|---|---|
| Prefix recognition | `fpl_grounded_assistant.input_normalizer` | Parse an argument-bearing resource form without routing it as plain text or a slash prompt. |
| Resource aliases/order | `fpl_grounded_assistant.intent_aliases` | Preserve all six existing resources and aliases; add only the two player-detail command forms. |
| Registry and handlers | `fpl_grounded_assistant.resource_registry` | Own immutable specs, deterministic bootstrap lookup, result construction, and stable registration order. |
| Dispatch | `fpl_grounded_assistant.decision_router` | Pass the parsed player argument to the registered handler and preserve explicit degraded outcomes. |
| Player identity | `fpl_tool_contract.tool_resolve_player` | Reuse verbatim; no new fuzzy, alias, or tie-breaking policy. |
| Minutes | already-loaded `bootstrap.elements[].minutes` | Python integer (but never `bool`), season-to-current-bootstrap accumulated playing minutes; zero is valid; missing, null, Boolean, non-integral, or negative is unavailable. |
| Role | already-loaded `bootstrap.elements[].element_type` plus the existing FPL position map | Nominal fantasy classification only: `GKP`, `DEF`, `MID`, or `FWD`; missing/unknown IDs are unavailable. |
| Stateless HTTP transport | existing `ask_v2` resource branch, `harness_adapter`, and `AskResponse.resource_rows` | Pure passthrough through `/ask`; no new endpoint or top-level response schema. Session transport is deferred as described below. |

The bootstrap is already supplied to `ask_v2` by the caller/server or resolved
through the existing owned bootstrap path before `decision_router.decide` runs.
Startup/bootstrap acquisition may occur under those pre-existing owners, but
the FI-7f parser, resolver call, registry handler, and dispatcher perform no
network I/O. Tests inject a fixed bootstrap and make every provider, HTTP, and
LLM seam fail if called.

No source timestamp exists per player in bootstrap. Therefore FI-7f does not
invent `updated_at` or `calculated_at`; it uses the existing exact
`data_age="current_bootstrap"` provenance label. Freshness is the freshness of
the caller's already-loaded bootstrap snapshot.

#### Command grammar and compatibility

Input normalization remains NFC, surrounding-whitespace trimmed, and
case-insensitive for the command token. Internal player-query handling remains
whatever `tool_resolve_player` currently governs.

| Input | Required interpretation |
|---|---|
| `@minutes <player>` | Player-specific accumulated-minutes resource. `<player>` is the entire trimmed remainder, 1–100 characters. |
| `@role <player>` | Player-specific nominal-position resource. Same argument rule. |
| `@minutes` | Preserve the existing alias for the argument-free `@top_minutes` ranking. This is a frozen compatibility exception. |
| `@top_minutes` and its other existing aliases | Preserve the existing ranking resource byte-for-byte. |
| `@role` | Degraded `missing_player_argument`; it has no legacy meaning. |

The internal canonical registry keys are `player_minutes` and `player_role`;
their user-facing command forms are `@minutes <player>` and `@role <player>`.
This avoids colliding with the existing canonical `top_minutes` resource.
Discoverability must show the command forms, not invite users to type the
internal keys. `@player_minutes` and `@player_role` are not public aliases.

The parser must retain the entire remainder rather than silently discard it,
which is current argument-free resource behavior. Whitespace separating the
command from its argument and surrounding whitespace are trimmed, but internal
whitespace in the player query is preserved verbatim for
`tool_resolve_player`, matching its current `str(query).strip()` boundary; FI-7f
does not add a whitespace-normalization policy. Thus
`@minutes   Bukayo    Saka` forwards exactly `Bukayo    Saka` and returns the
existing resolver's deterministic outcome for that string. Quotes are not a
separate grammar and are also passed literally. Options and flags are
unsupported: an argument containing a standalone token beginning `--` yields
`invalid_command_shape`. Any C0/C1 control character (`U+0000`–`U+001F` or
`U+007F`–`U+009F`) in the retained argument also yields
`invalid_command_shape`; it is never sanitized into a different identity or
written raw to a resolver/log. Other additional words are part of the player
query, because valid full names contain spaces. Inputs longer than 100
characters are also `invalid_command_shape`.

#### Identity lifecycle

The input to identity resolution is the parsed player query string. FI-7f calls
`fpl_tool_contract.tool_resolve_player(query, bootstrap)` exactly once and
branches only on its existing `status`:

- `ok`: use `player_id` internally to select exactly one bootstrap element;
- `ambiguous`: return `ambiguous_player`; do not choose or tie-break;
- `not_found`: return `unresolved_player`;
- any malformed/contradictory successful identity (missing ID, absent element,
  or more than one element with that ID): return `resource_data_unavailable`.

Existing exact ID, web-name, exact-name, and governed alias behavior is
inherited. FI-7f adds no alias table, fuzzy threshold, team qualifier, or new
tie-break. Resolved numeric IDs are not exposed in resource rows or human text;
the stable display identity is `web_name` plus `team_short`. This matches the
existing resource list's public identity convention while keeping resolution
consistent with FI tools and existing deterministic intents.

#### Logical response contracts

The existing list resources retain their current `ResourceResult.to_dict()`
bytes. FI-7f adds one immutable player-resource result type inside
`resource_registry.py`; it does not widen `AskResponse` because `resource_rows`
is already an opaque `dict[str, Any] | None` transport.
Every player-resource result serializes these keys in this order, with none
omitted:

| Field | Type | Invariant |
|---|---|---|
| `resource` | string | `player_minutes` or `player_role` |
| `title` | string | Frozen English display title |
| `columns` | array[string] | Frozen ordered row columns for that resource |
| `rows` | array[object] | Exactly one row on `ok`; empty on degradation |
| `data_age` | string | Exactly `current_bootstrap` |
| `status` | string | `ok` or `unavailable` |
| `reason` | string or null | Null on `ok`; one stable reason code otherwise |

`@minutes <player>` successful columns and row are:

```text
columns = ["web_name", "team_short", "position", "value", "unit", "scope", "provenance"]
row = {
  "web_name": string,
  "team_short": string,
  "position": "GKP" | "DEF" | "MID" | "FWD",
  "value": integer >= 0,
  "unit": "minutes",
  "scope": "current_season_to_bootstrap",
  "provenance": "fpl_bootstrap.elements.minutes"
}
```

`@role <player>` successful columns and row are:

```text
columns = ["web_name", "team_short", "role", "role_kind", "provenance"]
row = {
  "web_name": string,
  "team_short": string,
  "role": "GKP" | "DEF" | "MID" | "FWD",
  "role_kind": "nominal_fpl_position",
  "provenance": "fpl_bootstrap.elements.element_type"
}
```

`role` never means average position, flank, formation depth, observed tactical
deployment, inferred proxy, out-of-position score, or M2 tactical role. No
confidence or evidence is attached. JSON primitives are emitted directly;
field and column order is frozen as above, reason/status values are lowercase
stable strings, and no free-form LLM factual text is permitted.

#### Honest degradation

Degraded player-resource responses use the same seven top-level keys, empty
`rows`, `status="unavailable"`, and exactly one of these `reason` codes:

| Reason | Condition |
|---|---|
| `missing_player_argument` | Required player remainder is empty (`@role`; player-specific parser path only). |
| `invalid_command_shape` | More than 100 characters, any C0/C1 control character, or a standalone `--...` option/flag token. |
| `unresolved_player` | Existing resolver returns `not_found`. |
| `ambiguous_player` | Existing resolver returns `ambiguous`. |
| `minutes_unavailable` | Resolved row lacks a valid nonnegative integral `minutes`. |
| `role_unavailable` | Resolved row lacks a supported `element_type` mapping. |
| `resource_data_unavailable` | Bootstrap/identity structure is absent or contradictory, or the resolver returns an unsupported shape/status. |

There are no zero/default fallbacks. Zero minutes is a valid successful fact.
`True` and `False` are unavailable rather than the integer values one and zero,
even though Python `bool` subclasses `int`.
Degradation is a supported resource response, not an exception converted to an
LLM answer. Invalid Python input types and programmer-contract violations may
still raise existing typed errors; provider/network exceptions cannot arise
from the resource handler because it has no such dependency.

Exactly one degradation reason is emitted. The first failing stage owns it in
this fixed precedence: command-shape validation (`missing_player_argument` or
`invalid_command_shape`), then identity resolution (`unresolved_player`,
`ambiguous_player`, or malformed identity as `resource_data_unavailable`), then
resource-data validation (`minutes_unavailable`, `role_unavailable`, or
`resource_data_unavailable`). Later stages do not run after a failure.

#### Registration, dispatch, flags, and transport

The two immutable specs append after the six current specs in stable order:
`player_minutes`, then `player_role`. Duplicate canonical keys or duplicate
public command forms fail tests. `list_resource_specs` exposes both specs;
resource suggestions/discovery render the public syntaxes. Exact command-token
matching occurs before general alias fallback so `@minutes Saka` selects
`player_minutes`, while bare `@minutes` continues to select `top_minutes`.

FI-7f resources are general grounded bootstrap resources, not FI tool schemas.
They are always registered and are **not** gated by
`FOOTBALL_INTELLIGENCE_ENABLED`. OFF and ON therefore produce identical FI-7f
resource results for identical bootstrap/input, and OFF preserves all existing
resource behavior except the newly valid argument-bearing forms. FI-7f does
not modify `tool_schema_registry.py` or the orchestrator allowlist:

- static FI schemas remain 33;
- offered FI tools remain 29 OFF / 33 ON;
- FI runtime M1 → M2 → M3 behavior is untouched;
- M4/M5 remain unexecuted;
- recommendations and FI evidence are untouched.

Both commands use the existing direct resource branch of `ask_v2`. The adapter
copies `resource_rows` unchanged into stateless `AskResponse`; no new HTTP
endpoint, renderer, or UI schema is required. Repeated stateless calls over
identical input and bootstrap serialize identically. The resource response
carries no `FinalResponse.evidence`; it does not aggregate, enrich, or modify
FI evidence or recommendation output.

#### Session transport is deferred

Repository-grounded implementation testing found that the current session path
is `session_ask()` → `ConversationSession.respond()` →
`final_response.respond()`. Unlike stateless `ask_v2`, that path does not
dispatch ordinary `@resource` commands and returns `unsupported_intent` for an
FI-7f player-resource command. The earlier assumption that generic session
resource dispatch already existed was false.

FI-7f therefore authorizes **stateless resource parity only**. It does not add
session dispatch, `SessionAskResponse.resource_rows`, player-context behavior,
or session lifecycle tests for these commands. `conversation_state.py`,
`final_response.py`, `fpl_server.py`, session schemas, turn/history/audit
behavior, and `last_player_query` remain unchanged and outside this slice.
Session support requires its own documentation-first slice grounded in the
actual response-assembly boundary; until then, FI-7f session commands retain
the repository's existing unsupported behavior. No claim about resource-player
context persistence or pronoun reuse is made by this slice.

#### Implementation boundary and ownership

The later implementation is bounded to these likely homes, subject only to
independent review finding an existing test home that is more specific:

- `fpl_grounded_assistant/input_normalizer.py`: retain resource argument text
  and validate the bounded command shape;
- `fpl_grounded_assistant/intent_aliases.py`: public command/canonical mapping
  and stable discovery order without changing existing aliases;
- `fpl_grounded_assistant/resource_registry.py`: two specs, immutable result,
  bootstrap lookup, data validation, and serialization;
- `fpl_grounded_assistant/decision_router.py`: argument-aware dispatch and
  degraded result mapping;
- `tests/test_fi7f_resource_parity.py`: focused contract/mutation coverage;
- existing M1/G1 resource runners only where a regression pin belongs.

`harness.py`, `harness_adapter.py`, `conversation_state.py`, `final_response.py`,
`fpl_server.py`, response/session schemas, and UI require **no** implementation
change. Existing stateless generic handling already supports the logical
payload; session handling is explicitly deferred rather than inferred. If
stateless implementation proves to require one of these files, stop for
contract review rather than silently widening scope.
Parsing belongs only to the normalizer; identity only to
`tool_resolve_player`; retrieval/validation/serialization only to the resource
registry; dispatch/error mapping only to the decision router.

#### Acceptance and adversarial test matrix

| Area | Required implementation proof |
|---|---|
| Registration | Eight specs in frozen order; two new public syntaxes discoverable; no duplicate keys/forms; all six existing result bytes unchanged; FI static/offered counts remain 33 and 29/33. |
| Parsing | Valid mixed-case forms; NFC and surrounding whitespace; multiword player; `@minutes   Bukayo    Saka` is forwarded as exact `Bukayo    Saka`; bare `@minutes` legacy ranking; bare `@role`; empty/overlong input; C0/C1 control character; standalone option token; unknown resource; no silent argument discard or control-character sanitization. |
| Identity | Exact ID/name/web-name/governed alias behavior inherited; resolver called exactly once; unresolved and ambiguous remain distinct; ambiguity never tie-broken; resolved ID absent/duplicated in bootstrap fails honestly. |
| Minutes | Positive and zero values; `True`/`False`, null, missing, non-integral, and negative values unavailable; exact unit/scope/provenance; season-total semantics; stable ordered serialization; reversed unrelated bootstrap rows do not change output. |
| Role | Each `element_type` 1–4 maps to `GKP/DEF/MID/FWD`; null/unknown unavailable; `role_kind` and provenance exact; tests reject tactical/flank/depth/confidence/evidence fields. |
| Determinism | Input copy not mutated; repeated calls and fresh-process replay are byte-identical; no wall clock, random value, unordered-set serialization, or locale-sensitive formatting. |
| Quota isolation | Provider/Sportmonks clients, HTTP/network calls, FI runtime, and LLM seams are fail-on-call; command still succeeds over injected bootstrap; no new provider imports in bounded files. |
| Flags | Resource outputs identical OFF/ON; 33 static schemas; 29 offered OFF and 33 ON; M1/M2/M3 call counts unchanged and zero for resource calls; M4/M5 zero. |
| Transport | Direct decision, `ask_v2`, adapter, and stateless HTTP preserve the exact resource payload. Stateless handling remains stateless; evidence remains absent and no response schema is added. Session transport is not an acceptance target. |
| Regression | Existing resources/aliases/count/order and current bare `@minutes` ranking pass unchanged; recommendation output and FI evidence are unchanged; existing FI tests, stateless HTTP schemas, UI, session behavior, and FI-7e artifacts are byte-identical. |
| Mutations | Tests fail if the player remainder is dropped/collapsed; control characters pass; Boolean minutes become 0/1; reason precedence changes; bare `@minutes` is repurposed; ambiguous identity is selected; zero becomes unavailable; missing data becomes zero; role is labelled tactical; a provider/LLM/FI call occurs; flag changes output; IDs/evidence leak; field/order/provenance/reason changes; or existing registry order drifts. |

Expected validation includes the focused FI-7f tests, existing M1/G1 resource
runners, resolver/tool-contract tests, grounded-assistant regression suite, FI
tool registry invariant tests under OFF and ON, stateless HTTP contract tests,
the existing session suite as an unchanged regression boundary, contract gate,
`git diff --check`, and network/provider import scans. No live
provider account, token, or network is permitted.

#### Explicit non-goals and completion gates

FI-7f excludes FI model or M1/M2/M3 changes; M4/M5 activation; expected-minutes
prediction; tactical-role, flank, depth, average-position, or matchup
inference; recommendation or ranking changes; UI redesign; evidence creation or
evidence UI changes; external provider integration; new identity/fuzzy/alias
policy; LLM prompts; tool schemas; persistence; FI-7e artifact changes;
unrelated legacy fixes; atomic-tool-ranking work; and any stash operation.

FI-7f is complete only after this documentation is independently approved and
merged; implementation is derived from the merged specification; targeted and
full regression, registry-invariant, quota-isolation, transport, and contract
gates pass; recommendation/evidence byte identity is proven; independent
implementation review closes all findings; exact-head merge-readiness approval
is issued; and the implementation merge receives independent integrity
verification.

#### FI-7f closeout note (2026-08-08)

Every condition above is satisfied. The specification was approved and merged
(PRs #63/#64); the implementation was merged in **PR #65** at
`main@e12c8b9179a90624e6a3cf089022522c9f592283`, with reviewed head
`0ea9f6cb5b65059f1110acacec60b4f34e7bc19c` confirmed as a direct parent of the
merge commit. Evidence: **42/42** FI-7f parity tests; grounded-assistant
**592 passed / 1 skipped**; both required checks green on the resulting `main`.

Independent implementation review — by a reviewer with no involvement in the
implementation — returned **approve, no blockers, no required changes**. It
verified determinism (byte-identical output under element-order reversal),
quota isolation (no provider/network/LLM import in the execution path; identical
output with `FOOTBALL_INTELLIGENCE_ENABLED` off and on), FI-6 non-exposure
(`@minutes` reads `elements[].minutes`, `@role` maps `elements[].element_type`
locally), single-call identity resolution, the frozen seven-key response
envelope and column lists, and session-transport deferral.

**Two informational findings — recorded so a future reader need not rediscover
them. Neither is a defect and neither requires action:**

1. `resource_registry.py:36` imports `field` from `dataclasses` without using
   it. Confirmed **pre-existing** — the import line is untouched context in
   `git diff 81cc2d7..0ea9f6c`, not introduced by FI-7f. Left alone deliberately
   rather than swept into an unrelated slice.
2. The `except (AttributeError, KeyError, TypeError, ValueError)` guard around
   the `tool_resolve_player` call (`resource_registry.py:328-331`) is a narrower
   net than "no exception can escape" — an `IndexError` from a malformed
   resolver, for instance, would propagate. This is **explicitly permitted** by
   the contract above ("Invalid Python input types and programmer-contract
   violations may still raise existing typed errors"), so it is not a violation.
   Worth revisiting only if `tool_resolve_player`'s exception surface changes.

**Two items the reviewer could not verify, stated as limits rather than
assumed:** (a) the contract describes tests in which "every provider, HTTP, and
LLM seam fail if called"; the suite instead proves no such call occurs via
absence-of-import plus a resolver-call-count assertion — judged adequate, but
not literally that test shape; (b) repo-wide cross-package regression suites
were spot-checked rather than exhaustively re-run in that session.

### FI-8 — Trial readiness gate
- **Files new:** `sportmonks-client/scripts/trial_{auth,entities,fixtures,squads,lineups,injuries,stats,mapping}.py` (each: live call → raw snapshot → normalize → report; `--mock` mode for CI-less rehearsal); `TRIAL_STATUS.md` template; licensing checklist doc; go/no-go rubric doc (§14.4).
- **DoD:** §14.1 checklist fully ticked. **Trial-dep:** none to build; exists to spend the trial well. **Pre-trial:** yes.

### FI-8 — detailed slice specification (source of truth for S0–S6)

**Status:** planned. Supersedes the two-line FI-8 summary above for implementation detail. FI-8 requires **no Sportmonks account, token, or network** and is not gated on the FI-9 trial window; it exists to spend that window well.

#### Scope deviation, recorded

§15 lists **11** new files for FI-8. This spec adds a **12th**, `scripts/_trial_common.py`, holding the shared harness. Eight scripts each doing *live call → raw snapshot → normalize → report* would otherwise carry eight divergent copies of the same argument parsing, mock wiring, snapshot writing, and report emission. The deviation is deliberate and must be restated in the FI-8 commit message per §15's "document deviations" rule.

#### The hard constraint (governs every slice)

**No live Sportmonks call before FI-9 — anywhere, including tests.**

1. `--mock` is the **default** execution mode of every `trial_*.py`.
2. The live path **is written now and reviewed, but never executed**. It requires **both** `--live` (the mode selector) and `--i-understand-this-is-live` (the acknowledgement), mirroring `cli.py`'s two-part structure — the `smoke` subcommand selects the mode and the flag acknowledges it — and its `REFUSED` path and exit code 2. A single flag doing both jobs would make the refusal path unreachable, which is what the original one-flag wording accidentally specified.
3. **No test may perform a live network call.** Trial scripts and their tests construct clients through `SportmonksClient.offline(transport=…)` with a fake transport. The transport's own tests may construct `RequestsTransport` with an injected fake session — that never reaches the network, and those tests are what prove the transport is safe to use live in FI-9.
4. Rule 3 is **enforced structurally, not by convention**: an autouse fixture in `packages/sportmonks-client/tests/conftest.py` patches **every HTTP entry point the package's dependencies expose** to raise — currently `requests.Session.request` and `requests.adapters.HTTPAdapter.send`, `requests` being the package's only HTTP dependency. If an HTTP client is ever added to `requirements.txt`, its entry point joins the guard **in the same change**. A test that reaches the network boundary fails loudly rather than silently succeeding. This is the seam shape the FI-7f reviewer flagged as absent from that slice — adequately covered there by absence-of-import, but FI-8 is the code that will genuinely make live calls, so the real guard is built here.

   **Why the boundary and not `RequestsTransport`** — this rule previously read *"No test may construct `RequestsTransport`"*, with a guard patching that constructor. Measured against the suite, that guard produced **18 failed / 49 passed**: `tests/test_config_transport.py` constructs `RequestsTransport` **12 times** (lines 57, 66, 81, 90, 99, 115, 118, 128, 156, 181, 205, 228), always with a `MagicMock()` session, to prove redirect disabling, the streaming size cap, secret-safe error wrapping, and token redaction. One of the 18 failures was `test_contract_boundaries.py::test_live_smoke_opt_in_without_token_fails_without_network` — **the guard broke the test that proves the property the guard exists to enforce.** The boundary guard passes all **67**. `RequestsTransport` is a wrapper, not the boundary: `transport.py:28` is `self._session = session or requests.Session()` and the call is at line 34. Patching `requests.Session.request` therefore catches a live call made through *any* path, including one that bypasses `RequestsTransport` entirely — which the old grep would have missed. **This revision reads as a relaxation and is not one**; it was measured before it was made.
5. Payload-shape mismatches discovered in FI-9 are **plan-revision requests**, fixed only inside `sportmonks-client` (§17). Open trial questions must not be answered by assumption in code — §15: *stop and request plan revision*.

#### Frozen contract (defined in S2, consumed unchanged by S3–S6)

Every `trial_*.py` is a thin script over `_trial_common.py`. S2 freezes:

- **Invocation** — `python scripts/trial_<name>.py [--mock | --live] [--i-understand-this-is-live] [--out DIR]`. `--mock` is the default and `--mock`/`--live` are mutually exclusive. **`--live` is the mode selector and `--i-understand-this-is-live` is the acknowledgement** — two flags, not one, because S2 DoD 2 requires a *live-mode invocation without the acknowledgement* to be reachable and testable. With a single flag acting as both, the `REFUSED` path could never be exercised.
- **Exit codes** — `0` every claimed objective observed; `1` an objective is unmet or degraded; `2` refused (live requested without the acknowledgement flag); `3` configuration/auth failure.
- **Raw snapshots** — written via the existing `snapshot_hook` / `RawResponseSnapshot` seam. No new snapshot writer is introduced.
- **Artifact locations** — split by artifact *type*, not by mode, because the mode changes and the code path does not:
  - `packages/sportmonks-client/trial-output/` — **gitignored entirely.** The `--out` default. Every run and **every raw snapshot** lands here, in both `--mock` and live mode.
  - `packages/sportmonks-client/trial-reports/examples/` — **committed.** One frozen mock report per script.

  Raw snapshots are gitignored **unconditionally**. The same `snapshot_hook` writes them in `--mock` and live, so a slice that commits mock payloads because they are harmless makes FI-9 commit **real provider payloads by default, into a public repo, before licensing question 3 ("Does the Starter Football API license permit storing raw API data internally?") has been answered** — and that question is not answered until trial day 1. Question 7's restrictions on exposing raw fields and provider identifiers apply on top. Committing raw payloads now would answer an open licensing question by accident, in the most public way available. The ignore rule is therefore added in **S2, the same slice that creates the writer** — before the thing it guards exists, not after.

  The committed examples exist because `TRIAL_STATUS.md` requires an evidence pointer per objective and states that an objective with a status but no pointer *"is not observed; it is asserted"*. With every artifact ignored, every pre-trial evidence pointer would dangle and standing DoD item 2 would be unverifiable without re-running.
- **Deterministic mock output** — mock mode uses a fixed clock, so re-running regenerates byte-identical reports and the committed examples do not churn. This is what makes committing them viable at all; it is the same property pinned by FI-7f's byte-stability test.
- **Normalization** — calls the existing FI-4a offline normalizers in `football_intelligence.ingestion`. **FI-8 adds no normalizer and changes none.**
- **Report** — one machine-readable JSON plus one human-readable Markdown per script, with a fixed schema: `script`, `mode`, `objectives[]` (each `id`, `title`, `status ∈ {observed, unmet, degraded, not_applicable}`, `evidence`), `observed_shapes[]`, `warnings[]`.
- **Shape reporting over shape assertion** — reports record the shape actually found. A script must not fail merely because a payload differs from the documented shape; it records the difference and marks the objective `degraded`.

#### Standing DoD — applies to every slice S1–S6

Each of these is a command with a checkable result, not an intention:

> **Running these locally on Windows: pass `--basetemp`.**
> ```
> python -m pytest --basetemp=<a writable dir>   # plus PYTHONIOENCODING=utf-8
> ```
> Without it, every `tmp_path` test errors with `PermissionError: [WinError 5]` on
> `%LOCALAPPDATA%\Temp\pytest-of-<user>` — 54 errors in `fpl-grounded-assistant`,
> 22 in `sportmonks-client`. Those errors were treated as an environmental fact of
> the machine for most of FI-7 and FI-8, and every count in this document was
> therefore verified through a CI round-trip. They are fixable with this one flag.
> **A test that errors cannot falsify anything**, so a seeding probe or
> falsification matrix run without it silently over-reports survivors. With the
> flag, local runs are authoritative: `fpl-grounded-assistant` → 593 passed / 0
> errors, `sportmonks-client` → its full count / 0 errors.

1. `cd packages/sportmonks-client && python -m pytest` exits 0, with a test count **≥ the previous slice's** count (the S0 baseline is 67).
2. Every `trial_*.py` added by the slice runs `--mock` end-to-end, exits 0, and writes both report artifacts.
3. The autouse guard in `tests/conftest.py` patches every HTTP entry point the package's dependencies expose (frozen-contract rule 4) to raise, and a test proves it fires by attempting a real `requests.Session().request(...)`. Before S2 creates the guard, the slice must instead show that no new live-capable call path was added. **Do not substitute a `grep` for `RequestsTransport`** — that target is a wrapper, not the boundary, and greping it both misses bypass paths and flags the 12 legitimate constructions in `tests/test_config_transport.py`.
4. Required check **`Package test suites`** green.
5. Required check **`Contract and fixture drift check`** green.
6. Appendix A's FI-8 row updated with the slice and its test evidence.
7. No file outside `packages/sportmonks-client/`, `.github/workflows/package-test-suites.yml`, and this plan document is modified, except where a slice below explicitly says otherwise (only S6 does, and only to *read*).
8. Every artifact the slice creates or modifies is internally self-consistent: no table contradicts its own legend, no prose contradicts its own table, and no identifier appears in more than one spelling. Where a slice defines or consumes a vocabulary, schema, or enum, every use of it within the slice matches that definition exactly. Where the definition lives outside the slice, verify the spelling against its source repo-wide, not only within the slice — an identifier can be perfectly consistent inside a slice and still be wrong everywhere it appears.
9. `git ls-files packages/sportmonks-client/trial-output/` returns nothing, and no raw snapshot payload is tracked anywhere. The ignore rule is added in the same slice that creates the writer.
10. Every objective's `status` and `evidence`, and every `observed_shapes[]` entry, is derived from the response actually received — never a literal. Each is covered by a test that removes or blanks the underlying data and asserts the objective degrades and the shape entry disappears. Where an entry's **existence is itself the observation** (an outcome that must be reported even when the thing was absent), test instead that its **content changes with the input** — and **state in the slice which of the two applies to each entry**. **A shape entry appended unconditionally, with no declared reason and no content test, is an assertion wearing an observation's name.**
11. **Every derived value is proven derived by the two-input equality test below.** Item 10 says *what* must be derived; this says what counts as proof. Applies to every `evidence` string and every `observed_shapes[]` entry, under either branch of item 10. **The per-entry declaration item 10 requires must name the test supplying each entry's item-11 proof** — so an entry with no such test is visible as a gap in the declaration rather than silently absent, and the same set-equality check covers both obligations.

12. **A slice's failure paths are asserted as whole objective tuples, by `==`.** Every path that writes a report without observing anything — token absent, token rejected, provider refused — is asserted on `(id, status, evidence)` for **every** objective the script owns, not on the exit code. An exit code is one integer shared by every reason that produces it; asserting it proves the run failed, not that it reported *why*. S3's first draft asserted exit codes only, and a sweep found the consequence: `status` and `evidence` in the failure-path builder could both be replaced with plausible literals and every test stayed green — **six survivors, one omission, three constructs**. The exemplar already carried the right form (`test_the_two_unmet_reasons_are_not_interchangeable`); it was not carried across, which is why it is written here rather than left to be rediscovered per slice.

13. **Catch the narrow exception. A broad catch that spans credential errors converts an auth failure into a data observation.** `SportmonksConfigurationError` and `SportmonksAuthenticationError` both subclass `SportmonksError`, so any `except SportmonksError` wrapped around a per-item call swallows them. Measured in S3: a 401 on the first call made `trial_entities` exit **1** with the family reported `unavailable`, where the frozen contract requires exit **3**. With every family answering 401 the report would have read *"15 families unavailable"* — which on trial day 1 is read as *the Starter plan does not carry these endpoints*, the exact question that script exists to answer. **A rejected token must never be able to masquerade as a missing endpoint**, and every slice that converts per-item errors into per-item observations re-raises the two before its broad catch, pinned by a test driving a real 401 through the client's status handling.

**The declaration is machine-checked, not prose-checked.** Every declared entry name must appear as an emitted `ObservedShape` name in the same slice, and every emitted name must carry a declaration. **A test asserts the two sets are equal.** This exists because the clause's *first* use — written by the same person who added the clause — declared `team_stat_fields` and `player_stat_fields` while the script emitted `team_statistics_fields` and `player_statistics_fields`: two identifiers present nowhere in the repository, in a commitment whose entire purpose is being checkable against the entry. That is a string mismatch, and string mismatches do not need a reviewer. A declaration nobody can match to an entry is worse than none, because it reads as a commitment while committing to nothing.

The declaration clause is the load-bearing half. "Existence is the observation" is a legitimate reading — S3's per-family sweep must report `unavailable` as an outcome, so an entry that vanished on absence could not report it — but it is also exactly the shape a rationalisation takes when reached for after the fact. Requiring the author to declare per entry which obligation they are under makes the choice a commitment made in advance rather than a defence assembled in review. The review that produced this wording accepted the argument on its merits **and then held the slice to the obligation that reading creates**: entries that never disappear must have tests proving their content moves, and that slice had them for 3 of 15.

**A content test uses more than one input, expects different outputs, and asserts equality.** Wherever item 10 requires proof that an entry's content is derived, the proof is: **at least two inputs, pairwise-distinct expected values, asserted with `==` rather than containment** — and the distinctness itself asserted, so the parametrization cannot silently collapse into repetition. One input plus a substring check proves only that the entry *exists*; every literal containing that substring passes it, which is the defect it was written to exclude.

This clause is item 10's missing verb, and it was missing from the **frozen exemplar**. `trial_auth.py`'s `rejected_envelope` test — the reference four slices read and copied — fed one payload and asserted a substring of it. Replacing the derivation with the literal `"data[],pagination{current_page,has_more}"` left all 107 tests green. That entry is the highest-stakes fact in the phase: §17's top risk is *"docs != live payloads"*, and this is the entry that reports the payload the parser refused. So the recurrence rate read all phase as *"the implementer keeps repeating the mistake"* was substantially **the template teaching it** — S2 was rejected twice for this class on `envelope.meta.pagination`, S5 three times, and the exemplar all of them were reading had it throughout. Fixing instances at the copy sites while the template keeps re-emitting them is not convergence. Retrofitting the pattern also found a second defect the single-payload test could not: `render_skeleton` truncated below the second level, so a provider carrying pagination under `meta` was reported as `meta{pagination}` — the field names, which are the entire observation, silently dropped.

**A probe built from the author's own site list inherits the author's own sweep.** After the first remediation, the author's probe reported 0 survivors of 11 sites and the slice looked done. A re-review scoped *only* to enumeration completeness — explicitly forbidden from re-deriving falsifiability, handed the probe output as evidence — independently enumerated the file and found **12 sites the probe never listed**. One of them, the `pagination` entry's **location**, still held a literal: replacing `envelope.{page_location}` with `envelope.pagination` left all 122 green. That is precisely the defect S2 was rejected for twice, alive in the entry it was found in, because the only `meta.pagination` test exercised `observed_pagination` at unit level and never reached the f-string that builds the entry. Three `evidence` sub-fields and the two `_unmet_report` reasons were literal-survivable for the same reason.

So the enumeration is the weak point, not the seeding — and it is mechanical, which means it should not be a person's job. **[#93](https://github.com/darutto/FPL-Platform/issues/93) makes the probe a script with `--sites auto` and a required check, and blocks S3 until the already-merged slices have been swept by it.** Every mitigation this phase has produced until now has been a *rule*, and a rule about sweeping is a thing someone has to remember to apply. The evidence below rules that class out.

**And then the fix repeated the error it was written about.** The first version of that change closed `rejected_envelope` and left the four sibling entries one to three lines below it: `rate_limit_headers` proven by a single all-or-nothing input, `retry_after` by containment, objective 17's `evidence` never asserted with `==` at all, and `_degraded_report` — S2's own third correction — reached by **no test**, its entire body replaceable with `raise AssertionError` against a green suite. An independent seeding probe measured **4 of 6 construction sites surviving** and rejected it. So the sweep discipline the phase keeps failing is not a property of who writes the slice: the author of the rule, in the commit introducing the rule, in a file of 218 lines, applied it to one site. **What caught it every time is the probe, not the reading** — which is why item 11 is a required test rather than a review habit, and why the probe needs a no-op negative control: an early run of it scored every seed as "killed" because the runs were erroring, not failing. A probe that cannot pass cannot measure.

Item 10 exists because the principle was already in the frozen contract — *"shape reporting over shape assertion"* — and in `TRIAL_STATUS.md` — *"an objective with a status but no pointer is not observed; it is asserted"* — and **nothing executed either of them**. S2's first version reported `"rate-limit headers observed"` and a `rate_limit_headers` shape entry from hardcoded strings; deleting every header from the payload left the report byte-identical and still exiting 0. Two reviewers checked the schema's shape, its byte-stability, its example match, and its status enum, and neither asked whether the fields were derived from anything. The defect was found by an independent verifier **running** the experiment — strip the headers, observe nothing change — not by reading the code. Item 10 turns that experiment into a required test per objective, so S3–S6 cannot inherit the pattern even by copying the worked example.

Item 8 exists because of a measured gap, not a hypothetical one. S1 was reviewed by an independent verifier supplied with the plan section, the pinned suite counts, the invariants, and the slice under review. It returned APPROVE and found three real defects — and it did not find a fourth: a status table contradicting its own legend and its own explanatory note. Nothing in the criteria asked whether the artifact agreed with itself, so nothing checked it. Item 8 lives here rather than in the invocation precisely so it reaches the verifier automatically: the plan section is a supplied parameter, whereas an invocation clause is something a caller retypes correctly six times or does not. This matters most at **S2**, which freezes the report schema, the exit-code convention, and the transport guard — a frozen contract that contradicts itself is worse than no contract, because every later slice inherits the contradiction and each has a reason to resolve it differently.

#### Sweeping the already-merged slices — triage rule, pre-registered

The falsifiability probe ([#93](https://github.com/darutto/FPL-Platform/issues/93)) is about to be run against merged, approved code, and `_degraded_report` — unfalsifiable from the day the correction that created it landed, through an approval — says to expect survivors. **This rule is written before the sweep runs.** Choosing a threshold after seeing the count is choosing it to fit the result, and the S5 experience says the risk is not finding defects but the remediation loop that follows.

**Survivors in merged slices are triaged, not immediately fixed.** Each is recorded with its site and verdict, then classified:

| classification | disposition |
|---|---|
| the value is derived and the mechanical seed was implausible | exempt, **declared** with the reason |
| the value is a literal that should be derived | **fix** |
| the value is a literal and correct (an identifier, a constant) | exempt, **declared** with the reason |

Fixes land as **one PR per slice**, not one per finding — the sibling-sweep failure recurs specifically when findings are addressed one at a time.

**Rewrite threshold: more than 3 in-scope survivors in a slice, and that slice's tests are rewritten rather than patched** — the S5 stopping rule, applied to already-merged code. Three is the point at which the failures stop being independent: one or two are oversights at specific sites, but a slice carrying more than that has a test *design* that does not falsify, and patching site-by-site is the loop that consumed three passes of S5 without converging.

**Known property of the threshold, recorded before it is used.** Three is an absolute count applied to slices of very different size. Three survivors in `trial_auth.py` (22 sites) is a ~14% miss rate; three in a five-site script is 60% and means something much worse. The absolute figure is the right *floor* — it must still fire on the small script — but it will be lenient on the large ones exactly where a rate would be strict. This is noted rather than fixed: the threshold was chosen blind, before any sweep ran, and adjusting it now on reasoning alone would forfeit what choosing it blind bought. The moment to revisit is a sweep where the count and the rate disagree, with that data in hand.

Three is also the number the only available evidence supports: S5's three review passes returned 3, 6, and 4 substantive findings, so it is where observed non-convergence actually began rather than a round number.

The threshold counts **in-scope** survivors only. Exempt roles are printed but do not count, and an exemption invented during triage to duck the threshold is the failure this rule exists to prevent — which is why exemptions are declared with reasons and the exemption list itself is pinned by test.

#### The CI flip mode — an open environmental hazard, not a closed incident

The falsifiability probe returned different verdicts for identical seeds on identical code. Four pre-registered arms:

| arm | SHA | detector | env var | when | flips |
|---|---|---|---|---|---|
| A | `69b00ee` | off | off | earlier | **4/20** |
| B | `8a8e017` | on | on | later | 0/21 |
| C | experiment | off | on | later | 0/20 |
| D | `69b00ee` | off | off | **now** | **0/20** |

Arm D is byte-identical to arm A. **The mode was real** — 4/20, and 3 of those were false in-scope survivors that would have failed good code. **Its cause is external and unknown** — neither `PYTHONDONTWRITEBYTECODE` nor the seed-reaches-child detector fixed it, both proposed mechanisms (stale bytecode, a write-visibility race) were falsified by direct measurement, and arm D shows the mode stopped occurring at the *unchanged* commit. **The gate's current stability was inherited, not earned** — 61 consecutive clean runs say the mode is dormant, not that it is gone, and it can return without warning.

Survivor re-run confirmation is therefore a **recurrence detector**, not a fix: a survivor that does not reproduce is printed and counted as residual noise, never silently retried. Retrying in silence would stop the gate reporting its own failure rate, which is the one number that matters for a hazard nobody controls.

**The phase's actual finding, and the least expected one: the code being swept has been in better shape than the things doing the sweeping, consistently.** Three of five high-confidence claims failed on instruments — the live-call guard's outer layer, the probe's own enumeration, and the detector, which was broken while both its author and its reviewer argued to keep it on a mechanism that turned out impossible. The trial scripts themselves have needed one rewrite in total, caught mechanically, inside the pre-registered threshold. A reader will assume the risk lived in the domain code. It did not. **A cause that fits the data and cannot work is a coincidence with good manners.**

#### The probe is frozen at #109/#114 — improvements are filed, not built

**Probe work stops here.** Further improvements go on [#93](https://github.com/darutto/FPL-Platform/issues/93) as filed items; none is built until the remaining slices are written. #93 is kept **open** for exactly this reason — a freeze whose destination is a closed issue has no destination.

The reason is a measurement, not a preference. Roughly forty turns went into the instrument — enumeration, the AST allowlist, the lock, the clean-tree precondition at both ends, the stale-bytecode detector, four pre-registered flip-mode arms — and the durable result is **one line**: the mode was real, its cause is external and unknown, and the gate's stability is inherited. Everything else either fixed an instrument defect that the instrument itself introduced, or falsified a mechanism nobody can now act on. Over the same period five slices went unwritten against a fourteen-day trial clock that does not extend.

This is the same trade the phase has been getting wrong in one direction, and worth naming plainly because the conclusion will outlive the investigation that produced it: **the instruments have been in worse shape than the code they measure, and the correct response to that is not more instrument.** The probe as it stands catches what it was built to catch. It has an open environmental hazard against it that more probe work has already failed twice to close.

**What still applies:** the gate stays required, survivor re-run confirmation stays on as a recurrence detector, and a survivor that does not reproduce is printed and counted rather than silently retried. **What does not:** building anything new into `falsifiability_probe.py` before the slices are done.

#### Instruments that answer the adjacent question — a class, for S3–S6

Three failures this phase share one shape: **a confident, well-formed answer to a question next to the one being asked.** They are cheap to write and read as coverage, so name them before the remaining slices reach for them.

| instrument | question asked | question answered |
|---|---|---|
| `grep`ping source for `"checkout"` | does this code *use* git? | does this file *mention* git? |
| `git check-ignore -v`'s citation | is this path ignored *by our rule*? | does some rule match, at some line, in whatever tree you are on? |
| `git status --ignored` | is the rule present? | does an ignored path *currently exist on disk*? |
| a regex over CI logs for test IDs | which tests ran? | which test IDs contain no spaces? |
| `read_text` comparison | are these files byte-identical? | are they identical after universal-newline translation? |
| an outcome assertion over redundant layers | is *this* layer working? | is *some* layer working? |
| `inspect.getsource` | is the seeded code what actually *runs*? | what does the `.py` on disk *say*? |

The `inspect.getsource` entry is the sharpest of these and the one anyone would reach for: to check that a seed took effect, read the module's source. It re-reads the `.py` from disk, so it reports the seed **while stale bytecode executes** — a detector that returns success exactly when the bug it is looking for is active. The working form interrogates the compiled artifact: `spec.loader.get_code(...)`, which honours the bytecode cache, then searches `co_consts` for the literal the seed introduced. Measured cost of not having it: 3 false in-scope survivors in 20 CI runs, each a fully green suite with the seed genuinely on disk.

The regex one nearly cost a day: extracting test IDs with `[^ ]+` silently dropped every parametrized case whose id contains a space, reporting 170 where 181 ran. An 11-test gap between platforms is exactly the evidence that would have justified a "Windows is the lenient environment" investigation — one the direct set comparison had already ruled out. **A measurement that under-reports produces the most convincing kind of wrong answer: one that confirms a plausible prior.**

**Grepping source is the one to watch**, because it is the most tempting shortcut and diverges from behaviour on every comment, docstring, string literal, and dead branch. It failed here on a docstring that *explained why not to use `git checkout`* — the prose describing the prohibition tripped the check enforcing it. **Assert on what executes**: parse the AST and inspect the nodes that run, as `test_the_probe_never_shells_out_to_git_to_restore` does.

The general rule: when an instrument's output is a *proxy* for the property, state what the proxy can and cannot distinguish, and prefer the instrument whose two outcomes are different tokens over one whose two outcomes differ by a field you have to read correctly.

#### Redundant layers require an isolation test per layer

**Any defence in depth whose layers share an observable outcome will read as fully covered while only the innermost layer is actually tested.** The outer layers can be deleted silently: the test asserts *that* the call was refused, and the layer beneath refuses it identically.

The failure is silent **in the safest-looking direction**, which is why it survives review. Nothing is broken while the redundancy holds — the call really is caught — so there is no failing test, no wrong output, and no smell to notice. What is lost is the property the redundancy was built for: that any one layer suffices. Reviewers read the outcome test, see the guarded outcome, and approve.

Measured here, on the phase's hardest constraint. The step-4 subject-deletion sweep over all merged code returned exactly one survivor: `monkeypatch.setattr(requests.Session, "request", _refuse)` in `packages/sportmonks-client/tests/conftest.py`. Deleting it left **182 of 182 green**, including `test_the_guard_fires_on_a_real_session_request` — the test written to prove that patch works. `Session.request` fell through to the still-patched `HTTPAdapter.send`, which raises the same `AssertionError` with the same message. Every hand review of S2 approved it, including the ones that were specifically looking for this class. The mechanical sweep found it on the first pass — the strongest argument available that **enumeration should never have been a person's job**.

The remedy is a subject deletion built as a test, not an approximation of one:

- **Not** asserting a patch count, or that a named attribute is the guard's callable. That is the grep-the-source family one step removed — it checks that the code says what you think it says.
- **Instead**, per layer: hand that layer's real implementation back inside the test, then exercise the entry point the *other* layer guards, and assert the refusal still happens. The real callables are captured at module import, before any autouse fixture runs.

Two such tests now stand beside the outcome tests. Deleting either patch from `conftest.py` fails the isolation test naming that layer:

| seed | result |
|---|---|
| negative control (no-op) | `184 passed` |
| delete the `Session.request` layer | `1 failed` — `test_the_session_layer_refuses_on_its_own_with_the_adapter_layer_stood_down` |
| delete the `HTTPAdapter.send` layer | `2 failed` — the isolation test for that layer, plus the pre-existing outcome test |

This buys a property the sweep alone could not produce: previously one layer was known to be load-bearing and the other was unfalsifiable; now **each is known to catch the call alone**. The outcome tests are kept — they assert the boundary is guarded *at all*, which is a different claim.

For S3–S6: wherever a slice guards something twice, the second layer is unverified until a test stands each one up by itself. All such tests aim at `127.0.0.1:1`, so the failure mode when a layer is genuinely absent is a refused local connection and never a provider call.

**Sufficiency is not coverage, and coverage is a standing condition.** The isolation tests prove each layer catches the call alone. They say nothing about whether the two layers cover the *surface* — that holds only while `requests` is the package's sole route out. It is today: `transport.py:8` is the one import, and an AST enumeration of `sportmonks_client/`, `scripts/`, and `tests/` finds exactly two third-party roots (`requests`, `pytest`) and **no** network-capable stdlib module. But that is a fact about today's dependency list, and the day someone adds `httpx` the guard becomes incomplete — a discovery that would otherwise be made by a live call during FI-9.

So the condition is **pinned rather than remembered**, and pinned as an **allowlist**: the set of third-party imports must equal `{requests, pytest}`, so a client nobody thought of fails it too. A denylist only catches the libraries whose names the author could enumerate — the same enumeration-by-memory this phase has now measured failing four times. Stdlib routes are matched on the full dotted name, so `urllib.parse` (string handling) does not read as a violation while `urllib.request` does. Growth in the allowlist is an edit that must arrive with the conftest guard extended to the new library's entry points, or with an argument for why it cannot reach the network.

The pin's own vacuity is closed too: an enumerator that scanned nothing would satisfy both assertions, so a third test names the file the guard's premise rests on. Seeded — `import yaml` into `client.py`, `import socket` into `trial_auth.py`, and a gutted enumerator — each kills, the last killing all three tests.

#### A control that runs once cannot certify a property that varies per item

The probe's negative control establishes that the harness works — measured at the start of a sweep, on one seed. S3's run showed the limit of that. The control survived, twenty-two seeds scored normally, and the twenty-third aborted with 74 **errors**. The cause was not the seed: the label was 95 characters, and `--basetemp-root` plus label plus pytest's per-test directory came to **288 characters** against Windows' 260-character path limit. Reproduced with no seed applied at all — the unseeded suite at that path returns `5 failed, 151 passed, 74 errors`.

Harness validity was not a constant the control could establish once; it was **a function of each seed's own label**. The control certified the harness for the paths it happened to exercise, and every claim beyond that was extrapolation.

Note how narrowly the sweep escaped a false result. The rule "score kills only from runs that FAILED" was necessary and **not sufficient**: this broken harness produced five genuine-looking failures. What saved it was the second rule — **errored runs are INVALID, never kills**. Had the long path produced failures without errors, five would have been scored as kills and the slice would have reported stronger falsifiability than it had.

Two consequences, both instances of the same correction the control itself embodies — *check the thing that varies, not a representative of it*:

- The probe should measure headroom for the **longest label it is about to generate**, before the first run, rather than validating the root once and assuming every derived path is usable. Tracked against [#93](https://github.com/darutto/FPL-Platform/issues/93).
- "Validated once at the start" belongs beside the adjacent-question table as a class of its own: a control establishing a property at *t=0* says nothing about a property that is per-item.

#### What each seeding layer is allowed to certify

Not a caveat — a division of labour, and it says what may be claimed from a green run.

- **Mechanical seeding certifies the enumeration.** Its guarantee is that *no site was skipped*, which is precisely the class that has actually shipped in this phase: four times, including inside the probe itself, where a uniqueness check written as a guard was working as a filter that silently discarded five of twelve sites.
- **Semantic seeding certifies the derivation.** `{len(retry_afters)}` being satisfiable by `1 if retry_afters else 0` is a hypothesis about *meaning*, and nothing mechanical will generate it. Those seeds stay hand-written.

What the probe buys is that the hand-written semantic seeds now go on top of a **complete** list instead of the author's list. A green probe run is not a claim that every value is genuinely derived; it is a claim that every value was tested for it.

#### Slices

##### S0 — put the package under CI *(no FI-8 code)*

- **Files modified:** `.github/workflows/package-test-suites.yml` only.
- **Why first:** FI-8 adds 12 files to a package **no CI job currently watches**. That is the exact shape that left `fpl-tool-contract` at 39 silent failures and `fpl-tool-runner` dead at collection (see that workflow's own header comment). Capturing the 67-passed baseline now keeps any future deviation attributable to FI-8 rather than to drift.
- **Change:** add a fifth step, `sportmonks-client suite`, guarded by `if: ${{ !cancelled() }}`, `working-directory: packages/sportmonks-client`, `run: python -m pytest -v` — matching the existing four steps exactly. The job **name stays `Package test suites`**; renaming it would silently un-require the branch-protection check.
- **DoD (verifiable):**
  1. The workflow's fifth step appears in a completed run's log with `67 passed`.
  2. The job name string is unchanged: `grep -c "name: Package test suites"` → 1.
  3. No `paths:` filter is added, and **no `PYTHONPATH` env var** — the step must consume `packages/sportmonks-client/pytest.ini`'s `pythonpath = .`, which is what it exists to protect.
  4. No change to the `Install dependencies` step: `requirements.txt` is `requests>=2.31`, already satisfied by the pinned `requests==2.32.5`. If CI shows otherwise, **stop** — do not add a second install line without recording why.
  5. The 67-passed figure is written into Appendix A as the pre-FI-8 baseline.
- **Objectives covered:** none. This is infrastructure.
- **Non-goals:** no `scripts/` directory, no test, no fixture, no change to the four existing steps, no branch-protection change (the check is already required).

##### S1 — trial documentation *(prose only, zero code)*

- **Files new:** `packages/sportmonks-client/TRIAL_STATUS.md` (template), `packages/sportmonks-client/TRIAL_LICENSING_CHECKLIST.md`, `packages/sportmonks-client/TRIAL_GO_NO_GO.md`.
- **Why before the scripts:** these documents define *what every later script must report*. Writing them first means S2's report schema is built against a known output contract instead of retrofitted. They are also zero-risk and needed on trial day 1 regardless of script progress.
- **DoD (verifiable):**
  1. `TRIAL_STATUS.md` contains all **20** brief §11.3 objectives verbatim as a checklist, numbered 1–20, each with a status cell and an evidence-pointer cell.
  2. `TRIAL_LICENSING_CHECKLIST.md` contains all **14** §14.3 questions — the 12 from brief §11.5 plus the two audit-derived additions (grid-coordinate semantics; actual trial vs Starter rate limit) — each with a `sent / answered / answer` field.
  3. `TRIAL_GO_NO_GO.md` reproduces §14.4 exactly: six GO criteria (a)–(f), three NO-GO conditions, and the lineups-only partial fallback, with the decision recorded in `TRIAL_STATUS.md`.
  4. Every objective in `TRIAL_STATUS.md` names the `trial_*.py` that will report it, per the S3–S6 mapping below. Any objective with no owning script is a blocker.
- **Objectives covered:** **20** (raw-data storage and derived-data licensing) — answered by document, not by script.
- **Non-goals:** no code, no `scripts/` directory, no answers invented for the 14 licensing questions (they are for Sportmonks to answer on day 1).

##### S2 — harness + `trial_auth.py` + the structural live-call guard

- **Files new:** `packages/sportmonks-client/scripts/_trial_common.py`, `packages/sportmonks-client/scripts/trial_auth.py`, `packages/sportmonks-client/tests/test_trial_harness.py`.
- **Files modified:** `packages/sportmonks-client/tests/conftest.py` (autouse guard).
- **DoD (verifiable):**
  1. The autouse fixture patches every HTTP entry point per frozen-contract rule 4. **The seeded violation attempts a real `requests.Session().request(...)`** — not a `RequestsTransport` construction — so the proof matches what is actually guarded. Seed it, observe the failure, remove the seed; the same propagation proof used for the FI-2 CI pin. The **67 pre-existing tests must all still pass** with the guard installed and no seed — the guard introduces no failures. The slice's total count will exceed 67 because S2 adds `test_trial_harness.py`; standing DoD 1 governs the total.
  2. A test asserts the script runs in mock mode by default, and that a live-mode invocation **without** the acknowledgement flag returns **2** and prints a `REFUSED:` line, mirroring `cli.py:17`.
  3. **Token absent:** with `SPORTMONKS_API_TOKEN` unset, a live-mode invocation degrades cleanly through `SportmonksConfigurationError` and exits **3** — never a traceback, never a partial fetch.
  4. **Dummy token:** with a dummy token and a fake transport returning 401, the auth-failure path surfaces `SportmonksAuthenticationError` and exits **3**, and the report contains no token substring (`assert token not in report_text`). Items 3 and 4 together tick §14.1's token-wiring box.
  5. Pagination and rate-limit-header observation are exercised against `multi_page.json` and synthetic `Retry-After` headers, and reported.
  6. The report schema above is emitted and pinned by a test, so S3–S6 inherit a frozen shape. The pinned `status` set is **exactly the four** at the frozen contract above (`observed`, `unmet`, `degraded`, `not_applicable`); `not_started` is a `TRIAL_STATUS.md` dashboard value and must not enter the schema. S1's review caught precisely this over-claim in prose — S2 is where it would become permanent.
  7. **`.gitignore` covers `trial-output/`, added in this slice.** `git ls-files packages/sportmonks-client/trial-output/` returns nothing after a `--mock` run that wrote there. This lands with the writer, not after it.
  8. **`--out` defaults to `trial-output/`.** Whatever default `_trial_common.py` picks is the one S3–S6 inherit without re-reading, so it is part of the freeze.
  9. **Mock output is byte-stable.** A test runs a script twice under `--mock` and asserts identical bytes, and asserts the committed `trial-reports/examples/` copy matches. Without a fixed clock the committed examples churn on every run and stop being evidence.
- **Objectives covered:** **17** (API rate limits and pagination).
- **Non-goals:** no endpoint-family script beyond `trial_auth`; no normalizer; no identity-registry access; no change to `client.py`, `transport.py`, `config.py`, or `models.py` — S2 consumes the FI-3/FI-4a seams as they are. If a seam proves insufficient, **stop and request a plan revision** rather than widening it.

##### S3 — discovery: competitions, seasons, fixtures

- **Files new:** `scripts/trial_entities.py`, `scripts/trial_fixtures.py`, `tests/test_trial_discovery.py`.
- **DoD (verifiable):**
  1. `trial_entities.py` sweeps all 15 `ENDPOINTS` families against mock payloads and reports, per family: reachable / empty / unavailable, record count, and the `provider_id` set observed.
  2. `trial_fixtures.py` reports PL fixtures for a season and, separately, cross-competition fixtures for PL clubs — the two are distinguished in the report, since objectives 2 and 3 are distinct.
  3. Both exit 0 on mocks and exit 1 when a mock is swapped for an empty-result fixture from `edge_cases.json`, proving the unmet path is real rather than decorative.
  4. `TRIAL_STATUS.md` objectives 1–3 point at these scripts.
- **Objectives covered:** **1** (competition and season identifiers), **2** (Premier League fixtures), **3** (cross-competition fixtures).
- **Non-goals:** no squad, lineup, injury, stat, or identity work; no new family added to `ENDPOINTS`.

##### S4 — split into S4a and S4b before implementation

The original S4 was one slice covering seven objectives across two scripts, and it is **the slice the go/no-go actually depends on**. It is split because slice size, not model choice, is what predicted convergence in this phase:

| Slice | Scripts | Objectives | Passes to green |
|---|---|---|---|
| S0 | 0 | — | 1 |
| S1 | 0 (docs) | 1 | 2 |
| S2 | 2 | 1 | **4** |
| S3 | 2 | 3 | rejected, restarting |
| S5 | 2 | 6 | **3+** |
| S4 (as one slice) | 2 | **7** | — |

S4 would have been the largest slice in the phase *and* the only one with genuine design ambiguity — undocumented grid semantics (§14.3 q13), plus the 7/8/9 separation that GO criterion (b) hinges on. Small slices here converged fast and large ones did not, regardless of who wrote them. Splitting before starting is cheaper than discovering it in a fourth remediation of the slice that decides the subscription.

##### S4a — squads

- **Files new:** `scripts/trial_squads.py`, `tests/test_trial_squads.py`.
- **DoD (verifiable):**
  1. Squad and player-record completeness is reported as **counts with named missing fields, not a boolean**. A test supplies records where a field is present on some but not all, and asserts the exact `k/n` with `k ∉ {0, n}` — a count satisfiable only by `0/n` or `n/n` is satisfiable by a literal.
  2. Objectives 4 and 5 are **separately statused**: a complete squad list with impoverished player records must degrade 5 while leaving 4 observed.
- **Objectives covered:** **4** (team and squad completeness), **5** (current player records).
- **Non-goals:** no lineup, formation, grid, position, or substitution work — that is S4b. No `football-intelligence` module change.

##### S4b — lineups, formations, grid *(the highest-risk slice in FI-8)*

- **Files new:** `scripts/trial_lineups.py`, `tests/test_trial_lineups.py`, plus **new fixture entries** in `tests/fixtures/edge_cases.json`.
- **Why this slice carries the risk:** §14.4's GO criterion (b) and its *"M2 collapses to detailed_position only"* NO-GO both hinge on formation-grid semantics — and §14.3 question 13 exists precisely because those semantics are **undocumented**. Mock fixtures can prove the script runs; they cannot tell us whether the real grid means slot indices or pitch coordinates.
- **DoD (verifiable):**
  1. `trial_lineups.py` **reports the grid shape it finds rather than asserting an expected one.** A test feeds a payload whose grid field differs from the documented shape and asserts the script exits 1 with the objective marked `degraded` and the observed shape recorded — **not** a crash and **not** a silent pass.
  2. `edge_cases.json` gains **at least three** deliberately unexpected formation-grid fixtures: wrong type (string where a list is documented), unexpected nesting (list-of-lists), and the field missing entirely. Fixtures derived from documentation can only rehearse the documented case; a rehearsal covering only the expected input is not a rehearsal of the risk.
  3. The report distinguishes objectives 7 (formation *string*), 8 (formation-grid / lineup-position *field*), and 9 (detailed position identifier) as three separately-observable facts, each independently falsifiable per item 10. Collapsing them would hide exactly the NO-GO condition §14.4 is watching for: a formation string alone satisfies criterion (b) on a technicality while the grid is absent.
  4. Substitution relationships and minutes are reported as `(player_off, player_on, minute)` triples, with the on/off **direction asserted by test** — the field most likely to be inverted against a real payload, and one an inverted implementation would report just as confidently.
  5. No grid **semantics** are inferred or hardcoded. The scripts describe; FI-9 decides. Any temptation to encode a guess is a *stop and ask* per §17.
- **Objectives covered:** **6** (confirmed starters and substitutes), **7** (formation strings), **8** (formation-grid or lineup-position fields), **9** (detailed position identifiers), **10** (substitution relationships and minutes).
- **Non-goals:** no squad work (S4a); no change to M2 `tactical_role` or any `football-intelligence` module; no normalizer change; **no grid-semantics decision**.

##### S5 — split into S5a and S5b, for the same reason S4 was

Two scripts, six objectives, and the phase's worst convergence record — S5's three review passes returned 3, 6, and 4 substantive findings without converging, which is where the rewrite threshold came from. The two halves share no code beyond `_trial_common.py` and answer unrelated questions, so the split costs nothing.

They are also **separated in time**, which the original single slice could not express: S5a runs before the trial window and S5b runs on trial day 5–10 (see the trial-day order below). That gap is a recorded confound in the #100 measurement, not a scheduling detail.

##### S5a — health

- **Files new:** `scripts/trial_injuries.py`, `tests/test_trial_health_stats.py`.
- **DoD (verifiable):**
  1. Injuries, suspensions, and coach/manager records are reported as separately-statused facts. **The spec's original "three separately-statused objectives" conflicts with brief §11.3, which gives two ids** — objective 11 covers injuries *and* suspensions. Resolved by statusing all three internally and having objective 11 take the **worse** of injuries and suspensions, so a missing suspension feed cannot hide behind healthy injury data.
  2. Every injury record carries a freshness timestamp in the report — the input the §12 degradation matrix consumes to apply a confidence penalty. A record with no timestamp is reported `degraded`, never defaulted to "fresh".
  3. **The freshness field name is searched, not assumed.** The mock corpus carries no timestamps, so the mock synthesizes them and the report carries a warning saying so. Which field Sportmonks actually uses is unverified until FI-9, and a script that hardcodes one name reports `degraded` on live data for the wrong reason.
- **Objectives covered:** **11** (injuries and suspensions), **12** (coaches and manager records).
- **Non-goals:** no statistics work (S5b); no confidence-penalty logic (that is §8.1 / M-module territory); no M1 coefficient work.

##### S5b — statistics *(runs on trial day 5–10)*

- **Files new:** `scripts/trial_stats.py`, `tests/test_trial_stats.py`.
- **DoD (verifiable):**
  1. `trial_stats.py` reports fixture-level team statistics and player match statistics separately, each with per-field presence counts.
  2. **Objectives 15 and 16 are structurally different from the rest** and must be honestly labelled: update timing and post-match corrections can only be measured by repeated live observation across a real match. S5b ships the *recording scaffold* — a stable schema for pre/during/post samples and a diff between successive snapshots of the same fixture — and marks both objectives `not_applicable (requires FI-9 live observation)` in mock mode. The scaffold's diff logic is tested against two hand-written snapshot versions, and a test drives **both** keys in one run so the `not_applicable` status is itself falsifiable.
- **Objectives covered:** **13** (fixture-level team statistics), **14** (player match statistics), **15** (data update timing — scaffold only), **16** (post-match corrections — scaffold only).
- **Non-goals:** no health work (S5a); no live sampling; no confidence-penalty logic.

##### S6 — identity mapping *(the only slice that reads outside the package)*

- **Files new:** `scripts/trial_mapping.py`, `tests/test_trial_mapping.py`.
- **Reads (does not modify):** `packages/football-identity-registry/` — the FI-2 crosswalks, `overrides.yaml`, and ambiguity queue.
- **Why last:** it depends on the FI-2 registry and is the only script whose *output is itself a gate* (≥95% automatic matching, §14.1). Its FI-8 job is to be **ready to measure**; the measurement itself is FI-9.
- **DoD (verifiable):**
  1. `trial_mapping.py` computes an automatic-match rate against the FI-2 registry from a mock provider player pool and emits the unresolved queue in the same format FI-2's CLI already produces.
  2. A test pins the rate arithmetic on a hand-built pool with a known answer (e.g. 8/10 → exactly `80.0`), so a real-pool number in FI-9 can be trusted.
  3. The script reports `provider_id` stability by diffing two snapshots of the same entity set and listing any id that changed — objective 18's only mechanical check.
  4. **Fuzzy matching, speculative aliases, and unsafe fall-through tiers remain prohibited** (§14.1). A test asserts the script introduces no new matching tier: it calls the registry's existing matcher and does not implement its own.
  5. The script **must not write** to any registry file. Assert the `football-identity-registry` tree is byte-identical before and after a run.
  6. Below-threshold results exit **1** and are reported as unmet — never rounded up, never waived. The 86-item FI-2 unresolved queue stays a tracked blocker.
- **Objectives covered:** **18** (stable provider IDs), **19** (FPL identity-match rate).
- **Non-goals:** no registry data change, no override authored, no queue burn-down (that is FI-9, day 2–5), no new matching tier.

#### Objective coverage map — all 20 accounted for

| Slice | Brief §11.3 objectives |
|---|---|
| S0 | — (infrastructure) |
| S1 | 20 |
| S2 | 17 |
| S3 | 1, 2, 3 |
| S4a | 4, 5 |
| S4b | 6, 7, 8, 9, 10 |
| S5a | 11, 12 |
| S5b | 13, 14, 15\*, 16\* |
| S6 | 18, 19 |

\* scaffold only in FI-8; measured in FI-9.

#### Execution order is trial-day order, not plan order

**The slices above are written in dependency order. They are not to be executed in it.** Once the FI-9 window opens, the order is set by §14.2's day map — what a slice can be *used for* on the day it lands — and a fresh reader following the section order will build the wrong thing first.

| # | Slice | Trial window | Why here |
|---|---|---|---|
| 1 | **S5a** (health) | before / day 1 | Already written; needs its sweep finished. Nothing downstream waits on it. |
| 2 | **S4a** (squads) | day 2–5 | §14.2 day 2–5 is *"full PL squads + players ingest"*. Squads are the input the identity corpus is re-run against. |
| 3 | **S6** (identity) | day 2–5 | **Moved ahead of S4b.** §14.2 puts the identity corpus re-run and queue burn-down at day 2–5, and §14.1's ≥95% gate stands at **81.3449%** — the largest gap of any gate in the phase. S6 is the instrument that measures it, so it must exist while there is still trial time to act on a bad number. |
| 4 | **S4b** (lineups, grid) | day 5–10 | §14.2 puts lineups and formations at day 5–10, against preseason and opening fixtures. It is the highest-risk slice, but it cannot be validated earlier than the fixtures that validate it. |
| 5 | **S5b** (statistics) | day 5–10 | Stat completeness and update timing need real matches. Deferral recorded on [#101](https://github.com/darutto/FPL-Platform/issues/101). |

**S6 before S4b is the one inversion, and it is deliberate.** Dependency order puts S6 last because it reads outside the package; trial value puts it third because a below-threshold identity rate discovered on day 8 leaves nothing to do about it. The plan's own §14.4 makes the gate a GO criterion, so measuring it late is measuring it too late to change the answer.

The pre-registered #100 measurement is amended rather than protected: S5a and S5b will be measured under different conditions, weeks apart, and the summed comparison completes when S5b lands. **Reordering slices to keep an experiment clean would be optimising the experiment over the trial.**

#### Phase DoD

FI-8 is complete when §14.1's eight boxes are fully ticked. Attribution, box by box — **FI-8 owns five of the eight**:

| §14.1 box | Owner | Closed by |
|---|---|---|
| 1. FI-1…FI-7 merged; contract gate + corpus green, flags off **and** on over mocks | FI-7 | already closed (§15 FI-7 status, 2026-08-08) |
| 2. Mock end-to-end demo recorded | FI-7 | already closed (FI-7e, PR #61) |
| 3. `SPORTMONKS_API_TOKEN` wiring — token absent + dummy token | **FI-8** | **S2** (DoD 3 and 4) |
| 4. FI-8 acceptance scripts runnable end-to-end via `--mock` | **FI-8** | **S2–S6** (standing DoD 2) |
| 5. Identity matcher ≥95% on the real current-season corpus | FI-9 | **not** an FI-8 box — explicitly a trial gate |
| 6. Licensing question list ready to send day 1 | **FI-8** | **S1** (DoD 2) |
| 7. Go/no-go rubric agreed | **FI-8** | **S1** (DoD 3) |
| 8. Trial dashboard artifact: `TRIAL_STATUS.md` with the 20 objectives as a checklist | **FI-8** | **S1** (DoD 1) |

Box 8 in particular is **not** closed upstream — `TRIAL_STATUS.md` does not exist yet, and S1 is what creates it. A reader tallying boxes must verify it against S1 rather than assume FI-1…FI-7 ticked it.

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
| Sportmonks docs ≠ live payloads (grid fields especially) | All fixtures carry `"status": "unverified_against_live"`; FI-9 day-1 shape sweep; mismatches fixed only inside the adapter |
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
| FI-7 | c — existing-intent evidence enrichment | complete — merged PR #57 | FI-7c focused 11/11; combined FI-7b/c 75/75; grounded assistant 547 passed with 4 accepted legacy failures; football-intelligence 389 passed/2 skips; contract gate 16/16 | Exact eligible set: `captain_score`, `compare_players`, `transfer_advice`; evidence-only, master-flag gated, no recommendation or renderer change. Merged to main `49435bd004d4314567bb934e8f353db92d43130d`. |
| FI-7 | d — governed evidence UI | complete — merged PR #59 | FI-7d 43/43; full UI 449/449; TypeScript/build green; contract gate 16/16 | Ownership-based `EvidenceList` / `EvidenceChip` / per-item numeric `ConfidenceBadge`; consumes existing evidence only. Independently post-merge verified on `main@239bc8137358eeeb5aad137f53a9b0b66a22d0f2`; no runtime or second flag. |
| FI-7 | e — deterministic demo and verification evidence | complete — merged PR #61 | focused Python 75/75; FI-7d UI 43/43; Contract Drift Gate green; canonical checksum verification 22/22 and manifest 12/12 | Combined real-path backend trace, exact-payload local UI captures, checked-in machine evidence/screenshots/transcript/checksums, and immutable externally hosted hashed video. Merge integrity verified at `main@5e57a40b76bb9478abc5358ca6de700c4c8f6493`; no production behavior or `@minutes` / `@role` resource change. |
| FI-7 | f — resource-surface parity | complete — merged PR #65 | FI-7f parity 42/42; grounded-assistant 592 passed / 1 skipped; both required checks green (`Contract and fixture drift check`, `Package test suites`) | Deterministic, quota-free bootstrap-backed `@minutes <player>` season minutes and `@role <player>` nominal FPL position; bare `@minutes` ranking compatibility and FI 33/29/33 invariants preserved. Four files + one test; no protected surface touched; session transport deferred by contract. Independently reviewed and approved — no blockers, no required changes, two informational findings (see closeout note below). Merged at `main@e12c8b9179a90624e6a3cf089022522c9f592283`; reviewed head `0ea9f6cb` is a direct parent. |
| **FI-7** | **— phase complete —** | **complete** | **all six slices (a)–(f) merged and verified** | **"Completing FI-7 IS the trial-readiness bar" (§15 FI-7 DoD) is satisfied. FI-8 is unblocked.** |
| FI-8 | S0 — sportmonks-client under CI | complete | pre-FI-8 baseline: sportmonks-client **67 passed**, now pinned by CI as the fifth step of `Package test suites` (job name unchanged; no `paths:` filter, no `PYTHONPATH` env var, no install-step change) | Infrastructure only — no `scripts/`, no test, no fixture. Any later deviation from 67 is attributable to FI-8 rather than to drift. |
| FI-8 | S1 — trial documentation | complete | sportmonks-client 67/67 unchanged (prose-only slice, no code added); 20/20 §11.3 objectives verbatim; 14/14 §14.3 questions verbatim; go/no-go structure 6 GO / 3 NO-GO / 1 partial fallback | Adds `TRIAL_STATUS.md`, `TRIAL_LICENSING_CHECKLIST.md`, `TRIAL_GO_NO_GO.md`. Ticks three §14.1 boxes: licensing question list, go/no-go rubric, and the trial dashboard artifact. Every objective has a named owning script or document. Objectives 15 and 16 are marked `not_applicable` until live observation — they cannot be measured in `--mock` at all. |
| FI-8 | S4a — squads: teams, squad lists, player records | complete | sportmonks-client **275 passed** (250 intact, +25); falsifiability probe over `trial_squads.py`: **16/18 killed, 0 in-scope survivors**, the two survivors being the declared-exempt `Objective` titles in the failure-path builder; `--mock` exits 0 and writes both artifacts, byte-stable across repeats and matching the committed example byte-for-byte; the checked-in `edge_cases.json` empty envelope drives exit 1 | Adds `scripts/trial_squads.py` and `tests/test_trial_squads.py` (objectives 4 and 5). **Completeness is a per-field count, never a boolean** — the DoD asks for counts with named missing fields because `complete: true` is satisfiable by the literal `True`, and so is a count that can only read `0/n` or `n/n`. Every family reports `field k/n` over the records that arrived, and `test_partial_field_presence_is_counted_not_rounded` pins three counts with `k ∉ {0, n}` — `short_code 1/3`, `date_of_birth 3/4`, `position_id 1/2`. **A field carrying `null` counts as missing**: a provider shipping `date_of_birth: null` has not supplied a date of birth, and counting the key rather than the value would report completeness the §14.1 identity gate consumes and cannot use. Objectives 4 and 5 are computed from disjoint inputs, so the DoD's split case is asserted in **both** directions — impoverished player records degrade 5 with 4 `observed`, and incomplete squad fields degrade 4 with 5 `observed`. A status computed from the union of all three families would pass one and fail the other, and only running both shows which. Squad→player coverage is reported under objective 5 and is the slice's one item-10 second-branch entry: emitted whenever squad rows arrived, including when none resolves, because squads referencing players we cannot fetch is precisely the state objective 5 exists to catch. Rows are counted, not distinct players — two rows pointing at the same unfetchable player are two gaps in the squad. Standing DoD items 12 and 13 written in from the first draft, following S5a. Also commits one frozen mock report per the frozen contract, pinned byte-for-byte against a fresh run, so `TRIAL_STATUS.md`'s evidence pointer resolves to something nobody has to re-run — and joins the required probe gate in the same change. |
| FI-8 | S5a — health: injuries, suspensions, coaches | complete | sportmonks-client **274 passed** (250 intact, +24); falsifiability probe over `trial_injuries.py`, **three serial runs**: `14/18 killed, 18 seeds, 0 aborts, 0 in-scope survivors` each, the four survivors being the declared-exempt `Objective` titles. Runs 2 and 3 were compared **seed by seed** and are identical, exempt flags included; run 1 agrees on every figure it recorded. `--mock` exits 0 and writes both artifacts, byte-stable across repeats; the checked-in `edge_cases.json` empty envelope drives exit 1 | Adds `scripts/trial_injuries.py` and `tests/test_trial_health_stats.py` (objectives 11 and 12). **Two plan conflicts resolved in the script rather than by assumption.** (1) The spec asks for injuries, suspensions and coaches to be *three separately-statused* facts while brief §11.3 gives two ids; minting an 11b would break the 20-objective map the dashboard keys on, so all three are observed and evidenced separately and objective 11 takes the **worse** of injuries and suspensions — it cannot read `observed` unless both did, and the evidence names which fell short. (2) The mock corpus carries no freshness timestamp at all, so a faithful run would degrade against standing DoD 2's exit-0 requirement; mock mode synthesizes one and `SYNTHETIC_WARNING` travels in the report saying so. The field name is **searched, not assumed** — which key Sportmonks uses is an open trial question, and a hardcoded name would report `degraded` on live data for the wrong reason. Standing DoD items 12 and 13 were written in from the first draft rather than retrofitted, which is the first slice in the phase where that is true: failure paths asserted as whole `(id, status, evidence)` tuples by `==`, and both credential exceptions re-raised ahead of the broad catch. **Probe evidence was taken three times because one clean run is not the standard S3 set** — and because the CI flip mode is dormant, not gone. The first attempt ran in the foreground, timed out, and SIGTERM skipped the `finally` that restores: it left a seed on disk and both following runs aborted at `require_clean_tree`. The precondition caught it and nothing cleans it up automatically; filed on [#93](https://github.com/darutto/FPL-Platform/issues/93). This is data point one of the pre-registered [#100](https://github.com/darutto/FPL-Platform/pull/100) measurement, whose S5b half is deferred to trial day 5–10 — a confound recorded on [#101](https://github.com/darutto/FPL-Platform/issues/101), not a scheduling detail. |
| FI-8 | S3 — discovery: competitions, seasons, fixtures | complete | sportmonks-client **236 passed** (187 intact, +49); falsifiability probe over both new scripts: **17/23 killed, 0 in-scope survivors** (6 exempt `Objective` titles, declared); both scripts exit 0 on `--mock`, write both artifacts, and are byte-stable across repeats; the checked-in `edge_cases.json` empty envelope drives each to exit 1 | Adds `scripts/trial_entities.py` (objective 1, sweeping all 15 `ENDPOINTS` families), `scripts/trial_fixtures.py` (objectives 2 and 3), `tests/test_trial_discovery.py`, and `EndpointReplayTransport` + `match_by_name` in `_trial_common.py`. Both new scripts join the probe's required CI step. **The first probe run returned 6 in-scope survivors — over the pre-registered rewrite threshold of 3 — so the tests were rewritten rather than patched, per the rule chosen blind.** All six were one omission in three constructs: the failure-path report builder was reached only by tests asserting the **exit code**, never the report, so `status` and `evidence` were both literal-survivable; standing DoD **item 12** added. Investigating whether `_degraded_report` was dead code found something else: `SportmonksConfigurationError` and `SportmonksAuthenticationError` subclass `SportmonksError`, so `sweep`'s broad catch swallowed them — a seeded 401 made the script exit **1** with the family reported `unavailable` instead of exit **3**. With every family answering 401 the report would have read *"15 families unavailable"*, indistinguishable on trial day 1 from a Starter plan that carries none of these endpoints. Standing DoD **item 13** added; the regression is pinned per script by a real 401 driven through the client's status handling. `_degraded_report` is then deleted from `trial_entities` for the right reason — `sweep` converts family-scoped errors into observations and re-raises the two that are not, so no generic branch is enterable. Objective 3's cross-competition fixture is **synthesized** in mock mode (the corpus holds one fixture in one competition); the report carries `SYNTHETIC_WARNING` saying so, asserted by test, so the rehearsal cannot be read as evidence. Also: `EndpointReplayTransport` keys on endpoint rather than call order, because a sweep whose fixture stack drifts from its iteration order reports one family's payload under another's name — a misobservation that looks like data. `EndpointReplayTransport` raises on an unmapped endpoint rather than answering empty, since `empty` is a claim about the provider and the truth would be a gap in our own corpus. |
| FI-8 | S2 — the guard's completeness pinned | complete | sportmonks-client **187 passed** (184 intact, +3); seeded: no-op control `187 passed`; `import yaml` into `client.py` → `1 failed`; `import socket` into `trial_auth.py` → `1 failed`; enumerator returning nothing → `3 failed` (all three) | The isolation tests prove each guard layer catches the call *alone*; they say nothing about whether the two layers cover the *surface*. They do — an AST enumeration of `sportmonks_client/`, `scripts/`, and `tests/` finds exactly two third-party roots (`requests`, `pytest`) and no network-capable stdlib module — but that is a fact about today's dependency list, not a property. Pinned as an **allowlist** rather than a denylist, so a client nobody thought of fails it too; a denylist only catches names the author could enumerate, which is the failure mode this phase has measured four times. Stdlib routes match on the full dotted name so `urllib.parse` is not a false positive while `urllib.request` is a real one. Parsed, not grepped, for the reason in the adjacent-question table: a docstring naming `httpx` is not an import of it. Vacuity closed by a third test naming `transport.py` as the file the premise rests on — the other two are satisfiable by an enumerator that scanned nothing. The guard's incompleteness now announces itself at the commit that causes it instead of during a live FI-9 call. |
| FI-8 | S2 — the live-call guard, isolated per layer | complete | sportmonks-client **184 passed** (182 intact, +2); seeded: no-op control `184 passed`; deleting the `Session.request` layer → `1 failed`, the isolation test naming that layer; deleting the `HTTPAdapter.send` layer → `2 failed`, its isolation test plus the pre-existing outcome test | The step-4 subject-deletion sweep over all merged code returned **one survivor in eight subjects**, negative control behaving correctly — and it was the live-call guard, the structural enforcement of FI-8's hardest constraint, in the slice built specifically to make that enforcement structural. Deleting `monkeypatch.setattr(requests.Session, "request", _refuse)` from `tests/conftest.py` left **182 of 182 green**, including `test_the_guard_fires_on_a_real_session_request`, the test written to prove that patch works: `Session.request` fell through to the still-patched `HTTPAdapter.send`, which raises the identical `AssertionError`. Nothing was broken — the call really was caught — which is why every hand review approved it and the mechanical sweep found it on the first pass. Classified under the pre-registered triage rule as a mechanism with no assertion distinguishing it, one in-scope survivor, below the rewrite threshold of 3 → patched, one PR for the slice. Fixed by **isolation, not introspection**: asserting a patch count or a named callable checks that the code says what you think it says (the grep-the-source family). Each new test hands one layer's real implementation back — captured at module import, before any autouse fixture runs — and exercises the entry point the *other* layer guards, all aimed at `127.0.0.1:1`. The property gained is the one the sweep could not produce: each layer is now known to catch the call **alone**, not merely to be present. Generalized in §15 as *redundant layers require an isolation test per layer*, with the outcome-over-redundant-layers instrument added to the adjacent-question table. |
| FI-8 | S2 — the exemplar made falsifiable (fourth correction) | complete | sportmonks-client **134 passed** (107 intact, +27); merged seeding probe **0 survivors of 22 sites** — the author's 11 plus the 12 an independent enumeration added — with a no-op negative control surviving and a reinstated-bug positive control killed; per-entry declaration machine-checked against emitted names | The frozen exemplar taught the defect four slices were rejected for. `trial_auth.py`'s `rejected_envelope` test fed one payload and asserted a substring; the literal `"data[],pagination{current_page,has_more}"` left all 107 green — measured on `main`. That is the entry reporting the payload the parser refused, §17's top-risk observation. **The first fix repeated the phase's recurring error**: it closed that entry and left the four siblings one to three lines below it — `rate_limit_headers` had one input, `retry_after` asserted containment, objective 17's `evidence` was never asserted by `==` at all, and `_degraded_report` — S2's *third* correction — was reached by **no test**, its whole body replaceable with `raise AssertionError` against a green suite. Independent review measured 4 of 6 sites surviving and rejected it. Now: header subsets and throttle counts parametrized so the reported fields track the payload rather than the canonical set; two `Retry-After` values by `==`; the full evidence string pinned on three inputs (two were satisfiable by `1 if any else 0`); both provider-failure branches exercised; and a multi-response case proving `rejected_envelope` reads the response that was *refused*, not the first one. Retrofitting also exposed `render_skeleton` truncating below the second level — `meta{pagination}`, field names dropped, for any provider carrying pagination under `meta`. Standing DoD **item 11** added: two inputs, distinct expectations, equality not containment, declaration naming the covering test. **A second review, scoped only to enumeration completeness, then found 12 sites the author's probe never listed — and the `pagination` entry's *location* still held a literal**, the same defect S2 was rejected for twice, because the only `meta.pagination` test worked at unit level and never reached the entry. Closed by end-to-end cases at both locations, `==` on the three interpolated `missing` messages, distinguishable `_unmet_report` reasons, and a `DECLARED_SHAPES` mapping asserted equal to the emitted names with every named test resolved. Deferred with a decision to make: [#92](https://github.com/darutto/FPL-Platform/issues/92), depth-4 truncation still silent and the rendering not injective. **[#93](https://github.com/darutto/FPL-Platform/issues/93) blocks S3**: the probe becomes a script with mechanical site enumeration and a required check, and the already-merged slices get swept before S3 assumes it is reading a corrected template. |
| FI-8 | S2 — shape differences degrade (third correction) | complete | sportmonks-client **107 passed** (67 pre-existing intact) | A payload differing from the documented shape — §17's top risk and the one thing FI-8 exists to rehearse — exited **3** (defined as *configuration/auth* failure) with an empty `observed_shapes`, discarding the payload the trial most needs to see. The frozen contract already said the opposite; the code contradicted a contract that was already correct. Now: `SportmonksSchemaError` is caught where the exchange is still available, the refused envelope's skeleton is recorded as `rejected_envelope`, the objective degrades, exit 1. Fixed at the class rather than the instance — **only** `SportmonksConfigurationError` and `SportmonksAuthenticationError` map to exit 3; every other provider failure is a degraded observation. Also: a present-but-empty `pagination: {}` is recorded rather than read as absent. Deferred with a decision to make: [#85](https://github.com/darutto/FPL-Platform/issues/85), `body_skeleton` and data-valued keys. **Fan-out gate met.** |
| FI-8 | S2 — pagination observation (second correction) | superseded by the row above | sportmonks-client **103 passed** (67 pre-existing intact) | Second independent review **REJECTED** the first correction: the `pagination` shape was still a literal. It keyed off a 200-response count, so it survived deleting the pagination block entirely, and its string named `envelope.meta.pagination` while the fixtures carry pagination **top-level with no `meta` key at all** — a location the observed response never had, shipped on `main`. Now derived from a key-name-only body skeleton: location and present fields both read from the response, `next_page` named only when carried. Also: a 429 arriving without `Retry-After` was reported as zero throttles and exited 0 — now counted and degraded. `unmet` made reachable (failure paths never reached the provider, so nothing was observed) rather than frozen-but-unexercised before S3 inherits it. |
| FI-8 | S2 — observation correction (first, incomplete) | superseded by the row above | sportmonks-client **97 passed** (67 pre-existing intact) | Independent review **REJECTED** the first S2: objective 17's rate-limit half was a hardcoded literal — stripping every header from the payload left the report byte-identical and still exiting 0 — and DoD 5's synthetic `Retry-After` exercise was absent entirely. Fixed by `ObservingTransport`, which records status plus sanctioned headers of every response in **both** modes, so evidence and shapes are derived from what arrived. Same experiment now yields `degraded`, exit 1, shape dropped. Also: DoD 4's leak check made non-vacuous against real report bytes, guard tests retargeted from `api.sportmonks.com` to loopback, `mode` read from the resolved mode rather than inferred from `transport is not None`, one-flag grammar cleared from two stale docs. Standing DoD item 10 added — the rule the fix demonstrates. |
| FI-8 | S2 — harness, `trial_auth.py`, live-call guard | superseded by the row above | sportmonks-client **90 passed** (67 pre-existing all green with the guard installed, +23 new); `--mock` run exits 0 and writes both artifacts; `git ls-files trial-output/` empty after a run that wrote there | Freezes what S3–S6 inherit: report schema (status enum pinned to exactly the four, `not_started` rejected by construction), exit codes 0/1/2/3, `--out` default `trial-output/`, byte-stable mock output. Guard patches `requests.Session.request` + `HTTPAdapter.send`; seeded violation observed firing (`AssertionError` at `conftest.py:35`) and, with the guard disabled, reaching `adapters.py:729` instead. Ignore rule landed with the writer. Invocation gained `--live` so the `REFUSED` path is reachable — frozen contract updated to match. |
| FI-8 | trial gate artifacts | planned | see the S0 row above for the pre-FI-8 baseline | Sliced S0–S6; see "FI-8 — detailed slice specification (source of truth for S0–S6)" in §15. Adds a 12th file (`scripts/_trial_common.py`) beyond §15's stated 11 — deviation approved and to be restated in the FI-8 commit. Hard constraint: no live Sportmonks call before FI-9, anywhere including tests; `--mock` is the default and every test uses `SportmonksClient.offline(...)` behind a structural transport guard. |
| FI-9 | live trial | blocked until ~2026-08-10 | — | |
| FI-10 | calibration | blocked on FI-9 | — | |

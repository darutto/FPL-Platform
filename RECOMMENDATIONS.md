# fpl-platform · Validation Recommendations

> **Status:** Safe-execution-mode recommendation — no files have been modified in legacy projects.
>
> **Revised:** Upstream ownership model applied. `fpl-elo-insights` is now treated as a
> version-pinned upstream dependency, not an internalisation target.

---

## 0. Architectural Ownership Model

Before the phase recommendations, every package must be classified into one of three tiers.
This classification determines how the package is built, maintained, and updated.

### Tier A — Fully Owned Internal

The platform writes the code, holds the canonical version, and evolves it independently.
Logic was sourced from **internal** projects (`captaincy-showdown`, `captaincy-ml`,
`fpl-video-repurposer`, `FPL-team-stats`). Upstream source is a reference implementation,
not a dependency.

| Package / Module | Source project | Notes |
|---|---|---|
| `fpl-captain-engine` (all) | `captaincy-showdown`, `captaincy-ml` | Zero external dependencies; fully self-contained |
| `fpl-charts/theme.ts` | `captaincy-showdown`, `Top stats per week FPL` | Pure constants; no upstream tracking needed |
| `fpl-api-client/fpl_client.py` | `fpl-video-repurposer` | FPL bootstrap API client; internal origin |
| `fpl-api-client/football_data_client.py` | `FPL-team-stats` | football-data.org wrapper; internal origin |
| `fpl-api-client` (TypeScript) | `captaincy-showdown` | CSV loader + FPL client; internal origin |
| `fpl-player-registry` (all) | `captaincy-ml`, `fpl-video-repurposer` | SeasonIdMapper + nickname resolution; internal origin |
| `fpl-data-core/season_registry.py` | `captaincy-ml` | Season layout config; internal origin |
| `fpl-data-core/season_registry.yaml` | New file | No upstream equivalent; fully owned |
| `fpl-data-core/analytics.py` *(to be created)* | `captaincy-showdown` | `compute_rolling_xgi_per_90()` — internal origin; move from `stat_calculator.py` |

### Tier B — Upstream Contract Adapter

The platform writes a **thin adapter layer** that tracks an upstream interface. When upstream
changes, the adapter is updated to reflect it. The platform does **not** duplicate upstream logic.

| Package / Module | Upstream repo | Upstream file | What the adapter does |
|---|---|---|---|
| `fpl-data-core/schemas.py` | `FPL-Elo-Insights` | `scripts/export_data.py` (lines 12–43) | Mirrors `CUMULATIVE_COLS`, `ID_COLS`, `SNAPSHOT_COLS`, `TOURNAMENT_NAME_MAP`. Updated whenever upstream changes its CSV schema. |

**Update discipline for Tier B:** Each `schemas.py` change must include a comment
`# aligned-with: <fpl-elo-insights commit SHA>`. A CI check should compare
`CUMULATIVE_COLS` against the column list of the most recent upstream playerstats CSV.

### Tier C — Consumed as Output

The platform reads artifacts that an upstream pipeline has already computed. No platform
code duplicates the upstream computation. The integration contract is the **file format**
(CSV column schema), not a Python API.

| Upstream repo | What the platform consumes | Integration contract |
|---|---|---|
| `FPL-Elo-Insights` | Per-gameweek `playerstats.csv` and `player_gameweek_stats.csv` in `By Gameweek/GW{n}/` | CSV schema tracked in `schemas.py` (Tier B) |
| `FPL-Elo-Insights` | Tournament player stats CSVs in `By Tournament/` | Same schema contract |
| `fpl-elo-insights-clean` *(if adopted as canonical)* | Same CSV outputs via incremental sync | Must verify `TOURNAMENT_NAME_MAP` alignment with `schemas.py` |

**Corollary — `stat_calculator.py` must be partially retired:** `make_discrete()` and
`calculate_discrete_gameweek_stats()` are Tier C duplications — they re-implement what
`fpl-elo-insights` already computes. They must be removed. Only `compute_rolling_xgi_per_90()`
(which is a Tier A consumer of Tier C output) is retained, moved to `analytics.py`.

### Upstream Dependency Table (fpl-elo-insights)

| Attribute | Detail |
|-----------|--------|
| **Canonical upstream repo** | `FPL-Elo-Insights` (full rewrite strategy) |
| **Diverged fork** | `fpl-elo-insights-clean` (incremental sync strategy) — **choose one** |
| **Integration strategy** | Consume CSV output (Tier C); track CSV schema in `schemas.py` (Tier B) |
| **Version pinning** | Pin to upstream commit SHA recorded in `schemas.py` header |
| **Update trigger** | Any change to `CUMULATIVE_COLS`, column names, or GW directory structure |
| **Divergence detection** | CI assertion: `CUMULATIVE_COLS == pd.read_csv(latest_upstream_csv).columns.tolist()` |
| **Risk if upstream diverges** | Column rename → `compute_rolling_xgi_per_90()` returns 0.0 silently. Detect with parity test against known upstream output. |
| **Risk if upstream stops producing CSVs** | All consumers break. Mitigate: monitor output directory in CI; add a staleness check on CSV modification dates. |

---

## 1. Recommended First Package to Validate

### ✅ `packages/fpl-captain-engine` — TypeScript module

**Validate the TypeScript side first.**

This recommendation is unchanged by the upstream-ownership revision. `fpl-captain-engine`
(TypeScript) is a **Tier A — Fully Owned Internal** package with zero external dependencies.

### Rationale

| Factor | Assessment |
|--------|-----------|
| **Ownership tier** | Tier A — fully owned internal |
| **Risk rating** | 🟢 LOW (TypeScript) |
| **External dependencies** | Zero — pure functions, no I/O, no network calls, no upstream to track |
| **Logic provenance** | Verbatim copy of `captaincy-showdown/src/engine/captainScore.ts`; zero logic changes |
| **Verifiability** | Formula is closed-form arithmetic — every output can be verified by hand or against the source |
| **Existing test coverage** | `captaincy-showdown` already has `captainScore.spec.ts`; those tests can be copied over with only an import-path change |
| **No risky migrations needed** | Validation requires no config changes, no path rewrites, no database access |
| **Self-contained boundary** | `CaptainCandidate` + `MatchupData` types are defined inside the package; no upstream type dependency |

The Python side of `fpl-captain-engine` carries a **🟡 MEDIUM** risk because `tier_classifier.py`
was reconstructed without access to `advanced_captain_strategies.py` (which does not exist in the
repo). Validate the **TypeScript** module first; schedule the Python tier-classifier validation as
a separate task once `advanced_captain_strategies.py` is located or its replacement is confirmed.

### Validation steps (TypeScript)

1. Run the parity tests from `TEST_PLAN.md § fpl-captain-engine (TypeScript)` — these are a
   direct port of the source `captainScore.spec.ts`.
2. Confirm all 7 assertions pass (perfect score, form-dominated, fixture-dominated, xgi-dominated,
   zero minutes, exact weight distribution, clamping).
3. Open `captaincy-showdown` and change one import:
   ```diff
   - import { calculateCaptainScore } from "../engine/captainScore";
   + import { calculateCaptainScore } from "@fpl-platform/fpl-captain-engine";
   ```
4. Run the existing captaincy-showdown test suite. All tests should remain green.
5. If green → the package is validated; `captaincy-showdown` can fully migrate its local copy.

### Validation steps (Python — schedule separately)

Before validating the Python side, resolve the following blocker:

> **Blocker:** `captaincy-ml/phase4_tiered_recommendations.py` imports
> `advanced_captain_strategies` which **does not exist** in the repository.
> The `TieredCaptainSelector` in `fpl-captain-engine/python/tier_classifier.py` was
> reconstructed from source docstrings and cannot be verified as a faithful port until
> the original (or its intended replacement) is found.

---

## 2. Recommended First Consumer Project for Pilot Integration

### ✅ `captaincy-showdown` — React + TypeScript app

**This is the lowest-risk pilot consumer for the TypeScript captain-engine package.**

This recommendation is unchanged by the upstream-ownership revision. The pilot involves
only Tier A packages (`fpl-captain-engine`), which have no upstream tracking requirements.

### Rationale

| Factor | Assessment |
|--------|-----------|
| **Package tier involved** | Tier A — fully owned; no upstream alignment required during pilot |
| **Stack alignment** | Pure TypeScript/React — the shared package is also TypeScript |
| **Scope of change** | Single import-path change in `captainScore.ts`; all other files untouched |
| **No backend risk** | No Python, no Supabase, no upstream CSV dependency involved in the captain-scoring path |
| **Existing test suite** | `captainScore.spec.ts` already exists — integration health is immediately measurable |
| **Rollback simplicity** | One-line import revert if anything breaks |
| **Self-contained app** | Captaincy-showdown is a standalone Vite app; a breakage cannot cascade to other projects |

### What the pilot integration looks like

In `captaincy-showdown/package.json`, add a workspace reference:
```json
{
  "dependencies": {
    "@fpl-platform/fpl-captain-engine": "workspace:*"
  }
}
```

Change one import in `captaincyDataService.ts`:
```diff
- import { calculateCaptainScore, updateCaptainScores } from "../engine/captainScore";
+ import { calculateCaptainScore, updateCaptainScores } from "@fpl-platform/fpl-captain-engine";
```

Run `npm run test` and `npm run build`. If both pass, the pilot is complete.

### What the pilot does NOT include

- `csvLoader.ts` / `fplClient.ts` — deferred until the Vitest filesystem-fallback decision is made
- `schemas.py` or any Tier B module — upstream schema alignment must be confirmed first
- `stat_calculator.py` discrete-stat functions — these are scheduled for retirement
- Any changes to either `fpl-elo-insights` repo

---

## 3. Dependency Order for Full Migration (Revised)

The migration phases are revised to reflect the three-tier model. Tier A (fully owned)
packages proceed independently. Tier B and C integration requires upstream alignment first.

```
Phase 0 (Now — Tier A only)
  └─ Validate:  fpl-captain-engine (TypeScript)
  └─ Pilot:     captaincy-showdown imports captain-engine

Phase 1 (After Phase 0 — Tier A, low blast radius)
  ├─ Validate:  fpl-charts/theme.ts (pure Tier A constants, zero upstream deps)
  └─ Pilot:     captaincy-showdown imports fpl-charts theme

Phase 2 (After resolving Vitest fallback — Tier A)
  ├─ Validate:  fpl-api-client (TypeScript — csvLoader + fplClient)
  └─ Pilot:     captaincy-showdown replaces local dataLoader.ts + csvPathConfig.ts

Phase 3a (Upstream alignment prerequisite — Tier B/C)
  ├─ Prerequisite: Choose canonical fpl-elo-insights variant (main vs clean fork)
  ├─ Prerequisite: Record upstream commit SHA in schemas.py
  ├─ Validate:  fpl-data-core/season_registry.py (Tier A — safe to validate independently)
  ├─ Validate:  fpl-data-core/schemas.py (Tier B — only after upstream SHA pinned)
  ├─ Remove:    stat_calculator.py::make_discrete() + calculate_discrete_gameweek_stats()
  └─ Promote:   stat_calculator.py::compute_rolling_xgi_per_90() → analytics.py (Tier A)

Phase 3b (After Phase 3a — Tier A)
  ├─ Validate:  fpl-data-core/analytics.py (rolling xGI/90 — fully owned)
  └─ Pilot:     captaincy-ml imports season_registry + analytics from shared package

Phase 4 (After resolving map_between_seasons + advanced_captain_strategies — Tier A)
  ├─ Validate:  fpl-player-registry (Python)
  └─ Validate:  fpl-captain-engine (Python — tier classifier)
  └─ Pilot:     captaincy-ml imports player_registry + captain_score from shared packages

Phase 5 (After all packages validated)
  └─ Retire legacy source files in each project
  └─ Update MIGRATION_PLAN.md with completed status
  └─ Establish CI check: schemas.py CUMULATIVE_COLS vs upstream CSV column list
```

---

## 4. Blockers That Must Be Resolved Before Proceeding

### Pre-existing blockers (unchanged)

| Priority | Blocker | Affects | Owner action needed |
|----------|---------|---------|---------------------|
| 🔴 P0 | `advanced_captain_strategies.py` missing | `fpl-captain-engine` (Python), `captaincy-ml` Phase 4 | Locate file or confirm it was never written; decide if `tier_classifier.py` reconstruction is the replacement |
| 🔴 P0 | `map_between_seasons()` missing from `SeasonIdMapper` | `fpl-player-registry`, `test_sprint_b.py` | Add method or fix the test; method signature must be decided |
| 🟡 P1 | Vitest filesystem fallback removed from `csvLoader.ts` | `fpl-api-client` (TypeScript) | Decide: replicate fallback in shared module, or update captaincy-showdown tests to mock network |
| 🟡 P1 | football-data.org competition ID mismatch (`2021` vs `2025`) | `fpl-api-client` | Confirm correct competition ID for each use case; align defaults |
| 🟢 P2 | `packages/fpl-player-registry/typescript/` not yet written | Future TypeScript consumers | Low urgency — no TypeScript app currently uses player registry |

### New blockers from upstream ownership model

| Priority | Blocker | Affects | Owner action needed |
|----------|---------|---------|---------------------|
| 🔴 P0 | `stat_calculator.py::make_discrete()` duplicates upstream logic | `fpl-data-core` | Remove the two discrete-stat functions; move `compute_rolling_xgi_per_90()` to `analytics.py`; update `__init__.py` and `TEST_PLAN.md` |
| 🔴 P0 | Canonical upstream variant not chosen | `fpl-data-core/schemas.py`, all Tier C consumers | Choose between `FPL-Elo-Insights` (full rewrite) and `fpl-elo-insights-clean` (incremental); document the decision |
| 🟡 P1 | `schemas.py` has no upstream commit SHA recorded | `fpl-data-core/schemas.py` | Add `# aligned-with: <sha>` comment; set up CI column-list assertion |
| 🟡 P1 | No staleness check on upstream CSV output | All Tier C consumers | Add a CI check that asserts CSV files exist and were modified within expected recency window |

---

*Revised: three-tier ownership model applied. `fpl-elo-insights` classified as Tier C
upstream dependency. `schemas.py` reclassified as Tier B upstream contract adapter.
`stat_calculator.py` discrete-stat functions scheduled for retirement.*

*Generated by Claude in safe-execution mode — no legacy project files were modified.*



# PACKAGE AUDIT — `fpl-data-core`
**Status:** Pre-adoption (not yet integrated by any project)
**Audit date:** 2026-03-07 (revised with upstream ownership model)
**Risk level:** 🟡 MEDIUM

---

## ⚠️ Architectural Constraint (Added)

> **`fpl-elo-insights` is an upstream dependency, not an internalisation target.**
>
> Treat both `FPL-Elo-Insights` and `fpl-elo-insights-clean` as upstream data pipelines
> that are version-pinned and consumed at arm's length. Their stat-calculation logic must
> **not** be duplicated in this platform. The platform consumes their CSV output files.

This constraint changes the status of `stat_calculator.py` — see Ownership Model below.

---

## Purpose

Provides the foundational data contract for all FPL projects:
- The canonical CSV column schema (`CUMULATIVE_COLS`, `ID_COLS`, `SNAPSHOT_COLS`)  ← adapter/contract layer
- A YAML-driven season layout registry replacing hardcoded Python configs  ← **fully owned**
- Discrete gameweek stat calculation  ← ⚠️ **see Ownership Model — retire or re-scope**
- Rolling xGI/90 computation  ← **fully owned** (derived from internal `captaincy-showdown`)

---

## Ownership Model

Each module in this package has a distinct ownership classification:

| Module | Classification | Ownership | Rationale |
|--------|---------------|-----------|-----------|
| `season_registry.py` | **Fully owned internal** | Platform owns this | Derived from `captaincy-ml/ml/data/season_layouts.py` (internal project). No fpl-elo-insights dependency. |
| `season_registry.yaml` | **Fully owned internal** | Platform owns this | New file; externalises `_initialize_registry()` data. No upstream equivalent. |
| `schemas.py` | **Upstream contract adapter** | Track upstream; do not diverge silently | Constants (`CUMULATIVE_COLS`, `TOURNAMENT_NAME_MAP`, etc.) mirror `FPL-Elo-Insights/scripts/export_data.py` lines 12–43. Any upstream column rename must be reflected here within one sprint. |
| `stat_calculator.py::make_discrete()` | **⚠️ RETIRE** | Remove — duplicates upstream logic | This function is a direct port of `export_data.py::calculate_discrete_gameweek_stats()`. The calculation must remain upstream; the platform should read the CSVs that `fpl-elo-insights` produces. |
| `stat_calculator.py::calculate_discrete_gameweek_stats()` | **⚠️ RETIRE** | Remove — duplicates upstream logic | Same as above — this is the folder-walking wrapper around the upstream computation. |
| `stat_calculator.py::compute_rolling_xgi_per_90()` | **Fully owned internal** | Keep — derived from internal project | Python port of `captaincy-showdown/src/utils/performanceEnricher.ts::buildAggMap`. No fpl-elo-insights provenance. Should be moved to a separate `analytics.py` module after `stat_calculator.py` is retired. |

### What to do about `stat_calculator.py`

Two halves of the file have different fates:

1. **Retire `make_discrete()` + `calculate_discrete_gameweek_stats()`** — the upstream pipeline already produces these outputs. Duplicating the computation creates a dual-maintenance burden and a divergence risk every time `fpl-elo-insights` updates `CUMULATIVE_COLS` or its subtraction logic.

2. **Promote `compute_rolling_xgi_per_90()`** — move to a new `packages/fpl-data-core/python/analytics.py`. This function reads from the already-computed CSV output (it is a consumer, not a re-implementor of upstream logic).

---

## fpl-elo-insights Upstream Dependency

### Upstream Source Paths

| Repo | Path | Role |
|------|------|------|
| `FPL-Elo-Insights` | `scripts/export_data.py` | Canonical data pipeline (full rewrite strategy) |
| `fpl-elo-insights-clean` | `scripts/export_data.py` | Diverged fork (incremental sync strategy — see Known Risks) |

### Integration Strategy: Consume as Output

```
fpl-elo-insights pipeline
  ├── Reads from Supabase  (FPL stats stored by GW)
  ├── Runs export_data.py  (calculates discrete GW stats, tournament stats)
  └── Writes CSV files     ← platform reads THESE

fpl-platform consumers
  ├── Read CSV files via season_registry.yaml path config
  └── Run compute_rolling_xgi_per_90() on the CSV data
```

The platform does **not** call into `export_data.py`. It reads the files that `export_data.py` produces. The `season_registry.yaml` describes where those files live on disk — this is the integration contract.

### Recommended Integration Boundary

```python
# What the platform DOES own (reading CSV output):
from fpl_data_core.season_registry import get_season_layout
layout = get_season_layout("2025-2026")
csv_path = layout.base_path / "By Gameweek" / "GW38" / "playerstats.csv"
df = pd.read_csv(csv_path)   # consume upstream output

# What the platform does NOT own (stat computation):
# ❌ from fpl_data_core.stat_calculator import calculate_discrete_gameweek_stats
# ❌ calculate_discrete_gameweek_stats(base_path)  ← this is upstream's job
```

### Version Pinning

Because the platform consumes CSV output (file format), not a Python API, "version pinning" means:
- Agreeing on a **CSV schema contract**: column names, types, and the `CUMULATIVE_COLS` list
- `schemas.py` is the authoritative record of that contract at a given point in time
- When `fpl-elo-insights` changes its schema, update `schemas.py` in the same PR

Recommended process:
1. Tag each `schemas.py` update with the `fpl-elo-insights` commit SHA it was aligned to
2. Use a `# aligned-with: <sha>` comment at the top of `schemas.py`
3. Run parity tests against that specific upstream output before merging

### Update Strategy When Upstream Changes

| Upstream change | Platform action required | Urgency |
|----------------|--------------------------|---------|
| New column added to `CUMULATIVE_COLS` | Add to `schemas.py::CUMULATIVE_COLS` | High — consumers may miss new stat |
| Column renamed | Update `schemas.py`; update any code that references the column name by string | High — downstream reads will break |
| New tournament added to `TOURNAMENT_NAME_MAP` | Add to `schemas.py::TOURNAMENT_NAME_MAP` | Medium — only affects tournament consumers |
| Subtraction logic changed (e.g. new baseline strategy) | No platform code change needed (upstream handles it); verify CSV output shape is unchanged | Low |
| Supabase schema change | No platform code change needed; verify CSV output shape is unchanged | Low |
| New GW directory structure (e.g. `GW-38` instead of `GW38`) | Update `season_registry.yaml::gameweek_pattern` | High — `list_available_gameweeks()` will silently find 0 GWs |

### Risk If Upstream Diverges

| Divergence scenario | Impact | Detection |
|--------------------|--------|-----------|
| `fpl-elo-insights` adds new columns to playerstats CSVs | Platform reads silently succeed (extra columns are ignored by pandas). Rolling xGI still works. Low impact. | None — silent. Add an output-schema assertion test. |
| `fpl-elo-insights` renames a column referenced by `schemas.py` | `compute_rolling_xgi_per_90()` returns 0.0 for all players if `xg` or `xa` renamed. Scoring pipeline produces wrong captain tiers. | High impact. Parity test against known output detects this. |
| `fpl-elo-insights` changes cumulative→discrete logic | Platform reads pre-computed CSVs; no impact. If `schemas.py::CUMULATIVE_COLS` drifts, downstream that re-computes anything will be wrong. | Caught by `schemas.py` parity test. |
| `fpl-elo-insights` stops producing CSVs (migrates to DB output only) | All platform CSV consumers break. | Critical. Would require a new adapter layer. Add a CI check that asserts CSV files exist at expected paths. |
| `fpl-elo-insights-clean` adopted as canonical instead of `FPL-Elo-Insights` | No impact on `season_registry.py` or `schemas.py`. CSV schema must be verified to be the same (it has a smaller `TOURNAMENT_NAME_MAP`). | Audit the CSV output schema of the clean variant before switching. |

---

## Source Files Derived From

| Source file | Lines used | Action taken |
|---|---|---|
| `captaincy-ml/ml/data/season_layouts.py` | Full file (179 lines) | **Copied as-is**, import paths updated, `_initialize_registry()` replaced with YAML loader. **Internal project — fully owned.** |
| `FPL-Elo-Insights/scripts/export_data.py` | Lines 12–43 (constants) | **Extracted** into `schemas.py` as adapter/contract layer. **Upstream — track changes.** |
| `FPL-Elo-Insights/scripts/export_data.py` | Lines 75–186 (function) | **Extracted** into `stat_calculator.py`. **⚠️ Retire the discrete-stat functions; keep only `compute_rolling_xgi_per_90`.** |
| `captaincy-showdown/src/utils/performanceEnricher.ts` | `buildAggMap` (lines 32–93) | **Python port** into `stat_calculator.py::compute_rolling_xgi_per_90()`. **Internal project — fully owned.** |

---

## What Was Copied As-Is vs Adapted

### `season_registry.py` ← **fully owned**
- `SeasonLayout` dataclass → **copied verbatim**
- `get_season_layout()`, `register_season()`, `list_available_seasons()` → **copied verbatim**
- `list_available_gameweeks()` → **copied verbatim** (including the `season == "2025-2026"` branch — see Known Risks)
- `_initialize_registry()` → **replaced** with `load_registry_from_yaml()` backed by `season_registry.yaml`

### `schemas.py` ← **upstream contract adapter** — track `FPL-Elo-Insights/scripts/export_data.py`
- `CUMULATIVE_COLS` list → **copied verbatim** from `export_data.py` line 30–37
- `ID_COLS`, `SNAPSHOT_COLS`, `TOURNAMENT_NAME_MAP` → **copied verbatim**
- `normalise_position()` → **new helper** ported from `candidateMapper.ts`
- Add `# aligned-with: <commit-sha>` at top of file once upstream SHA is recorded

### `stat_calculator.py`
- `make_discrete()` → ⚠️ **Retire** — direct port of upstream logic
- `calculate_discrete_gameweek_stats()` → ⚠️ **Retire** — direct port of upstream logic
- `compute_rolling_xgi_per_90()` → **Keep** (derived from internal captaincy-showdown); move to `analytics.py`

---

## Assumptions

1. The `season_registry.yaml` file is co-located with the package (one directory up from `python/`). Any consumer that uses a non-standard workspace root must call `load_registry_from_yaml(custom_path)` explicitly.
2. All seasons use `GW{n}` directory naming. The `gameweek_pattern` field in the YAML handles this; non-standard naming is not yet supported.
3. The `id` column is the join key for all player stats DataFrames. The `player_id_column` registry field was read but retained functions currently hardcode `on='id'` in the merge.
4. `By Gameweek` and `By Tournament` trees share the same cumulative baseline (tournament stats subtract the preceding By-Gameweek GW, not the preceding tournament GW). This is upstream behaviour — the platform does not re-implement it; it reads the output files that upstream has already computed correctly.

---

## Known Risks

### 🔴 CRITICAL: `stat_calculator.py::make_discrete()` duplicates upstream logic
Maintaining this function alongside `fpl-elo-insights/export_data.py` means the platform
must track every upstream change to `CUMULATIVE_COLS`, merge key behaviour, and subtraction
strategy. Any upstream change that is not mirrored here will produce silently wrong outputs.

**Action required:** Remove `make_discrete()` and `calculate_discrete_gameweek_stats()` from
this package. Move `compute_rolling_xgi_per_90()` to a new `analytics.py`. Update `__init__.py`
to remove the retired exports. Update `TEST_PLAN.md` to remove parity tests for the retired
functions (they tested against the wrong level of abstraction).

### 🔴 CRITICAL: `fpl-elo-insights-clean/scripts/export_data.py` is architecturally diverged
The "clean" fork is **not a minor edit** of the main `export_data.py`. It is a fundamentally
different incremental architecture:
- Has no `CUMULATIVE_COLS` or `calculate_discrete_gameweek_stats` at all
- Uses `fetch_data_since_gameweek()` for partial syncs (incremental from latest GW)
- Uses `update_csv()` with deduplication — not a full-rewrite strategy
- Has a smaller `TOURNAMENT_NAME_MAP` (5 entries vs 8)
- Uses `select('*', count='exact')` without pagination — **may silently truncate tables > 1000 rows**

Under the upstream-dependency constraint, this means **the platform must choose exactly one
variant as its canonical upstream**. `schemas.py` can only track one `CUMULATIVE_COLS` definition.

**Action required:** The owner must decide which variant is canonical. Once decided:
- If `FPL-Elo-Insights` is canonical: document that `fpl-elo-insights-clean` is not consumed by
  the platform
- If `fpl-elo-insights-clean` is canonical: update `schemas.py` to match its (smaller)
  `TOURNAMENT_NAME_MAP` and confirm whether discrete stats are pre-computed by the clean pipeline

### 🟡 MEDIUM: `list_available_gameweeks()` has a hardcoded season branch
The `if self.season == "2025-2026":` branch scans a `By Gameweek/` subfolder. All other seasons
use a `matches/` subfolder. This hardcoded season name must be replaced with a registry-driven
field (e.g. `gameweek_scan_dir`) before a third season is added.

### 🟡 MEDIUM: `schemas.py` has no upstream-sync mechanism
When `fpl-elo-insights` adds or renames columns, there is currently no automated check that
`schemas.py` is updated. Recommend: add a CI step that compares `CUMULATIVE_COLS` against the
column list of the most recent playerstats CSV produced by the upstream pipeline.

### 🟢 LOW: Tournament discrete stats use cross-tree baseline
Tournament GW stats subtract from `By Gameweek/GW{n-1}` not from the previous tournament GW.
This is correct for FPL season-cumulative stats but unexpected. It is documented in upstream
source comments. Since the platform now reads rather than re-computes this, the risk is lower.

---

## Dependencies

| Dependency | Version | Notes |
|---|---|---|
| `pandas` | ≥ 1.3 | Core DataFrame operations |
| `PyYAML` | ≥ 5.4 | YAML registry loading |
| `pathlib` | stdlib | Path operations |

No Supabase client dependency — data is expected to already be on disk as CSV files. The Supabase
fetch logic stays in `FPL-Elo-Insights/scripts/export_data.py` (upstream; not owned by platform).

---

## Acceptance Criteria for First Adoption

### `season_registry` (fully owned — validate first)
- [ ] `test_fpl_data_core.py` smoke tests pass (see `TEST_PLAN.md`)
- [ ] `captaincy-ml` existing tests (`test_sprint_a.py`) pass unchanged after switching imports to this package
- [ ] `season_registry.yaml` contains entries for at least `2024-2025` and `2025-2026`
- [ ] `list_available_gameweeks()` returns at least 10 GWs for a season with real data on disk

### `schemas.py` (upstream contract adapter — validate against upstream output)
- [ ] `CUMULATIVE_COLS` matches the column list of current `FPL-Elo-Insights` output CSVs exactly
- [ ] `TOURNAMENT_NAME_MAP` is confirmed against canonical upstream variant (resolve fork first)
- [ ] `schemas.py` header includes `# aligned-with: <upstream-commit-sha>`

### `stat_calculator.py` (transition plan)
- [ ] `make_discrete()` and `calculate_discrete_gameweek_stats()` marked for removal
- [ ] `compute_rolling_xgi_per_90()` moved to `analytics.py`
- [ ] `TEST_PLAN.md` parity tests for retired functions updated to reflect new approach (read upstream output, don't re-compute)

---

*Revised: upstream dependency model added. `fpl-elo-insights` treated as version-pinned
upstream. Platform consumes CSV output; does not duplicate stat calculation logic.*



# fpl-platform · Package Status
**Last updated:** 2026-03-08
**After:** Phase 0 (TypeScript captain engine) + Phase 1a (Python data-core)

Status vocabulary:
- `planned` — described in audit, no platform code written yet
- `created` — platform code written, not yet tested
- `parity-validated` — tested against source implementation, assertions pass
- `pilot-validated` — integrated into a consumer project, tests pass end-to-end
- `adopted` — consumer project has permanently switched its imports

---

## `fpl-captain-engine` (TypeScript)

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `pilot-validated` |
| **Public surface** | `calculateCaptainScore(form, fixture_difficulty, xgi_per_90, minutes_risk) → float`<br>`updateCaptainScores(candidates[]) → candidates[]`<br>`CaptainCandidate` (type)<br>`MatchupData` (type) |
| **Platform path** | `packages/fpl-captain-engine/typescript/src/` |
| **Source of truth** | `captaincy-showdown/src/engine/captainScore.ts` (verbatim copy) |
| **Upstream dependency risk** | None — zero external npm or upstream-repo dependencies |
| **Pilot** | `captaincy-showdown` — import alias active in `captaincyDataService.ts`; 29/29 tests pass |
| **Next step** | Python parity package (Phase 2) — now unblocked by `analytics.py` |

---

## `fpl-data-core` — `season_registry`

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `parity-validated` |
| **Public surface** | `SeasonLayout` (dataclass)<br>`SEASON_REGISTRY` (dict)<br>`get_season_layout(season) → SeasonLayout`<br>`list_available_seasons() → list[str]`<br>`register_season(layout)`<br>`load_registry_from_yaml(path)` |
| **Platform path** | `packages/fpl-data-core/fpl_data_core/season_registry.py` |
| **Source of truth** | `captaincy-ml/ml/data/season_layouts.py` + new `season_registry.yaml` |
| **Upstream dependency risk** | None — pure Python + YAML, no external repos |
| **Test coverage** | 19 assertions (A1–A14, B1–B5) across smoke + edge cases; 5 data-conditional tests skip cleanly in CI |
| **Next step** | Consumer import switch in `captaincy-ml` (Phase 3) |

---

## `fpl-data-core` — `analytics`

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `parity-validated` |
| **Public surface** | `compute_rolling_xgi_per_90(df, player_id, lookback=3) → float` |
| **Platform path** | `packages/fpl-data-core/fpl_data_core/analytics.py` |
| **Source of truth** | `captaincy-showdown/src/utils/performanceEnricher.ts::buildAggMap` (Python equivalent)<br>Reference copy in `fpl-data-core/python/stat_calculator.py` |
| **Upstream dependency risk** | None — pure pandas, no upstream-repo dependency |
| **Test coverage** | 15 assertions (E1–E13, F1–F2) including cross-language parity: `1.74` matches `epicA.test.ts` stdout |
| **Next step** | Consumed by Python captain engine parity package (Phase 2) |

---

## `fpl-data-core` — `schemas`

| Field | Value |
|-------|-------|
| **Tier** | B — Upstream Contract Adapter |
| **Status** | `created` |
| **Public surface** | `CUMULATIVE_COLS` (26 items)<br>`ID_COLS`, `SNAPSHOT_COLS`<br>`TOURNAMENT_NAME_MAP`, `EXCLUDED_TOURNAMENTS`, `EXCLUDED_GAMEWEEKS`<br>`POSITION_MAP`<br>`normalise_position(element_type) → str` |
| **Platform path** | `packages/fpl-data-core/fpl_data_core/schemas.py` |
| **Source of truth** | `FPL-Elo-Insights/scripts/export_data.py` (lines 12–43) |
| **Upstream dependency risk** | **Medium** — if upstream changes its CSV column set (e.g. FPL adds a new stat), `CUMULATIVE_COLS` silently drifts. Detected only by running §1.4 contract test. `# aligned-with: <sha>` comment not yet populated. |
| **Test coverage** | 13 smoke assertions pass (C1–C9, D×14). §1.4 upstream contract tests written but not yet executed against real GW1 CSV. |
| **Next step** | **Phase 1b candidate** — run §1.4 against real data; add upstream SHA comment |

---

## `fpl-data-core` — `stat_calculator`

| Field | Value |
|-------|-------|
| **Tier** | C — Duplication (retirement candidate) |
| **Status** | `created` (reference only, in `python/` audit folder) |
| **Public surface** | `make_discrete()`, `calculate_discrete_gameweek_stats()` — **NOT exported from `fpl_data_core`**<br>`compute_rolling_xgi_per_90()` — **promoted to `analytics.py`; remove from here at retirement** |
| **Platform path** | `packages/fpl-data-core/python/stat_calculator.py` (reference, not in active package) |
| **Source of truth** | `FPL-Elo-Insights/scripts/export_data.py` (duplicated upstream logic) |
| **Upstream dependency risk** | High if kept — dual-maintenance burden with upstream. Retirement eliminates the risk. |
| **Next step** | Retire `make_discrete` + `calculate_discrete_gameweek_stats` after upstream confirms no callers. `compute_rolling_xgi_per_90` already superseded by `analytics.py`. |

---

## `fpl-api-client` (Python)

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `created` (reference files in `python/` audit folder; no active package directory yet) |
| **Public surface** | `fetch_json(url) → dict`<br>`get_bootstrap() → dict`<br>`get_players(bootstrap) → list`<br>`get_teams(bootstrap) → list`<br>`get_current_gameweek(bootstrap) → int\|None`<br>`get_fixture_difficulty_map(gw, teams) → dict`<br>`FootballDataClient(api_key)` |
| **Platform path** | `packages/fpl-api-client/python/` (reference copy only) |
| **Source of truth** | `fpl_client.py` ← `fpl-video-repurposer/build_fpl_kb.py`<br>`football_data_client.py` ← `FPL-team-stats` |
| **Upstream dependency risk** | Medium — FPL bootstrap API is undocumented and can change shape silently. No official changelog. |
| **Next step** | **Phase 1b candidate** — bootstrap-only package with HTTP-mock smoke tests |

---

## `fpl-api-client` (TypeScript)

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `created` (files in `typescript/src/`) |
| **Public surface** | `getCsvPath(opts) → string` (csvLoader.ts)<br>`loadCSVData(url) → Promise<Row[]>` (csvLoader.ts)<br>`fetchBootstrap()` (fplClient.ts — placeholder) |
| **Platform path** | `packages/fpl-api-client/typescript/src/` |
| **Source of truth** | `captaincy-showdown/src/utils/csvPathConfig.ts` + `src/services/captaincyDataService.ts` |
| **Upstream dependency risk** | Low — path construction is pure string logic; no external dependency |
| **Next step** | TypeScript tests from TEST_PLAN §2.1–2.3 (Phase 1b or later) |

---

## `fpl-player-registry`

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `created` (reference file in `python/` audit folder; no active package directory yet) |
| **Public surface** | `SeasonIdMapper(workspace_root)`<br>`to_canonical(season, ids[]) → list`<br>`to_season(canonical_ids[], season) → list`<br>`resolve_nickname(name, players[]) → dict\|None`<br>`build_name_lookup(players[]) → dict`<br>`KNOWN_NICKNAMES` |
| **Platform path** | `packages/fpl-player-registry/python/player_registry.py` (reference copy only) |
| **Source of truth** | `captaincy-ml/ml/data/season_id_mapper.py` + `fpl-video-repurposer` nickname logic |
| **Upstream dependency risk** | Low for logic; medium for ID mappings (requires bootstrap data from FPL API) |
| **Next step** | Phase 1c — depends on `fpl-api-client` bootstrap for full integration tests |

---

## `fpl-charts` (TypeScript)

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `created` (single `theme.ts` file) |
| **Public surface** | `COLORS`, `BRAND`, `CHART_COLORS`<br>`RISK`, `getRiskLevel(minutes_risk) → 'low'\|'medium'\|'high'` |
| **Platform path** | `packages/fpl-charts/src/theme.ts` |
| **Source of truth** | `captaincy-showdown/src/brand.ts` + `src/components/PlayerCard.tsx` |
| **Upstream dependency risk** | None — pure constants and pure function |
| **Next step** | Vitest tests from TEST_PLAN §5.1–5.3 (deferred to Phase 2+; not on critical path) |

---

## `fpl-pipeline`

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `planned` |
| **Public surface** | None yet |
| **Source of truth** | N/A — new orchestration layer |
| **Upstream dependency risk** | None until modules are wired in |
| **Next step** | Deferred until all Phase 1 packages reach `parity-validated` |

---

## Summary table

| Package / Module | Tier | Status | Blocker |
|---|---|---|---|
| `fpl-captain-engine` TypeScript | A | `pilot-validated` | — |
| `fpl-data-core/season_registry` | A | `parity-validated` | — |
| `fpl-data-core/analytics` | A | `parity-validated` | — |
| `fpl-data-core/schemas` | B | `created` | §1.4 contract test not yet run |
| `fpl-data-core/stat_calculator` | C | `created` | Retirement pending upstream sign-off |
| `fpl-api-client` Python | A | `created` | Active package dir not yet built |
| `fpl-api-client` TypeScript | A | `created` | Tests not yet written |
| `fpl-player-registry` | A | `created` | Needs `fpl-api-client` for ID tests |
| `fpl-charts` | A | `created` | Tests not yet written |
| `fpl-pipeline` | A | `planned` | All others first |



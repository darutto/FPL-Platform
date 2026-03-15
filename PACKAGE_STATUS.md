# fpl-platform · Package Status
**Last updated:** 2026-03-14
**After:** Phase 4d (integration examples — examples/ package + 115/115 assertions)

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
| **Next step** | No action — stable |

---

## `fpl-captain-engine` (Python)

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `parity-validated` |
| **Public surface** | `calculate_captain_score(form, fixture_difficulty, xgi_per_90, minutes_risk) → float`<br>`CaptainTier` (enum)<br>`get_captain_tier(score) → CaptainTier`<br>`evaluate_role_signals(element, bootstrap) → dict` |
| **Platform path** | `packages/fpl-captain-engine/fpl_captain_engine/` |
| **Source of truth** | `packages/fpl-captain-engine/typescript/src/captainScore.ts` (cross-language parity) |
| **Upstream dependency risk** | None — pure computation, no external dependencies |
| **Test coverage** | Phases 2a–2h; 78+112+133+132+160+165 assertions across scoring, ranking, auto-derivation, fixture difficulty, tiers, role signals |
| **Next step** | No action — consumed by fpl-tool-contract and fpl-grounded-assistant |

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
| **Test coverage** | 19 assertions (A1–A14, B1–B5) across smoke + edge cases |
| **Next step** | Consumer import switch in `captaincy-ml` (deferred) |

---

## `fpl-data-core` — `analytics`

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `parity-validated` |
| **Public surface** | `compute_rolling_xgi_per_90(df, player_id, lookback=3) → float` |
| **Platform path** | `packages/fpl-data-core/fpl_data_core/analytics.py` |
| **Source of truth** | `captaincy-showdown/src/utils/performanceEnricher.ts::buildAggMap` (Python equivalent) |
| **Upstream dependency risk** | None — pure pandas, no upstream-repo dependency |
| **Test coverage** | 15 assertions including cross-language parity: `1.74` matches `epicA.test.ts` stdout |
| **Next step** | Consumed by fpl-captain-engine Python — no action |

---

## `fpl-data-core` — `schemas`

| Field | Value |
|-------|-------|
| **Tier** | B — Upstream Contract Adapter |
| **Status** | `created` |
| **Public surface** | `CUMULATIVE_COLS` (26 items)<br>`ID_COLS`, `SNAPSHOT_COLS`<br>`TOURNAMENT_NAME_MAP`, `EXCLUDED_TOURNAMENTS`, `EXCLUDED_GAMEWEEKS`<br>`POSITION_MAP`<br>`normalise_position(element_type) → str` |
| **Platform path** | `packages/fpl-data-core/fpl_data_core/schemas.py` |
| **Source of truth** | `FPL-Elo-Insights/scripts/export_data.py` (lines 12–43) |
| **Upstream dependency risk** | **Medium** — FPL adds stats silently; `CUMULATIVE_COLS` can drift. `# aligned-with: <sha>` not yet populated. |
| **Test coverage** | 13 smoke assertions pass. §1.4 upstream contract tests written but not run against real GW CSV. |
| **Next step** | Run §1.4 against real data; add upstream SHA comment |

---

## `fpl-data-core` — `stat_calculator`

| Field | Value |
|-------|-------|
| **Tier** | C — Duplication (retirement candidate) |
| **Status** | `created` (reference only, in `python/` audit folder) |
| **Public surface** | Not exported — reference copy only |
| **Platform path** | `packages/fpl-data-core/python/stat_calculator.py` |
| **Upstream dependency risk** | High if kept — dual-maintenance burden. Retirement eliminates the risk. |
| **Next step** | Retire after upstream confirms no callers. `compute_rolling_xgi_per_90` already superseded by `analytics.py`. |

---

## `fpl-api-client` (Python)

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `parity-validated` |
| **Public surface** | `fetch_json(url) → Any`<br>`get_bootstrap() → dict`<br>`get_players(bootstrap) → list`<br>`get_teams(bootstrap) → list`<br>`get_current_gameweek(bootstrap) → int\|None`<br>`get_fixtures(gameweek) → list` *(Phase 4a)*<br>`get_fixture_difficulty_map(fixtures, bootstrap) → dict[int, int]` *(Phase 4a)* |
| **Platform path** | `packages/fpl-api-client/fpl_api_client/` |
| **Source of truth** | `packages/fpl-api-client/python/fpl_client.py` (audit copy) |
| **Upstream dependency risk** | Medium — FPL bootstrap API is undocumented and can change shape silently |
| **Test coverage** | Phase 1c smoke tests; `get_fixtures` + `get_fixture_difficulty_map` integration-tested live in Phase 4a (E1–E13) |
| **Next step** | No action — consumed by fpl-pipeline |

---

## `fpl-api-client` (TypeScript)

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `created` |
| **Public surface** | `getCsvPath(opts) → string`<br>`loadCSVData(url) → Promise<Row[]>`<br>`fetchBootstrap()` (placeholder) |
| **Platform path** | `packages/fpl-api-client/typescript/src/` |
| **Upstream dependency risk** | Low — path construction is pure string logic |
| **Next step** | TypeScript tests (deferred — not on Python platform critical path) |

---

## `fpl-player-registry`

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `parity-validated` |
| **Public surface** | `resolve_player(query, bootstrap) → dict\|None`<br>`build_name_lookup(bootstrap) → dict`<br>`KNOWN_NICKNAMES`<br>Alias/nickname resolution (KDB, Salah, etc.) |
| **Platform path** | `packages/fpl-player-registry/fpl_player_registry/` |
| **Source of truth** | `fpl-video-repurposer` nickname logic + FPL bootstrap element names |
| **Upstream dependency risk** | Low for logic; medium for player IDs (FPL bootstrap dependent) |
| **Test coverage** | Phase 1d tests; exercised across all grounded-assistant tool phases |
| **Next step** | No action — consumed by fpl-tool-contract |

---

## `fpl-query-tools`

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `parity-validated` |
| **Public surface** | Player lookup composition layer — bridges fpl-player-registry name resolution with bootstrap element lookup |
| **Platform path** | `packages/fpl-query-tools/fpl_query_tools/` |
| **Upstream dependency risk** | None — pure composition of fpl-player-registry + bootstrap |
| **Test coverage** | Phase 1e tests; exercised across all grounded-assistant tool phases |
| **Next step** | No action — consumed by fpl-tool-contract |

---

## `fpl-tool-contract`

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `parity-validated` |
| **Public surface** | `tool_resolve_player(query, bootstrap) → dict`<br>`tool_get_player_summary(query, bootstrap) → dict`<br>`tool_get_current_gameweek(bootstrap) → dict`<br>`tool_get_captain_score(query, bootstrap, candidate_inputs) → dict`<br>`tool_rank_captain_candidates(candidates, bootstrap) → dict` |
| **Platform path** | `packages/fpl-tool-contract/fpl_tool_contract/` |
| **Upstream dependency risk** | None — pure composition of captain engine + player registry |
| **Test coverage** | Phase 1f tests (run_phase1f_tests.py) |
| **Next step** | No action — consumed by fpl-tool-runner |

---

## `fpl-tool-runner`

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `parity-validated` |
| **Public surface** | `run_tool(name, args, bootstrap) → dict`<br>`TOOL_REGISTRY` (ToolRegistry)<br>`ToolRegistry`<br>`ToolSpec` |
| **Platform path** | `packages/fpl-tool-runner/fpl_tool_runner/` |
| **Upstream dependency risk** | None — pure dispatch layer |
| **Test coverage** | Phase 1g tests (run_phase1g_tests.py); bug fixed in Phase 4a (`_rank_captain_candidates_handler` was passing full args dict instead of `args["candidates"]`) |
| **Next step** | No action — consumed by fpl-grounded-assistant |

---

## `fpl-pipeline`

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `parity-validated` |
| **Public surface** | `assemble_captain_context(gameweek=None, *, bootstrap=None, fixtures=None) → dict`<br>Returns: `bootstrap` (with `fixture_difficulty_map` injected), `gameweek`, `fixtures`, `fixture_difficulty_map`, `meta` |
| **Platform path** | `packages/fpl-pipeline/fpl_pipeline/` |
| **Source of truth** | New orchestration layer — no upstream source |
| **Upstream dependency risk** | None — composes fpl-api-client calls only |
| **Test coverage** | Phase 2e tests (run_phase2e_tests.py); live integration-tested in Phase 4a (E1–E13) |
| **Next step** | No action — consumed by fpl-grounded-assistant callers |

---

## `fpl-grounded-assistant`

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `pilot-validated` |
| **Public surface** | `respond(user_message, bootstrap, *, client, model, candidate_inputs, candidates_list, api_key, include_debug) → FinalResponse`<br>`FinalResponse` (frozen dataclass — stable contract)<br>`FinalResponseDebug` (frozen dataclass — debug only)<br>`adapt(...) → AdapterResponse`<br>`dispatch(...) → DispatchResult`<br>`ask(...) → dict`<br>Outcome/intent constants, fixture definitions, `run_all_final_response()` |
| **Platform path** | `packages/fpl-grounded-assistant/fpl_grounded_assistant/` |
| **Source of truth** | New — no upstream source; this is the primary platform product |
| **Upstream dependency risk** | LLM layer: Anthropic API availability (graceful fallback to deterministic path when unavailable) |
| **Test coverage** | 22 standalone test runners, 3,675 total assertions (Phases 1h–4d); 82 live integration assertions against real FPL API (Phase 4a); 119 CLI assertions (Phase 4b); 148 HTTP assertions (Phase 4c); 115 integration example assertions (Phase 4d) |
| **Pilot** | Phase 4a — `assemble_captain_context() → respond()` wiring verified with live FPL bootstrap; 82/82 PASS |
| **Contract doc** | `packages/fpl-grounded-assistant/FINAL_RESPONSE_CONTRACT.md` — stable caller-facing surface (Phase 3d) |
| **Integration examples** | `packages/fpl-grounded-assistant/examples/` — CLI and HTTP examples for all 5 canonical scenarios (Phase 4d) |
| **Next step** | Phase 4e (multi-turn state) or Phase 4f (LLM intent classification) — see HANDOFF.md |

---

## `fpl-charts` (TypeScript)

| Field | Value |
|-------|-------|
| **Tier** | A — Fully Owned Internal |
| **Status** | `created` |
| **Public surface** | `COLORS`, `BRAND`, `CHART_COLORS`<br>`RISK`, `getRiskLevel(minutes_risk) → 'low'\|'medium'\|'high'` |
| **Platform path** | `packages/fpl-charts/src/theme.ts` |
| **Upstream dependency risk** | None — pure constants and pure function |
| **Next step** | Deferred — not on Python platform critical path |

---

## Summary table

| Package / Module | Tier | Status | Notes |
|---|---|---|---|
| `fpl-captain-engine` TypeScript | A | `pilot-validated` | Stable |
| `fpl-captain-engine` Python | A | `parity-validated` | Phases 2a–2h |
| `fpl-data-core/season_registry` | A | `parity-validated` | Stable |
| `fpl-data-core/analytics` | A | `parity-validated` | Stable |
| `fpl-data-core/schemas` | B | `created` | §1.4 upstream contract test not yet run |
| `fpl-data-core/stat_calculator` | C | `created` | Retirement pending |
| `fpl-api-client` Python | A | `parity-validated` | Phase 1c + 4a fixtures |
| `fpl-api-client` TypeScript | A | `created` | Not on critical path |
| `fpl-player-registry` | A | `parity-validated` | Phase 1d |
| `fpl-query-tools` | A | `parity-validated` | Phase 1e |
| `fpl-tool-contract` | A | `parity-validated` | Phase 1f |
| `fpl-tool-runner` | A | `parity-validated` | Phase 1g; bug fixed 4a |
| `fpl-pipeline` | A | `parity-validated` | Phase 2e; live-tested 4a |
| `fpl-grounded-assistant` | A | `pilot-validated` | Phases 1h–4d; 3,675 assertions |
| `fpl_cli` (CLI entrypoint) | A | `parity-validated` | Phase 4b; 119 assertions |
| `fpl_server` (HTTP entrypoint) | A | `parity-validated` | Phase 4c; 148 assertions |
| `examples/` (integration examples) | A | `parity-validated` | Phase 4d; 115 assertions |
| `fpl-charts` TypeScript | A | `created` | Not on critical path |

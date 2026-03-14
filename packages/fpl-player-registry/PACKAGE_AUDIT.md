# PACKAGE AUDIT — `fpl-player-registry`
**Status:** Pre-adoption (not yet integrated by any project)
**Audit date:** 2026-03-07
**Risk level:** 🔴 HIGH

---

## Purpose

Provides a unified player and team identity layer across all FPL projects:
- Cross-season player ID mapping (`SeasonIdMapper`)
- Spanish community nickname resolution (`KNOWN_NICKNAMES`, `resolve_nickname`)
- Fast name lookup dict builder (`build_name_lookup`)
- TypeScript candidate mapper for scoring pipeline (`mapToCaptainCandidates`)

---

## Source Files Derived From

| Source file | Lines used | Action taken |
|---|---|---|
| `captaincy-ml/ml/data/season_id_mapper.py` | Full file (249 lines) | **Copied**, single import path changed (`from .season_layouts` → `from fpl_data_core.season_registry`) |
| `fpl-video-repurposer/build_fpl_kb.py` | `KNOWN_NICKNAMES` (73–100), `SPANISH_PORTUGUESE_PATTERNS` (62–70) | **Extracted** as module-level constants |
| `fpl-video-repurposer/build_fpl_kb.py` | `build_master_squad()` (38–57) | **Not copied** — superseded by `fpl_client.get_players()` + `get_teams()` |
| `captaincy-ml/check_players.py` | `validation_players` dict | **Not copied** — intended to become test fixtures |
| `captaincy-showdown/src/utils/candidateMapper.ts` | Full file (98 lines) | **Not yet written** — noted as `typescript/src/candidateMapper.ts` to be promoted |

---

## What Was Copied As-Is vs Adapted

### `player_registry.py`

**`SeasonIdMapper`** → **inline copy**, one import path change only:
```python
# Was:    from .season_layouts import get_season_layout
# Now:    from fpl_data_core.season_registry import get_season_layout
```
All method signatures, logic, and caching behaviour are identical to the source.

**`KNOWN_NICKNAMES`** → **copied verbatim** from `build_fpl_kb.py` lines 73–100.

**`resolve_nickname()`** → **new function** that did not exist in any source project; synthesised from the intent of `correct_transcript.py`'s name lookup pattern.

**`build_name_lookup()`** → **new function**; synthesised from the `build_phonetic_map()` function implied but not directly readable in `build_fpl_kb.py`.

---

## Assumptions

1. `SeasonIdMapper` stores its generated JSON mapping files under `data/id_maps/` relative to `workspace_root`. The original stores them under `ml/data/id_maps/` — **this path was changed** in the shared module to be more neutral.
2. Canonical player identity is `players.csv.player_id`. Any project that uses a different canonical ID column must override `_load_players_canonical()`.
3. `KNOWN_NICKNAMES` reflects the Spanish FPL community circa 2025-26. New signings will not be in this list until manually added.
4. `resolve_nickname()` performs a case-insensitive prefix match after stripping "el " from Spanish aliases. This is a heuristic; it will misfire on players with very short names (e.g. "Mo" could match other players).

---

## Known Risks

### 🔴 CRITICAL: `SeasonIdMapper.map_between_seasons()` is called in tests but does not exist
`captaincy-ml/test_sprint_b.py` line 28 calls:
```python
target_ids = mapper.map_between_seasons("2024-2025", "2025-2026", source_ids)
```
But the `SeasonIdMapper` class (both in the source `season_id_mapper.py` and in this package) has **no such method**. The class only exposes `to_canonical()` and `to_season()`. The test would fail at runtime with `AttributeError`.

**Impact:** The existing Sprint B test is broken. The shared package inherits this broken state.

**Action required before adoption:** Either:
  - (a) Add `map_between_seasons()` as a convenience wrapper around `to_canonical()` + `to_season()`, OR
  - (b) Fix `test_sprint_b.py` to use the two-step API that actually exists

This must be resolved before marking this package as ready.

### 🔴 CRITICAL: `advanced_captain_strategies.py` is missing from `captaincy-ml`
`captaincy-ml/phase4_tiered_recommendations.py` line 30 imports:
```python
from advanced_captain_strategies import (
    AdvancedCaptainSelector, CaptainRecommendation, ...
)
```
This file **does not exist** in the `captaincy-ml` project directory. `phase4_tiered_recommendations.py` cannot run at all in its current state. This is not caused by this package but must be understood: the `TierClassifier` in this package was derived from the code that *exists*, not from the full Phase 4 system (which is incomplete in the source).

**Impact:** The `fpl-captain-engine::tier_classifier.py` is complete and self-contained. But `captaincy-ml/phase4_tiered_recommendations.py` as a consumer will still fail until `advanced_captain_strategies.py` is provided or reconstructed.

### 🟡 MEDIUM: `id_maps/` path change may break `captaincy-ml` existing mappings
The source `SeasonIdMapper` writes JSON files to `ml/data/id_maps/`. The shared module writes to `data/id_maps/`. Existing cached mapping files will **not be found** after migration unless they are moved.

**Action required:** Either move existing `ml/data/id_maps/*.json` files, or pass the original path explicitly:
```python
mapper = SeasonIdMapper(workspace_root=Path("."))
# Then override: mapper.id_maps_dir = Path("ml/data/id_maps")
```

### 🟡 MEDIUM: `KNOWN_NICKNAMES` is not driven by live FPL data
Player nicknames are hardcoded. When players leave the Premier League (e.g. Kane's move to Bayern in the list suggests it is already stale), stale entries will not cause errors but will miss matches. There is no sync mechanism.

### 🟢 LOW: `TypeScript candidateMapper.ts` not yet created
`packages/fpl-player-registry/typescript/src/candidateMapper.ts` is listed in the migration plan but the file was not yet written in the consolidation area. It is the source `captaincy-showdown/src/utils/candidateMapper.ts` promoted verbatim.

---

## Dependencies

### Python
| Dependency | Version | Notes |
|---|---|---|
| `pandas` | ≥ 1.3 | CSV loading in `SeasonIdMapper` |
| `fpl-data-core` | (this monorepo) | `get_season_layout` |

### TypeScript
| Dependency | Version | Notes |
|---|---|---|
| `@fpl-platform/captain-engine` | (this monorepo) | `CaptainCandidate` type |

---

## Acceptance Criteria for First Adoption

- [ ] `SeasonIdMapper.map_between_seasons()` existence question resolved (add or fix test)
- [ ] `SeasonIdMapper.to_canonical("2024-2025", [328, 351, 17, 110])` returns `[381, 430, 16, 135]` (from Sprint B test's expected values)
- [ ] `SeasonIdMapper` uses same JSON cache files after path adjustment
- [ ] `resolve_nickname("el Vikingo", players)` returns Haaland
- [ ] `resolve_nickname("KDB", players)` returns De Bruyne
- [ ] `build_name_lookup(players)["salah"]` returns the Salah player dict
- [ ] `captaincy-ml/test_sprint_b.py` passes (after fixing the missing method)



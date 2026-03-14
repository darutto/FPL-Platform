# FPL Platform — Shared Module Migration Plan
**Status:** Pre-migration (analysis only — no files moved)
**Date:** 2026-03-07

> **Rule:** Do NOT delete or move any file from an existing project until migration is explicitly approved.
> This document describes what *will* change, not what *has* changed.

---

## Consolidation Area Map

```
fpl-platform/
  packages/
    fpl-api-client/
      python/
        fpl_client.py              ← NEW (from fpl-video-repurposer/build_fpl_kb.py)
        football_data_client.py    ← NEW (from FPL-team-stats/app.py)
        __init__.py
      typescript/
        src/
          fplClient.ts             ← NEW (browser FPL API wrapper)
          csvLoader.ts             ← NEW (from captaincy-showdown/src/utils/dataLoader.ts)
          index.ts
    fpl-data-core/
      python/
        season_registry.py         ← PROMOTED (from captaincy-ml/ml/data/season_layouts.py)
        schemas.py                 ← NEW (from FPL-Elo-Insights/scripts/export_data.py)
        stat_calculator.py         ← NEW (from FPL-Elo-Insights/scripts/export_data.py)
        __init__.py
      season_registry.yaml         ← NEW (externalises captaincy-ml/_initialize_registry)
    fpl-player-registry/
      python/
        player_registry.py         ← MERGED (season_id_mapper + build_fpl_kb + check_players)
        __init__.py
      typescript/
        src/
          candidateMapper.ts       ← PROMOTED (from captaincy-showdown/src/utils/candidateMapper.ts)
    fpl-captain-engine/
      python/
        captain_score.py           ← NEW (Python port of captainScore.ts)
        tier_classifier.py         ← PROMOTED (from captaincy-ml/phase4_tiered_recommendations.py)
        __init__.py
      typescript/
        src/
          captainScore.ts          ← PROMOTED (from captaincy-showdown/src/engine/captainScore.ts)
    fpl-charts/
      src/
        theme.ts                   ← MERGED (brand.ts + main.css + Chart.js color array)
```

---

## Module 1: `fpl-api-client`

### What files will move

| From (source project) | File | To (shared module) | Action |
|---|---|---|---|
| `fpl-video-repurposer/build_fpl_kb.py` | `fetch_json()`, `BOOTSTRAP_URL`, `FIXTURES_URL`, `build_master_squad()`, `build_next_fixture_map()` | `packages/fpl-api-client/python/fpl_client.py` | Extract functions |
| `FPL-team-stats/app.py` | `FOOTBALL_DATA_BASE_URL`, both route handler bodies | `packages/fpl-api-client/python/football_data_client.py` | Extract into `FootballDataClient` class |
| `FPL-team-stats/football-proxy-server/src/routes/api.js` | `API_BASE_URL`, `router.get('/matchday')` | Retired — `FootballDataClient` replaces the Node.js proxy | Delete after migration |
| `captaincy-showdown/src/utils/dataLoader.ts` | `loadCSVData()` | `packages/fpl-api-client/typescript/src/csvLoader.ts` | Promote |
| `captaincy-showdown/src/utils/csvPathConfig.ts` | `getCsvPath()` | `packages/fpl-api-client/typescript/src/csvLoader.ts` | Merge (same file) |
| `captaincy-showdown/src/services/cache.ts` | Cache map logic | `packages/fpl-api-client/typescript/src/csvLoader.ts` | Merge into `loadCSVData` |
| `captaincy-showdown/src/services/http.ts` | (empty placeholder) | Deleted | File was empty |

### What imports will change

**Python — `fpl-video-repurposer/build_fpl_kb.py`:**
```python
# BEFORE (lines 14-26)
BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/?event={}"
def fetch_json(url):
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()

# AFTER
from fpl_api_client import fetch_json, get_bootstrap, get_players, get_teams, get_fixtures
```

**Python — `FPL-team-stats/app.py`:**
```python
# BEFORE (lines 1-51) — entire Flask proxy implementation
import requests as py_requests
FOOTBALL_DATA_BASE_URL = 'https://api.football-data.org/v2/'
# ...two route handlers with inline requests.get() calls...

# AFTER — slim Flask adapter
from fpl_api_client import FootballDataClient
client = FootballDataClient()  # reads FOOTBALL_DATA_API_KEY from env

@app.route('/api/premierleague/competition')
def get_competition_data():
    return jsonify(client.get_competition())

@app.route('/api/premierleague/matches')
def get_matches_data():
    return jsonify({"matches": client.get_matches()})
```

**TypeScript — `captaincy-showdown/src/utils/dataLoader.ts`:**
```typescript
// BEFORE (current file)
export async function loadCSVData<T>(url: string): Promise<T[]> { ... }

// AFTER — delete file, update all consumers:
import { loadCSVData } from '@fpl-platform/api-client';
```

**TypeScript — `captaincy-showdown/src/utils/csvPathConfig.ts`:**
```typescript
// BEFORE (current file)
export function getCsvPath(...): string { ... }

// AFTER — delete file, update all consumers:
import { getCsvPath } from '@fpl-platform/api-client';
```

**TypeScript — `captaincy-showdown/src/services/captaincyDataService.ts` (line 1-5):**
```typescript
// BEFORE
import { getCsvPath } from '../utils/csvPathConfig';
import { loadCSVData } from '../utils/dataLoader';

// AFTER
import { getCsvPath, loadCSVData } from '@fpl-platform/api-client';
```

**TypeScript — `captaincy-showdown/src/utils/performanceEnricher.ts` (line 5-6):**
```typescript
// BEFORE
import { getCsvPath } from './csvPathConfig';
import { loadCSVData } from './dataLoader';

// AFTER
import { getCsvPath, loadCSVData } from '@fpl-platform/api-client';
```

---

## Module 2: `fpl-data-core`

### What files will move

| From | File | To | Action |
|---|---|---|---|
| `captaincy-ml/ml/data/season_layouts.py` | `SeasonLayout`, `SEASON_REGISTRY`, `get_season_layout`, `list_available_seasons`, `register_season` | `packages/fpl-data-core/python/season_registry.py` | Promote; replace `_initialize_registry()` with YAML loader |
| `captaincy-ml/ml/data/season_layouts.py` | `_initialize_registry()` hardcoded Python data | `packages/fpl-data-core/season_registry.yaml` | Externalise to YAML |
| `FPL-Elo-Insights/scripts/export_data.py` | `CUMULATIVE_COLS`, `ID_COLS`, `SNAPSHOT_COLS`, `TOURNAMENT_NAME_MAP` (lines 12-43) | `packages/fpl-data-core/python/schemas.py` | Extract constants |
| `FPL-Elo-Insights/scripts/export_data.py` | `calculate_discrete_gameweek_stats()` (lines 75-186) | `packages/fpl-data-core/python/stat_calculator.py` | Extract function |
| `fpl-elo-insights-clean/scripts/export_data.py` | Same function (diverged fork) | **Reconcile differences first, then delete the fork** | Merge & delete |

### What imports will change

**Python — `captaincy-ml/ml/data/fpl_data_access.py` (line 10):**
```python
# BEFORE
from .season_layouts import get_season_layout, SeasonLayout

# AFTER
from fpl_data_core.season_registry import get_season_layout, SeasonLayout
```

**Python — `captaincy-ml/ml/data/season_id_mapper.py` (line 12):**
```python
# BEFORE
from .season_layouts import get_season_layout

# AFTER
from fpl_data_core.season_registry import get_season_layout
```

**Python — `FPL-Elo-Insights/scripts/export_data.py`:**
```python
# BEFORE (lines 12-43) — constants defined inline
CUMULATIVE_COLS = ['total_points', 'minutes', ...]
ID_COLS = ['id', 'first_name', ...]
TOURNAMENT_NAME_MAP = {'friendly': 'Friendlies', ...}

# AFTER
from fpl_data_core.schemas import (
    CUMULATIVE_COLS, ID_COLS, SNAPSHOT_COLS, TOURNAMENT_NAME_MAP
)
from fpl_data_core.stat_calculator import calculate_discrete_gameweek_stats
```

**Python — `fpl-elo-insights-clean/scripts/export_data.py`:**
```python
# BEFORE — same constants re-declared (diverged fork)
# AFTER — same imports as above (after reconciling divergence)
```

### Critical: reconciling the two `export_data.py` forks

Before migration, diff the two files to find what diverged:
```bash
diff FPL-Elo-Insights/scripts/export_data.py \
     fpl-elo-insights-clean/scripts/export_data.py
```
Resolve any intentional differences by merging them into `stat_calculator.py`, then delete the `fpl-elo-insights-clean` fork.

---

## Module 3: `fpl-player-registry`

### What files will move

| From | File | To | Action |
|---|---|---|---|
| `captaincy-ml/ml/data/season_id_mapper.py` | `SeasonIdMapper` class (full file) | `packages/fpl-player-registry/python/player_registry.py` | Inline (with updated imports) |
| `fpl-video-repurposer/build_fpl_kb.py` | `KNOWN_NICKNAMES` dict (lines 73-100) | `packages/fpl-player-registry/python/player_registry.py` | Extract |
| `fpl-video-repurposer/build_fpl_kb.py` | `SPANISH_PORTUGUESE_PATTERNS` (lines 62-70) | `packages/fpl-player-registry/python/player_registry.py` | Extract |
| `fpl-video-repurposer/build_fpl_kb.py` | `build_master_squad()` (lines 38-58) | Moved to `fpl_client.get_players()` + `get_teams()` | Already in `fpl-api-client` |
| `captaincy-ml/check_players.py` | `validation_players` dict | Convert to test fixtures in `fpl-player-registry/tests/` | Retire as script |
| `captaincy-showdown/src/utils/candidateMapper.ts` | `mapToCaptainCandidates()`, `normalizePosition()` | `packages/fpl-player-registry/typescript/src/candidateMapper.ts` | Promote |

### What imports will change

**Python — `captaincy-ml/ml/data/season_id_mapper.py`:**
```python
# BEFORE — standalone module with local import
from .season_layouts import get_season_layout

# AFTER — this file is deleted; SeasonIdMapper lives in player_registry
# Consumers update to:
from fpl_player_registry.player_registry import SeasonIdMapper
```

**Python — `captaincy-ml/phase4_tiered_recommendations.py`:**
```python
# BEFORE (implicit — SeasonIdMapper accessed through ml/data/)
# AFTER
from fpl_player_registry.player_registry import SeasonIdMapper, KNOWN_NICKNAMES
```

**Python — `fpl-video-repurposer/build_fpl_kb.py`:**
```python
# BEFORE (lines 62-100) — KNOWN_NICKNAMES and SPANISH_PORTUGUESE_PATTERNS defined inline
KNOWN_NICKNAMES = { "Salah": [...], ... }

# AFTER
from fpl_player_registry.player_registry import KNOWN_NICKNAMES, resolve_nickname
```

**Python — `fpl-video-repurposer/correct_transcript.py`:**
```python
# BEFORE — loads fpl_db/fpl_names.json directly
# AFTER
from fpl_player_registry.player_registry import build_name_lookup
from fpl_api_client import get_players
players = get_players()
lookup = build_name_lookup(players)
```

**TypeScript — `captaincy-showdown/src/services/captaincyDataService.ts` (line 3):**
```typescript
// BEFORE
import { mapToCaptainCandidates } from '../utils/candidateMapper';

// AFTER
import { mapToCaptainCandidates } from '@fpl-platform/player-registry';
```

---

## Module 4: `fpl-captain-engine`

### What files will move

| From | File | To | Action |
|---|---|---|---|
| `captaincy-showdown/src/engine/captainScore.ts` | `calculateCaptainScore()`, `updateCaptainScores()` (full file) | `packages/fpl-captain-engine/typescript/src/captainScore.ts` | Promote (zero logic change) |
| `captaincy-showdown/src/types/index.ts` | `CaptainCandidate`, `MatchupData` interfaces | `packages/fpl-captain-engine/typescript/src/captainScore.ts` | Merge into same file |
| `captaincy-ml/phase4_tiered_recommendations.py` | `TierClassifier`, `TieredRecommendation`, `TieredCaptainSelector`, `TIER_CRITERIA` | `packages/fpl-captain-engine/python/tier_classifier.py` | Extract classes |
| `captaincy-showdown/src/engine/captainScore.spec.ts` | All test cases | `packages/fpl-captain-engine/typescript/src/captainScore.spec.ts` | Move (zero changes) |
| `captaincy-showdown/src/engine/captainScore.test.ts` | All test cases | `packages/fpl-captain-engine/typescript/src/captainScore.test.ts` | Move (zero changes) |

### What imports will change

**TypeScript — `captaincy-showdown/src/services/captaincyDataService.ts` (line 5):**
```typescript
// BEFORE
import { updateCaptainScores } from '../engine/captainScore';

// AFTER
import { updateCaptainScores } from '@fpl-platform/captain-engine';
```

**TypeScript — `captaincy-showdown/src/types/index.ts`:**
```typescript
// BEFORE — types defined locally

// AFTER — re-export from shared package (so existing consumers don't break)
export type { CaptainCandidate, MatchupData } from '@fpl-platform/captain-engine';
```

**Python — `captaincy-ml/phase4_tiered_recommendations.py`:**
```python
# BEFORE (lines 18-33)
from advanced_captain_strategies import (
    AdvancedCaptainSelector, CaptainRecommendation, ...
)
@dataclass
class TieredRecommendation: ...
class TierClassifier: ...
class TieredCaptainSelector: ...

# AFTER
from fpl_captain_engine import (
    CaptainCandidate,
    calculate_captain_score, update_captain_scores,
    TieredRecommendation, TierClassifier, TieredCaptainSelector,
)
# phase4_tiered_recommendations.py becomes a thin script that
# calls the shared engine with its data, not a re-implementation.
```

---

## Module 5: `fpl-charts`

### What files will move

| From | File | To | Action |
|---|---|---|---|
| `captaincy-showdown/src/brand.ts` | `BRAND` object | `packages/fpl-charts/src/theme.ts` | Merge |
| `Top stats per week FPL/styles/main.css` | CSS custom property values | `packages/fpl-charts/src/theme.ts` | Extract as TS constants |
| `captaincy-showdown/src/components/PlayerCard.tsx` | Full component | `packages/fpl-charts/src/components/PlayerCard.tsx` | Promote |
| `captaincy-showdown/src/components/ScoreDeltaBadge.tsx` | Full component | `packages/fpl-charts/src/components/ScoreDeltaBadge.tsx` | Promote |
| `captaincy-showdown/src/components/ComparisonView.tsx` | Full component | `packages/fpl-charts/src/components/ComparisonView.tsx` | Promote |
| `captaincy-showdown/src/components/EnhancedPlayerCard.tsx` | Full component | `packages/fpl-charts/src/components/EnhancedPlayerCard.tsx` | Promote |
| `captaincy-showdown/src/components/VersusIndicator.tsx` | Full component | `packages/fpl-charts/src/components/VersusIndicator.tsx` | Promote |
| `Top stats per week FPL/scripts/chart.js` | `PlayerChart` class hierarchy | `packages/fpl-charts/src/PlayerChart.ts` | Port to TypeScript |

### What imports will change

**TypeScript — `captaincy-showdown/src/components/*.tsx` (all component files):**
```typescript
// BEFORE
import type { CaptainCandidate } from '../types';

// AFTER
import type { CaptainCandidate } from '@fpl-platform/captain-engine';
```

**TypeScript — `captaincy-showdown/src/App.tsx` and `EnhancedApp.tsx`:**
```typescript
// BEFORE
import { PlayerCard } from './components/PlayerCard';
import { BRAND } from './brand';

// AFTER
import { PlayerCard } from '@fpl-platform/charts';
import { BRAND } from '@fpl-platform/charts';
```

**HTML — `Top stats per week FPL/index.html`:**
```html
<!-- BEFORE: load chart.js inline -->
<script src="scripts/chart.js"></script>

<!-- AFTER: bundle from @fpl-platform/charts (or keep static, using theme.ts exported CSS vars) -->
```

---

## Migration Execution Order

Execute phases in this order to avoid breaking existing projects:

### Phase 1 — `fpl-data-core` (lowest risk, already tested)
1. **Reconcile** the two `export_data.py` forks (diff them, merge differences).
2. Copy `captaincy-ml/ml/data/season_layouts.py` → `packages/fpl-data-core/python/season_registry.py`.
3. Update `season_registry.py` to load from `season_registry.yaml` instead of `_initialize_registry()`.
4. Update `captaincy-ml/ml/data/fpl_data_access.py` import (1-line change).
5. Update `captaincy-ml/ml/data/season_id_mapper.py` import (1-line change).
6. Run `captaincy-ml` tests — they must still pass.
7. Extract `CUMULATIVE_COLS` / `TOURNAMENT_NAME_MAP` into `schemas.py`.
8. Update `FPL-Elo-Insights/scripts/export_data.py` to import from `fpl_data_core`.
9. Run `export_data.py` against test data to verify output.

### Phase 2 — `fpl-api-client` (requires env var setup)
1. Create Python package with `fpl_client.py` and `football_data_client.py`.
2. Update `fpl-video-repurposer/build_fpl_kb.py` — replace 4 functions with imports.
3. Update `FPL-team-stats/app.py` — replace 2 route handlers with `FootballDataClient`.
4. **Optionally retire** `football-proxy-server/` Node.js proxy (Flask already proxies).
5. Promote `csvLoader.ts` + merge `csvPathConfig.ts`, `dataLoader.ts`, `cache.ts`.
6. Update `performanceEnricher.ts` and `captaincyDataService.ts` (2 import lines each).

### Phase 3 — `fpl-player-registry` (requires Phase 1 complete)
1. Copy `season_id_mapper.py` into `player_registry.py`, update its 1 import.
2. Extract `KNOWN_NICKNAMES` from `build_fpl_kb.py`.
3. Update `build_fpl_kb.py` to import from package.
4. Promote `candidateMapper.ts`.
5. Update `captaincyDataService.ts` import (1 line).
6. Convert `check_players.py` into test fixtures.

### Phase 4 — `fpl-captain-engine` (requires Phase 3 complete)
1. Promote `captainScore.ts` verbatim — no logic changes.
2. Move test files alongside it.
3. Extract `TierClassifier` + `TieredRecommendation` from `phase4_tiered_recommendations.py`.
4. Update `captaincyDataService.ts` + `phase4_tiered_recommendations.py` imports.
5. Run all captaincy-showdown tests — they must still pass.

### Phase 5 — `fpl-charts` (requires Phase 4 complete)
1. Merge `brand.ts` + CSS colour values into `theme.ts`.
2. Promote `PlayerCard.tsx`, `ScoreDeltaBadge.tsx`, `ComparisonView.tsx`, etc.
3. Update captaincy-showdown component imports.
4. Port `PlayerChart` JS class to TypeScript.
5. Connect `Top stats per week FPL` dashboard to live data via `csvLoader.ts`.

---

## Files That Will Be Deleted After Migration

| File | Reason |
|------|--------|
| `captaincy-ml/ml/data/season_layouts.py` | Replaced by `fpl-data-core/python/season_registry.py` + YAML |
| `captaincy-ml/ml/data/season_id_mapper.py` | Replaced by `fpl-player-registry/python/player_registry.py` |
| `captaincy-ml/check_players.py` | Converted to test fixtures |
| `captaincy-showdown/src/utils/csvPathConfig.ts` | Replaced by `fpl-api-client/typescript/src/csvLoader.ts` |
| `captaincy-showdown/src/utils/dataLoader.ts` | Same |
| `captaincy-showdown/src/services/cache.ts` | Same |
| `captaincy-showdown/src/services/http.ts` | Was empty placeholder |
| `captaincy-showdown/src/engine/captainScore.ts` | Replaced by `fpl-captain-engine/typescript/src/captainScore.ts` |
| `captaincy-showdown/src/brand.ts` | Replaced by `fpl-charts/src/theme.ts` |
| `FPL-team-stats/football-proxy-server/` | Replaced by `FootballDataClient` |
| `fpl-elo-insights-clean/scripts/export_data.py` | Diverged fork — reconcile and delete |
| `FPL Capitanes V2_ARCHIVE/` | Pure archive of old FPL-Elo-Insights snapshot |

---

## Quick-reference: All Import Changes by File

### Python files

| File | Line(s) | Old import | New import |
|------|---------|-----------|-----------|
| `captaincy-ml/ml/data/fpl_data_access.py` | 10 | `from .season_layouts import get_season_layout, SeasonLayout` | `from fpl_data_core.season_registry import get_season_layout, SeasonLayout` |
| `captaincy-ml/ml/data/season_id_mapper.py` | 12 | `from .season_layouts import get_season_layout` | `from fpl_data_core.season_registry import get_season_layout` |
| `captaincy-ml/phase4_tiered_recommendations.py` | 18–33 | `from advanced_captain_strategies import ...` + local dataclasses | `from fpl_captain_engine import CaptainCandidate, TierClassifier, TieredCaptainSelector` |
| `FPL-Elo-Insights/scripts/export_data.py` | 12–43 | Constants defined inline | `from fpl_data_core.schemas import CUMULATIVE_COLS, ID_COLS, TOURNAMENT_NAME_MAP` + `from fpl_data_core.stat_calculator import calculate_discrete_gameweek_stats` |
| `fpl-elo-insights-clean/scripts/export_data.py` | Same | Same constants inline (diverged) | Same new imports (after reconcile) |
| `fpl-video-repurposer/build_fpl_kb.py` | 14–26, 62–100 | Inline `fetch_json`, `BOOTSTRAP_URL`, `KNOWN_NICKNAMES` | `from fpl_api_client import fetch_json, get_players, get_teams` + `from fpl_player_registry.player_registry import KNOWN_NICKNAMES` |

### TypeScript files

| File | Line(s) | Old import | New import |
|------|---------|-----------|-----------|
| `captaincy-showdown/src/services/captaincyDataService.ts` | 1 | `import { getCsvPath } from '../utils/csvPathConfig'` | `import { getCsvPath } from '@fpl-platform/api-client'` |
| `captaincy-showdown/src/services/captaincyDataService.ts` | 2 | `import { loadCSVData } from '../utils/dataLoader'` | `import { loadCSVData } from '@fpl-platform/api-client'` |
| `captaincy-showdown/src/services/captaincyDataService.ts` | 5 | `import { updateCaptainScores } from '../engine/captainScore'` | `import { updateCaptainScores } from '@fpl-platform/captain-engine'` |
| `captaincy-showdown/src/services/captaincyDataService.ts` | 4 | `import { mapToCaptainCandidates } from '../utils/candidateMapper'` | `import { mapToCaptainCandidates } from '@fpl-platform/player-registry'` |
| `captaincy-showdown/src/utils/performanceEnricher.ts` | 5–6 | `import { getCsvPath } from './csvPathConfig'` + `loadCSVData` | `import { getCsvPath, loadCSVData } from '@fpl-platform/api-client'` |
| `captaincy-showdown/src/components/*.tsx` | 1–2 | `import type { CaptainCandidate } from '../types'` | `import type { CaptainCandidate } from '@fpl-platform/captain-engine'` |
| `captaincy-showdown/src/App.tsx` | top | `import { BRAND } from './brand'` | `import { BRAND } from '@fpl-platform/charts'` |

---

*No files were moved or modified to produce this plan. All proposed shared modules are in `fpl-platform/packages/` as new files.*



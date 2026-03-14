# PACKAGE AUDIT — `fpl-api-client`
**Status:** Pre-adoption (not yet integrated by any project)
**Audit date:** 2026-03-07
**Risk level:** 🟡 MEDIUM

---

## Purpose

Centralises all HTTP communication with external data sources:
- **Python:** Official FPL bootstrap API, fixtures API, football-data.org API
- **TypeScript:** Browser/Node FPL API wrapper, CSV file loader with caching

Eliminates three independent "fetch a URL and parse JSON" implementations spread across three projects.

---

## Source Files Derived From

### Python

| Source file | Lines used | Action taken |
|---|---|---|
| `fpl-video-repurposer/build_fpl_kb.py` | `fetch_json` (22–26), `BOOTSTRAP_URL` (14), `FIXTURES_URL` (15), `build_master_squad` (38–57), `build_next_fixture_map` (implied) | **Extracted and generalised** into `fpl_client.py` with retry logic added |
| `FPL-team-stats/app.py` | Route handler bodies (17–51) | **Extracted** into `FootballDataClient` class. Flask app becomes a thin adapter. |
| `FPL-team-stats/football-proxy-server/src/routes/api.js` | Router handler (10–29) | **Superseded** by `FootballDataClient`; Node.js proxy can be retired |

### TypeScript

| Source file | Lines used | Action taken |
|---|---|---|
| `captaincy-showdown/src/utils/dataLoader.ts` | Full file (85 lines) | **Copied and adapted** — logic preserved; dynamic `import()` for papaparse added (see Known Risks) |
| `captaincy-showdown/src/utils/csvPathConfig.ts` | Full file (34 lines) | **Copied verbatim** into `csvLoader.ts` as `getCsvPath()` |
| `captaincy-showdown/src/services/cache.ts` | Empty file | Merged — in-memory `Map` cache built into `loadCSVData()` |
| `captaincy-showdown/src/services/http.ts` | Empty file | Superseded — `fplClient.ts` replaces it |
| `captaincy-showdown/src/services/captaincyDataService.ts` | `getFixtureDifficulty` helper (34–66) | **Ported** to `fpl_client.py::get_fixture_difficulty_map()` and `fplClient.ts::getFixtureDifficultyMap()` |

---

## What Was Copied As-Is vs Adapted

### `fpl_client.py`
- `fetch_json()` → **adapted**: added retry loop with exponential backoff (was bare `requests.get()`)
- `get_bootstrap()` / `get_players()` / `get_teams()` → **new wrappers** around bootstrap JSON fields; field selection matches `build_master_squad()` exactly
- `get_fixture_difficulty_map()` → **new function** ported from TS `getFixtureDifficulty()` helper in `captaincyDataService.ts`

### `football_data_client.py`
- `get_competition()` / `get_matches()` → **adapted**: inline route handlers extracted into a class; header auth unchanged
- `get_finished_matches()` → **new helper** encapsulating the `status === 'FINISHED'` filter from `script.js::calculateTeamStats()`

### `csvLoader.ts`
- `loadCSVData<T>()` → **adapted**: the Node.js filesystem fallback (`readFromFs`) that checks `import.meta.vitest` was **removed** and replaced with a dynamic `import("papaparse")`. This changes Vitest behaviour — see Known Risks.
- `getCsvPath()` → **copied verbatim**

---

## Assumptions

1. `get_bootstrap()` is the canonical source of player and team identity. Consumers should call it once per session and pass the result to `get_players()` and `get_teams()` to avoid double-fetching.
2. The FPL API is public and requires no authentication. `football-data.org` requires an API key passed as `FOOTBALL_DATA_API_KEY` env variable.
3. `getCsvPath()` assumes CSV files are served from the app's `/data/` base URL (relative to window origin in browser, `public/data/` on filesystem in tests).
4. Retry logic in `fpl_client.py` uses 3 attempts with 2×backoff. The original `build_fpl_kb.py` had no retries.

---

## Known Risks

### 🔴 CRITICAL: `loadCSVData` Vitest filesystem fallback was removed
The original `dataLoader.ts` has a special `isVitest` branch that reads CSV files directly from the filesystem under `public/`. The shared `csvLoader.ts` uses dynamic `import("papaparse")` instead and does **not** have this fallback.

**Impact:** All existing `captaincy-showdown` tests that call `loadCSVData` (via `captaincyDataService.ts`, `performanceEnricher.ts`) will fail in Vitest after migration unless either:
  - (a) The `isVitest` filesystem fallback is reinstated in the shared module, OR
  - (b) Tests are refactored to mock `loadCSVData` at the boundary

**Action required:** Before `captaincy-showdown` adopts this package, decide which approach to take and adjust `csvLoader.ts` accordingly.

### 🟡 MEDIUM: `football-data.org` uses v2 in source, v4 in shared module
`FPL-team-stats/football-proxy-server/src/routes/api.js` calls `/v2/competitions/2025` (note: competition ID `2025`, not `2021`). The Flask `app.py` uses `/v2/competitions/2021`. The shared `FootballDataClient` defaults to `v4` and ID `2021`. The Node.js proxy used a different competition ID entirely — this inconsistency existed before this package.

**Action required:** Confirm the correct competition ID and API version with the project owner before retiring the proxy.

### 🟡 MEDIUM: No rate-limiting on FPL bootstrap calls
The official FPL API is unofficial/undocumented with no published rate limits. Hitting it too frequently can result in temporary 429 bans. The shared client has retry logic but no proactive rate limiting or cache-to-disk.

### 🟢 LOW: `FootballDataClient` only covers Premier League
The class defaults to competition ID 2021 (PL) and only exposes competition + matches endpoints. Any future multi-league use case needs additional methods.

### 🟢 LOW: `fplClient.ts` uses browser-native `fetch`
Works in all modern browsers and Node.js 18+. Not compatible with Node.js < 18 without a polyfill. `captaincy-showdown` uses Vite/browser targets, so this is not currently a problem.

---

## Dependencies

### Python
| Dependency | Version | Notes |
|---|---|---|
| `requests` | ≥ 2.25 | HTTP calls |

### TypeScript
| Dependency | Version | Notes |
|---|---|---|
| `papaparse` | ≥ 5.x | CSV parsing |
| Browser `fetch` | — | Native; Node 18+ polyfill not needed |

---

## Acceptance Criteria for First Adoption

- [ ] Smoke tests in `TEST_PLAN.md` pass against live FPL API (bootstrap returns ≥ 500 players, ≥ 20 teams)
- [ ] `FootballDataClient.get_competition()` returns the same payload structure as the retired Flask proxy
- [ ] `getCsvPath()` produces identical paths for all test cases compared to the original `csvPathConfig.ts`
- [ ] `loadCSVData` Vitest behaviour decision documented and implemented
- [ ] `fpl-video-repurposer/build_fpl_kb.py` produces identical `master_squad.json` after switching to `fpl_client.py`



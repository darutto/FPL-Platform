# Phase 0 Post-Migration Report
**Package:** `fpl-captain-engine` (TypeScript)
**Pilot target:** `captaincy-showdown`
**Date:** 2026-03-08
**Status:** ✅ VALIDATED — integration successful, no regressions

---

## 1. Package Validated

`fpl-platform/packages/fpl-captain-engine/typescript/src/captainScore.ts`

This is a verbatim copy of `captaincy-showdown/src/engine/captainScore.ts`. The platform package exports `calculateCaptainScore`, `updateCaptainScores`, `CaptainCandidate`, and `MatchupData` through a new `index.ts` entry point. It has zero external npm dependencies and no upstream (fpl-elo-insights) entanglement — Tier A fully owned.

---

## 2. Files Changed

### Created (platform)

| File | Description |
|------|-------------|
| `fpl-platform/packages/fpl-captain-engine/typescript/src/index.ts` | Public entry point; re-exports all four symbols from `captainScore.ts` |

### Modified (captaincy-showdown pilot)

| File | Change |
|------|--------|
| `src/services/captaincyDataService.ts` | Line 5: import source changed from `'../engine/captainScore'` to `'@fpl-platform/fpl-captain-engine'` |
| `vite.config.ts` | Added `import path from 'path'` and `resolve.alias` mapping `@fpl-platform/fpl-captain-engine` to the platform source (dev/build alias) |
| `vitest.config.ts` | Same `resolve.alias` added (test-time resolution) |
| `tsconfig.app.json` | Added `paths` entry for TypeScript type resolution; expanded `include` to cover the platform source tree |

No other files in captaincy-showdown or any other project were modified.

---

## 3. Parity Validation Result

Before touching any project files, the engine logic was validated offline using plain Node.js (no bundler, no vitest — required because Windows `node_modules` are incompatible with the Linux VM).

**Run:** `node run_parity.mjs` — 14 / 14 passed

| Group | Tests | Result |
|-------|-------|--------|
| §SPEC — captainScore.spec.ts coverage | 4 | ✅ All passed |
| §TEST — captainScore.test.ts coverage | 5 | ✅ All passed |
| Additional guards (clamping, immutability, edge cases) | 5 | ✅ All passed |

**Compatibility surface check:** `node run_compatibility_check.mjs` — 11 / 11 passed

Verified: `updateCaptainScores` accepts `CaptainCandidate[]`, returns mutated array with correct `captain_score` values for 7 input profiles (Haaland, Salah, Foden, Kane, worst-case, best-case, extreme-clamp). Output matches captaincyDataService.ts usage pattern exactly.

---

## 4. Local Test Results (captaincy-showdown, post-fix)

```
Test Files  6 failed | 16 passed (22)
      Tests  29 passed (29)
   Duration  9.77s
```

### Passing suites (16 / 22)

All migration-relevant tests pass. The captain score logic is unchanged end-to-end:

| Suite | Tests |
|-------|-------|
| `src/__tests__/captainScore.test.ts` | 3 |
| `src/engine/captainScore.test.ts` | 3 |
| `test/captainScore.test.ts` | 3 |
| `src/engine/captainScore.spec.ts` | 1 |
| `src/__tests__/dataEngine.epicA.test.ts` | 3 |
| `src/__tests__/epicA1.enricher.mapper.test.ts` | 3 |
| `src/__tests__/ui.enhancedApp.compareFlow.test.tsx` | 1 |
| `src/__tests__/ui.enhancedPlayerCard.a11yState.test.tsx` | 1 |
| `src/__tests__/ui.enhancedPlayerCard.focus.test.tsx` | 1 |
| `src/__tests__/ui.playerCard.render.test.tsx` | 2 |
| `src/__tests__/ui.playerCard.a11y.test.tsx` | 1 |
| `src/__tests__/ui.comparisonView.test.tsx` | 1 |
| `src/__tests__/ui.comparisonView.deltaBadge.test.tsx` | 1 |
| `src/__tests__/ui.comparisonView.responsive.test.tsx` | 1 |
| `src/__tests__/ui.captaincyComparison.render.test.tsx` | 1 |
| `src/__tests__/ui.scoreDeltaBadge.test.tsx` | 3 |

### Failing suites (6 / 22) — see Section 6

`cache`, `csv`, `dataClient`, `dataConfig`, `http`, `useData` — all pre-existing empty stubs, unrelated to the migration.

---

## 5. Root Cause of Integration Issue and Its Fix

### Symptom

After the initial alias configuration, the `@fpl-platform/fpl-captain-engine` import in `captaincyDataService.ts` failed to resolve at both build and test time. The captain score logic tests passed (they import `captainScore.ts` directly), which masked the service-layer failure.

### Root cause

The relative path used in all three config files was one directory level too deep:

```
Captaincy-showdown root:  C:/Users/thera/FPL-Elo-Insights/apps/captaincy-showdown/
fpl-platform root:        C:/Users/thera/fpl-platform/

Levels up needed:
  ../   → apps/
  ../../ → FPL-Elo-Insights/
  ../../../ → C:/Users/thera/   ← correct landing directory

Used:  ../../../../fpl-platform/...  (resolves to C:/Users/fpl-platform/ — does not exist)
Fixed: ../../../fpl-platform/...    (resolves to C:/Users/thera/fpl-platform/ — correct)
```

### Fix applied

Four path occurrences corrected across three files:

| File | Location | Before | After |
|------|----------|--------|-------|
| `vite.config.ts` | `resolve.alias` value | `../../../../fpl-platform/...` | `../../../fpl-platform/...` |
| `vitest.config.ts` | `resolve.alias` value | `../../../../fpl-platform/...` | `../../../fpl-platform/...` |
| `tsconfig.app.json` | `paths` entry | `../../../../fpl-platform/...` | `../../../fpl-platform/...` |
| `tsconfig.app.json` | `include` entry | `../../../../fpl-platform/...` | `../../../fpl-platform/...` |

---

## 6. Why the 6 Failing Suites Are Unrelated to This Migration

The six failing files are completely empty (0 bytes):

```
src/__tests__/cache.test.ts
src/__tests__/csv.test.ts
src/__tests__/dataClient.test.ts
src/__tests__/dataConfig.test.ts
src/__tests__/http.test.ts
src/__tests__/useData.test.tsx
```

Vitest collects these because they match the include pattern `src/**/*.{test,spec}.{ts,tsx}` but emits `Error: No test suite found in file` because they contain no `describe`, `test`, or `it` blocks. This error class existed before Phase 0 began and is unaffected by:
- The import change in `captaincyDataService.ts`
- The alias additions in `vite.config.ts` and `vitest.config.ts`
- The `paths` additions in `tsconfig.app.json`

They represent planned-but-unwritten tests for `cache.ts`, `csv.ts`, `dataClient.ts`, `dataConfig.ts`, `http.ts`, and `useData.ts`. They are pre-existing project debt, not migration regressions. See Section 7 for handling options.

---

## 7. Empty Stub File Recommendation

The six empty files give a false failure signal: all 29 actual tests pass but the run exits non-zero. There are three options.

### Option A — Replace each with `it.todo(...)` (Recommended)

Add a single `describe` block with `it.todo` stubs to each file:

```typescript
// example: src/__tests__/cache.test.ts
import { describe, it } from 'vitest'

describe('cache', () => {
  it.todo('returns cached value on second call')
  it.todo('expires entry after TTL')
})
```

**Why this is recommended:**
- Converts hard `FAIL` to Vitest's built-in `todo` state (yellow, not red), so `npm run test:run` exits 0
- The todo stubs document _what_ coverage is expected, not just that a file exists
- No configuration changes required; files stay in the include pattern as reminders
- Consistent with how Vitest's own test suite signals planned-but-not-yet-written tests

### Option B — Rename so Vitest does not collect them

Rename each file from `*.test.ts` → `*.todo.ts` (or move to `src/__tests__/todo/`):

```
src/__tests__/cache.todo.ts
src/__tests__/csv.todo.ts
...
```

**Tradeoff:** Removes false failures immediately with zero content. However, `*.todo.ts` is not a standard convention and IDE tooling may not recognise the files as test stubs. Also requires a `vitest.config.ts` change to the exclude list if you want to be explicit, or relies on the include pattern not matching.

### Option C — Leave as-is

No change. The 6 failures are clearly labelled "No test suite found" and do not affect the 29 passing tests.

**Tradeoff:** The CI exit code will always be non-zero until tests are written. This makes it impossible to use `npm run test:run` as a gating check (e.g. in a pre-commit hook or CI pipeline) without ignoring the exit code — which would mask real failures.

### Decision required

Option A is recommended. It converts false failures to intentional signals without hiding the coverage gap or requiring config changes. **Do not execute until approved.**

---

## 8. Rollback Steps

If the pilot needs to be reverted to the pre-Phase-0 state:

**Step 1 — Revert the import in `captaincyDataService.ts` (line 5):**
```diff
- import { updateCaptainScores } from '@fpl-platform/fpl-captain-engine'; // Phase 0 pilot
+ import { updateCaptainScores } from '../engine/captainScore';
```

**Step 2 — Remove the `resolve.alias` block from `vite.config.ts`:**
Remove the `import path from 'path'` line and the `resolve: { alias: { ... } }` block.

**Step 3 — Remove the `resolve.alias` block from `vitest.config.ts`:**
Same removal as Step 2.

**Step 4 — Revert `tsconfig.app.json`:**
Remove the `paths` key from `compilerOptions` and remove the platform source path from `include`.

**Step 5 (optional) — Delete the platform `index.ts`:**
`fpl-platform/packages/fpl-captain-engine/typescript/src/index.ts` can be deleted. The underlying `captainScore.ts` is untouched.

Running `npm run test:run` after rollback should return to the pre-Phase-0 state (25 tests passing, same 6 stub failures as before).

---

## 9. Lessons Learned for Future Package Adoption

**L1 — Always calculate relative paths from the consuming project root, not from a subdirectory.**
The `../../../../` error was caused by mentally counting from `src/services/` rather than from the project root. For future aliases, write the full Windows path of both endpoints on paper first, then count `../` jumps from the project root.

**L2 — Keep the platform `index.ts` as the only public surface.**
`captaincyDataService.ts` now imports from `@fpl-platform/fpl-captain-engine` (the index), not directly from `captainScore.ts`. This allows internal file reorganisation inside the package without touching consumers.

**L3 — Parity tests must be runnable without a bundler.**
The Linux VM cannot run Vitest against Windows `node_modules`. The plain-Node `.mjs` parity test pattern (`node:assert/strict`, no imports from the test framework) should be used for all future pre-commit logic verification on shared packages.

**L4 — Validate the alias resolves before modifying the consumer import.**
In retrospect, the correct order is: (a) add alias to config, (b) verify resolution with a dummy `console.log(require.resolve(...))` or dry run, (c) then change the import. Changing the import first made the failure harder to localise.

**L5 — Three configs must stay in sync for full toolchain coverage.**
Vite (runtime/build), Vitest (tests), and `tsconfig` (type-checking) each resolve modules independently. A missing or wrong path in any one of them will break a different part of the workflow silently. For each future platform package onboarded, update all three in the same commit.

**L6 — Empty stub files cause non-zero exit codes.**
A test run that exits non-zero cannot be used as a reliable CI gate. Before onboarding the next package, the empty stubs should be resolved (see Section 7, Option A) so the baseline is a clean green run.

---

## 10. Phase 0 Summary

| Item | Outcome |
|------|---------|
| Engine logic parity | ✅ 14/14 assertions |
| Compatibility surface | ✅ 11/11 checks |
| Import alias resolution | ✅ Fixed (3→4 level path correction) |
| captaincyDataService.ts pilot | ✅ Integrated |
| Migration regressions | ✅ None |
| Pre-existing failures | 6 empty stubs (unchanged from baseline) |
| Tests passed | 29 / 29 |
| Phase 0 gate | **PASSED** |



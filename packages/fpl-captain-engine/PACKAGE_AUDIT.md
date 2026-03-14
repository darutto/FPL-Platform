# PACKAGE AUDIT — `fpl-captain-engine`
**Status:** Pre-adoption (not yet integrated by any project)
**Audit date:** 2026-03-07
**Risk level:** 🟢 LOW (TypeScript) / 🟡 MEDIUM (Python)

---

## Purpose

The single canonical implementation of captain scoring and tier classification:
- **TypeScript:** `calculateCaptainScore()` and `updateCaptainScores()` — the battle-tested, fully unit-tested scoring formula
- **Python:** `captain_score.py` — exact port of the TS formula; `tier_classifier.py` — tier classification from Phase 4

---

## Source Files Derived From

| Source file | Lines used | Action taken |
|---|---|---|
| `captaincy-showdown/src/engine/captainScore.ts` | Full file (50 lines) | **Copied verbatim** — zero logic changes |
| `captaincy-showdown/src/types/index.ts` | Full file (23 lines) | **Merged** into `captainScore.ts` (types live alongside functions) |
| `captaincy-ml/phase4_tiered_recommendations.py` | `TieredRecommendation` dataclass (lines 20–48), `TierClassifier` class (~50–120), `TieredCaptainSelector` (~120–190), `TIER_CRITERIA` constants | **Extracted** into `tier_classifier.py` |
| `captaincy-showdown/src/engine/captainScore.spec.ts` | All tests | Intended to move alongside — **not yet moved** |
| `captaincy-showdown/src/engine/captainScore.test.ts` | All tests | Intended to move alongside — **not yet moved** |

---

## What Was Copied As-Is vs Adapted

### `captainScore.ts`
**Copied verbatim.** The only change is that `CaptainCandidate` and `MatchupData` interfaces (previously in `src/types/index.ts`) are now co-located in the same file. Import paths in consumers change; logic does not.

### `captain_score.py`
**New file — rewrite in Python.** The maths are a direct port of the TypeScript formula:
```
score = form(0-10 → 0-100) × 0.4
      + fixture(1-5 → 0-100) × 0.3
      + xGI/90(0-2 → 0-100) × 0.2
      + (100 - minutes_risk) × 0.1
```
All normalisation and clamping behaviour is identical. The `CaptainCandidate` dataclass mirrors the TypeScript interface field-for-field.

### `tier_classifier.py`
**Extracted and lightly adapted.** `TieredRecommendation` and `TierClassifier` are directly from `phase4_tiered_recommendations.py`. `TieredCaptainSelector` is reconstructed from the documented intent (5 Premium + 3 Differential + 2 Outlier) because the original `TieredCaptainSelector` in the source depended on the missing `AdvancedCaptainSelector` — which does not exist. The tier selection logic itself (sorting by score, bucketing) matches the Phase 4 comments and documentation.

---

## Assumptions

1. The scoring formula weights (40/30/20/10) are **canonical across both languages**. Any change to these weights must be applied to both `captainScore.ts` and `captain_score.py` simultaneously.
2. `form_score` represents the player's last-4-GW average point score divided by 10 for normalisation. If data sources change this convention (e.g. raw form string from FPL API), callers must normalise before passing to the engine.
3. `fixture_difficulty` is on a 1–5 integer scale (1 = easiest). This matches both the FPL API `team_h_difficulty`/`team_a_difficulty` fields and the `captaincyDataService.ts` logic.
4. `minutes_risk` is on a 0–100 scale where 100 = certain non-starter. Callers must convert FPL's `chance_of_playing_next_round` (0–100 where 100 = certain starter) by inverting: `minutes_risk = 100 - chance`.

---

## Known Risks

### 🔴 HIGH: `phase4_tiered_recommendations.py` depends on a missing file
`captaincy-ml/phase4_tiered_recommendations.py` imports `advanced_captain_strategies.py` which does not exist in the repository. This means:
- The source of `TieredCaptainSelector`'s full Phase 4 behaviour cannot be verified against the original
- The `tier_classifier.py` reconstruction is based on documentation and inline comments, not the running code

**Impact on this package:** `tier_classifier.py` is a functional, self-contained implementation. However, it cannot be verified as behaviourally identical to the original Phase 4 system because the original cannot run.

**Action required:** Locate or reconstruct `advanced_captain_strategies.py` and run side-by-side comparison before marking `tier_classifier.py` as a verified port.

### 🟡 MEDIUM: Floating-point parity between Python and TypeScript
The scoring formula uses JavaScript `Math.min(Math.max(...))` clamping vs Python `min(max(...))`. For extreme inputs these are equivalent. For normal FPL inputs (form 0–15, xGI 0–2, risk 0–100) the outputs will be numerically identical. However:
- JavaScript uses 64-bit IEEE 754 doubles
- Python uses arbitrary precision for intermediate calculations before converting to float
For form = 9.999999999 style edge cases, outputs may differ by ±ε. This is unlikely in practice but should be verified in parity tests.

### 🟢 LOW: Test files not yet relocated
`captainScore.spec.ts` and `captainScore.test.ts` remain in `captaincy-showdown/src/engine/`. They should move to this package. Until they do, running `vitest` in the shared package will report 0 tests.

### 🟢 LOW: `TieredCaptainSelector` TIER_SIZES are hardcoded
5 Premium + 3 Differential + 2 Outlier is hardcoded in `TIER_SIZES`. The source documentation suggests these might be configurable per YouTube series context. Making this configurable would require a constructor argument.

---

## Dependencies

### Python
| Dependency | None | Notes |
|---|---|---|
| stdlib only | — | `dataclasses`, `typing`. No external packages. |

### TypeScript
| Dependency | Version | Notes |
|---|---|---|
| None | — | Pure TypeScript, no runtime dependencies |

This is the only package with **zero external runtime dependencies** in both languages.

---

## Acceptance Criteria for First Adoption

**TypeScript (highest confidence):**
- [ ] All existing `captainScore.test.ts` tests pass when pointed at this package
- [ ] All existing `captainScore.spec.ts` tests pass
- [ ] `calculateCaptainScore({form:8.5, fixture_difficulty:2, xgi_per_90:1.8, minutes_risk:10})` returns `≈ 87.0` (from existing test)

**Python:**
- [ ] `calculate_captain_score(form=8.5, fixture_difficulty=2, xgi_per_90=1.8, minutes_risk=10)` returns the same value (within 1e-10) as the TypeScript formula
- [ ] `update_captain_scores()` sets `captain_score` on all candidates without mutation errors
- [ ] `TierClassifier` produces at least 1 premium, 1 differential, and 1 outlier for a realistic 20-player input set

**Overall:**
- [ ] `advanced_captain_strategies.py` situation documented and resolved



---
title: Agentic-loop class-2 grader fixes + composition wiring
found_via: code review of newly-implemented Q10/Q11 validators and experiment driver
captured: 2026-08-19
relevant_to: [fixtures, orchestrator, instruments, tooling]
status: fixed
---

## Summary

Fixed three high-severity defects in the class-2 ("composition") grader that prevented any fixture validation, then wired the composition check into the experiment driver so composition pass/fail rates are recorded and reported.

## What prompted this

Class-2 scenarios (Q10/Q11) were added to measure whether agentic loops improve answer quality by composing multiple tools (ranking + fixture grounding). The grader was implemented but had three critical bugs:
1. Fixture lookup used int keys against a string-keyed bootstrap
2. Tests masked the bug by reshaping bootstrap
3. Composition validation was never called from the driver

### Defects

#### 1. Fixture grounding lookup bug — severity: **high**
**What happens:** Grading a correct Q10 payload (with fixtures from bootstrap) returns `invalid` with errors like `fixture_evidence_gw_not_found`, when it should be `valid`.

**Evidence:** 
- Frozen bootstrap (`agentic-loop-bootstrap-2026-08-18.json`) has `team_fixtures` with **string keys**: `{"1": [...], "2": [...], ...}`
- Grader lookup used `team_fixtures.get(rec_team, [])` where `rec_team` is an int (1, 2, ...)
- Int lookup `team_fixtures.get(1)` returns `[]`, empty list
- Fixture validation then fails on every entry with `fixture_evidence_gw_not_found`
- **Result:** Dead check; always fails immediately regardless of payload correctness

**Where:** `experiment_measurement.py:652` (before fix)

**Why it happens:** JSON deserialization creates string keys. Code assumed int keys (or didn't verify both patterns).

**Fix:** Use tolerant pattern `team_fixtures.get(rec_team) or team_fixtures.get(str(rec_team)) or []` (already used elsewhere in codebase, e.g., `fixture_outlook.py:286`).

**Verification:** ✓ Payload built from bootstrap's own team_fixtures now validates as valid ✓ Mutations (difficulty, opponent_team, is_home) detected with specific error codes

---

#### 2. Test bootstrap reshaping masks the bug — severity: **high**
**What happens:** Tests manually convert `team_fixtures` keys from strings to ints before grading. This fixes Defect 1 locally, so the test passes even though production code is broken.

**Evidence:** `test_class2_grader.py:31-36` (before fix):
```python
bootstrap_raw["team_fixtures"] = {
    int(team_id): fixtures for team_id, fixtures in team_fixtures.items()
}
```
This normalization reshapes the bootstrap *before* any grading happens. If the bug (int lookup) were not there, the test would fail.

**Where:** `test_class2_grader.py:24-37`

**Why it happens:** A well-intentioned attempt to normalize data, but tests must load the frozen artifact **exactly as the driver does** (`json.load()` and nothing else). Any reshaping hides the class of bug that just shipped.

**Fix:** Remove normalization. Load with plain `json.load()` and keep string keys.

**Verification:** ✓ Bootstrap keys remain strings ✓ Tests now catch Defect 1 immediately

---

#### 3. Composition check doesn't exist in production — severity: **high**
**What happens:** The experiment driver never calls `check_composition`, so composition pass/fail data is never recorded. The summary table has no Composition column. A paid run yields zero composition data despite this being the entire reason class-2 scenarios exist.

**Evidence:** 
- `check_composition()` function implemented and unit-tested in `experiment_measurement.py:514-553`
- Driver (`run_agentic_loop_experiment.py:415-418`) imports only `classify_user_visible` and `grade_structured_output`
- No call to `check_composition` at observation recording site (~line 498-511)
- No Composition column in summary table (line 321)

**Where:** `scripts/run_agentic_loop_experiment.py` (observation recording and artifact rendering)

**Why it happens:** The function was implemented (PR during class-2 scenario addition) but integration was never completed.

**Fix:** 
1. Import `check_composition` in driver
2. Record result for every observation (Q10/Q11 get composition check; Q6/Q7/Q9 get `not_applicable`)
3. Add Composition column to summary table with per-arm counts

**Verification:** ✓ Q10/Q11 observations record composition result ✓ Q6/Q7/Q9 record not_applicable ✓ Summary table includes Composition column ✓ Composition distinguishes arms: A/B show `✓0 ✗3` (can't compose), C/D show `✓3 ✗0` (can compose)

---

### Additional fix: Rendering ambiguity + unknown status

#### 4. Composition "0/3" collides with catastrophic rate — severity: **med**
**What happens:** The Composition column used format `0/3` (e.g., `0 valid, 3 invalid`), which is identical in appearance to the Catastrophic rate column's `0/3` (0 failures, 3 total). They sit adjacent and mean opposite things.

**Evidence:** Before fix, summary table:
```
| ... | Catastrophic rate | Axis 2 | Composition | ...
| ... | 0/3 (good, no failures) | ... | 0/3 (bad, no valid) | ...
```

**Fix:** Render composition as `✓N ✗M` (e.g., `✓0 ✗3`) to avoid collision. Keeps `not_applicable` as-is.

**Verification:** ✓ Visual distinction from catastrophic column ✓ Arms A/B show `✓0 ✗3`, arms C/D show `✓3 ✗0` (clearly different)

---

#### 5. Unknown/missing composition status renders as measured result — severity: **high**
**What happens:** `summarize_composition()` silently drops rows with missing `composition` key. A `worker_error` run with 3 observations (no composition recorded) renders as `0/0`, which looks like "measured nothing" rather than "didn't measure".

**Evidence:** `summarize_composition([{}, {}])` before fix → `{'valid':0, 'invalid':0, 'not_applicable':0}`, rendered as `0/0`. No indication that data was missing.

**Where:** `experiment_measurement.py:793-804` (before fix)

**Why it happens:** Function only counted known statuses and defaulted unknown to zero.

**Fix:** 
1. Add `unknown` bucket to summary
2. Count rows with missing `composition` key as unknown
3. Render as `—` (or `✓N ✗M (?U)` if partial unknown) to visibly distinguish from measured values

**Verification:** ✓ `summarize_composition([{}, {}])` reports `{'valid':0, 'invalid':0, 'not_applicable':0, 'unknown':2}` ✓ All unknown renders as `—` (distinct from measured) ✓ Partial unknown renders with indicator (e.g., `✓1 ✗1 (?1)`)

---

## Open questions

None. All defects fixed, wiring complete, verification passed.

## Commits / PRs

All changes in worktree `exp/agentic-loop` (not yet merged to main):
- Defect 1 fix: `experiment_measurement.py:652`
- Defect 2 fix: `test_class2_grader.py:24-31` (normalization removed)
- Defect 3 wiring: `scripts/run_agentic_loop_experiment.py:280, 421-425, 522-527`; `experiment_measurement.py:793-824`
- Rendering fixes: `experiment_measurement.py:793-824`, `scripts/run_agentic_loop_experiment.py:328-336`

## Verification artifacts

All verification deterministic (no API calls):
- Direct mutation testing against frozen bootstrap (2026-08-18)
- Correct payload validates as valid
- Mutations (difficulty, opponent_team, is_home) produce distinct error codes
- Composition logic verified: single-tool fails, priced+fixture passes
- Rendering logic verified: no collision with catastrophic column, unknown status visibly distinct
- All existing tests still pass (no regressions)

See `test_composition_wiring.py` and `test_composition_rendering_fix.py` in scratchpad for verification scripts (both pass ✓).

---

## Impact on downstream work

### For the agentic-loop experiment (primary)

When operator runs the paid experiment with this branch:
- Q10/Q11 observations will record composition pass/fail (was silent before)
- Summary table will show Composition column with `✓N ✗M` format
- Arms A/B will show `✓0 ✗N` (baseline can't compose; expected control)
- Arms C/D will show `✓N ✗M` (loop treatment effect)
- Worker errors will show `—` (not confused with measured results)

### For class-2 future work

Composition is now measurable and reported. Future refinements to the orchestrator or class-2 scenarios can rely on this data.

### For field-notes housekeeping

Documentation consolidated from package root into this single entry. Previous files deleted to avoid rot.

# FPL Grounded Assistant - UAT Findings Template

## Session Summary

| Field | Value |
|---|---|
| Tester |  |
| Date |  |
| Build / branch |  |
| Scope | V1.5 (phases 8a1 / 8b / 8c / 8d / 8e / 8f) |
| Data mode | Live data / Fallback debug |
| Primary surface | CLI REPL |
| Secondary surfaces used |  |
| Validation runner result | N/44 PASS (run `python run_validation.py`) |
| Overall recommendation | Go / No-Go |

---

## Severity Rubric

| Severity | Meaning |
|---|---|
| blocker | Crash, unusable manual path, invented facts, wrong core routing, broken session behavior, broken structured contract |
| major | Materially misleading answer, repeated failure on supported prompts, missing key structured metadata, severe clarity issue |
| minor | Limited wording or usability issue that does not break trust or task completion |
| polish | Improvement idea only |

---

## Findings Log

| ID | Scenario ID | Surface | Prompt Or Sequence | Expected Semantics | Actual Result | Structured Check | Severity | Owner | Action |
|---|---|---|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |  |  |

---

## Blockers

Record only active blocker issues here.

| ID | Summary | Repro | Status |
|---|---|---|---|
| B1 |  |  |  |

---

## Major Issues

| ID | Summary | Repro | Status |
|---|---|---|---|
| M1 |  |  |  |

---

## V1.5 Structured Checks Summary

Quick reference for the V1.5-specific checks. Update as you run them.

| Check ID | Area | Expected | Status | Notes |
|---|---|---|---|---|
| P8A-01–05 | Position-aware scoring | `position_score` in comparison JSON (CLI + HTTP); transfer uses `score_delta` (position-score-based delta); differential ranking is position-score-based internally (`position_score` not a serialized JSON field) | | |
| P8B-01–08 | Venue-aware FDR | `is_home` + `effective_fdr` in comparison context | | |
| P8C-01–05 | Free hit signal | `chip.signal_label` correct for current GW type | | |
| SES-06–07 | Session follow-ups | fixture_run + differential follow-up routes deterministically | | |
| P8E-01–06 | Budget constraint + chip unavailable | Hard blocks fire and do not persist | | |
| P8E-07–09 | Hit warning | Advisory flag fires only for marginal_transfer_in + FT==1 | | |
| P8E-11–12 | Session statelessness | Constraint absent on next turn without squad_context | | |

---

## Notes On Style And Trust

Capture short observations here:
- Are recommendations grounded and concise?
- Are unsupported answers explicit enough?
- Do follow-up turns feel natural and correctly scoped?
- Does debug output help rather than confuse?
- Do squad_context constraints produce clear, actionable messages (not error noise)?

---

## Final Recommendation

### Go / No-Go

Write one short paragraph here.

### Recommended Next Action

Choose one:
- fix blockers before any new feature work
- run a second focused UAT pass after fixes
- proceed to carefully scoped post-MVP prioritization
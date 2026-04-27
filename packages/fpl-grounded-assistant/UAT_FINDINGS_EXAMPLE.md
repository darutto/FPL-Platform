# FPL Grounded Assistant - UAT Findings Example (V1.5)

This file shows what a complete V1.5 UAT findings record looks like.
All values marked `[SAMPLE: ...]` are illustrative — replace with your own observations.
Copy `UAT_FINDINGS_TEMPLATE.md` to a dated `UAT_FINDINGS_YYYYMMDD.md` before your pass — see `UAT_ARCHIVE_CONVENTION.md`.

---

## Session Summary

| Field | Value |
|---|---|
| Tester | [SAMPLE: Operator initials or name] |
| Date | [SAMPLE: 2026-04-05] |
| Build / branch | [SAMPLE: main, working tree] |
| Scope | V1.5 (phases 8a1 / 8b / 8c / 8d / 8e / 8f) |
| Data mode | [SAMPLE: Live data — GW32, 823 players loaded] |
| Primary surface | CLI REPL |
| Secondary surfaces used | [SAMPLE: Single-turn CLI `--debug`, HTTP `/ask`, HTTP `/session`] |
| Validation runner result | [SAMPLE: 44/44 PASS] |
| Overall recommendation | [SAMPLE: Go] |

---

## Findings Log

| ID | Scenario ID | Surface | Prompt Or Sequence | Expected Semantics | Actual Result | Structured Check | Severity | Owner | Action |
|---|---|---|---|---|---|---|---|---|---|
| 1 | P8B-07 | REPL `--debug` | `compare Salah and Saka` | REPL debug line shows `efdr=N.N(H)` for each player | [SAMPLE: Salah showed `efdr=3.5(H)`; Saka showed `efdr=4.5(H)`. Both home this GW. Values match raw FDR with −0.5 home adjustment.] | [SAMPLE: Pass — `is_home` and `effective_fdr` correct] | pass | — | none |
| 2 | P8C-01 | CLI `--debug` | `should I free hit this week` | `chip.signal_label` = `"normal gameweek"` for current GW | [SAMPLE: `chip.signal_label: "normal gameweek"`, `signal_value: 0.0`, `recommendation: "conditions_unfavorable"`. Matches current GW type.] | [SAMPLE: Pass — chip JSON correct] | pass | — | none |
| 3 | P8E-01 | CLI `--debug` | `should I sell Saka for Salah --itb 2.0` | `transfer.budget_constraint: true`; final_text contains budget message | [SAMPLE: `budget_constraint: true`. Final text: "Unable to recommend this transfer: your available budget (£2.0m) is less than the upgrade cost."] | [SAMPLE: Pass] | pass | — | none |
| 4 | P8E-11 | HTTP session | Turn 1 with `itb:20` → Turn 2 no squad_context | Turn 2 `transfer.budget_constraint` must be `false` | [SAMPLE: Turn 1 `budget_constraint: true`. Turn 2 `budget_constraint: false`. Constraint correctly not persisted.] | [SAMPLE: Pass — statelessness confirmed] | pass | — | none |
| 5 | SES-07 | REPL `--debug` | `good differentials this week` → `what about Mbeumo?` | Turn 2 routes to `captain_score`; `resolver_source = "differential_followup"` | [SAMPLE: Turn 2 `intent: captain_score`, `captain.web_name: "Mbeumo"`, `debug.resolver.resolver_source: "differential_followup"`. No LLM resolver used.] | [SAMPLE: Pass — deterministic follow-up confirmed] | pass | — | none |
| 6 | P8A-05 | REPL | `good differentials this week` | Differential ranking is position-score-based; note any GKPs/DEFs in results | [SAMPLE: Top 5 was 2 MID, 2 FWD, 1 GKP. GKP in rank 4 with form=4.5, saves/90=3.1. Directionally expected from 8a1 weight profile. No surprise inversions.] | [SAMPLE: `differential` present] | minor | — | noted for backtesting record |

---

## Blockers

No blockers recorded in this pass.

| ID | Summary | Repro | Status |
|---|---|---|---|
| — | — | — | — |

---

## Major Issues

No major issues recorded in this pass.

| ID | Summary | Repro | Status |
|---|---|---|---|
| — | — | — | — |

---

## V1.5 Structured Checks Summary

| Check ID | Area | Expected | Status | Notes |
|---|---|---|---|---|
| P8A-01–05 | Position-aware scoring | `position_score` in comparison JSON (CLI + HTTP); transfer uses `score_delta`; differential ranking is position-score-based | [SAMPLE: Pass] | [SAMPLE: MID parity held. Raya position_score=64.2 vs captain_score=51.1. One GKP in differential top-5.] |
| P8B-01–08 | Venue-aware FDR | `is_home` + `effective_fdr` in comparison; `is_home` in HTTP differential; no venue tags in REPL differential | [SAMPLE: Pass] | [SAMPLE: Both Salah and Saka home GW32. efdr values correct. P8B-08: plain text confirmed no H/A tags.] |
| P8C-01–05 | Free hit signal | `chip.signal_label` correct for current GW type | [SAMPLE: Pass] | [SAMPLE: Current GW normal → label="normal gameweek", signal_value=0.0. Validation runner 44/44.] |
| SES-06–07 | Session follow-ups | fixture_run + differential follow-up routes deterministically | [SAMPLE: Pass] | [SAMPLE: Both follow-ups resolved without LLM. resolver_source confirmed deterministic.] |
| P8E-01–06 | Budget constraint + chip unavailable | Hard blocks fire and do not persist | [SAMPLE: Pass] | [SAMPLE: Both constraints fired correctly via CLI and HTTP.] |
| P8E-07–09 | Hit warning | Advisory flag fires only for marginal_transfer_in + FT==1 | [SAMPLE: Pass] | [SAMPLE: Strong transfer → hit_warning=false. Marginal transfer → hit_warning=true.] |
| P8E-11–12 | Session statelessness | Constraint absent on next turn without squad_context | [SAMPLE: Pass] | [SAMPLE: Turn 2 budget_constraint=false confirmed.] |

---

## Notes On Style And Trust

[SAMPLE observations — replace with your own:]

- Recommendations were grounded and concise. No unnecessary hedging observed.
- `is Haaland injured?` returned an explicit unsupported response without invented data — correct behavior.
- Budget constraint message was clear and actionable: "your available budget (£2.0m) is less than the upgrade cost." No error noise.
- Session follow-up prompts resolved naturally. `what about Mbeumo?` after a differential turn was a realistic operator prompt; it routed correctly without restating the full question.
- REPL `--debug` metadata lines are useful for spot-checking `efdr` and `pos_score` values inline without switching to CLI JSON mode.
- One GKP in differential top-5 is expected heuristic behavior from 8a1 saves weighting. The player had form=4.5 and saves/90=3.1 — a plausible result, not a noise artifact. Noted, not a blocker.

---

## Final Recommendation

### Go / No-Go

[SAMPLE:]

**Go.** All V1.5 surfaces behaved as documented. Core CLI and session scenarios passed without blockers or major issues. V1.5-specific structured checks — position-aware scoring in comparison, venue-aware FDR, free hit signal_label, session follow-up routing, and squad_context constraints — all produced correct observable behavior across CLI, HTTP, and session surfaces. Session statelessness was confirmed: constraints applied on turn 1 did not persist to turn 2. The validation runner returned 44/44 PASS. The one noted caution (GKP in differential top-5 from 8a1 saves weighting) is a known heuristic limitation documented in `UAT_FINDINGS.md` Case 5 — it is not new, not a blocker, and is in scope for Layer 3 backtesting.

### Recommended Next Action

[SAMPLE:]
- Proceed to carefully scoped post-MVP prioritization.
- Track GKP overpromotion in differentials for Layer 3 backtesting resolution.

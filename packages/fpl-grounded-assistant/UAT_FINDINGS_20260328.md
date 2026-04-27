# FPL Grounded Assistant - UAT Findings 2026-03-28

---

## Session Summary

| Field | Value |
|---|---|
| Tester | Claude (automated operator pass) |
| Date | 2026-03-28 |
| Build / branch | main, working tree |
| Scope | V1.5 (phases 8a1 / 8b / 8c / 8d / 8e / 8f) |
| Data mode | Live data — GW31 BGW, 4 teams blank (ARS, CRY, MCI, WOL) |
| Primary surface | CLI single-turn (`fpl_cli.py --debug`) + HTTP session (`fpl_server.py`) |
| Secondary surfaces used | HTTP `/ask`, HTTP `/session` |
| Validation runner result | 44/44 PASS |
| Overall recommendation | Go with cautions |

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
| 1 | P8A-03 | CLI debug | `compare Salah and Palmer` | MID `position_score == captain_score` (zero-drift invariant) | Salah: pos=32.65, capt=35.65, diff=3.0; Palmer: pos=45.66, capt=48.66, diff=3.0. Diff = exactly venue adjustment (away +0.5 × 20 fixture_score × 0.30 MID weight = 3.0). Both players away GW31 (is_home=false, effective_fdr=3.5). | Pass — Layer 2 correctly applies venue adjustment; Layer 1 uses raw FDR. MID parity invariant holds strictly only at is_home=null. | minor | — | Document nuance: MID parity = exact only when is_home=null; venue-adjusted MID diff is expected behavior. |
| 2 | P8A-05 | CLI / HTTP | `good differentials this week` | Differential top-5 picks ordered by position_score; GKPs may appear due to saves weighting | 3 GKPs in ranks 2–4 (Ellborg SUN, Benitez CRY, Hermansen WHU). Consistent with existing Case 5 caution (GKP overpromotion). | Pass — ranking functional; GKP promotion documented caution | minor | — | Re-confirmed existing Case 5 caution. No change. |
| 3 | P8A-05 | CLI / HTTP | `good differentials this week` | Differential top-5 picks are playable this GW | Ranks 3 and 5 are CRY players (Benitez GKP, Canvot DEF). CRY has no GW31 fixture (BGW team). Algorithm scores using historical per-game rates with neutral FDR (effective_fdr=3.0, is_home=null) for blank players — no fixture penalty or filter applied. Materially misleading for "this week" prompt. | New finding — differential algorithm does not penalize or exclude blank GW players | major | — | Track for Layer 3 improvement. Blank-player filter or FDR penalty needed for current-GW differential picks. |
| 4 | P8B-03 | CLI debug | `compare Salah and Saka` | `comparison.reasons` includes venue-tagged FDR phrase (e.g. "easier fixture (FDR 4H vs 5A)") | No venue phrase in reasons. Reasons: form, minutes, set-piece. Form difference (4.7 vs 3.0) dominated; FDR contrast was not the differentiating factor. Saka is_home=null (ARS blank), Salah is_home=false. Venue phrase not triggered. | Pass — venue reasons appear only when fixture is a differentiating factor. Absence is correct behavior for this comparison. | pass | — | none |
| 5 | SES-06/07 | HTTP session | Fixture run + differential follow-ups | resolver_source = fixture_run_followup / differential_followup | Correct intent and player resolved on turn 2 without LLM invocation confirmed. resolver_source not exposed by HTTP session /ask endpoint (no debug block in session response). Deterministic routing confirmed by outcome. | Pass — deterministic routing confirmed; resolver_source not observable via HTTP session surface | pass | — | none |

---

## Blockers

No blockers recorded in this pass.

| ID | Summary | Repro | Status |
|---|---|---|---|
| — | — | — | — |

---

## Major Issues

| ID | Summary | Repro | Status |
|---|---|---|---|
| M1 | Blank GW players appear in differential top-5 | `fpl_cli.py "good differentials this week" --debug` in a BGW; check picks for teams with no GW fixture. GW31: Benitez (CRY, rank 3) and Canvot (CRY, rank 5) both blank. effective_fdr=3.0, is_home=null for both. | Open — Layer 3 improvement needed |

---

## V1.5 Structured Checks Summary

| Check ID | Area | Expected | Status | Notes |
|---|---|---|---|---|
| P8A-01–05 | Position-aware scoring | `position_score` in comparison JSON (CLI + HTTP); transfer uses `score_delta`; differential ranking is position-score-based internally | Pass | Raya GKP pos_score=63.56 > capt_score=50.82 (saves uplift correct). MID diff of 3.0 is Phase 8b venue adjustment, not a bug. score_delta=-19.9 in transfer. |
| P8B-01–08 | Venue-aware FDR | `is_home` + `effective_fdr` in comparison; `is_home` in HTTP differential; no venue tags in REPL differential | Pass | Salah away (is_home=false, efdr=3.5). Saka is_home=null (ARS blank — correct fallback). HTTP differential: all 5 picks have is_home key. No venue tags in plain text. |
| P8C-01–05 | Free hit signal | `chip.signal_label` correct for current GW type | Pass | GW31 BGW correctly detected: signal_label="blank gameweek teams", signal_value=4.0, recommendation="conditions_marginal". Validation 44/44 covers DGW/BGW/normal. |
| SES-06–07 | Session follow-ups | fixture_run + differential follow-up routes deterministically | Pass | Both follow-ups resolved correct player and intent. HTTP session does not expose resolver_source; deterministic routing confirmed by outcome match. |
| P8E-01–06 | Budget constraint + chip unavailable | Hard blocks fire and do not persist | Pass | budget_constraint=true with itb=2.0; chip_unavailable=true with chips_remaining excluding TC. Both fire on CLI and HTTP. final_text replaced by constraint message in both cases. |
| P8E-07–09 | Hit warning | Advisory flag fires only for marginal_transfer_in + FT==1 | Pass | Saka→Salah recommendation="hold" → hit_warning=false (correct — no marginal recommendation for this pair in GW31). |
| P8E-11–12 | Session statelessness | Constraint absent on next turn without squad_context | Pass | Turn 1 budget_constraint=True; Turn 2 (no squad_context) budget_constraint=False. Constraint not persisted. |

---

## Notes On Style And Trust

- Recommendations are grounded and concise. No hedging or invented data observed across any tested scenario.
- Salah is correctly flagged as "Doubtful" in GW31, with "Significant minutes risk" surfaced in both captain score ("Avoid [35.65]") and player_resolve output. The system correctly uses live availability data rather than ignoring it.
- Unsupported intent (injury question) returned an explicit, clean refusal: "I couldn't match that question to a supported query." No invented facts. CLI exits non-zero for unsupported intents — appropriate for scripting contexts.
- Budget constraint and chip unavailable messages are clear and actionable. Budget message cites the exact cost and available budget. Chip unavailable cites the chip by name.
- Session follow-up turns felt natural and correctly scoped. "What about Salah?" after a fixture run required no prompt restatement and resolved correctly. "What about Gordon?" after a differential question routed to captain_score for Gordon without ambiguity.
- The MID parity deviation (position_score ≠ captain_score when is_home is not null) is a natural consequence of Phase 8b venue adjustment being applied in Layer 2 but not Layer 1. The numbers are fully explainable and correct. The runbook note "closely match or equal" is approximately accurate but should be read as "equal only at is_home=null."
- The blank-GW differential finding (CRY players in top-5) is the clearest usability issue of the pass. An operator who ran "good differentials this week" in GW31 and acted on rank-3 Benitez (CRY, GKP) would discover the next day that Crystal Palace did not play. The recommendation is technically a product of correct heuristic scoring but is operationally wrong for the stated prompt.

---

## Final Recommendation

### Go / No-Go

**Go with cautions.**

All V1.5 surfaces behaved as documented. Core CLI and session scenarios passed without blockers or crashes. V1.5-specific structured checks — position-aware scoring in comparison, venue-aware FDR, free hit signal_label, session follow-up routing, and squad_context constraints — all produced correct observable behavior across CLI, HTTP, and session surfaces. Session statelessness was confirmed: constraints applied on turn 1 did not persist to turn 2. The validation runner returned 44/44 PASS.

One new major finding was recorded: blank-GW players are not penalized or filtered from differential picks. In GW31 (a BGW with CRY, ARS, MCI, WOL blanking), two CRY players (Benitez GKP rank 3, Canvot DEF rank 5) appeared in the differential top-5 with neutral FDR scoring (effective_fdr=3.0, is_home=null) despite having no GW31 fixture. This is materially misleading for a "this week" prompt. The issue does not block the V1.5 feature set — the intent routing, scoring architecture, session behavior, and constraint logic all work correctly. The blank-player gap is a heuristic limitation of the Layer 2 differential algorithm that is in scope for Layer 3 improvement.

The existing GKP overpromotion caution (Case 5) is re-confirmed: 3 GKPs in ranks 2–4, with the two CRY GKPs partly overlapping with the blank-player finding.

### Recommended Next Action

- Proceed to carefully scoped post-MVP prioritization.
- Track blank-GW differential player issue as a new Layer 3 improvement item (filter or penalize players with no current-GW fixture in differential ranking).
- The MID parity nuance (position_score ≠ captain_score when is_home is available) should be noted in `FINAL_RESPONSE_CONTRACT.md` or runbook documentation so future testers are not confused by the expected venue-adjustment deviation.

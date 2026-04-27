# FPL Grounded Assistant — UAT Findings 2026-03-28 GKP Calibration

---

## Session Summary

| Field | Value |
|---|---|
| Tester | Claude (automated operator pass) |
| Date | 2026-03-28 |
| Build / branch | main, working tree |
| Scope | GKP position-score calibration (saves 0.25→0.15, form 0.30→0.40) |
| Data mode | Live data — GW31 BGW, 4 teams blank (ARS, CRY, MCI, WOL) |
| Primary surface | CLI (`fpl_cli.py --debug`) + respond() controlled fixtures |
| Validation runner result | 44/44 PASS |
| Overall recommendation | Go — calibration effective for marginal GKPs; residual risk documented |

---

## Severity Rubric

| Severity | Meaning |
|---|---|
| blocker | Crash, unusable manual path, invented facts, wrong core routing, broken session behavior, broken structured contract |
| major | Materially misleading answer, repeated failure on supported prompts, missing key structured metadata |
| minor | Limited wording or usability issue that does not break trust or task completion |
| polish | Improvement idea only |

---

## Findings Log

| ID | Scenario | Surface | Prompt / Sequence | Expected | Actual | Severity | Status |
|---|---|---|---|---|---|---|---|
| 1 | Post-calib differential | CLI debug | `good differentials this week` | Top-3 outfield; GKPs in ranks 4–5 if saves high | Gordon MID #1 (67.3), Beto FWD #2 (59.4), King MID #3 (59.3), Ellborg GKP #4 (58.4), Leno GKP #5 (58.2). Outfield leads top-3. | — | pass |
| 2 | Residual GKP caution | CLI debug | `good differentials this week` | High-saves GKPs may remain in ranks 4–5 (residual risk, expected) | Ellborg (SUN, saves high) rank 4; Leno (FUL, saves moderate) rank 5. Both teams play GW31. Consistent with documented residual risk. | minor (existing caution, not new) | open — Layer 3 |
| 3 | GKP comparison | CLI debug | `compare Ellborg and Gordon` | position_score present; winner = Gordon (higher form + home fixture) | Gordon (67.29) edges Ellborg (58.39) margin=8.9 (moderate). position_score on both players. Drift visible: Ellborg pos=58.39 vs capt=44.07 (+14.32 saves uplift). | — | pass |
| 4 | Transfer with GKP | CLI debug | `should I transfer Saka for Leno` | position_score drives comparison; calibrated weights apply | Leno position_score=58 > Saka(doubtful) position_score=53 → "transfer_in". FUL home FDR=2H strong. score_delta=5.65. Cross-position (DEF→GKP) working. | — | pass |
| 5 | Balanced-fixture marginal GKP | respond() | controlled GKP_BALANCED_BOOTSTRAP | 0 GKPs in position top-5 under calibrated weights | GKP=0 confirmed. Kaminski (saves=3.0) at rank 6 (56.75), Jimenez FWD at rank 5 (57.22). Calibration effective. | — | pass |
| 6 | Strong-GKP residual | respond() | controlled GKP_OVERPROMOTION_BOOTSTRAP | GKPs with saves≥3.0 remain top-5 (residual risk, expected) | GKP=3 (Flekken #1, Fabianski #2, Pickford #4). Drifts: +18.12, +14.75, +11.38 respectively. All reduced vs pre-calibration (+21.88, +18.25, +14.12). | minor (documented residual) | open — Layer 3 |

---

## Blockers

No blockers recorded in this pass.

| ID | Summary | Status |
|---|---|---|
| — | — | — |

---

## Calibration Evidence Summary

### What changed
Production GKP profile in `position_score.py` (applied in this cycle, verified here):

| Weight | Pre-calibration | Post-calibration |
|---|---|---|
| form | 0.30 | **0.40** |
| saves | 0.25 | **0.15** |
| clean_sheet | 0.15 | 0.15 (unchanged) |
| fixture | 0.20 | 0.20 (unchanged) |
| minutes | 0.10 | 0.10 (unchanged) |
| xgi | 0.00 | 0.00 (unchanged) |

### What improved
Marginal GKP promotion eliminated in the controlled balanced fixture (GKP_BALANCED_BOOTSTRAP): Kaminski (saves=3.0) dropped from position rank 3 (pre-calibration position_score=60.75) to rank 6 (post-calibration=56.75). GKP count in top-5 changed from 1→0. Outfield top-3 confirmed.

In live GW31 data, top-3 differential picks are now consistently outfield (Gordon MID, Beto FWD, King MID). GKPs appear only in ranks 4–5 for high-saves players who genuinely play this week.

GKP drift values reduced across all fixtures:
- Flekken: pre=+21.88 → post=+18.12
- Fabianski: pre=+18.25 → post=+14.75
- Pickford: pre=+14.12 → post=+11.38

### What remains (residual risk — intentional)
GKPs with saves_per_90 ≥ 3.2 still rank in position top-5 under calibrated weights. This is the correct outcome given the evidence base: no tested weight variant eliminates high-saves GKPs without removing the saves signal entirely or penalising GKPs to an arbitrary degree. Residual risk requires outcome backtesting (Layer 3) to resolve.

Observable in GW31 live output: Ellborg (SUN GKP, rank 4, saves high) and Leno (FUL GKP, rank 5, saves moderate). Both teams play GW31 (not blank). The concern is not blank-GW (that is fixed) but the relative ranking weight given to saves vs outfield metrics.

---

## Regression Check Summary

| Suite | Result | Notes |
|---|---|---|
| `run_validation.py --no-artifacts` | 44/44 PASS | Core corpus unaffected by GKP calibration |
| `run_blank_gw_differential_tests.py` | 28/28 PASS | Blank-GW filter intact after calibration |
| `run_gkp_overpromotion_analysis.py` | 26/26 PASS | Includes calibration verification on GKP_BALANCED_BOOTSTRAP |
| `run_gkp_weight_sensitivity.py` | 18/18 PASS | pre_calibration vs new_production before/after confirmed |

---

## Notes on Live Behavior

- Differential top-3 in live GW31: Gordon (MID), Beto (FWD), King (MID). All outfield, all playing, all good form. This is the correct operator experience for a normal GW.
- The two GKPs in ranks 4–5 (Ellborg, Leno) are playing this week and have high saves rates. An FPL operator who picks Ellborg as a differential GKP would have a reasonable base (save volume), though captaining a GKP remains unusual. The position_score reflects real saves data, not invented signal.
- Transfer advice path (Saka→Leno example): calibrated position_score enables cross-position transfer comparisons. Leno at 58 > Saka-doubtful at 53 is correct given FUL home FDR=2. Operators should consider team composition and position budget constraints separately (that is outside the assistant's scope).
- The captain_score surface remains unchanged (Layer 1 frozen). Ellborg captain_score=44.07 (Differential tier) correctly reflects weak attacking process. The saves uplift lives only in position_score (Layer 2), not captain_score.

---

## Caution Register (current)

| ID | Description | Status |
|---|---|---|
| C1 | GKP overpromotion — marginal GKPs (saves ~2.8–3.0) | **Resolved by 2026-03-28 calibration.** Marginal GKPs no longer promoted in controlled balanced fixture. |
| C2 | GKP overpromotion — strong high-saves GKPs (saves ≥ 3.2) | **Open — Layer 3 only.** Calibration reduces drift but does not eliminate. Requires outcome backtesting. |
| C3 | Blank-GW players in differential top-5 | **Resolved.** Blank-GW filter applied in Phase blank-GW fix (confirmed by 28/28 PASS). |

---

## Final Recommendation

**Go — calibration effective for the evidence-backed scope.**

The GKP position-score calibration (saves 0.25→0.15, form 0.30→0.40) has been verified in live operator output and controlled fixtures. The marginal GKP promotion pattern observed in the pre-calibration UAT pass (20260328) is resolved for the balanced-saves range. The residual high-saves GKP caution (C2) is documented, stable, and not a new finding — it was present before calibration and is correctly deferred to Layer 3.

All V1.5 structural checks verified in the prior pass remain valid. No new blockers or major issues were found in this refresh. The four regression suites all pass at their existing totals.

**Recommended next action:** No immediate calibration work required. The next productive action is outcome data collection for Layer 3 backtesting (C2 resolution path). The current heuristic is the right production state given available evidence.

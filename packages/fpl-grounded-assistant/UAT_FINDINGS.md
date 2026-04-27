# FPL Grounded Assistant - UAT Findings

## About this file

This is the **append-only historical log** of completed UAT passes.
It is a summary index — not the full evidence record.

Full evidence for each pass lives in two dated files:
- `UAT_CAPTURE_<YYYYMMDD>.md` — command output and per-check capture
- `UAT_FINDINGS_<YYYYMMDD>.md` — full findings, blockers, cautions, and recommendation

See `UAT_ARCHIVE_CONVENTION.md` for naming rules and bundle completeness criteria.

When you finish a pass, append one section here following the template below.
Keep each section to 15–25 lines. Reference the dated files rather than duplicating their content.

---

## Per-Pass Summary Template

Copy this block and fill it in. Do not leave `[placeholders]` in completed entries.

Four values must match exactly between this summary section and the Pass Index row (see sync rules below the index):
- section heading date+label → index **Date** + **Label** columns
- `Recommendation` field → index **Recommendation** column
- `Capture file` field → index **Capture** column
- `Findings file` field → index **Findings** column

```
## Pass YYYYMMDD[_label]

| Field | Value |
|---|---|
| Date | YYYY-MM-DD |
| Tester | name or initials |
| GW / data mode | GW__ / Live data  OR  Fallback debug |
| Validation result | __/44 PASS |
| Recommendation | Go / No-Go |
| Capture file | UAT_CAPTURE_YYYYMMDD[_label].md |
| Findings file | UAT_FINDINGS_YYYYMMDD[_label].md |

**New blockers:** none  OR  list issue IDs with one-line summary each

**New cautions:** none  OR  list caution IDs with one-line summary each

**Key observations (2–4 bullet points):**
- ...
```

---

## Pass Index

| Date | Label | GW | Result | Recommendation | Capture | Findings |
|---|---|---|---|---|---|---|
| 2026-03-23 | V1 baseline | GW30 (est.) | — (pre-runner) | Go | *(pre-convention)* | *(inline below)* |
| 2026-03-26 | Phase 8a1 | GW31 | — (pre-runner) | Go with caution | *(pre-convention)* | *(inline below)* |
| 2026-03-28 | — | GW31 BGW | 44/44 PASS | Go with cautions | `UAT_CAPTURE_20260328.md` | `UAT_FINDINGS_20260328.md` |
| 2026-03-28 | gkp_calibration | GW31 BGW | 44/44 PASS | Go | `UAT_CAPTURE_20260328_gkp_calibration.md` | `UAT_FINDINGS_20260328_gkp_calibration.md` |

*Pre-convention passes predate the dated-file archive format. Their full evidence is inline in the legacy section below.*
*Future passes: add a row here and a compact summary section immediately above the **`<!-- END OF REAL PASS SUMMARIES -->`** marker below.*

**Sync rules — these four values must be identical in both the index row and the summary section:**

| Index column | Must equal | Summary section field |
|---|---|---|
| **Date** | same date as | section heading `YYYYMMDD` + `Date` field |
| **Label** | same label as | section heading `[_label]` suffix and both filenames |
| **Recommendation** | same value as | `Recommendation` field in summary header table |
| **Capture** / **Findings** | same filenames as | `Capture file` / `Findings file` fields in summary header table |

Label rule: the optional `[_label]` suffix must appear consistently in the index Label column, the section heading (`## Pass YYYYMMDD_label`), and both dated filenames (`UAT_CAPTURE_YYYYMMDD_label.md`, `UAT_FINDINGS_YYYYMMDD_label.md`). If there is no label, omit the suffix in all four places.

---

## Pass 2026-03-23 — V1 Baseline

| Field | Value |
|---|---|
| Date | 2026-03-23 |
| Tester | Manual UAT pass |
| GW / data mode | GW30 est. / Live data |
| Validation result | — (pre-44-scenario runner) |
| Recommendation | Go |
| Capture file | *(pre-convention — full detail inline below)* |
| Findings file | *(pre-convention — full detail inline below)* |

**New blockers:** B1 — `player_fixture_run` returned error on live data due to missing `team_fixtures` in bootstrap. Fixed and retested same day. Closed.

**New cautions:** none

**Key observations:**
- All core CLI intents (captain, comparison, transfer, chip, fixture run, multi-intent) returned grounded responses
- HTTP `/ask` surface matched CLI semantics after restarting a stale server process
- Unsupported prompts (`is Haaland injured?`) returned explicit unsupported responses — no invented data
- `player_fixture_run` blocker was the only issue; resolved within the same pass

---

## Pass 2026-03-26 — Phase 8a1 Position-Aware Scoring

| Field | Value |
|---|---|
| Date | 2026-03-26 |
| Tester | Manual UAT pass + automated script (`run_phase8a1_uat.py`) |
| GW / data mode | GW31, 825 players / Live data |
| Validation result | — (pre-44-scenario runner) |
| Recommendation | Go with caution (C1: GKP overpromotion in differentials) |
| Capture file | `phase8a1_uat_evidence.json` *(pre-convention)* |
| Findings file | *(pre-convention — full detail inline below)* |

**New blockers:** none

**New cautions:**
- C1 — GKP overpromotion in differential picks: 3 GKPs in top-5 (0 in canonical top-5). Saves weight (0.25) lifts available GKPs with median saves/90 above high-form MIDs. Not a bug — documented heuristic limitation. Resolution: Layer 3 backtesting.
- C2 — GKP beats FWD on position_score in direct comparison when canonical shows opposite. Same root cause and resolution path as C1.

**Key observations:**
- MID and FWD zero-drift invariants hold exactly (position_score == captain_score)
- GKP and DEF receive directionally correct uplifts (saves/CS credit)
- All 7 scoring components visible and auditable; cross-surface parity perfect (CLI/HTTP/session identical)
- GKP overpromotion is structural (threshold-independent, present at every ownership filter level)

## Pass 20260328

| Field | Value |
|---|---|
| Date | 2026-03-28 |
| Tester | Claude (automated operator pass) |
| GW / data mode | GW31 BGW (ARS, CRY, MCI, WOL blank) / Live data |
| Validation result | 44/44 PASS |
| Recommendation | Go with cautions |
| Capture file | `UAT_CAPTURE_20260328.md` |
| Findings file | `UAT_FINDINGS_20260328.md` |

**New blockers:** none

**New cautions:**
- C3 — *(Resolved same session)* Blank-GW players not filtered from differential picks: Benitez (CRY, GKP, rank 3) and Canvot (CRY, DEF, rank 5) appeared in top-5 despite CRY having no GW31 fixture. Fixed by adding `_has_current_gw_fixture` filter in `differential_picks.py`. Players with no current-GW fixture are now excluded when `team_fixtures` data is available. Confirmed on live data: CRY players no longer appear. 28/28 unit tests + 44/44 V1 regression pass.
- C1/C2 GKP overpromotion unchanged from 2026-03-26 (3 GKPs in ranks 2–4; partly overlaps C3 in this BGW).

**Key observations:**
- All core V1.5 structured checks passed: position_score in comparison (CLI + HTTP), venue-aware FDR, BGW free-hit signal correctly detected, session follow-ups deterministic, all squad_context constraints fired and did not persist.
- MID position_score deviation from captain_score (diff=3.0) is Phase 8b venue adjustment — not a bug. Position_score applies away-penalty to effective_fdr; captain_score uses raw FDR (Layer 1 frozen). Deviation equals exactly 0.5 × 20 × 0.30 = 3.0 for both Salah and Palmer (away, raw_fdr=3). MID parity invariant holds strictly only at is_home=null.
- Salah correctly flagged as Doubtful in GW31 live data; "Avoid" tier and minutes risk surfaced across all surfaces.
- First real dated-pass evidence bundle produced under the archive convention workflow.

## Pass 20260328_gkp_calibration

| Field | Value |
|---|---|
| Date | 2026-03-28 |
| Tester | Claude (automated operator pass) |
| GW / data mode | GW31 BGW / Live data |
| Validation result | 44/44 PASS |
| Recommendation | Go |
| Capture file | UAT_CAPTURE_20260328_gkp_calibration.md |
| Findings file | UAT_FINDINGS_20260328_gkp_calibration.md |

**New blockers:** none

**New cautions:** none — C2 (strong high-saves GKP overpromotion) remains open at Layer 3; C1 (marginal GKP) and C3 (blank-GW) both resolved.

**Key observations:**
- Calibration verified live: GW31 top-3 differentials are all outfield (Gordon MID, Beto FWD, King MID). GKPs appear only in ranks 4–5 for high-saves players who are playing this week.
- Marginal GKP elimination confirmed in GKP_BALANCED_BOOTSTRAP controlled fixture: GKP=0 in top-5. Kaminski (saves=3.0) at rank 6, Jimenez FWD at rank 5 (57.22 vs 56.75).
- GKP drift reduced across all fixtures post-calibration (Flekken: 21.88→18.12, Fabianski: 18.25→14.75, Pickford: 14.12→11.38). Residual strong-GKP caution (C2) is expected and documented.
- 44/44 V1 corpus + 28/28 blank-GW + 26/26 overpromotion + 18/18 sensitivity all pass.

<!-- END OF REAL PASS SUMMARIES -->
<!-- Append new real pass summaries immediately above this line. Do not add real entries below it. -->

---

## Appendix A — Illustrative Example (not real evidence)

*This section shows what a completed V1.5 pass summary looks like. It is not a real pass record.*
*Do not add real passes here. Real passes go above the `END OF REAL PASS SUMMARIES` marker.*

**Pass 20260405 — V1.5 Full Pass [EXAMPLE]**

| Field | Value |
|---|---|
| Date | [EXAMPLE] 2026-04-05 |
| Tester | [EXAMPLE] |
| GW / data mode | [EXAMPLE] GW33 / Live data |
| Validation result | [EXAMPLE] 44/44 PASS |
| Recommendation | [EXAMPLE] Go |
| Capture file | `UAT_CAPTURE_20260405.md` |
| Findings file | `UAT_FINDINGS_20260405.md` |

**New blockers:** none

**New cautions:** none (C1/C2 GKP overpromotion remains open from 2026-03-26 — no change)

**Key observations:**
- All V1.5 checks passed: position_score in comparison, score_delta in transfer, venue-aware FDR, free hit signal_label, session follow-ups, squad_context constraints and statelessness
- Validation runner: 44/44 PASS
- No new issues found relative to previous pass

---

## Appendix B — Legacy Detailed Evidence

*Pre-convention full findings detail. Preserved as authoritative record. Do not modify.*
*Compact summaries for these passes are in the Pass Summary sections above.*

### V1 Findings Log (2026-03-23)

| ID | Scenario ID | Surface | Prompt Or Sequence | Expected Semantics | Actual Result | Structured Check | Severity | Owner | Action |
|---|---|---|---|---|---|---|---|---|---|
| 1 | CLI-08 / META-06 | REPL, CLI debug | `Salah fixtures`, `Haaland fixtures` | `player_fixture_run` should return a grounded fixture schedule for a resolved player | Returned `No fixture schedule available (team_fixtures not in bootstrap).` with `outcome=error` on live data | `fixture_run` unavailable because the turn errored | blocker | engineering | Fixed in follow-up retest on 2026-03-23 |
| 2 | CLI-08 / META-06 / HTTP spot | REPL, CLI debug, HTTP `/ask` | `Salah fixtures`, `Haaland fixtures` | `player_fixture_run` should return grounded upcoming fixtures with structured `fixture_run` metadata | REPL returned grounded next-5-fixtures text for both players; CLI debug returned `outcome=ok` with populated `fixture_run`; HTTP `/ask` for `Salah fixtures` returned `outcome=ok` with non-null `fixture_run` after restarting a stale old server process | `fixture_run` populated with player, team, position, current_gameweek, and fixture list | resolved | engineering | Closed |

---

### Phase 8a1 Findings Log (2026-03-26)

Live data: GW31, 825 players. UAT script: `run_phase8a1_uat.py`. Evidence: `phase8a1_uat_evidence.json`.

### Case 1: GKP Comparison — Raya (GKP) vs B.Fernandes (MID)

| Check | Result |
|---|---|
| Prompt | `compare Raya and B.Fernandes` |
| Outcome | `ok` |
| Winner | B.Fernandes (clear margin, 11.6) |
| Raya captain_score | 50.82 |
| Raya position_score | 63.56 |
| Raya drift | +12.74 (+25.1%) |
| B.Fernandes drift | 0.00 (MID, zero by design) |
| Assessment | **PASS.** GKP gets positive uplift from saves (saves_score=40, weight=0.25) and clean sheets (cs_score=96, weight=0.15). B.Fernandes still wins — position correction helps GKP compete but does not flip strong MID results. |

### Case 2: DEF Comparison — Truffert (DEF) vs B.Fernandes (MID)

| Check | Result |
|---|---|
| Prompt | `compare Truffert and B.Fernandes` |
| Outcome | `ok` |
| Winner | B.Fernandes (clear margin, 22.4) |
| Truffert captain_score | 50.14 |
| Truffert position_score | 52.70 |
| Truffert drift | +2.56 (+5.1%) |
| Assessment | **PASS.** DEF gets modest CS credit. Drift is small and directionally correct — does not distort the ranking. |

### Case 2b: DEF Transfer — Senesi vs Truffert

| Check | Result |
|---|---|
| Prompt | `should I sell Senesi for Truffert` |
| Outcome | `ok` |
| Recommendation | hold (score_delta=-0.2) |
| Text quality | `Recommendation: Hold Senesi. Score: 53 vs Truffert's 53 (-0.2).` |
| Assessment | **PASS.** Label says "Score:" not "Captain score:". Close DEF-vs-DEF case handled correctly. |

### Case 3: MID Control — B.Fernandes (MID) vs J.Gomes (MID)

| Check | Result |
|---|---|
| Prompt | `compare B.Fernandes and J.Gomes` |
| B.Fernandes drift | 0.0000 |
| J.Gomes drift | 0.0000 |
| Assessment | **PASS.** MID zero-drift invariant holds. position_score == captain_score for both. |

### Case 4: FWD Control — Beto (FWD) vs B.Fernandes (MID)

| Check | Result |
|---|---|
| Prompt | `compare Beto and B.Fernandes` |
| Beto drift | 0.0000 |
| Assessment | **PASS.** FWD=MID bridge working. Zero drift confirmed. |

### Case 5: Differential Picks — GKP/DEF Overpromotion Check

| Check | Result |
|---|---|
| Canonical top-5 (captain_score only) | Gordon (MID), J.Gomes (MID), Gibbs-White (MID), Sarr (MID), Beto (FWD) |
| Phase 8a1 top-5 (position_score) | **Ellborg (GKP), Hermansen (GKP), Gordon (MID), Benitez (GKP), Canvot (DEF)** |
| GKP/DEF count in top 5 | **4 out of 5** |
| GKP drift range | +20.6 to +25.4 points |
| Root cause | GKPs with saves_per_90 ~3.0–3.3 get saves_score 75–84 weighted at 0.25 = ~18–21 points. Combined saves+CS contribution is ~30 points, lifting GKPs with captain_score 37–44 up to 62–65. |
| Assessment | **CAUTION.** This is a known heuristic limitation, not a deterministic bug. The GKP saves weight (0.25) is aggressive — it lifts any available GKP with decent per-90 saves into differential contention regardless of form. The plan explicitly flagged this as a required backtesting item: "how often does `position_score` push GKPs/DEFs into top-5 candidates? How often would that have been correct historically?" This finding confirms the concern is real and validates the need for Layer 3 outcome calibration before broad promotion. |

**Detailed GKP component evidence:**

| Player | Form | FDR | Saves/90 | CS/90 | saves_score | cs_score | position_score | captain_score | drift |
|---|---|---|---|---|---|---|---|---|---|
| Ellborg | 4.0 | 3 | 3.33 | 0.33 | 83 | 66 | 64.7 | 44.1 | +20.6 |
| Hermansen | 3.5 | 3 | 3.36 | 0.36 | 84 | 72 | 64.3 | 42.0 | +22.3 |
| Benitez | 2.3 | 3 | 3.00 | 1.00 | 75 | 100 | 62.6 | 37.2 | +25.4 |

### Case 6: GKP vs FWD Direct — Raya (GKP) vs Beto (FWD)

| Check | Result |
|---|---|
| Winner | Raya (moderate margin, 7.2) |
| Raya captain_score | 50.82 → position_score 63.56 |
| Beto captain_score | 56.35 → position_score 56.35 |
| Assessment | **Directionally interesting.** Under canonical scoring, Beto (56.4) beats Raya (50.8). Under position_score, Raya (63.6) beats Beto (56.4). This is the position correction working as designed — but whether it is *correct* for differential/transfer advice requires outcome backtesting. |

### Case 7: Raw Component Inspection

| Check | Result |
|---|---|
| GKP profile visible | Yes — `position_profile: GKP`, saves=0.25, clean_sheet=0.15, xgi=0.00 |
| MID profile visible | Yes — `position_profile: MID`, form=0.40, fixture=0.30, xgi=0.20 |
| All 7 components present | Yes — including dc_score at zero weight |
| Assessment | **PASS.** Full auditability confirmed. |

### Case 8: Cross-Surface Parity

| Surface | B.Fernandes position_score | Beto position_score |
|---|---|---|
| CLI (respond) | 75.15 | 56.35 |
| HTTP (/ask) | 75.15 | 56.35 |
| Session (/session/{id}/ask) | 75.15 | 56.35 |
| Assessment | **PASS.** All three surfaces return identical values. |

---

## Blockers

| ID | Summary | Repro | Status |
|---|---|---|---|
| B1 | Live `player_fixture_run` was broken in primary UAT flow because fixture data was missing from the assembled bootstrap | Previously reproducible via `python fpl_repl.py` -> `Salah fixtures` and `python fpl_cli.py "Salah fixtures" --debug`; no longer reproduces after the live bootstrap assembly fix | Closed 2026-03-23 |

No new blockers from Phase 8a1.

---

## Phase 8a1 Cautions

| ID | Summary | Evidence | Severity | Resolution Path |
|---|---|---|---|---|
| C1 | GKP overpromotion in differential picks | 3 GKPs in top 5 differentials; canonical ranking has 0 GKPs in top 5. Saves weight (0.25) lifts any available GKP with decent saves/90 into contention regardless of form. | caution | Layer 3 backtesting required. Weight calibration may need adjustment. Not a blocker for V1.5 heuristic baseline — the overpromotion is predictable and explainable, and `captain_score` is preserved for comparison. |
| C2 | GKP beats FWD on position_score in direct comparison (Raya 63.6 vs Beto 56.4) when canonical shows opposite (Raya 50.8 vs Beto 56.4) | Case 6 | caution | Same resolution path. The ranking reversal is the position correction working as designed, but correctness is unvalidated without outcome data. |

### Phase 8a1 Overpromotion Triage (2026-03-26)

Investigation script: `run_phase8a1_overpromotion_triage.py`. Data: GW31, 523 scored available players.

**Decision: Caution only. No code change.**

**Investigation A — Is overpromotion specific to differentials?**
No. In the full pool (no ownership filter), 5 GKPs appear in the top-10 by `position_score` vs 0 by canonical. This is a broader cross-position comparability issue in `position_score` itself, not a differential-specific problem.

**Investigation B — Does ownership filtering contribute?**
No. All positions have ~97% of players below 15% ownership. Pool composition is proportional across positions. The overpromotion exists identically at every ownership threshold from 5% to 100%.

**Investigation C — Drift magnitude by position:**

| Position | Avg drift | Max drift | Cause |
|---|---|---|---|
| GKP | +4.1 | +26.8 | saves (0.25) + CS (0.15) = 40% weight on GKP-exclusive signals |
| DEF | +2.7 | +17.9 | CS (0.20) - xgi reduction (0.15 vs 0.20) |
| MID | 0.0 | 0.0 | Zero by design |
| FWD | 0.0 | 0.0 | FWD=MID bridge |

Worst-case GKP example: Trafford (form=0.0, saves/90=3.67) gets drift=+26.8, rising from captain_score 28.0 to position_score 54.8. A form-zero player scoring 54.8 is clearly an overpromotion artifact.

**Investigation D — Would reducing saves weight fix it?**
Partially. Saves=0.15 (from 0.25) moves GKPs from positions #1–#4 to #4–#6 in the differential ranking. But 4 GKPs still appear in the top-10. The issue is structural: 40% of the GKP profile (saves 0.25 + CS 0.15) goes to signals that have a high floor for any playing goalkeeper (~3.0 saves/90 is normal, giving saves_score=75). This creates a floor contribution of ~30 points regardless of form, which is enough to lift low-form GKPs above high-form MIDs.

**Investigation E — Threshold stability:**
3 GKPs appear in the top-5 at every ownership threshold tested (5%, 10%, 15%, 25%, 50%, 100%). The problem is completely threshold-independent.

**Why no code change:**
1. The Phase 8a1 plan explicitly defers weight calibration to backtesting (Layer 3)
2. Adjusting saves weight without outcome evidence is speculative — saves/90 might actually predict GKP points well
3. The plan's "Task-Awareness" section notes that task-specific weight sets are a Layer 3 concern
4. `captain_score` is preserved alongside `position_score` — no information is lost
5. The constraint is clear: "if no clearly justified narrow fix emerges, prefer documenting the caution over speculative model changes"

**Resolution path (unchanged):**
- Layer 3 backtesting must measure: does saves_per_90 actually predict GKP next-GW points?
- If saves/90 is weakly predictive, reduce weight; if strongly predictive, the current weight may be correct
- Consider differential-specific ranking head that blends `captain_score` and `position_score`
- Overpromotion check item #6 from the backtesting plan covers this exactly

---

## Major Issues

No major issues recorded in this pass. No deterministic bugs found.

---

## Notes On Style And Trust

- All other suggested paths were reported as successful in the same live-data UAT pass.
- `is Haaland injured?` returned an explicit unsupported response. That is correct for the current scope and should be treated as a pass for unsupported-intent coverage, not as a blocker.
- `Liverpool fixtures` returned `No player found matching 'Liverpool'.` That is consistent with the current player-only `player_fixture_run` scope and is not logged as a blocker.
- The initial HTTP retest hit a stale older server process already bound to port 8000 and therefore showed the pre-fix behavior. After restarting a clean server instance, HTTP `/ask` returned `outcome=ok` with populated `fixture_run` for `Salah fixtures`.
- Phase 8a1 user-facing text correctly labels scores as "Score:" not "Captain score:" — this was fixed during implementation before UAT.

---

## Final Recommendation

### Go / No-Go

**Go with caution.** Phase 8a1 should be treated as the working V1.5 heuristic baseline pending future backtesting.

**Rationale:**
- MID and FWD zero-drift invariants hold exactly
- GKP and DEF get directionally correct uplifts (saves/CS credit)
- All 7 components are visible, auditable, and correctly weighted
- Cross-surface parity is perfect (CLI/HTTP/session identical)
- No deterministic bugs found
- User-facing labels are accurate
- `captain_score` (Layer 1) is preserved unchanged alongside `position_score` for comparison

**Caution:**
- GKP overpromotion in differentials is a real heuristic limitation (C1)
- The saves weight (0.25) may be too aggressive — it lifts mediocre-form GKPs into top-5 contention
- This was anticipated in the Phase 8a1 plan as a required backtesting item
- Until Layer 3 outcome calibration, `position_score` is an operational heuristic, not a validated prediction

### Recommended Next Action

- Accept Phase 8a1 as V1.5 heuristic baseline
- Do not adjust weights without outcome evidence (Layer 3 backtesting)
- Track C1/C2 cautions for resolution in backtesting phase
- Proceed to Phase 8b (home/away fixture work) or other planned work
- Keep `position_bias.py` for side-by-side backtesting comparison when Layer 3 infrastructure is built

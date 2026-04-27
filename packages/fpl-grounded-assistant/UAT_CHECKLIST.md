# FPL Grounded Assistant - UAT Checklist

Use this checklist during manual testing.
Mark pass or fail, capture short notes, and link follow-up actions where needed.

Legend:
- `Pass` = behavior acceptable for current V1.5 scope
- `Fail` = issue found and logged
- `N/A` = not executed in this pass

Interpretation notes:
- an explicit unsupported response is a `Pass` for unsupported-intent coverage
- `player_fixture_run` checks are player-only; team fixture prompts are out of scope for this checklist
- squad_context checks require CLI `--itb`, `--chips-remaining`, `--free-transfers` flags or HTTP `squad_context` payload field

---

## Preflight

| ID | Surface | Check | Expected | Status | Notes |
|---|---|---|---|---|---|
| PF-01 | CLI REPL | `python fpl_repl.py` starts | Live data loads and shell is usable |  |  |
| PF-02 | CLI REPL | `/gw` works | Current GW and player count displayed |  |  |
| PF-03 | CLI REPL | `/debug` toggle works | Metadata display turns on and off cleanly |  |  |
| PF-04 | HTTP | `python fpl_server.py` starts | Server binds locally without error |  |  |
| PF-05 | HTTP | `GET /health` | Healthy response returned |  |  |

---

## Core CLI Capabilities

| ID | Surface | Prompt | Expected Semantics | Structured Check | Status | Notes |
|---|---|---|---|---|---|---|
| CLI-01 | REPL | `should I captain Salah` | `captain_score`, grounded recommendation | `captain` present |  |  |
| CLI-02 | REPL | `top captains this week` | `rank_candidates`, ordered results | `captain_ranking` present |  |  |
| CLI-03 | REPL | `who is Palmer` | `player_resolve`, no invention | none expected |  |  |
| CLI-04 | REPL | `tell me about Haaland` | `player_summary`, grounded summary | none expected |  |  |
| CLI-05 | REPL | `compare Haaland and Salah` | `compare_players`, bounded winner/reasons | `comparison` present |  |  |
| CLI-06 | REPL | `should I sell Saka for Salah?` | `transfer_advice`, grounded recommendation | `transfer` present |  |  |
| CLI-07 | REPL | `should I use triple captain this week?` | `chip_advice`, bounded recommendation | `chip` present |  |  |
| CLI-08 | REPL | `Salah fixtures` | `player_fixture_run`, near-term fixtures only | `fixture_run` present |  |  |
| CLI-09 | REPL | `good differentials this week` | `differential_picks`, low-ownership picks | `differential` present |  |  |
| CLI-10 | REPL | `what is the current gameweek and who is Palmer` | `multi_intent`, both sub-answers present | `sub_responses` present |  |  |

---

## Follow-Up And Session Behavior

Run these in one uninterrupted REPL session unless stated otherwise.

| ID | Surface | Prompt Sequence | Expected Semantics | Structured Check | Status | Notes |
|---|---|---|---|---|---|---|
| SES-01 | REPL | `compare Haaland and Salah` -> `and Saka?` | follow-up rewrites to comparison with prior anchor | `comparison` present on both turns |  |  |
| SES-02 | REPL | `who is Salah` -> `should I captain him?` | pronoun uses prior player context | `captain` present on second turn |  |  |
| SES-03 | REPL | `should I sell Saka for Salah?` -> `what about Haaland instead?` | transfer follow-up rewrites against last transfer out-player | `transfer` present on both turns |  |  |
| SES-04 | REPL | unrelated scenario groups separated by `/reset` | context clears cleanly | prior context no longer leaks |  |  |
| SES-05 | HTTP session | create -> ask -> follow-up -> inspect -> delete | session lifecycle works end to end | inspect returns bounded state only |  |  |
| SES-06 | REPL `--debug` | `Haaland fixtures` -> `what about Salah?` | fixture run follow-up resolves Salah deterministically | `resolver_source == fixture_run_followup`; `fixture_run.web_name == Salah` |  |  |
| SES-07 | REPL `--debug` | `good differentials this week` -> `what about Mbeumo?` | differential follow-up rewrites to captain score for Mbeumo | `resolver_source == differential_followup`; `captain` present on second turn |  |  |

---

## Failure Modes

| ID | Surface | Prompt | Expected Semantics | Structured Check | Status | Notes |
|---|---|---|---|---|---|---|
| ERR-01 | REPL | `is Haaland injured?` | explicit unsupported response | no unrelated metadata |  |  |
| ERR-02 | REPL | `should I captain Smith` | explicit ambiguous or not-found handling | no invented player facts |  |  |
| ERR-03 | REPL | `compare someone and Salah` | safe not-found or ambiguity path | no invented winner |  |  |
| ERR-04 | HTTP | malformed or irrelevant prompt | explicit bounded response | contract still valid |  |  |

---

## Structured Metadata Parity Spot Checks

| ID | Surface | Scenario | Expected | Status | Notes |
|---|---|---|---|---|---|
| META-01 | CLI debug | captain success | `captain` present, others absent unless relevant |  |  |
| META-02 | CLI debug | ranking success | `captain_ranking` present |  |  |
| META-03 | CLI debug | comparison success | `comparison` present with reasons |  |  |
| META-04 | CLI debug | transfer success | `transfer` present |  |  |
| META-05 | CLI debug | chip success | `chip` present |  |  |
| META-06 | CLI debug | fixture run success | `fixture_run` present |  |  |
| META-07 | CLI debug | differential success | `differential` present |  |  |
| META-08 | CLI debug | multi-intent success | `sub_responses` present and aligned |  |  |
| META-09 | HTTP ask | same prompt family spot check | field names/shapes remain aligned with CLI |  |  |

---

## Phase 8b: Venue-Aware Metadata Spot Checks

These checks verify that home/away fixture factor (Phase 8b) is correctly exposed across surfaces.

| ID | Surface | Scenario | Expected | Status | Notes |
|---|---|---|---|---|---|
| P8B-01 | CLI debug | `compare Salah and Saka --debug` | `comparison.player_a.is_home` and `comparison.player_b.is_home` present and `True` (both home GW28) |  |  |
| P8B-02 | CLI debug | `compare Salah and Saka --debug` | `comparison.player_a.effective_fdr` = 3.5 (Salah, LIV home); `comparison.player_b.effective_fdr` = 4.5 (Saka, ARS home) |  |  |
| P8B-03 | CLI debug | `compare Salah and Saka --debug` | `comparison_reasons` contains `"easier fixture (FDR 4H vs 5H)"` (venue-tagged phrase) |  |  |
| P8B-04 | CLI debug | `compare Salah and Saka --debug` | `comparison.player_a.captain_score` and `player_b.captain_score` use raw int FDR (Layer 1 unchanged) |  |  |
| P8B-05 | HTTP ask | `good differentials this week` | each `picks[n].is_home` is `true`, `false`, or `null` (never missing key) in HTTP JSON response; `is_home` is not included in CLI debug JSON for differential picks |  |  |
| P8B-06 | HTTP ask | `compare Salah and Saka` | same `is_home` and `effective_fdr` fields present in JSON response body |  |  |
| P8B-07 | REPL `--debug` | `compare Salah and Saka` | REPL metadata line shows `efdr=3.5(H)` for Salah and `efdr=4.5(H)` for Saka |  |  |
| P8B-08 | REPL | `good differentials this week` | REPL differential plain text does NOT show per-pick venue tags (venue-awareness affects ranking via `effective_fdr` in `position_score` computation only); verify absence of `H`/`A`/`?` tags in pick lines as expected behavior — each line shows score, ownership, and price only |  |  |

### Phase 8b fallback verification

| ID | Surface | Scenario | Expected | Status | Notes |
|---|---|---|---|---|---|
| P8B-F1 | CLI debug | comparison with bootstrap lacking `team_fixtures` | `is_home=null`, `effective_fdr` equals raw FDR (no adjustment applied) |  |  |
| P8B-F2 | CLI debug | transfer advice prompt | `is_home` and `effective_fdr` present in backend score_inputs (debug bundle if available) |  |  |

---

## Phase 8a1: Position-Aware Scoring Spot Checks

| ID | Surface | Scenario | Expected | Status | Notes |
|---|---|---|---|---|---|
| P8A-01 | CLI `--debug` | `compare Raya and Salah` | Both `captain_score` and `position_score` present in comparison player contexts |  |  |
| P8A-02 | CLI `--debug` | `compare Raya and Salah` | Raya (GKP) `position_score` reflects saves/clean_sheet weighting; `xgi_score` component has zero weight for GKP |  |  |
| P8A-03 | CLI `--debug` | any two MID comparison (e.g. `compare Salah and Palmer`) | MID `position_score ≈ captain_score` (MID weights equal the canonical formula; no drift) |  |  |
| P8A-04 | HTTP ask | `compare Raya and Salah` | `comparison.player_a.position_score` and `player_b.position_score` present in JSON |  |  |
| P8A-05 | REPL | `good differentials this week` | differential ranking is position-score-based (not pure `captain_score`); verify any GKP in results is scored by saves/cs weighting; `position_score` is not a serialized JSON field in current differential output on any surface | `differential` present |  |

---

## Phase 8c: Free Hit Signal Label Verification

| ID | Surface | Scenario | Expected | Status | Notes |
|---|---|---|---|---|---|
| P8C-01 | CLI `--debug` | `should I free hit this week` | `chip.signal_label` is one of: `"double gameweek teams"`, `"blank gameweek teams"`, `"normal gameweek"` |  |  |
| P8C-02 | CLI `--debug` | `should I free hit this week` | `chip.signal_value` is consistent with label (0.0 for normal; positive N for DGW/BGW) |  |  |
| P8C-03 | CLI `--debug` | `should I free hit this week` | `chip.recommendation` is `conditions_favorable` (DGW), `conditions_marginal` (BGW), or `conditions_unfavorable` (normal) |  |  |
| P8C-04 | HTTP ask | `should I free hit this week` | `chip.signal_label` present and valid in JSON response |  |  |
| P8C-05 | Validation runner | `python run_validation.py --no-artifacts` | Scenarios `chip_advice_fh_dgw`, `chip_advice_fh_bgw`, `chip_advice_fh_normal` all PASS |  |  |

---

## Phase 8e: Squad Context Constraints

### Budget constraint

| ID | Surface | Scenario | Expected | Status | Notes |
|---|---|---|---|---|---|
| P8E-01 | CLI `--debug` | `should I sell Saka for Salah --itb 2.0` | `transfer.budget_constraint == true`; `final_text` contains budget constraint message |  |  |
| P8E-02 | CLI `--debug` | `should I sell Saka for Salah` (no `--itb`) | `transfer.budget_constraint == false`; advice proceeds normally |  |  |
| P8E-03 | HTTP ask | `squad_context: {"itb": 20}` with same transfer question | `transfer.budget_constraint == true` in JSON response |  |  |

### Chip unavailable

| ID | Surface | Scenario | Expected | Status | Notes |
|---|---|---|---|---|---|
| P8E-04 | CLI `--debug` | `should I use triple captain --chips-remaining wildcard,bench_boost,free_hit` | `chip.chip_unavailable == true`; `final_text` contains chip unavailable message |  |  |
| P8E-05 | CLI `--debug` | `should I use triple captain` (no `--chips-remaining`) | `chip.chip_unavailable == false`; chip advice proceeds normally |  |  |
| P8E-06 | HTTP ask | `squad_context: {"chips_remaining": ["wildcard","bench_boost","free_hit"]}` | `chip.chip_unavailable == true` in JSON response |  |  |

### Hit warning

| ID | Surface | Scenario | Expected | Status | Notes |
|---|---|---|---|---|---|
| P8E-07 | CLI `--debug` | `should I sell Saka for Salah --free-transfers 1` | `transfer.hit_warning == true` **only** if recommendation is `marginal_transfer_in`; `final_text` unchanged (advisory, not a hard block) |  |  |
| P8E-08 | CLI `--debug` | `should I sell Saka for Salah --free-transfers 1` | If recommendation is `transfer_in`, `hit_warning == false` even with `--free-transfers 1` |  |  |
| P8E-09 | HTTP ask | `squad_context: {"free_transfers": 1}` with marginal transfer | `transfer.hit_warning == true`; `transfer.recommendation == "marginal_transfer_in"` |  |  |

### Composability

| ID | Surface | Scenario | Expected | Status | Notes |
|---|---|---|---|---|---|
| P8E-10 | CLI `--debug` | `should I sell Saka for Salah --itb 2.0 --free-transfers 1` | `budget_constraint` and `hit_warning` are independent; each reflects its own condition |  |  |

### Session statelessness

| ID | Surface | Scenario | Expected | Status | Notes |
|---|---|---|---|---|---|
| P8E-11 | HTTP session | Turn 1: `squad_context: {"itb": 20}` → Turn 2: no `squad_context` | Turn 2 `transfer.budget_constraint == false`; constraint not persisted to `ConversationState` |  |  |
| P8E-12 | HTTP session | Turn 1: `squad_context: {"chips_remaining": [...]}` → Turn 2: no `squad_context` | Turn 2 `chip.chip_unavailable == false`; constraint not persisted |  |  |

---

## Exit Decision

| Check | Required For Go | Status | Notes |
|---|---|---|---|
| No blocker issues remain | Yes |  |  |
| Core CLI capability coverage complete | Yes |  |  |
| Follow-up/session coverage (incl. SES-06, SES-07) complete | Yes |  |  |
| Structured metadata spot checks complete | Yes |  |  |
| Phase 8b venue-aware metadata verified | Yes |  |  |
| Phase 8a1 position_score in comparison JSON; score_delta in transfer; rank-ordering in differential | Yes |  |  |
| Phase 8c free hit signal_label correct for current GW type | Yes |  |  |
| Phase 8e squad_context: budget_constraint, chip_unavailable, hit_warning | Yes |  |  |
| Phase 8e session statelessness: constraint does not persist across turns | Yes |  |  |
| Validation runner `run_validation.py` shows 44/44 PASS | Yes |  |  |
| Findings log written | Yes |  |  |
| Go or no-go decision written | Yes |  |  |
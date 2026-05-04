# FPL Grounded Assistant — Validation Report

Generated: 2026-05-04 13:13 UTC

## Summary

- **65 scenarios** tested
- **65 PASS**, **0 FAIL**

## Scenario Overview

| ID | Family | Intent | Outcome | Surfaces | Status |
|---|---|---|---|---|---|
| direct_captain_score | captain | captain_score | ok | cli, http | ✓ PASS |
| ranked_captain_candidates | ranking | rank_candidates | ok | cli, http | ✓ PASS |
| player_summary | summary | player_summary | ok | cli, http | ✓ PASS |
| player_resolve | resolve | player_resolve | ok | cli, http | ✓ PASS |
| direct_comparison | comparison | compare_players | ok | cli, http | ✓ PASS |
| unsupported_prompt | failure_modes | unsupported | unsupported_intent | cli, http | ✓ PASS |
| ambiguous_player | failure_modes | player_resolve | ambiguous | cli, http | ✓ PASS |
| not_found_player | failure_modes | captain_score | not_found | cli, http | ✓ PASS |
| no_session_follow_up | failure_modes | captain_score | not_found | cli, http | ✓ PASS |
| comparison_followup_det | comparison_followup_det | compare_players | ok | session_cli, session_http | ✓ PASS |
| comparison_followup_llm | comparison_followup_llm | compare_players | ok | session_cli | ✓ PASS |
| pronoun_det | pronoun_det | captain_score | ok | session_cli, session_http | ✓ PASS |
| pronoun_llm | pronoun_llm | captain_score | ok | session_cli | ✓ PASS |
| natural_captain_phrasing | llm_classify | captain_score | ok | cli, http, session_cli, session_http | ✓ PASS |
| natural_comparison_phrasing | llm_classify | compare_players | ok | cli, http, session_cli, session_http | ✓ PASS |
| natural_ranking_phrasing | llm_classify | rank_candidates | ok | cli, http, session_cli, session_http | ✓ PASS |
| transfer_advice_direct | transfer | transfer_advice | ok | cli, http | ✓ PASS |
| transfer_advice_not_found | transfer | transfer_advice | not_found | cli, http | ✓ PASS |
| chip_advice_tc | chip | chip_advice | ok | cli, http | ✓ PASS |
| chip_advice_wc | chip | chip_advice | ok | cli, http | ✓ PASS |
| chip_advice_fh | chip | chip_advice | ok | cli, http | ✓ PASS |
| multi_intent_gw_and_summary | multi_intent | multi_intent | ok | cli, http | ✓ PASS |
| multi_intent_captain_and_resolve | multi_intent | multi_intent | ok | cli, http | ✓ PASS |
| multi_intent_captain_and_comparison | multi_intent | multi_intent | ok | cli, http | ✓ PASS |
| chip_advice_triple_captain_structured | chip_advice | chip_advice | ok | cli, http | ✓ PASS |
| fixture_run_direct | player_fixture_run | player_fixture_run | ok | cli, http | ✓ PASS |
| fixture_run_not_found | player_fixture_run | player_fixture_run | not_found | cli, http | ✓ PASS |
| differential_picks_direct | differential_picks | differential_picks | error | cli, http | ✓ PASS |
| differential_picks_low_ownership | differential_picks | differential_picks | error | cli, http | ✓ PASS |
| transfer_followup_det | transfer_followup | transfer_advice | ok | session_cli, session_http | ✓ PASS |
| venue_aware_comparison | comparison | compare_players | ok | cli, http | ✓ PASS |
| differential_picks_structured | differential_picks | differential_picks | ok | cli, http | ✓ PASS |
| chip_advice_fh_dgw | chip_advice | chip_advice | ok | cli, http | ✓ PASS |
| chip_advice_fh_bgw | chip_advice | chip_advice | ok | cli, http | ✓ PASS |
| chip_advice_fh_normal | chip_advice | chip_advice | ok | cli, http | ✓ PASS |
| fixture_run_followup | fixture_run | player_fixture_run | ok | session_cli, session_http | ✓ PASS |
| differential_followup | captain | captain_score | ok | session_cli, session_http | ✓ PASS |
| transfer_budget_constraint | transfer | transfer_advice | ok | cli, http | ✓ PASS |
| transfer_hit_warning | transfer | transfer_advice | ok | cli, http | ✓ PASS |
| chip_unavailable_tc | chip | chip_advice | ok | cli, http | ✓ PASS |
| transfer_budget_constraint_session | transfer | transfer_advice | ok | session_cli, session_http | ✓ PASS |
| chip_unavailable_session | chip | chip_advice | ok | session_cli, session_http | ✓ PASS |
| transfer_hit_warning_session | transfer | transfer_advice | ok | session_cli, session_http | ✓ PASS |
| squad_context_stateless | transfer | transfer_advice | ok | session_http | ✓ PASS |
| spanish_compare_accusative_a | comparison | compare_players | ok | cli, http | ✓ PASS |
| spanish_compare_tengo_a | comparison | compare_players | not_found | cli, http | ✓ PASS |
| spanish_player_summary_resumen | summary | player_summary | ok | cli, http | ✓ PASS |
| spanish_rank_captain_quien_deberia | ranking | rank_candidates | ok | cli, http | ✓ PASS |
| spanish_rank_captain_ranking | ranking | rank_candidates | ok | cli, http | ✓ PASS |
| spanish_captain_score_named | captain | captain_score | ok | cli, http | ✓ PASS |
| degraded_flag_on_provider_failure | failure_modes | captain_score | ok | cli, http | ✓ PASS |
| player_form_last_3_salah | player_form | player_form | ok | cli, http | ✓ PASS |
| player_form_historial_salah | player_form | player_form | ok | cli, http | ✓ PASS |
| player_summary_with_totals | summary | player_summary | ok | cli, http | ✓ PASS |
| injury_check_named_player | summary | player_summary | ok | cli, http | ✓ PASS |
| injury_list_gw_wide | injury_list | injury_list | ok | cli, http | ✓ PASS |
| price_changes_risers | price_changes | price_changes | ok | cli, http | ✓ PASS |
| team_calendar_easiest_spanish | team_fixture_calendar | team_fixture_calendar | ok | cli, http | ✓ PASS |
| team_calendar_hardest_english | team_fixture_calendar | team_fixture_calendar | ok | cli, http | ✓ PASS |
| team_calendar_easiest_english_n | team_fixture_calendar | team_fixture_calendar | ok | cli, http | ✓ PASS |
| team_calendar_dgw_labeled | team_fixture_calendar | team_fixture_calendar | ok | cli, http | ✓ PASS |
| team_calendar_bgw_labeled | team_fixture_calendar | team_fixture_calendar | ok | cli, http | ✓ PASS |
| chip_wildcard_timing_antes_despues | chip | chip_advice | ok | cli, http | ✓ PASS |
| chip_bench_boost_conditional_tiene_sentido | chip | chip_advice | ok | cli, http | ✓ PASS |
| chip_wildcard_spent_sequencing | chip | chip_advice | ok | cli, http | ✓ PASS |

## Scenario Details

### direct_captain_score  (✓ PASS)

**Family:** captain  
**Description:** Realistic direct captaincy question for a known player.  
**Question:** `should I captain Salah`  
**Expected:** intent=`captain_score` outcome=`ok` supported=`True`  
**Notes:** Salah: tier='safe', role_bonus=5.0 (penalty taker). captain metadata present; comparison and captain_ranking absent.

**Surface results:**

- `cli`: intent=`captain_score` outcome=`ok` supported=`True`
  captain.tier=`safe` captain.role_bonus=`5.0`
- `http`: intent=`captain_score` outcome=`ok` supported=`True`
  captain.tier=`safe` captain.role_bonus=`5.0`

### ranked_captain_candidates  (✓ PASS)

**Family:** ranking  
**Description:** Ranked captain query with three explicitly supplied candidates.  
**Question:** `top captains this week`  
**Expected:** intent=`rank_candidates` outcome=`ok` supported=`True`  
**Notes:** Three candidates; Salah ranks #1 (safe), Haaland #2 (upside), Saka #3 (differential). captain and comparison absent.

**Surface results:**

- `cli`: intent=`rank_candidates` outcome=`ok` supported=`True`
  captain_ranking: 3 entries, #1=Salah
- `http`: intent=`rank_candidates` outcome=`ok` supported=`True`
  captain_ranking: 3 entries, #1=Salah

### player_summary  (✓ PASS)

**Family:** summary  
**Description:** Player stats/summary lookup for a known player.  
**Question:** `tell me about Haaland`  
**Expected:** intent=`player_summary` outcome=`ok` supported=`True`  
**Notes:** No structured metadata expected (player_summary has no captain/comparison/captain_ranking fields).

**Surface results:**

- `cli`: intent=`player_summary` outcome=`ok` supported=`True`
- `http`: intent=`player_summary` outcome=`ok` supported=`True`

### player_resolve  (✓ PASS)

**Family:** resolve  
**Description:** Player identity lookup for a known player.  
**Question:** `who is Salah`  
**Expected:** intent=`player_resolve` outcome=`ok` supported=`True`  
**Notes:** No structured metadata expected.

**Surface results:**

- `cli`: intent=`player_resolve` outcome=`ok` supported=`True`
- `http`: intent=`player_resolve` outcome=`ok` supported=`True`

### direct_comparison  (✓ PASS)

**Family:** comparison  
**Description:** Direct two-player comparison between two known players.  
**Question:** `Haaland vs Salah`  
**Expected:** intent=`compare_players` outcome=`ok` supported=`True`  
**Notes:** comparison metadata present: winner, margin, label, reasons, player_a (Haaland/FWD), player_b (Salah/MID). captain and captain_ranking absent.

**Surface results:**

- `cli`: intent=`compare_players` outcome=`ok` supported=`True`
  comparison.winner=`Salah` comparison.label=`moderate`
- `http`: intent=`compare_players` outcome=`ok` supported=`True`
  comparison.winner=`Salah` comparison.label=`moderate`

### unsupported_prompt  (✓ PASS)

**Family:** failure_modes  
**Description:** Question outside the supported intent set.  
**Question:** `Is Haaland fit to play?`  
**Expected:** intent=`unsupported` outcome=`unsupported_intent` supported=`False`  
**Notes:** supported=False; all three structured metadata fields absent. final_text still contains a user-facing message.

**Surface results:**

- `cli`: intent=`unsupported` outcome=`unsupported_intent` supported=`False`
- `http`: intent=`unsupported` outcome=`unsupported_intent` supported=`False`

### ambiguous_player  (✓ PASS)

**Family:** failure_modes  
**Description:** Player name matches multiple entries in the registry.  
**Question:** `who is Doe`  
**Expected:** intent=`player_resolve` outcome=`ambiguous` supported=`True`  
**Notes:** Uses AMBIGUOUS_BOOTSTRAP with two players sharing web_name 'Doe'. supported=True; outcome=ambiguous; no structured metadata.

**Surface results:**

- `cli`: intent=`player_resolve` outcome=`ambiguous` supported=`True`
- `http`: intent=`player_resolve` outcome=`ambiguous` supported=`True`

### not_found_player  (✓ PASS)

**Family:** failure_modes  
**Description:** Supported intent but player not in registry.  
**Question:** `should I captain xyznotaplayer999`  
**Expected:** intent=`captain_score` outcome=`not_found` supported=`True`  
**Notes:** supported=True (intent recognised); outcome=not_found (registry lookup fails). captain absent.

**Surface results:**

- `cli`: intent=`captain_score` outcome=`not_found` supported=`True`
- `http`: intent=`captain_score` outcome=`not_found` supported=`True`

### no_session_follow_up  (✓ PASS)

**Family:** failure_modes  
**Description:** Pronoun follow-up issued without any session context. The system treats 'him' as a literal player query and returns not_found rather than crashing.  
**Question:** `should I captain him`  
**Expected:** intent=`captain_score` outcome=`not_found` supported=`True`  
**Notes:** No ConversationSession — 'him' is passed as-is to the player registry and not found. Validates graceful failure, not resolution.

**Surface results:**

- `cli`: intent=`captain_score` outcome=`not_found` supported=`True`
- `http`: intent=`captain_score` outcome=`not_found` supported=`True`

### comparison_followup_det  (✓ PASS)

**Family:** comparison_followup_det  
**Description:** Session comparison follow-up resolved deterministically. Prior turn establishes Haaland vs Salah; follow-up 'And Saka?' is rewritten to 'compare Haaland and Saka'.  
**Question:** `And Saka?`  
**Expected:** intent=`compare_players` outcome=`ok` supported=`True`  
**Notes:** Prior turn: compare Haaland and Salah. Follow-up: 'And Saka?' → deterministic rewrite to compare Haaland and Saka. resolver_source == 'comparison_followup' on session_cli. comparison metadata present on both surfaces.

**Surface results:**

- `session_cli`: intent=`compare_players` outcome=`ok` supported=`True`
  resolver_source=`comparison_followup`
  rewritten=`compare Haaland and Saka`
  comparison.winner=`Haaland` comparison.label=`clear`
- `session_http`: intent=`compare_players` outcome=`ok` supported=`True`
  comparison.winner=`Haaland` comparison.label=`clear`

### comparison_followup_llm  (✓ PASS)

**Family:** comparison_followup_llm  
**Description:** Session comparison follow-up resolved by the LLM resolver stub. Prior turn establishes Haaland vs Salah; Spanish '¿Y Saka?' is rewritten to 'compare Haaland and Saka' via the Phase 5f stub.  
**Question:** `¿Y Saka?`  
**Expected:** intent=`compare_players` outcome=`ok` supported=`True`  
**Notes:** Surfaces: session_cli only — HTTP session uses deterministic fallback (no resolver_client). This is intentional. Stub returns {is_comparison_followup:true, new_player:'Saka', confidence:0.95}. resolver_source == 'comparison_followup_llm' confirms Phase 5f path.

**Surface results:**

- `session_cli`: intent=`compare_players` outcome=`ok` supported=`True`
  resolver_source=`comparison_followup_llm`
  rewritten=`compare Haaland and Saka`
  comparison.winner=`Haaland` comparison.label=`clear`

### pronoun_det  (✓ PASS)

**Family:** pronoun_det  
**Description:** Session pronoun follow-up resolved by Phase 4e deterministic substitution. Prior turn sets last_player=Salah; 'should I captain him' rewrites to 'should I captain Salah'.  
**Question:** `should I captain him`  
**Expected:** intent=`captain_score` outcome=`ok` supported=`True`  
**Notes:** resolver_source == 'fallback_regex' (Phase 4e deterministic path). captain metadata present; Salah as the resolved player. session_http also resolves correctly via deterministic fallback.

**Surface results:**

- `session_cli`: intent=`captain_score` outcome=`ok` supported=`True`
  resolver_source=`fallback_regex`
  rewritten=`should I captain Salah`
  captain.tier=`safe` captain.role_bonus=`5.0`
- `session_http`: intent=`captain_score` outcome=`ok` supported=`True`
  captain.tier=`safe` captain.role_bonus=`5.0`

### pronoun_llm  (✓ PASS)

**Family:** pronoun_llm  
**Description:** Session follow-up resolved by the Phase 4f LLM reference resolver stub. Prior turn sets last_player=Salah; Spanish '¿Y él?' is rewritten to 'should I captain Salah' via the Phase 4f stub.  
**Question:** `¿Y él?`  
**Expected:** intent=`captain_score` outcome=`ok` supported=`True`  
**Notes:** Surfaces: session_cli only — HTTP session uses deterministic fallback. This is intentional. Stub returns {resolved_query:'Salah', intent_guess:'captain_score', confidence:0.9, language:'es'}. resolver_source == 'llm' confirms Phase 4f path.

**Surface results:**

- `session_cli`: intent=`captain_score` outcome=`ok` supported=`True`
  resolver_source=`llm`
  rewritten=`should I captain Salah`
  captain.tier=`safe` captain.role_bonus=`5.0`

### natural_captain_phrasing  (✓ PASS)

**Family:** llm_classify  
**Description:** Natural captain question that deterministic route() cannot handle. LLM classifier rewrites to canonical form; route() then routes it.  
**Question:** `is Saka worth captaining?`  
**Expected:** intent=`captain_score` outcome=`ok` supported=`True`  
**Notes:** Phase 4l: all 4 surfaces. Stub returns canonical 'should I captain Saka'; route() extracts Saka. classification_source == 'llm_classifier' in debug bundle on all surfaces.

**Surface results:**

- `cli`: intent=`captain_score` outcome=`ok` supported=`True`
  captain.tier=`differential` captain.role_bonus=`0.5`
- `http`: intent=`captain_score` outcome=`ok` supported=`True`
  captain.tier=`differential` captain.role_bonus=`0.5`
- `session_cli`: intent=`captain_score` outcome=`ok` supported=`True`
  resolver_source=`none`
  rewritten=`is Saka worth captaining?`
  captain.tier=`differential` captain.role_bonus=`0.5`
- `session_http`: intent=`captain_score` outcome=`ok` supported=`True`
  captain.tier=`differential` captain.role_bonus=`0.5`

### natural_comparison_phrasing  (✓ PASS)

**Family:** llm_classify  
**Description:** Natural comparison question that deterministic route() cannot handle. LLM classifier rewrites to canonical form; route() extracts both players.  
**Question:** `what's the score differential between Salah and Haaland?`  
**Expected:** intent=`compare_players` outcome=`ok` supported=`True`  
**Notes:** Phase 4l: all 4 surfaces. Stub returns canonical 'compare Salah and Haaland'; route() extracts both. classification_source == 'llm_classifier'. comparison metadata present.

**Surface results:**

- `cli`: intent=`compare_players` outcome=`ok` supported=`True`
  comparison.winner=`Salah` comparison.label=`moderate`
- `http`: intent=`compare_players` outcome=`ok` supported=`True`
  comparison.winner=`Salah` comparison.label=`moderate`
- `session_cli`: intent=`compare_players` outcome=`ok` supported=`True`
  resolver_source=`none`
  rewritten=`what's the score differential between Salah and Haaland?`
  comparison.winner=`Salah` comparison.label=`moderate`
- `session_http`: intent=`compare_players` outcome=`ok` supported=`True`
  comparison.winner=`Salah` comparison.label=`moderate`

### natural_ranking_phrasing  (✓ PASS)

**Family:** llm_classify  
**Description:** Natural ranking question that deterministic route() cannot handle. LLM classifier rewrites to canonical form; candidates_list supplied.  
**Question:** `who looks best for captain this week?`  
**Expected:** intent=`rank_candidates` outcome=`ok` supported=`True`  
**Notes:** Phase 4l: all 4 surfaces. Stub returns canonical 'top captains this week'; candidates_list supplied. classification_source == 'llm_classifier'. captain_ranking present.

**Surface results:**

- `cli`: intent=`rank_candidates` outcome=`ok` supported=`True`
  captain_ranking: 3 entries, #1=Salah
- `http`: intent=`rank_candidates` outcome=`ok` supported=`True`
  captain_ranking: 3 entries, #1=Salah
- `session_cli`: intent=`rank_candidates` outcome=`ok` supported=`True`
  resolver_source=`none`
  rewritten=`who looks best for captain this week?`
  captain_ranking: 3 entries, #1=Salah
- `session_http`: intent=`rank_candidates` outcome=`ok` supported=`True`
  captain_ranking: 3 entries, #1=Salah

### transfer_advice_direct  (✓ PASS)

**Family:** transfer  
**Description:** Direct transfer advice: sell Saka for Salah. Both players known in STANDARD_BOOTSTRAP. Deterministic recommendation with structured TransferMeta.  
**Question:** `should I sell Saka for Salah`  
**Expected:** intent=`transfer_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 6a/7a: deterministic transfer advice with structured metadata. Salah (higher captain_score) vs Saka -- recommendation should be 'transfer_in'. FinalResponse.transfer non-null: player_out='Saka', player_in='Salah', recommendation='transfer_in', score_delta (float > 0), price_delta (int), reasons (non-empty list). captain, comparison, captain_ranking all absent.

**Surface results:**

- `cli`: intent=`transfer_advice` outcome=`ok` supported=`True`
  transfer.player_out=`Saka` transfer.player_in=`Salah` transfer.recommendation=`transfer_in`
- `http`: intent=`transfer_advice` outcome=`ok` supported=`True`
  transfer.player_out=`Saka` transfer.player_in=`Salah` transfer.recommendation=`transfer_in`

### transfer_advice_not_found  (✓ PASS)

**Family:** transfer  
**Description:** Transfer advice where the target player cannot be found. Outcome should be not_found, supported=True.  
**Question:** `should I sell Saka for UnknownPlayerXYZ`  
**Expected:** intent=`transfer_advice` outcome=`not_found` supported=`True`  
**Notes:** Phase 6a: transfer advice not_found path. UnknownPlayerXYZ is not in STANDARD_BOOTSTRAP. supported=True (intent was recognised), outcome=not_found.

**Surface results:**

- `cli`: intent=`transfer_advice` outcome=`not_found` supported=`True`
- `http`: intent=`transfer_advice` outcome=`not_found` supported=`True`

### chip_advice_tc  (✓ PASS)

**Family:** chip  
**Description:** Chip advice for triple captain. Routing detects 'triple captain' + advisory phrase. Returns conditions_marginal for STANDARD_BOOTSTRAP (GW28, top score ~60).  
**Question:** `should I use triple captain this week`  
**Expected:** intent=`chip_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 6b: chip advice capability. STANDARD_BOOTSTRAP GW28, top MID/FWD captain score ~60 (between _TC_MARGINAL_THRESHOLD=55 and _TC_FAVORABLE_THRESHOLD=75). Recommendation: conditions_marginal. final_text contains 'Triple captain conditions: marginal'.

**Surface results:**

- `cli`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`triple_captain` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`top captain score`
- `http`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`triple_captain` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`top captain score`

### chip_advice_wc  (✓ PASS)

**Family:** chip  
**Description:** Chip advice for wildcard. Routing detects 'wildcard' + 'this week'. GW28 is in the viable window (7 <= 28 < 29) -> conditions_marginal.  
**Question:** `should I wildcard this week`  
**Expected:** intent=`chip_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 6b: wildcard chip advice. STANDARD_BOOTSTRAP GW28 falls in viable window (_WC_EARLY_CUTOFF=6 < 28 < _WC_LATE_CUTOFF=29). Recommendation: conditions_marginal. final_text contains 'Wildcard conditions: marginal'.

**Surface results:**

- `cli`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`wildcard` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`current gameweek`
- `http`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`wildcard` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`current gameweek`

### chip_advice_fh  (✓ PASS)

**Family:** chip  
**Description:** Chip advice for free hit in a normal gameweek. Phase 8c: STANDARD_BOOTSTRAP has no DGW/BGW teams -> recommendation=conditions_unfavorable.  
**Question:** `should I free hit this week`  
**Expected:** intent=`chip_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 8c: free hit chip advice with DGW/BGW detection. STANDARD_BOOTSTRAP GW28: all 5 teams have exactly 1 GW28 fixture -> gameweek_type='normal' -> recommendation=conditions_unfavorable. outcome=ok (intent recognised, chip processed). final_text contains 'Free hit conditions: unfavorable'.

**Surface results:**

- `cli`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`free_hit` chip.recommendation=`conditions_unfavorable` chip.gw=`28` chip.signal_label=`normal gameweek`
- `http`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`free_hit` chip.recommendation=`conditions_unfavorable` chip.gw=`28` chip.signal_label=`normal gameweek`

### multi_intent_gw_and_summary  (✓ PASS)

**Family:** multi_intent  
**Description:** Multi-intent question combining current-gameweek and player-summary. Both halves independently route; respond() returns intent=multi_intent.  
**Question:** `tell me about Salah and what gameweek is it`  
**Expected:** intent=`multi_intent` outcome=`ok` supported=`True`  
**Notes:** Phase 6c: first multi-intent slice. Part 1: 'tell me about Salah' -> player_summary OK. Part 2: 'what gameweek is it' -> current_gameweek OK. combined outcome=ok; sub_responses has 2 entries. final_text concatenates both sub-responses separated by blank line.

**Surface results:**

- `cli`: intent=`multi_intent` outcome=`ok` supported=`True`
- `http`: intent=`multi_intent` outcome=`ok` supported=`True`

### multi_intent_captain_and_resolve  (✓ PASS)

**Family:** multi_intent  
**Description:** Multi-intent question combining captain-score and player-resolve. Both halves independently route; respond() returns intent=multi_intent.  
**Question:** `should I captain Haaland and who is Saka`  
**Expected:** intent=`multi_intent` outcome=`ok` supported=`True`  
**Notes:** Phase 6c: multi-intent combining captain_score and player_resolve. Part 1: 'should I captain Haaland' -> captain_score OK. Part 2: 'who is Saka' -> player_resolve OK. sub_responses[0].intent=captain_score, sub_responses[1].intent=player_resolve. single-intent turns: sub_responses absent.

**Surface results:**

- `cli`: intent=`multi_intent` outcome=`ok` supported=`True`
- `http`: intent=`multi_intent` outcome=`ok` supported=`True`

### multi_intent_captain_and_comparison  (✓ PASS)

**Family:** multi_intent  
**Description:** Multi-intent combining captain-score and comparison. Both sub-responses expose bounded structured metadata: captain on the captain sub-intent, comparison on the compare sub-intent.  
**Question:** `should I captain Haaland and compare Salah and Haaland`  
**Expected:** intent=`multi_intent` outcome=`ok` supported=`True`  
**Notes:** Phase 6d: structured sub-response metadata. Part 1: 'should I captain Haaland' -> captain_score OK; sub_responses[0].captain non-null. Part 2: 'compare Salah and Haaland' -> compare_players OK; sub_responses[1].comparison non-null. Splits on first ' and '; part_b contains its own ' and ' (two-player connector). Top-level response: intent=multi_intent, sub_responses has 2 entries. CLI debug + HTTP body expose captain/comparison per sub-response.

**Surface results:**

- `cli`: intent=`multi_intent` outcome=`ok` supported=`True`
- `http`: intent=`multi_intent` outcome=`ok` supported=`True`

### chip_advice_triple_captain_structured  (✓ PASS)

**Family:** chip_advice  
**Description:** Triple captain chip advice returns structured ChipAdviceMeta with chip, recommendation, gw, signal_value, and signal_label.  
**Question:** `should I use triple captain this week`  
**Expected:** intent=`chip_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 7b: structured chip metadata. FinalResponse.chip non-null; chip=='triple_captain'. recommendation in {conditions_favorable, conditions_marginal, conditions_unfavorable}. signal_value is top MID/FWD captain score (float); signal_label=='top captain score'. gw is current gameweek (int). CLI debug and HTTP /ask body both expose 'chip' dict. Non-debug CLI output is final_text only (unchanged).

**Surface results:**

- `cli`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`triple_captain` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`top captain score`
- `http`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`triple_captain` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`top captain score`

### fixture_run_direct  (✓ PASS)

**Family:** player_fixture_run  
**Description:** Player fixture run via suffix form ('Salah fixtures') returns structured FixtureRunMeta with web_name, team_short, position, horizon, current_gameweek, and a list of upcoming fixture entries.  
**Question:** `Salah fixtures`  
**Expected:** intent=`player_fixture_run` outcome=`ok` supported=`True`  
**Notes:** Phase 7h: player fixture run with structured metadata. FinalResponse.fixture_run non-null; web_name=='Salah', team_short=='LIV', position=='MID'. horizon==5; len(fixtures)==5; each fixture has gameweek, opponent_short, is_home, difficulty. CLI debug and HTTP /ask body both expose 'fixture_run' dict. Non-debug CLI output is plain text only (unchanged).

**Surface results:**

- `cli`: intent=`player_fixture_run` outcome=`ok` supported=`True`
  fixture_run.web_name=`Salah` fixture_run.team_short=`LIV` fixture_run.horizon=`5` fixtures=5
- `http`: intent=`player_fixture_run` outcome=`ok` supported=`True`
  fixture_run.web_name=`Salah` fixture_run.team_short=`LIV` fixture_run.horizon=`5` fixtures=5

### fixture_run_not_found  (✓ PASS)

**Family:** player_fixture_run  
**Description:** Player fixture run for an unknown player returns not_found outcome with supported=True and fixture_run=None.  
**Question:** `NonExistentXYZ fixtures`  
**Expected:** intent=`player_fixture_run` outcome=`not_found` supported=`True`  
**Notes:** Phase 7h: fixture run not-found path. Player 'NonExistentXYZ' does not exist in the registry. FinalResponse.fixture_run is None; outcome='not_found'; supported=True. final_text is a graceful 'not found' message.

**Surface results:**

- `cli`: intent=`player_fixture_run` outcome=`not_found` supported=`True`
- `http`: intent=`player_fixture_run` outcome=`not_found` supported=`True`

### differential_picks_direct  (✓ PASS)

**Family:** differential_picks  
**Description:** Differential picks query returns ok outcome with DifferentialPicksMeta when the bootstrap contains available players with ownership < 15%.  
**Question:** `good differentials`  
**Expected:** intent=`differential_picks` outcome=`error` supported=`True`  
**Notes:** Phase 7g: differential picks intent routing. STANDARD_BOOTSTRAP has no available players with ownership < 15% (De Bruyne is 14.2% but injured), so the tool returns status='empty' which maps to outcome='error' (not 'ok'). Intent routing is correct (differential_picks). FinalResponse.differential is None since outcome != ok. See run_phase7g_tests.py for full ok-path coverage using DIFFERENTIAL_BOOTSTRAP.

**Surface results:**

- `cli`: intent=`differential_picks` outcome=`error` supported=`True`
- `http`: intent=`differential_picks` outcome=`error` supported=`True`

### differential_picks_low_ownership  (✓ PASS)

**Family:** differential_picks  
**Description:** Low ownership keyword form routes to differential_picks intent.  
**Question:** `low ownership picks`  
**Expected:** intent=`differential_picks` outcome=`error` supported=`True`  
**Notes:** Phase 7g: low-ownership keyword routing. 'low ownership picks' routes to differential_picks intent. Same bootstrap caveat as differential_picks_direct.

**Surface results:**

- `cli`: intent=`differential_picks` outcome=`error` supported=`True`
- `http`: intent=`differential_picks` outcome=`error` supported=`True`

### transfer_followup_det  (✓ PASS)

**Family:** transfer_followup  
**Description:** Session transfer follow-up resolved deterministically. Prior turn establishes sell Saka for Salah; follow-up 'what about Haaland instead' is rewritten to 'sell Saka for Haaland'.  
**Question:** `what about Haaland instead`  
**Expected:** intent=`transfer_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 7f: deterministic transfer follow-up rewrite. Prior turn: sell Saka for Salah (sets last_transfer=('Saka','Salah')). Follow-up: 'what about Haaland instead' -> 'sell Saka for Haaland'. resolver_source == 'transfer_followup' on session_cli. FinalResponse.transfer non-null on both surfaces: player_out='Saka', player_in='Haaland'. Haaland (FWD, high form) vs Saka (doubtful, lower minutes). recommendation is likely 'transfer_in' or 'marginal_transfer_in'.

**Surface results:**

- `session_cli`: intent=`transfer_advice` outcome=`ok` supported=`True`
  resolver_source=`transfer_followup`
  rewritten=`sell Saka for Haaland`
  transfer.player_out=`Saka` transfer.player_in=`Haaland` transfer.recommendation=`transfer_in`
- `session_http`: intent=`transfer_advice` outcome=`ok` supported=`True`
  transfer.player_out=`Saka` transfer.player_in=`Haaland` transfer.recommendation=`transfer_in`

### venue_aware_comparison  (✓ PASS)

**Family:** comparison  
**Description:** Phase 8b: comparison with STANDARD_BOOTSTRAP (has team_fixtures) returns ComparisonMeta with is_home and effective_fdr per player. Salah (LIV home GW28, efdr=3.5) vs Saka (ARS home GW28, efdr=4.5); Salah wins; FDR reason includes venue tag.  
**Question:** `compare Salah and Saka`  
**Expected:** intent=`compare_players` outcome=`ok` supported=`True`  
**Notes:** Phase 8b: venue-aware comparison cross-surface parity. Both players are home in GW28 per STANDARD_BOOTSTRAP team_fixtures. Salah (LIV, raw FDR=4, efdr=3.5) wins over Saka (ARS, raw FDR=5, efdr=4.5). comparison.player_a and player_b each expose is_home=True and effective_fdr. comparison_reasons includes 'easier fixture (FDR 4H vs 5H)' because efdr diff = 1.0 >= threshold and both players are tagged home. Layer 1 captain_score still uses raw int FDR (no venue adjustment). CLI debug and HTTP /ask body both expose the comparison dict.

**Surface results:**

- `cli`: intent=`compare_players` outcome=`ok` supported=`True`
  comparison.winner=`Salah` comparison.label=`clear`
- `http`: intent=`compare_players` outcome=`ok` supported=`True`
  comparison.winner=`Salah` comparison.label=`clear`

### differential_picks_structured  (✓ PASS)

**Family:** differential_picks  
**Description:** Differential picks with DIFFERENTIAL_BOOTSTRAP returns DifferentialPicksMeta with at least one qualifying pick.  
**Question:** `good differentials`  
**Expected:** intent=`differential_picks` outcome=`ok` supported=`True`  
**Notes:** Phase 7g: differential picks structured ok-path (V2 corpus). DIFFERENTIAL_BOOTSTRAP adds Palmer (CHE, 3.5% owned, status='a') and Mbeumo (MUN, 8.2% owned, status='a'). Both qualify (< 15%). FinalResponse.differential non-null: ownership_threshold==15.0, top_n==5, len(picks) >= 1. picks[0].rank==1; each pick has web_name, team_short, position, captain_score, ownership, now_cost. CLI debug and HTTP /ask body both expose 'differential' dict.

**Surface results:**

- `cli`: intent=`differential_picks` outcome=`ok` supported=`True`
  differential.ownership_threshold=`15.0` picks=2 top=`Mbeumo`
- `http`: intent=`differential_picks` outcome=`ok` supported=`True`
  differential.ownership_threshold=`15.0` picks=2 top=`Mbeumo`

### chip_advice_fh_dgw  (✓ PASS)

**Family:** chip_advice  
**Description:** Free hit chip advice with DGW_BOOTSTRAP: 6 teams each play twice in GW28 -> recommendation=conditions_favorable.  
**Question:** `should I free hit this week`  
**Expected:** intent=`chip_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 8c: free hit in large double gameweek. DGW_BOOTSTRAP: ARS, MCI, LIV, CHE, MUN, TOT each have 2 GW28 fixtures -> _classify_gameweek_type returns ('double', [...], 6). affected_count (6) >= _FH_DGW_FAVORABLE_TEAMS (6) -> recommendation=conditions_favorable. FinalResponse.chip non-null: chip='free_hit', signal_value=6.0, signal_label='double gameweek teams'. final_text contains 'Free hit conditions: favorable'.

**Surface results:**

- `cli`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`free_hit` chip.recommendation=`conditions_favorable` chip.gw=`28` chip.signal_label=`double gameweek teams`
- `http`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`free_hit` chip.recommendation=`conditions_favorable` chip.gw=`28` chip.signal_label=`double gameweek teams`

### chip_advice_fh_bgw  (✓ PASS)

**Family:** chip_advice  
**Description:** Free hit chip advice with BGW_BOOTSTRAP: 2 teams (ARS, MCI) have no GW28 fixture -> recommendation=conditions_marginal.  
**Question:** `should I free hit this week`  
**Expected:** intent=`chip_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 8c: free hit in blank gameweek. BGW_BOOTSTRAP: ARS and MCI have no GW28 entries -> _classify_gameweek_type returns ('blank', ['ARS', 'MCI'], 2). recommendation=conditions_marginal (save for next DGW). FinalResponse.chip non-null: chip='free_hit', signal_value=2.0, signal_label='blank gameweek teams'. final_text contains 'Free hit conditions: marginal'.

**Surface results:**

- `cli`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`free_hit` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`blank gameweek teams`
- `http`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`free_hit` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`blank gameweek teams`

### chip_advice_fh_normal  (✓ PASS)

**Family:** chip_advice  
**Description:** Free hit chip advice with STANDARD_BOOTSTRAP: all 5 teams have exactly 1 GW28 fixture -> recommendation=conditions_unfavorable.  
**Question:** `should I free hit this week`  
**Expected:** intent=`chip_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 8c: free hit in normal gameweek. STANDARD_BOOTSTRAP: all 5 teams have 1 GW28 fixture each -> _classify_gameweek_type returns ('normal', [], 0). recommendation=conditions_unfavorable. FinalResponse.chip non-null: chip='free_hit', signal_value=0.0, signal_label='normal gameweek'. final_text contains 'Free hit conditions: unfavorable'.

**Surface results:**

- `cli`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`free_hit` chip.recommendation=`conditions_unfavorable` chip.gw=`28` chip.signal_label=`normal gameweek`
- `http`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`free_hit` chip.recommendation=`conditions_unfavorable` chip.gw=`28` chip.signal_label=`normal gameweek`

### fixture_run_followup  (✓ PASS)

**Family:** fixture_run  
**Description:** Deterministic fixture run follow-up: after 'Haaland fixtures', 'what about Salah?' rewrites to 'Salah fixtures' without LLM.  
**Question:** `what about Salah?`  
**Expected:** intent=`player_fixture_run` outcome=`ok` supported=`True`  
**Notes:** Phase 8d-i: deterministic fixture run follow-up rewrite. Prior turn: 'Haaland fixtures' (sets last_fixture_run_player='Haaland'). Follow-up: 'what about Salah?' → deterministic rewrite to 'Salah fixtures'. resolver_source='fixture_run_followup'. fixture_run.web_name should be 'Salah' (resolved from STANDARD_BOOTSTRAP). No LLM call required for the rewrite.

**Surface results:**

- `session_cli`: intent=`player_fixture_run` outcome=`ok` supported=`True`
  resolver_source=`fixture_run_followup`
  rewritten=`Salah fixtures`
  fixture_run.web_name=`Salah` fixture_run.team_short=`LIV` fixture_run.horizon=`5` fixtures=5
- `session_http`: intent=`player_fixture_run` outcome=`ok` supported=`True`
  fixture_run.web_name=`Salah` fixture_run.team_short=`LIV` fixture_run.horizon=`5` fixtures=5

### differential_followup  (✓ PASS)

**Family:** captain  
**Description:** Deterministic differential follow-up: after 'good differentials', 'what about Mbeumo?' rewrites to 'should I captain Mbeumo?' without LLM.  
**Question:** `what about Mbeumo?`  
**Expected:** intent=`captain_score` outcome=`ok` supported=`True`  
**Notes:** Phase 8d-ii: deterministic differential follow-up rewrite. Prior turn: 'good differentials' (sets last_differential=True). Follow-up: 'what about Mbeumo?' -> deterministic rewrite to 'should I captain Mbeumo?'. resolver_source='differential_followup'. Resolves via captain score path (INTENT_CAPTAIN_SCORE). No LLM call required for the rewrite.

**Surface results:**

- `session_cli`: intent=`captain_score` outcome=`ok` supported=`True`
  resolver_source=`differential_followup`
  rewritten=`should I captain Mbeumo?`
  captain.tier=`differential` captain.role_bonus=`5.0`
- `session_http`: intent=`captain_score` outcome=`ok` supported=`True`
  captain.tier=`differential` captain.role_bonus=`5.0`

### transfer_budget_constraint  (✓ PASS)

**Family:** transfer  
**Description:** Transfer advice with squad_context itb below price_delta: 'sell Saka buy Salah' with itb=20 (£2.0m), price_delta=35 (£3.5m) -> budget_constraint=True in TransferMeta.  
**Question:** `should I sell Saka for Salah`  
**Expected:** intent=`transfer_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 8e1: budget_constraint override. Saka now_cost=100, Salah now_cost=135, price_delta=35 (£3.5m). itb=20 (£2.0m) < 35 -> budget_constraint=True in TransferMeta. final_text becomes budget constraint message. transfer metadata is still populated (intent=ok).

**Surface results:**

- `cli`: intent=`transfer_advice` outcome=`ok` supported=`True`
  transfer.player_out=`Saka` transfer.player_in=`Salah` transfer.recommendation=`transfer_in` budget_constraint=`True`
- `http`: intent=`transfer_advice` outcome=`ok` supported=`True`
  transfer.player_out=`Saka` transfer.player_in=`Salah` transfer.recommendation=`transfer_in` budget_constraint=`True`

### transfer_hit_warning  (✓ PASS)

**Family:** transfer  
**Description:** Transfer advice with squad_context free_transfers==1 and a marginal recommendation -> hit_warning=True in TransferMeta.  
**Question:** `should I sell Haaland for Salah`  
**Expected:** intent=`transfer_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 8e2: hit_warning flag. MARGINAL_TRANSFER_BOOTSTRAP has Haaland form=9.1 (score ~59.25) vs Salah form=9.5 (score ~60.58), delta ~1.33 -> marginal_transfer_in. free_transfers==1 + marginal_transfer_in -> hit_warning=True. final_text is NOT overridden (advisory flag only, not a hard block). recommendation stays marginal_transfer_in.

**Surface results:**

- `cli`: intent=`transfer_advice` outcome=`ok` supported=`True`
  transfer.player_out=`Haaland` transfer.player_in=`Salah` transfer.recommendation=`marginal_transfer_in` hit_warning=`True`
- `http`: intent=`transfer_advice` outcome=`ok` supported=`True`
  transfer.player_out=`Haaland` transfer.player_in=`Salah` transfer.recommendation=`marginal_transfer_in` hit_warning=`True`

### chip_unavailable_tc  (✓ PASS)

**Family:** chip  
**Description:** Chip advice with squad_context chips_remaining that excludes triple_captain -> chip_unavailable=True in ChipAdviceMeta.  
**Question:** `should I use my triple captain`  
**Expected:** intent=`chip_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 8e1: chip_unavailable override. Requested chip: triple_captain. chips_remaining excludes triple_captain -> chip_unavailable=True. final_text becomes chip unavailable message. chip metadata is still populated (intent=ok).

**Surface results:**

- `cli`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`triple_captain` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`top captain score` chip_unavailable=`True`
- `http`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`triple_captain` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`top captain score` chip_unavailable=`True`

### transfer_budget_constraint_session  (✓ PASS)

**Family:** transfer  
**Description:** Transfer budget constraint applied via squad_context on a session turn. Validates that session surfaces enforce the constraint identically to the stateless cli/http surfaces.  
**Question:** `should I sell Saka for Salah`  
**Expected:** intent=`transfer_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 8f2: budget_constraint on session surfaces. Mirrors scenario 38 on session_cli and session_http. itb=20 (£2.0m) < price_delta=35 (£3.5m) -> budget_constraint=True. squad_context is per-turn; session state is not modified.

**Surface results:**

- `session_cli`: intent=`transfer_advice` outcome=`ok` supported=`True`
  resolver_source=`none`
  rewritten=`should I sell Saka for Salah`
  transfer.player_out=`Saka` transfer.player_in=`Salah` transfer.recommendation=`transfer_in` budget_constraint=`True`
- `session_http`: intent=`transfer_advice` outcome=`ok` supported=`True`
  transfer.player_out=`Saka` transfer.player_in=`Salah` transfer.recommendation=`transfer_in` budget_constraint=`True`

### chip_unavailable_session  (✓ PASS)

**Family:** chip  
**Description:** Chip unavailable override applied via squad_context on a session turn. Validates that session surfaces enforce the constraint identically to the stateless cli/http surfaces.  
**Question:** `should I use my triple captain`  
**Expected:** intent=`chip_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 8f2: chip_unavailable on session surfaces. Mirrors scenario 40 on session_cli and session_http. chips_remaining excludes triple_captain -> chip_unavailable=True. squad_context is per-turn; session state is not modified.

**Surface results:**

- `session_cli`: intent=`chip_advice` outcome=`ok` supported=`True`
  resolver_source=`none`
  rewritten=`should I use my triple captain`
  chip.chip=`triple_captain` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`top captain score` chip_unavailable=`True`
- `session_http`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`triple_captain` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`top captain score` chip_unavailable=`True`

### transfer_hit_warning_session  (✓ PASS)

**Family:** transfer  
**Description:** Transfer hit warning applied via squad_context on a session turn. Validates that session surfaces enforce the advisory flag identically to the stateless cli/http surfaces.  
**Question:** `should I sell Haaland for Salah`  
**Expected:** intent=`transfer_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 8f2: hit_warning on session surfaces. Mirrors scenario 39 on session_cli and session_http. MARGINAL_TRANSFER_BOOTSTRAP: Haaland form=9.1, delta ~1.33 -> marginal_transfer_in. free_transfers==1 + marginal_transfer_in -> hit_warning=True. final_text is NOT overridden (advisory flag only).

**Surface results:**

- `session_cli`: intent=`transfer_advice` outcome=`ok` supported=`True`
  resolver_source=`none`
  rewritten=`should I sell Haaland for Salah`
  transfer.player_out=`Haaland` transfer.player_in=`Salah` transfer.recommendation=`marginal_transfer_in` hit_warning=`True`
- `session_http`: intent=`transfer_advice` outcome=`ok` supported=`True`
  transfer.player_out=`Haaland` transfer.player_in=`Salah` transfer.recommendation=`marginal_transfer_in` hit_warning=`True`

### squad_context_stateless  (✓ PASS)

**Family:** transfer  
**Description:** squad_context applied on turn 1 does not persist to turn 2. Prior turn: 'sell Saka for Salah' WITH itb=20 -> budget_constraint=True. Final turn: same question WITHOUT squad_context -> budget_constraint=False.  
**Question:** `should I sell Saka for Salah`  
**Expected:** intent=`transfer_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 8f2: squad_context statelessness. Turn 1: budget_constraint fires (itb=20 < price_delta=35). Turn 2 (asserted): same question, no squad_context -> budget_constraint=False. Confirms squad_context is NOT persisted to ConversationState between turns. session_http only: prior-turn squad_context is injected per-payload. session_cli excluded — cli_run_session takes a single context for all turns.

**Surface results:**

- `session_http`: intent=`transfer_advice` outcome=`ok` supported=`True`
  transfer.player_out=`Saka` transfer.player_in=`Salah` transfer.recommendation=`transfer_in`

### spanish_compare_accusative_a  (✓ PASS)

**Family:** comparison  
**Description:** Spanish 'compara a Salah y Haaland' — accusative 'a' must be stripped from player tokens before registry lookup.  
**Question:** `compara a Salah y Haaland`  
**Expected:** intent=`compare_players` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6b Story 1.1: _strip_spanish_name_prefix removes leading 'a ' so 'a Salah' → 'Salah' before registry lookup. Both Salah and Haaland are in STANDARD_BOOTSTRAP. comparison.winner should be non-null (Salah or Haaland). Before the fix: compare_players intent with 'a Salah' → not_found. After the fix: ok with valid comparison metadata.

**Surface results:**

- `cli`: intent=`compare_players` outcome=`ok` supported=`True`
  comparison.winner=`Salah` comparison.label=`moderate`
- `http`: intent=`compare_players` outcome=`ok` supported=`True`
  comparison.winner=`Salah` comparison.label=`moderate`

### spanish_compare_tengo_a  (✓ PASS)

**Family:** comparison  
**Description:** Spanish 'tengo a Saka y Haaland' — 'tengo a ' prefix noise must be stripped so 'tengo a Saka' resolves as 'Saka'.  
**Question:** `tengo a saka y rashford en mi equipo, a cuál vendo primero`  
**Expected:** intent=`compare_players` outcome=`not_found` supported=`True`  
**Notes:** Phase 2.6b Story 1.1: bare ' y ' connector routes to compare_players. After _strip_spanish_name_prefix: 'tengo a saka' → 'saka' (resolves OK). 'rashford en mi equipo, a cuál vendo primero' is not in STANDARD_BOOTSTRAP → not_found. intent=compare_players confirms routing success; the name-prefix fix is validated on part_a (saka resolves). Rashford is absent from STANDARD_BOOTSTRAP — not_found is expected.

**Surface results:**

- `cli`: intent=`compare_players` outcome=`not_found` supported=`True`
- `http`: intent=`compare_players` outcome=`not_found` supported=`True`

### spanish_player_summary_resumen  (✓ PASS)

**Family:** summary  
**Description:** Spanish 'dame un resumen de Salah' routes to player_summary via the new Spanish _SUMMARY_PREFIXES entries.  
**Question:** `dame un resumen de Salah`  
**Expected:** intent=`player_summary` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6b Story 1.4: 'dame un resumen de' added to _SUMMARY_PREFIXES. Prefix stripped → 'Salah' → found in STANDARD_BOOTSTRAP. Before the fix: unsupported_intent. After: player_summary ok.

**Surface results:**

- `cli`: intent=`player_summary` outcome=`ok` supported=`True`
- `http`: intent=`player_summary` outcome=`ok` supported=`True`

### spanish_rank_captain_quien_deberia  (✓ PASS)

**Family:** ranking  
**Description:** Spanish 'quién debería capitanear esta semana' routes to rank_candidates via the new Spanish _RANK_PREFIXES entries.  
**Question:** `quién debería capitanear esta semana`  
**Expected:** intent=`rank_candidates` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6b Story 1.4: generic Spanish captain ranking. 'quién debería capitanear esta semana' added to _RANK_PREFIXES. Routes to rank_candidates; candidates_list supplied. Before the fix: unsupported_intent. After: rank_candidates ok.

**Surface results:**

- `cli`: intent=`rank_candidates` outcome=`ok` supported=`True`
  captain_ranking: 2 entries, #1=Salah
- `http`: intent=`rank_candidates` outcome=`ok` supported=`True`
  captain_ranking: 2 entries, #1=Salah

### spanish_rank_captain_ranking  (✓ PASS)

**Family:** ranking  
**Description:** Spanish 'dame el ranking de capitanes' routes to rank_candidates via the new Spanish _RANK_PREFIXES / _RANKING_KEYWORDS entries.  
**Question:** `dame el ranking de capitanes`  
**Expected:** intent=`rank_candidates` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6b Story 1.4: 'dame el ranking de capitanes' added to _RANK_PREFIXES. 'ranking de capitanes' added to _RANKING_KEYWORDS for substring matching. Before the fix: unsupported_intent. After: rank_candidates ok.

**Surface results:**

- `cli`: intent=`rank_candidates` outcome=`ok` supported=`True`
  captain_ranking: 3 entries, #1=Salah
- `http`: intent=`rank_candidates` outcome=`ok` supported=`True`
  captain_ranking: 3 entries, #1=Salah

### spanish_captain_score_named  (✓ PASS)

**Family:** captain  
**Description:** Spanish 'debería capitanear a Haaland' routes to captain_score via the new Spanish _CAPTAIN_SCORE_PREFIXES entries.  
**Question:** `debería capitanear a Haaland`  
**Expected:** intent=`captain_score` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6b Story 1.4 + Story 1.1: 'debería capitanear a' added to _CAPTAIN_SCORE_PREFIXES (1.4). _strip_spanish_name_prefix removes leading 'a ' → 'Haaland' (1.1). Haaland in STANDARD_BOOTSTRAP → ok with captain metadata. Before the fix: unsupported_intent. After: captain_score ok.

**Surface results:**

- `cli`: intent=`captain_score` outcome=`ok` supported=`True`
  captain.tier=`upside` captain.role_bonus=`5.0`
- `http`: intent=`captain_score` outcome=`ok` supported=`True`
  captain.tier=`upside` captain.role_bonus=`5.0`

### degraded_flag_on_provider_failure  (✓ PASS)

**Family:** failure_modes  
**Description:** When the LLM provider call fails, FinalResponse.degraded=True so callers can surface a 'provider unavailable' notice. The deterministic final_text is still returned (outcome=ok).  
**Question:** `should I captain Salah`  
**Expected:** intent=`captain_score` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6b Story 1.3: degraded flag. This scenario tests the contract shape only (deterministic path). In CI without an LLM client, provider_failed=False → degraded=False. The live degraded=True path is validated in run_phase26b_tests.py using a stub provider that returns an error_code. Corpus test confirms: degraded field present (bool) on all surfaces.

**Surface results:**

- `cli`: intent=`captain_score` outcome=`ok` supported=`True`
  captain.tier=`safe` captain.role_bonus=`5.0`
- `http`: intent=`captain_score` outcome=`ok` supported=`True`
  captain.tier=`safe` captain.role_bonus=`5.0`

### player_form_last_3_salah  (✓ PASS)

**Family:** player_form  
**Description:** Spanish 'cómo ha estado Salah en los últimos 3 partidos' routes to player_form and returns 3 GW history entries via bootstrap injection.  
**Question:** `como ha estado Salah en los ultimos 3 partidos`  
**Expected:** intent=`player_form` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6d Story 2.1: player form routing + API injection. PLAYER_FORM_BOOTSTRAP injects 3 history entries for Salah (id=2). player_form.web_name='Salah', n_games=3, len(history)==3. Before fix: unsupported_intent. After: player_form ok.

**Surface results:**

- `cli`: intent=`player_form` outcome=`ok` supported=`True`
- `http`: intent=`player_form` outcome=`ok` supported=`True`

### player_form_historial_salah  (✓ PASS)

**Family:** player_form  
**Description:** Spanish 'historial de puntos de Salah' routes to player_form with default n_games=5, returns available history.  
**Question:** `historial de puntos de Salah`  
**Expected:** intent=`player_form` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6d Story 2.1: 'historial de puntos de' prefix routing. PLAYER_FORM_BOOTSTRAP has 3 history entries; n_games defaults to 5 but only 3 are available → n_games=3 in output.

**Surface results:**

- `cli`: intent=`player_form` outcome=`ok` supported=`True`
- `http`: intent=`player_form` outcome=`ok` supported=`True`

### player_summary_with_totals  (✓ PASS)

**Family:** summary  
**Description:** Player summary for Salah includes form and minutes from bootstrap (Story 2.2 enrichment). total_points absent in STANDARD_BOOTSTRAP.  
**Question:** `tell me about Salah`  
**Expected:** intent=`player_summary` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6d Story 2.2: form='9.5' and minutes=2250 are present in STANDARD_BOOTSTRAP elements for Salah. total_points=None (not in STANDARD_BOOTSTRAP). Renderer shows Form and Mins extras.

**Surface results:**

- `cli`: intent=`player_summary` outcome=`ok` supported=`True`
- `http`: intent=`player_summary` outcome=`ok` supported=`True`

### injury_check_named_player  (✓ PASS)

**Family:** summary  
**Description:** Spanish 'está lesionado Saka' routes to player_summary via new injury-check prefix coverage.  
**Question:** `esta lesionado Saka`  
**Expected:** intent=`player_summary` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6d Story 2.3a: 'esta lesionado' added to _SUMMARY_PREFIXES. Saka (status='d') is in STANDARD_BOOTSTRAP → ok with status_label=Doubtful. Before fix: unsupported_intent. After: player_summary ok.

**Surface results:**

- `cli`: intent=`player_summary` outcome=`ok` supported=`True`
- `http`: intent=`player_summary` outcome=`ok` supported=`True`

### injury_list_gw_wide  (✓ PASS)

**Family:** injury_list  
**Description:** Spanish 'hay dudas para esta jornada' routes to injury_list and returns doubtful/injured players from bootstrap.  
**Question:** `hay dudas para esta jornada`  
**Expected:** intent=`injury_list` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6d Story 2.3b: 'hay dudas para esta jornada' routes to get_injury_list. STANDARD_BOOTSTRAP: Saka (d) + De Bruyne (i) → total=2. injury_list.total=2, doubtful has Saka, injured has De Bruyne. Before fix: unsupported_intent. After: injury_list ok.

**Surface results:**

- `cli`: intent=`injury_list` outcome=`ok` supported=`True`
- `http`: intent=`injury_list` outcome=`ok` supported=`True`

### price_changes_risers  (✓ PASS)

**Family:** price_changes  
**Description:** Spanish 'quién está subiendo de precio esta semana' routes to price_changes and returns Salah as riser from PRICE_CHANGES_BOOTSTRAP.  
**Question:** `quien esta subiendo de precio esta semana`  
**Expected:** intent=`price_changes` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6d Story 2.4: price_changes routing + deterministic output. PRICE_CHANGES_BOOTSTRAP: Salah cost_change_event=+1 (riser), De Bruyne cost_change_event=-1 (faller). price_changes.risers non-empty, price_changes.fallers non-empty. Before fix: unsupported_intent. After: price_changes ok.

**Surface results:**

- `cli`: intent=`price_changes` outcome=`ok` supported=`True`
- `http`: intent=`price_changes` outcome=`ok` supported=`True`

### team_calendar_easiest_spanish  (✓ PASS)

**Family:** team_fixture_calendar  
**Description:** Spanish 'que equipos tienen el mejor calendario las proximas 5 jornadas' routes to team_fixture_calendar with mode='easiest', horizon=5.  
**Question:** `que equipos tienen el mejor calendario las proximas 5 jornadas`  
**Expected:** intent=`team_fixture_calendar` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6e: easiest team fixture calendar. STANDARD_BOOTSTRAP has 5 teams with team_fixtures. team_calendar.mode='easiest', horizon=5, teams non-empty. Liverpool (avg 2.8) expected to rank #1. Before fix: unsupported_intent. After: team_fixture_calendar ok.

**Surface results:**

- `cli`: intent=`team_fixture_calendar` outcome=`ok` supported=`True`
- `http`: intent=`team_fixture_calendar` outcome=`ok` supported=`True`

### team_calendar_hardest_english  (✓ PASS)

**Family:** team_fixture_calendar  
**Description:** English 'teams with worst upcoming fixtures' routes to team_fixture_calendar with mode='hardest', horizon=5 (default).  
**Question:** `teams with worst upcoming fixtures`  
**Expected:** intent=`team_fixture_calendar` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6e: hardest team fixture calendar. team_calendar.mode='hardest'. Man Utd (avg 4.2) expected to rank #1 in hardest. Before fix: unsupported_intent. After: team_fixture_calendar ok.

**Surface results:**

- `cli`: intent=`team_fixture_calendar` outcome=`ok` supported=`True`
- `http`: intent=`team_fixture_calendar` outcome=`ok` supported=`True`

### team_calendar_easiest_english_n  (✓ PASS)

**Family:** team_fixture_calendar  
**Description:** English 'best fixtures next 5 gameweeks' routes to team_fixture_calendar with mode='easiest', horizon=5.  
**Question:** `best fixtures next 5 gameweeks`  
**Expected:** intent=`team_fixture_calendar` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6e: English 'best fixtures next N gameweeks' routing. Horizon extracted as 5 from 'next 5 gameweeks'. team_calendar.mode='easiest'. Before fix: unsupported_intent. After: team_fixture_calendar ok.

**Surface results:**

- `cli`: intent=`team_fixture_calendar` outcome=`ok` supported=`True`
- `http`: intent=`team_fixture_calendar` outcome=`ok` supported=`True`

### team_calendar_dgw_labeled  (✓ PASS)

**Family:** team_fixture_calendar  
**Description:** DGW_BOOTSTRAP (horizon=1): all 6 teams have 2 GW28 fixtures. Every team entry must carry has_dgw=True, dgw_gameweeks=[28].  
**Question:** `mejor calendario`  
**Expected:** intent=`team_fixture_calendar` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6e.2: DGW labeling. DGW_BOOTSTRAP: all teams have 2 GW28 fixtures. All teams in result must have has_dgw=True and dgw_gameweeks=[28]. Exact label values verified in run_phase26e2_tests.py.

**Surface results:**

- `cli`: intent=`team_fixture_calendar` outcome=`ok` supported=`True`
- `http`: intent=`team_fixture_calendar` outcome=`ok` supported=`True`

### team_calendar_bgw_labeled  (✓ PASS)

**Family:** team_fixture_calendar  
**Description:** BGW_BOOTSTRAP (horizon=2): ARS and MCI have no GW28 fixture. ARS and MCI entries must carry has_bgw=True, bgw_gameweeks=[28].  
**Question:** `mejor calendario`  
**Expected:** intent=`team_fixture_calendar` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6e.2: BGW labeling. BGW_BOOTSTRAP: ARS and MCI blank GW28 while LIV/CHE/MUN play. ARS/MCI must have has_bgw=True and bgw_gameweeks containing 28. LIV/CHE/MUN must have has_bgw=False (they play GW28). Exact label values verified in run_phase26e2_tests.py.

**Surface results:**

- `cli`: intent=`team_fixture_calendar` outcome=`ok` supported=`True`
- `http`: intent=`team_fixture_calendar` outcome=`ok` supported=`True`

### chip_wildcard_timing_antes_despues  (✓ PASS)

**Family:** chip  
**Description:** Spanish wildcard timing question using 'antes o después' phrase routes to chip_advice via new advisory phrase coverage.  
**Question:** `debería usar el wildcard antes o después de la doble jornada`  
**Expected:** intent=`chip_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6c Story 1b.1: wildcard timing phrasing. 'deberia usar' + 'antes o despues' added to _CHIP_ADVISORY_PHRASES. chip='wildcard'; recommendation varies by GW. Before the fix: unsupported_intent. After: chip_advice ok.

**Surface results:**

- `cli`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`wildcard` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`current gameweek`
- `http`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`wildcard` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`current gameweek`

### chip_bench_boost_conditional_tiene_sentido  (✓ PASS)

**Family:** chip  
**Description:** Spanish bench boost conditional question using 'tiene sentido' and 'activar' phrases routes to chip_advice.  
**Question:** `tiene sentido activar el bench boost con 10 jugadores disponibles`  
**Expected:** intent=`chip_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6c Story 1b.2: bench boost conditional phrasing. 'tiene sentido' and 'activar' added to _CHIP_ADVISORY_PHRASES. chip='bench_boost'; deterministic recommendation from bootstrap. Before the fix: unsupported_intent. After: chip_advice ok.

**Surface results:**

- `cli`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`bench_boost` chip.recommendation=`conditions_unfavorable` chip.gw=`28` chip.signal_label=`average FDR (top 10)`
- `http`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`bench_boost` chip.recommendation=`conditions_unfavorable` chip.gw=`28` chip.signal_label=`average FDR (top 10)`

### chip_wildcard_spent_sequencing  (✓ PASS)

**Family:** chip  
**Description:** Spanish spent-chip sequencing question using 'ya usé' phrase routes to chip_advice via new advisory phrase coverage.  
**Question:** `ya use el wildcard, que chip me queda mas rentable para el final`  
**Expected:** intent=`chip_advice` outcome=`ok` supported=`True`  
**Notes:** Phase 2.6c Story 1b.3: spent-chip sequencing phrasing. 'ya use' (and accented 'ya usé') added to _CHIP_ADVISORY_PHRASES. chip='wildcard' (keyword extracted from question). Advisor returns recommendation for wildcard this GW. Before the fix: unsupported_intent. After: chip_advice ok.

**Surface results:**

- `cli`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`wildcard` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`current gameweek`
- `http`: intent=`chip_advice` outcome=`ok` supported=`True`
  chip.chip=`wildcard` chip.recommendation=`conditions_marginal` chip.gw=`28` chip.signal_label=`current gameweek`

---

_Generated by `run_validation.py` — FPL Grounded Assistant Phase V1/V2 validation corpus._

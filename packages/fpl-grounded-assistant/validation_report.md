# FPL Grounded Assistant — Validation Report

Generated: 2026-03-21 04:35 UTC

## Summary

- **13 scenarios** tested
- **13 PASS**, **0 FAIL**

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

---

_Generated by `run_validation.py` — FPL Grounded Assistant Phase V1 validation corpus._

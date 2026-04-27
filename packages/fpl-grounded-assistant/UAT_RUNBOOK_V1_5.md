# FPL Grounded Assistant — V1.5 UAT Runbook

All commands run from `packages/fpl-grounded-assistant/` unless stated otherwise.

---

## 1. Preflight

### REPL startup

```
python fpl_repl.py
```

In the shell:

```
/gw
/debug
/debug
```

**Pass criteria:**
- REPL starts and prints `Ready. GWxx | NNN players loaded.`
- `/gw` prints `[GWxx | NNN players loaded]`
- First `/debug` prints `[Debug metadata: ON]`; second prints `[Debug metadata: OFF]`

### HTTP startup (separate terminal)

```
python fpl_server.py
```

Then:

```
curl http://localhost:8000/health
```

**Pass criteria:**
- Server binds and prints startup log without error
- Health endpoint returns `{"status": "ok"}` (or equivalent healthy response)

---

## 2. Core V1.5 Capability Pass in REPL

Run these in one uninterrupted REPL session. `/debug` should be OFF unless stated.

```
should I captain Salah
```
Validates: captain scoring, grounded recommendation, `captain` metadata present

```
top captains this week
```
Validates: `rank_candidates` intent, ordered results, `captain_ranking` metadata present

```
who is Palmer
```
Validates: `player_resolve` intent, no invented facts

```
tell me about Haaland
```
Validates: `player_summary` intent, grounded summary

```
compare Haaland and Salah
```
Validates: `compare_players` intent, bounded winner and reasons, `comparison` metadata present

```
should I sell Saka for Salah?
```
Validates: `transfer_advice` intent, grounded recommendation, `transfer` metadata present

```
should I use triple captain this week?
```
Validates: `chip_advice` intent, bounded recommendation, `chip` metadata present

```
Salah fixtures
```
Validates: `player_fixture_run` intent, near-term fixtures only, `fixture_run` metadata present

```
good differentials this week
```
Validates: `differential_picks` intent, low-ownership picks, `differential` metadata present

```
what is the current gameweek and who is Palmer
```
Validates: `multi_intent` routing, both sub-answers present, `sub_responses` metadata present

**Pass criteria for all prompts:**
- Answers are grounded and concise
- No fabricated player facts
- No crashes or Python tracebacks
- Resolved intent clearly matches each prompt

---

## 3. Follow-Up Behavior and Session Memory

Continue in the same REPL session (do not `/reset` between sequences).

**Comparison follow-up**

```
compare Haaland and Salah
and Saka?
```
Expected: second turn rewrites to comparison using the prior anchor (Haaland or Salah). `comparison` present on both turns.

**Pronoun follow-up**

```
who is Salah
should I captain him?
```
Expected: second turn resolves `him` to Salah from session context. `captain` present on second turn.

**Transfer follow-up**

```
should I sell Saka for Salah?
what about Haaland instead?
```
Expected: second turn rewrites to transfer keeping Saka as the sell player; Haaland becomes the new buy target. `transfer` present on both turns.

**Fixture run follow-up** (enable `/debug` before this sequence)

```
/debug
Haaland fixtures
what about Salah?
/debug
```
Expected: second turn resolves Salah's fixture run deterministically. Debug output shows `resolver_source == fixture_run_followup` and `fixture_run.web_name == Salah`.

**Differential follow-up** (enable `/debug` before this sequence)

```
/debug
good differentials this week
what about Mbeumo?
/debug
```
Expected: second turn routes to captain score for Mbeumo (not another differential). Debug output shows `resolver_source == differential_followup` and `captain` present.

**Context clear check**

```
/reset
should I captain him?
```
Expected: pronoun no longer resolves to Salah; prior context has been cleared.

**Pass criteria:**
- Each follow-up rewrites to the correct intent without hallucinating context
- `resolver_source` values match expected values in debug output
- `/reset` fully clears prior session anchors

---

## 4. Failure-Mode Coverage

```
is Haaland injured?
```
Expected: explicit unsupported response. No unrelated metadata (no `captain`, `transfer`, etc.).

```
should I captain Smith
```
Expected: explicit ambiguous or not-found handling. No invented player facts or invented score values.

```
compare someone and Salah
```
Expected: safe not-found or ambiguity path. No invented winner.

**Pass criteria:**
- Injury prompt is explicitly acknowledged as unsupported
- Ambiguous/not-found prompts do not invent player data
- Assistant stays safe and bounded in all three cases

---

## 5. CLI Debug Spot Checks for Structured Metadata

All commands use `python fpl_cli.py "..." --debug`.

**Comparison — position-aware scoring and venue-aware metadata**

```
python fpl_cli.py "compare Salah and Saka" --debug
```

Check for in output:
- `comparison.winner` and `comparison.reasons`
- `comparison.player_a.position_score` and `comparison.player_b.position_score`
- `comparison.player_a.is_home` and `comparison.player_b.is_home`
- `comparison.player_a.effective_fdr` and `comparison.player_b.effective_fdr`

**Transfer — score_delta and constraint flags**

```
python fpl_cli.py "should I sell Saka for Salah" --debug
```

Check for in output:
- `transfer.player_out`
- `transfer.player_in`
- `transfer.recommendation`
- `transfer.score_delta`
- `transfer.budget_constraint == false`
- `transfer.hit_warning == false`

**Chip — signal_label**

```
python fpl_cli.py "should I use triple captain this week" --debug
```

Check for in output:
- `chip.chip`
- `chip.recommendation`
- `chip.signal_label`
- `chip.chip_unavailable == false`

**Fixture run**

```
python fpl_cli.py "Salah fixtures" --debug
```

Check for in output:
- `fixture_run.web_name == Salah`
- Non-empty fixture list
- Each fixture entry has: `gameweek`, `opponent_short`, `is_home`, `difficulty`

**Differential picks**

```
python fpl_cli.py "good differentials this week" --debug
```

Check for in output:
- Non-empty `differential.picks`
- Each pick has: `rank`, `web_name`, `team_short`, `position`, `captain_score`, `ownership`, `now_cost`
- No player with a blank-GW fixture appears at the top (when fixture data available)
- Strong outfield presence near the top (post-GKP calibration); no marginal GKP overpromotion

Note: `position_score` and `is_home` are not serialised in differential CLI output — ranking happens internally.

---

## 6. Phase 8e Squad Context Checks

**Budget constraint**

```
python fpl_cli.py "should I sell Saka for Salah" --debug --itb 2.0
```
Check: `transfer.budget_constraint == true`; final text mentions budget limitation

```
python fpl_cli.py "should I sell Saka for Salah" --debug
```
Check: `transfer.budget_constraint == false`; advice proceeds normally

**Chip unavailable**

```
python fpl_cli.py "should I use triple captain" --debug --chips-remaining wildcard,bench_boost,free_hit
```
Check: `chip.chip_unavailable == true`; final text says chip is unavailable

```
python fpl_cli.py "should I use triple captain" --debug
```
Check: `chip.chip_unavailable == false`; chip advice proceeds normally

**Hit warning**

```
python fpl_cli.py "should I sell Saka for Salah" --debug --free-transfers 1
```
Check: `transfer.hit_warning == true` **only if** recommendation is `marginal_transfer_in`; final text unchanged (advisory, not a hard block)

Note: if recommendation is `transfer_in` (clear upgrade), `hit_warning` stays `false` even with `--free-transfers 1`.

**Combined constraint check**

```
python fpl_cli.py "should I sell Saka for Salah" --debug --itb 2.0 --free-transfers 1
```
Check: `budget_constraint` and `hit_warning` are independent; each reflects only its own condition

---

## 7. HTTP Parity and Session Lifecycle

Server must be running (`python fpl_server.py`) before these checks.

**Stateless ask**

```
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "should I captain Salah"}'
```
Check: HTTP 200, `supported == true`, `final_text` non-empty, `captain` present in response body

**Squad context via HTTP**

```
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "should I sell Saka for Salah", "squad_context": {"itb": 20}}'
```
Check: `transfer.budget_constraint == true`

```
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "should I use triple captain", "squad_context": {"chips_remaining": ["wildcard","bench_boost","free_hit"]}}'
```
Check: `chip.chip_unavailable == true`

```
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "should I sell Saka for Salah", "squad_context": {"free_transfers": 1}}'
```
Check: if recommendation is `marginal_transfer_in`, `transfer.hit_warning == true`

**Full session flow**

```
# 1. Create session
curl -X POST http://localhost:8000/session
# → note the session_id from the response

# 2. First ask
curl -X POST http://localhost:8000/session/{SESSION_ID}/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "compare Haaland and Salah"}'

# 3. Follow-up
curl -X POST http://localhost:8000/session/{SESSION_ID}/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "and Saka?"}'

# 4. Inspect
curl http://localhost:8000/session/{SESSION_ID}

# 5. Delete
curl -X DELETE http://localhost:8000/session/{SESSION_ID}
```
Check: session lifecycle works end to end; inspect returns bounded state only; delete returns `{"status": "cleared", ...}`

**Session statelessness for squad_context**

```
# Turn 1 — with squad_context
curl -X POST http://localhost:8000/session/{SESSION_ID}/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "should I sell Saka for Salah", "squad_context": {"itb": 20}}'

# Turn 2 — no squad_context
curl -X POST http://localhost:8000/session/{SESSION_ID}/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "should I sell Saka for Salah"}'
```
Check: Turn 1 shows `budget_constraint == true`; Turn 2 shows `budget_constraint == false`. Constraint does **not** persist into conversation state.

This explicitly validates the V1.5 requirement: per-turn constraints do not leak across turns.

---

## 8. What "Everything Up to V1.5" Means in This Pass

The following shipped behaviors must be confirmed explicitly:

| Behavior | Where to verify |
|---|---|
| Position-aware scoring in comparison | Section 5 comparison spot check: `position_score` in both player contexts |
| Position-aware scoring in transfer delta | Section 5 transfer spot check: `score_delta` uses adjusted score |
| Position-aware scoring in differential ranking | Section 5 differential spot check: outfield dominates, no marginal GKP promotion |
| Venue-aware fixture factor in comparison | Section 5 comparison spot check: `is_home`, `effective_fdr` present |
| DGW/BGW/normal signal_label for free hit | Section 5 chip spot check: `chip.signal_label` is one of the three valid values |
| Deterministic follow-ups (comparison, transfer, fixture run, differential) | Section 3 follow-up sequences |
| squad_context: budget_constraint | Section 6 budget constraint block |
| squad_context: chip_unavailable | Section 6 chip unavailable block |
| squad_context: hit_warning | Section 6 hit warning block |
| Session statelessness for squad_context | Section 7 statelessness check |
| Blank-GW exclusion in differentials | Section 5 differential spot check: blank-GW players absent from top results |
| Reduced marginal GKP promotion | Section 5 differential spot check: strong outfield presence near top |

---

## 9. Evidence Closeout

As you test:
- Fill the dated capture sheet for each section above
- Record any non-pass findings in the dated findings file

When done:
1. Complete the Exit Decision in the capture file
2. Write the final Go or No-Go recommendation in the findings file
3. Remove the `IN PROGRESS` marker from both files
4. Add one Pass Index row and one compact summary section to `UAT_FINDINGS.md` above the `END OF REAL PASS SUMMARIES` marker
5. Keep date, label, recommendation, and filenames exactly synchronised between the row and the summary block

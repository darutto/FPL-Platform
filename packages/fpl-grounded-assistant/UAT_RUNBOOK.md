# FPL Grounded Assistant - UAT Runbook

## Purpose

This runbook defines the primary manual acceptance workflow for the V1.5 surface.

The goal is confidence, not new capability.
Run this before starting any further post-V1.5 feature expansion.

V1.5 adds (relative to V1):
- Position-aware scoring (`position_score`) in comparisons, transfers, and differential picks (8a/8a1)
- Venue-aware fixture factor (`is_home`, `effective_fdr`) in comparisons (8b)
- DGW/BGW/normal free hit detection with `signal_label` (8c)
- Deterministic session follow-ups for fixture runs and differential picks (8d)
- `squad_context` per-turn constraints: `budget_constraint`, `chip_unavailable`, `hit_warning` (8e)

Primary decisions for this phase:
- Live data first
- CLI first
- HTTP/session second
- Deterministic fixture/example flows are fallback debugging tools, not primary evidence

Important scope notes:
- `player_fixture_run` is currently a player-focused capability. Team prompts such as `Liverpool fixtures` are out of scope unless a team fixture intent is added later.
- Unsupported prompts such as injury questions are expected to return an explicit unsupported response. That counts as a pass for unsupported-handling coverage, not as a product bug.

---

## UAT Gate

The UAT phase is complete only when all of the following are true:
- Core CLI scenarios have been executed manually
- Follow-up/session flows have been executed manually
- Structured metadata has been spot-checked across major supported intents
- No blocker issues remain open
- Any major issues are either fixed or explicitly accepted
- A short UAT findings report has been written
- `UAT_FINDINGS.md` Pass Index row added and compact summary section inserted above the `<!-- END OF REAL PASS SUMMARIES -->` marker; four sync values (date, label, recommendation, filenames) confirmed consistent — see sync-rules table in `UAT_FINDINGS.md`

**Evidence pack:**
- `UAT_CAPTURE_SHEET.md` — command-and-capture form with blank slots; use this to record your evidence as you run through each checklist section
- `UAT_FINDINGS_EXAMPLE.md` — a completed example findings record with `[SAMPLE]` values; shows what a clean V1.5 pass looks like
- `UAT_CHECKLIST.md` — canonical checklist IDs and pass/fail criteria
- `UAT_FINDINGS_TEMPLATE.md` — blank findings template; copy to a dated `UAT_FINDINGS_YYYYMMDD.md` before your pass
- `UAT_ARCHIVE_CONVENTION.md` — naming convention and contents checklist for completed pass files; defines what constitutes a complete evidence bundle

---

## Scope

Manual testing in this phase covers:
- `captain_score`
- `rank_candidates`
- `player_summary`
- `player_resolve`
- `compare_players`
- comparison follow-up
- `transfer_advice` — including `budget_constraint` and `hit_warning` via `squad_context`
- transfer follow-up
- `chip_advice` — including `chip_unavailable` via `squad_context`, and DGW/BGW/normal `signal_label`
- `player_fixture_run`
- `differential_picks`
- `multi_intent`
- `unsupported_intent`
- `ambiguous`
- `not_found`
- session follow-ups: comparison, transfer, fixture run, differential picks
- `squad_context` per-turn constraints: `itb`, `chips_remaining`, `free_transfers`
- session statelessness: constraints must not persist between turns

Reference contracts:
- `FINAL_RESPONSE_CONTRACT.md`
- `SESSION_CONTRACT.md`
- `validation_report.md`

---

## Before You Begin — Create Your Dated Files

Before starting any commands, create the two dated files for this pass.
Replace `YYYYMMDD` with today's date (e.g. `20260405`):

```
Copy UAT_CAPTURE_SHEET.md    → UAT_CAPTURE_YYYYMMDD.md
Copy UAT_FINDINGS_TEMPLATE.md → UAT_FINDINGS_YYYYMMDD.md
```

Add `_label` to both names only if you need to distinguish this pass (e.g. `_regression`).
If no label, omit the suffix in both filenames — and later in the Pass Index row and summary heading too.

Add this line at the very top of each new file while the pass is in progress:
```
<!-- IN PROGRESS — not a completed evidence record -->
```
Remove it only when you reach step 10 (historical-log closeout) at the end of the pass.

Full naming rules and the in-progress convention: `UAT_ARCHIVE_CONVENTION.md` → "How to start a pass".

---

## Preflight

From `packages/fpl-grounded-assistant`:

```powershell
python fpl_repl.py
```

Expected startup signals:
- `FPL Grounded Assistant - UAT Shell`
- `Loading live FPL data...`
- `Ready. GW... | ... players loaded.`

If the REPL does not start:
- verify network access
- verify the package directory is the current working directory
- retry with the Python environment selected for the workspace

If live data is temporarily unavailable, do not treat fallback runs as final UAT evidence.
Use fallback paths only to debug the failure and resume live-data UAT later.

---

## Primary Workflow: CLI REPL

Launch the interactive shell:

```powershell
python fpl_repl.py
```

Launch with structured metadata visible:

```powershell
python fpl_repl.py --debug
```

Useful shell commands:
- `/help` shows supported intents and example prompts
- `/debug` toggles structured metadata display
- `/reset` clears conversation context and starts a fresh session
- `/gw` shows the loaded gameweek and player count
- `/quit` exits the shell

Recommended execution pattern:
1. Start in plain mode and validate response quality, clarity, and grounding.
2. Toggle `/debug` on for spot checks of structured fields.
3. Use `/reset` between unrelated scenario groups.
4. Record findings immediately in your dated `UAT_FINDINGS_YYYYMMDD.md`.

Suggested prompt sequence:
- `should I captain Salah`
- `top captains this week`
- `who is Palmer`
- `tell me about Haaland`
- `compare Haaland and Salah`
- `and Saka?`
- `should I sell Saka for Salah?`
- `what about Haaland instead?`
- `should I use triple captain this week?`
- `Salah fixtures`
- `good differentials this week`
- `what is the current gameweek and who is Palmer`
- `is Haaland injured?`
- `should I captain Smith`

What to check during CLI UAT:
- intent matches the prompt
- answer stays grounded and concise
- unsupported prompts remain explicit and safe
- ambiguous and not-found cases do not fabricate facts
- follow-up turns use the correct prior context
- debug metadata appears only when relevant to the resolved intent
- no crashes or unusable shell behavior occur

Interpretation rule:
- mark unsupported prompts as `Pass` when the assistant clearly says the intent is not supported and does not invent facts
- mark player fixture prompts as `Fail` only when the supported `player_fixture_run` path itself breaks or returns an unusable live-data error
- do not mark team fixture prompts as bugs unless team-level fixture support is intentionally added to scope

---

## Secondary Workflow: Single-Turn CLI

Use these commands when you want copy-pasteable evidence for a single prompt:

```powershell
python fpl_cli.py "should I captain Salah"
python fpl_cli.py "compare Haaland and Salah" --debug
python fpl_cli.py "should I use triple captain this week" --debug
python fpl_cli.py "Salah fixtures" --debug
```

**Squad context flags** (Phase 8e) — supply one or more per command:

```powershell
# Budget constraint: £2.0m in the bank; transfer costs more → budget_constraint=True
python fpl_cli.py "should I sell Saka for Salah" --itb 2.0 --debug

# Chip unavailable: triple captain not in chips_remaining list → chip_unavailable=True
python fpl_cli.py "should I use triple captain" --chips-remaining "wildcard,bench_boost,free_hit" --debug

# Hit warning: 1 free transfer + marginal recommendation → hit_warning=True
python fpl_cli.py "should I sell Saka for Salah" --free-transfers 1 --debug
```

Expected fields in debug JSON when flags fire:
- `transfer.budget_constraint: true` (itb path)
- `chip.chip_unavailable: true` (chips_remaining path)
- `transfer.hit_warning: true` (free_transfers path, only when recommendation is `marginal_transfer_in`)

Use this surface for:
- quick reproduction of a bug found in REPL
- capturing structured JSON for a single turn
- checking that CLI non-interactive behavior matches REPL semantics

---

## Secondary Workflow: HTTP And Session

Start the server from `packages/fpl-grounded-assistant`:

```powershell
python fpl_server.py
```

In a second PowerShell session:

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/health
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask -ContentType 'application/json' -Body '{"question":"should I captain Salah"}'
```

Session flow:

```powershell
$session = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/session
$id = $session.session_id
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/session/$id/ask" -ContentType 'application/json' -Body '{"question":"compare Haaland and Salah"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/session/$id/ask" -ContentType 'application/json' -Body '{"question":"and Saka?"}'
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/session/$id"
Invoke-RestMethod -Method Delete -Uri "http://127.0.0.1:8000/session/$id"
```

**Squad context on stateless `/ask`** (Phase 8e):

```powershell
# Budget constraint
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType 'application/json' `
  -Body '{"question":"should I sell Saka for Salah","squad_context":{"itb":20}}'

# Chip unavailable
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType 'application/json' `
  -Body '{"question":"should I use triple captain","squad_context":{"chips_remaining":["wildcard","bench_boost","free_hit"]}}'

# Hit warning (marginal transfer + 1 free transfer)
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType 'application/json' `
  -Body '{"question":"should I sell Saka for Salah","squad_context":{"free_transfers":1}}'
```

**Session squad_context and statelessness check** (Phase 8f2):

```powershell
$session = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/session
$id = $session.session_id

# Turn 1: constrained — budget_constraint should be true
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/session/$id/ask" `
  -ContentType 'application/json' `
  -Body '{"question":"should I sell Saka for Salah","squad_context":{"itb":20}}'

# Turn 2: no squad_context — budget_constraint must be false (not persisted)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/session/$id/ask" `
  -ContentType 'application/json' `
  -Body '{"question":"should I sell Saka for Salah"}'

Invoke-RestMethod -Method Delete -Uri "http://127.0.0.1:8000/session/$id"
```

On turn 2, `transfer.budget_constraint` must be `false`. If it is `true`, squad_context is incorrectly persisting.

What to check during HTTP/session UAT:
- stateless `/ask` matches CLI semantics for single-turn questions
- session follow-ups preserve conversational context
- session inspect returns bounded operational state only
- clear/delete removes the session cleanly
- structured JSON fields appear where expected and are absent where not expected
- `squad_context` is per-turn and not persisted (turn 2 without squad_context reverts cleanly)

---

## Structured Metadata Spot Checks

Verify at least one successful live-data example for each:
- `captain`
- `captain_ranking`
- `comparison`
- `transfer`
- `chip`
- `fixture_run`
- `differential`
- `sub_responses` for at least one `multi_intent` turn

Also verify absence semantics:
- `captain` absent on non-captain turns
- `comparison` absent on non-comparison turns
- `transfer` absent on non-transfer turns
- `chip` absent on non-chip turns

---

## Phase 8b: Venue-Aware Fixture Factor Verification

These checks verify that home/away venue information is correctly reflected in metadata after the Phase 8b addition.

### What Phase 8b adds

- `is_home: bool | null` — `true` if the player's team is at home this GW, `false` if away, `null` if venue data is unavailable.
- `effective_fdr: float` — home/away adjusted FDR used by Layer 2 (`position_score`). Home teams: `raw_fdr − 0.5`; away: `raw_fdr + 0.5`; clamped to [1.0, 5.0]. Layer 1 (`captain_score`) is unchanged.
- Venue-tagged FDR reason phrases: `"easier fixture (FDR 4H vs 5A)"` — `H`/`A`/no suffix for home/away/unknown.

### CLI verification (with `/debug`)

```
python fpl_repl.py --debug
compare [home player] and [away player]
```

In the debug output look for:
```
[comparison]   winner=...
               [player A]: pos_score=...  capt_score=...  efdr=3.5(H)
               [player B]: pos_score=...  capt_score=...  efdr=4.5(A)
```

What to check:
- `efdr` values reflect home/away adjustment (home gets lower efdr)
- The venue tag `(H)` or `(A)` is present for each player
- `capt_score` is unchanged from a player with the same raw inputs (Layer 1 is frozen)
- If `is_home` is unknown, the display shows `?` instead of `H`/`A`

### Differential picks verification

Venue-awareness in differential picks affects ranking via `effective_fdr` used in `position_score` computation, but venue tags are **not** rendered per pick in REPL plain text output and `is_home` is **not** included in CLI debug JSON.

`is_home` IS included per pick in the HTTP JSON response body. To verify:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType 'application/json' `
  -Body '{"question":"good differentials this week"}'
```

Expected shape for each pick in `response.differential.picks[n]`:
```json
{
  "rank": 1,
  "web_name": "Palmer",
  "team_short": "CHE",
  "position": "MID",
  "captain_score": ...,
  "ownership": ...,
  "now_cost": ...,
  "is_home": true
}
```

Note: `position_score` is not a serialized field in differential picks on any current surface. The `score` shown in REPL plain text uses `position_score` internally (via renderer fallback) but it is not a named JSON key.

### HTTP verification

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType 'application/json' `
  -Body '{"question":"compare Salah and Haaland"}'
```

Expected fields in `response.comparison.player_a`:
```json
{
  "is_home": true,
  "effective_fdr": 3.5,
  "captain_score": ...,
  "position_score": ...
}
```

### Fallback check (no venue data)

When `team_fixtures` is absent from the bootstrap (or when the server is started without current-GW team fixture data), expected behavior:
- `is_home: null` for all players
- `effective_fdr` equals the raw FDR integer (no adjustment)
- `captain_score` and `position_score` differ only by position weights, not by venue

This is the safe fallback — no wrong venue assumption is made.

---

---

## Phase 8a1: Position-Aware Scoring Spot Checks

These checks verify that `position_score` is present and uses position-appropriate weights in comparison output. Note: `position_score` is not a serialized JSON field in current transfer or differential output — transfer exposes `score_delta` (computed from position-score delta), and differential picks are ranked by `position_score` internally but the field is not included in CLI debug JSON or HTTP response bodies for differential picks.

### What Phase 8a1 adds

- `position_score` — composite 0–100 score using position-specific component weights
- GKP weight profile emphasises saves and clean sheets; MID weights match the canonical formula exactly; FWD same as MID (transitional); DEF emphasises clean sheets
- `captain_score` (Layer 1) is **frozen** — position_score never modifies it
- All 7 normalised components are visible in debug: `form_score`, `fixture_score`, `xgi_score`, `minutes_score`, `saves_score`, `cs_score`, `dc_score`

### CLI verification (with `--debug`)

```powershell
python fpl_repl.py --debug
compare Raya and Salah
```

In the debug output look for:
```
[comparison]  winner=Salah  margin=...
              Raya (GKP): pos_score=...  capt_score=...
              Salah (MID): pos_score=...  capt_score=...
```

What to check:
- Both players have `position_score` and `captain_score` in their context
- Raya's `position_score` reflects saves/clean_sheet weight, not xgi (GKP has xgi weight = 0)
- Salah's `position_score` should closely match or equal `captain_score` (MID weights = canonical formula)
- `captain_score` values are identical to a run without `--debug` (Layer 1 is frozen)

### MID parity invariant

If you can compare two MID players (e.g. Salah vs Palmer), their `position_score` should equal their `captain_score` within floating-point precision. Any divergence is a bug.

### HTTP verification

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType 'application/json' `
  -Body '{"question":"compare Raya and Salah"}'
```

Expected fields in `response.comparison.player_a` (and `player_b`):
```json
{
  "captain_score": ...,
  "position_score": ...,
  "position": "GKP"
}
```

---

## Phase 8c: Free Hit DGW/BGW/Normal Signal Label Verification

These checks verify that the free hit chip detection correctly classifies the current gameweek and exposes the right `signal_label`.

### What Phase 8c adds

- `chip.signal_label` — one of `"double gameweek teams"`, `"blank gameweek teams"`, or `"normal gameweek"`
- `chip.signal_value` — count of affected teams (DGW: N teams playing twice; BGW: N teams blanked; normal: 0)
- `chip.recommendation` — `conditions_favorable` (DGW, ≥6 affected teams), `conditions_marginal` (BGW), or `conditions_unfavorable` (normal)

### CLI verification

```powershell
python fpl_cli.py "should I free hit this week" --debug
```

Expected JSON shape in debug output:
```json
{
  "chip": {
    "chip": "free_hit",
    "recommendation": "conditions_unfavorable",
    "signal_value": 0.0,
    "signal_label": "normal gameweek",
    "gw": 28
  }
}
```

In a real DGW the label should be `"double gameweek teams"` and `signal_value` reflects the count of affected teams.

What to check:
- `signal_label` is one of the three valid strings above
- `signal_value` is consistent with the label (0.0 for normal, positive int for DGW/BGW)
- `recommendation` matches the classification (favorable/marginal/unfavorable)
- The validation corpus confirms this deterministically for all three cases (run `python run_validation.py`)

### Deterministic fallback

If the current live GW is not a DGW or BGW, use the validation runner to confirm DGW/BGW classification still works:

```powershell
python run_validation.py --no-artifacts
```

Scenarios `chip_advice_fh_dgw`, `chip_advice_fh_bgw`, and `chip_advice_fh_normal` each assert their respective `signal_label`.

---

## Phase 8d: Session Follow-Up Behaviors

These checks verify the two deterministic session follow-up paths added in Phase 8d.

### Fixture run follow-up

```
python fpl_repl.py --debug
Haaland fixtures
what about Salah?
```

Expected on the second turn:
- intent = `player_fixture_run`
- `fixture_run.web_name` = `Salah` (resolved from the follow-up prompt)
- `debug.resolver.resolver_source` = `fixture_run_followup`

### Differential picks follow-up

```
python fpl_repl.py --debug
good differentials this week
what about Mbeumo?
```

Expected on the second turn:
- intent = `captain_score`
- `captain` metadata present for Mbeumo
- `debug.resolver.resolver_source` = `differential_followup`

### What to check

- The follow-up turn does not require the full question to be restated
- No LLM call is made (resolver_source is deterministic, not `llm_resolver`)
- The prior context is used for exactly one follow-up; a generic subsequent question routes fresh

---

## Phase 8e: Squad Context Constraints and Advisory Flags

These checks verify that per-turn `squad_context` constraints fire correctly and do not persist across turns.

### Budget constraint (transfer)

Condition: `itb` (in tenths of £) is less than `price_delta` (upgrade cost in tenths of £).

```powershell
# itb=2.0 → 20 tenths; price_delta for Saka→Salah is typically 35 (£3.5m)
python fpl_cli.py "should I sell Saka for Salah" --itb 2.0 --debug
```

Expected:
- `transfer.budget_constraint: true`
- `transfer.recommendation` is still populated (intent succeeds)
- `final_text` is replaced with a budget constraint message (hard block)

### Chip unavailable

Condition: requested chip is not in `chips_remaining`.

```powershell
python fpl_cli.py "should I use triple captain" --chips-remaining "wildcard,bench_boost,free_hit" --debug
```

Expected:
- `chip.chip_unavailable: true`
- `chip.recommendation` is still populated
- `final_text` is replaced with a chip unavailable message (hard block)

### Hit warning (advisory)

Condition: `free_transfers == 1` AND `recommendation == "marginal_transfer_in"`.

```powershell
python fpl_cli.py "should I sell Saka for Salah" --free-transfers 1 --debug
```

Expected (if recommendation is marginal):
- `transfer.hit_warning: true`
- `final_text` is **not** overridden — advisory only
- `transfer.recommendation` remains `marginal_transfer_in`

If recommendation is `transfer_in` (clear upgrade), `hit_warning` stays `false` even with `--free-transfers 1`.

### Composability

`budget_constraint` and `hit_warning` are independent flags. Both can be true simultaneously if the conditions for each are met.

### Statelessness (session_http)

See HTTP/Session section above. The key check: on turn 2 without `squad_context`, `transfer.budget_constraint` must be `false`. If it is `true`, squad_context is incorrectly persisting to `ConversationState`.

---

## Severity Rubric

- `blocker`: crash, unusable REPL/server path, invented facts, wrong intent on core prompts, broken session follow-up, broken structured payload contract
- `major`: materially misleading recommendation, repeated routing failure, missing key metadata on a supported OK path, severe style or clarity regression
- `minor`: wording issue, weak explanation ordering, low-friction usability problem, minor metadata inconsistency that does not break callers
- `polish`: small improvements that do not affect trust or task completion

---

## Fallback Debugging Paths

Use these only when live-data UAT is blocked:
- `python examples/cli_examples.py`
- `python examples/http_examples.py`
- `python examples/session_examples.py`
- `python run_validation.py --no-artifacts`

These paths are useful for debugging and regression confirmation, but they do not replace live manual acceptance.

---

## Outputs Of This Phase

A completed pass produces:
- `UAT_CAPTURE_YYYYMMDD[_label].md` — filled command-and-capture form with all capture blocks and section status boxes marked
- `UAT_FINDINGS_YYYYMMDD[_label].md` — completed findings record with go/no-go recommendation written

At closeout, also update `UAT_FINDINGS.md`:
- Add a Pass Index row
- Insert a compact summary section immediately above the `<!-- END OF REAL PASS SUMMARIES -->` marker
- Confirm four sync values match (date, label, recommendation, filenames) — see sync-rules table in `UAT_FINDINGS.md`

The go/no-go summary in the dated findings file should cover:
- what was tested
- what failed
- severity distribution
- whether more feature work should remain paused
# FPL Grounded Assistant - V1.5 UAT Capture Sheet

Use alongside `UAT_CHECKLIST.md` and `UAT_RUNBOOK.md`.
For each section: run the command, paste the key output lines into the capture block, mark status.
Carry findings into your dated `UAT_FINDINGS_YYYYMMDD.md` (already created before starting — see "Before You Begin" in `UAT_RUNBOOK.md`).

**Before starting:** copy this file and the findings template to dated names — e.g.
`UAT_CAPTURE_20260405.md` and `UAT_FINDINGS_20260405.md`.
See `UAT_ARCHIVE_CONVENTION.md` for the full naming convention and bundle checklist.

**Surface legend:**
- `REPL` — `python fpl_repl.py` interactive shell
- `REPL --debug` — `python fpl_repl.py --debug` interactive shell
- `CLI debug` — `python fpl_cli.py "..." --debug` single-turn JSON
- `HTTP` — `Invoke-RestMethod` against `fpl_server.py`

---

## Preflight

### PF-01 to PF-03 — REPL startup and shell commands

**Command:**
```powershell
python fpl_repl.py
```
Then type:
```
/gw
/debug
/debug
```

**Look for:**
- Shell starts without error, live data loads
- `/gw` prints current GW number and player count
- `/debug` toggles metadata on; second `/debug` toggles it off

**Captured — `/gw` output:**
```
[paste /gw output line here]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

### PF-04 to PF-05 — HTTP server startup

**Command:**
```powershell
python fpl_server.py
# (in a second terminal)
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/health
```

**Look for:** Server binds without error; health returns a non-error response.

**Captured — health response:**
```
[paste health response here]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

## Core CLI Capabilities (CLI-01 to CLI-10)

Run in the interactive REPL. Use REPL `--debug` for spot checks.

### CLI-01 / CLI-02 — Captain score and ranking

**Commands (REPL):**
```
should I captain Salah
top captains this week
```

**Look for:**
- `should I captain Salah` → recommendation with score and tier; `captain` metadata present in debug
- `top captains this week` → ordered list of ranked candidates; `captain_ranking` present in debug

**Captured — captain response (key line):**
```
[paste response line or debug json snippet]
```

**Captured — ranking response (top 3 lines):**
```
[paste ranking output lines]
```

**Status CLI-01:** ☐ Pass  ☐ Fail  ☐ N/A
**Status CLI-02:** ☐ Pass  ☐ Fail  ☐ N/A

---

### CLI-05 — Comparison

**Command (CLI debug):**
```powershell
python fpl_cli.py "compare Haaland and Salah" --debug
```

**Look for:**
- `comparison.winner` present
- `comparison.player_a.position_score` and `player_b.position_score` present
- `comparison.player_a.is_home`, `effective_fdr` present

**Captured — `comparison` JSON sub-object:**
```json
[paste comparison block here]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

### CLI-06 — Transfer advice

**Command (CLI debug):**
```powershell
python fpl_cli.py "should I sell Saka for Salah" --debug
```

**Look for:**
- `transfer.player_out`, `transfer.player_in`, `transfer.recommendation` present
- `transfer.score_delta` present (this is the position-score-based delta — see asymmetry note)
- `transfer.budget_constraint` and `transfer.hit_warning` present (should both be `false` with no squad_context flags)

> **Asymmetry note:** `position_score` is not a named field in `transfer` JSON. Position-aware scoring surfaces here as `score_delta`. Do not look for `transfer.position_score`.

**Captured — `transfer` JSON:**
```json
[paste transfer block here]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

### CLI-07 — Chip advice

**Command (CLI debug):**
```powershell
python fpl_cli.py "should I use triple captain this week" --debug
```

**Look for:**
- `chip.chip` = `"triple_captain"`
- `chip.recommendation` present
- `chip.signal_label` present
- `chip.chip_unavailable` = `false` (no `--chips-remaining` flag used)

**Captured — `chip` JSON:**
```json
[paste chip block here]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

### CLI-08 — Fixture run

**Command (CLI debug):**
```powershell
python fpl_cli.py "Salah fixtures" --debug
```

**Look for:**
- `fixture_run.web_name` = `"Salah"`
- `fixture_run.fixtures` is non-empty, each entry has `gameweek`, `opponent_short`, `is_home`, `difficulty`

**Captured — `fixture_run` JSON:**
```json
[paste fixture_run block here]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

### CLI-09 — Differential picks

**Command (CLI debug):**
```powershell
python fpl_cli.py "good differentials this week" --debug
```

**Look for:**
- `differential.picks` non-empty, each with `rank`, `web_name`, `team_short`, `position`, `captain_score`, `ownership`, `now_cost`
- `differential.picks[0].captain_score` > 0

> **Asymmetry note:** `position_score` and `is_home` are NOT in CLI debug JSON for differential picks. Position-aware ranking happens internally — the CLI debug JSON only exposes `captain_score` per pick. To check `is_home`, use the HTTP surface (P8B-05).

**Captured — `differential` picks (first 2 entries):**
```json
[paste picks[0] and picks[1] here]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

## Failure Modes (ERR-01 to ERR-04)

### ERR-01 and ERR-02 — Unsupported and not-found

**Commands (REPL):**
```
is Haaland injured?
should I captain Smith
```

**Look for:**
- `is Haaland injured?` → explicit unsupported response; no invented data; no metadata noise
- `should I captain Smith` → explicit ambiguous or not-found response; no invented captain score

**Captured — unsupported response line:**
```
[paste response line]
```

**Captured — not-found response line:**
```
[paste response line]
```

**Status ERR-01:** ☐ Pass  ☐ Fail  ☐ N/A
**Status ERR-02:** ☐ Pass  ☐ Fail  ☐ N/A

---

## Follow-Up and Session Behavior (SES-01 to SES-07)

Run SES-01 to SES-04 in a single uninterrupted REPL session.

### SES-01 to SES-03 — Core follow-ups

**Commands (REPL sequence):**
```
compare Haaland and Salah
and Saka?
/reset
who is Salah
should I captain him?
/reset
should I sell Saka for Salah?
what about Haaland instead?
```

**Look for:**
- `and Saka?` → comparison with Saka; `comparison` present; prior Haaland/Salah anchor used
- `should I captain him?` → `captain` present for Salah (pronoun resolved)
- `what about Haaland instead?` → transfer advice for Saka→Haaland; `transfer` present

**Captured — comparison follow-up winner:**
```
[paste winner line from second comparison]
```

**Status SES-01:** ☐ Pass  ☐ Fail  ☐ N/A
**Status SES-02:** ☐ Pass  ☐ Fail  ☐ N/A
**Status SES-03:** ☐ Pass  ☐ Fail  ☐ N/A

---

### SES-06 — Fixture run follow-up

**Commands (REPL --debug sequence):**
```
Haaland fixtures
what about Salah?
```

**Look for on turn 2:**
- `intent` = `player_fixture_run`
- `fixture_run.web_name` = `"Salah"`
- `debug.resolver.resolver_source` = `"fixture_run_followup"`

**Captured — turn 2 debug resolver block:**
```json
[paste resolver sub-object here]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

### SES-07 — Differential follow-up

**Commands (REPL --debug sequence):**
```
good differentials this week
what about Mbeumo?
```

**Look for on turn 2:**
- `intent` = `captain_score`
- `captain.web_name` = `"Mbeumo"` (or closest resolved match)
- `debug.resolver.resolver_source` = `"differential_followup"`

**Captured — turn 2 intent and resolver_source:**
```
intent: [paste]
resolver_source: [paste]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

## Phase 8a1: Position-Aware Scoring (P8A-01 to P8A-05)

### P8A-01 to P8A-03 — Comparison position_score

**Command (CLI debug):**
```powershell
python fpl_cli.py "compare Raya and Salah" --debug
```

**Look for:**
- `comparison.player_a.position_score` and `comparison.player_b.position_score` both present
- Raya (GKP) `position_score` > Raya `captain_score` (saves/CS uplift)
- Salah (MID) `position_score` ≈ Salah `captain_score` (MID zero-drift invariant)

**MID parity check (CLI debug):**
```powershell
python fpl_cli.py "compare Salah and Palmer" --debug
```

**Look for:** Both `position_score` and `captain_score` equal within floating-point precision for each player.

**Captured — Raya player context:**
```json
[paste comparison.player_a block here]
```

**Captured — Salah/Palmer position_score vs captain_score values:**
```
Salah: position_score=... captain_score=...  diff=...
Palmer: position_score=... captain_score=...  diff=...
```

**Status P8A-01:** ☐ Pass  ☐ Fail  ☐ N/A
**Status P8A-02:** ☐ Pass  ☐ Fail  ☐ N/A
**Status P8A-03:** ☐ Pass  ☐ Fail  ☐ N/A

---

### P8A-04 — HTTP comparison position_score

**Command:**
```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType 'application/json' `
  -Body '{"question":"compare Raya and Salah"}'
```

**Look for:** `comparison.player_a.position_score` and `comparison.player_b.position_score` present in JSON.

**Captured — `comparison.player_a` from HTTP response:**
```json
[paste player_a here]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

### P8A-05 — Differential ranking quality

**Command (REPL):**
```
good differentials this week
```

> **Asymmetry note:** `position_score` is not a serialized field in differential picks output on any surface. This check is a behavioral/ranking quality check only. Look for whether any GKPs or DEFs appear in the picks — if so, that is the position-scoring working (for better or worse). Note positions in results.

**Captured — differential top 3 picks (positions and scores):**
```
1. [name] ([pos]) score [n], [n]% owned
2. [name] ([pos]) score [n], [n]% owned
3. [name] ([pos]) score [n], [n]% owned
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

## Phase 8b: Venue-Aware FDR (P8B-01 to P8B-08)

### P8B-01 to P8B-04 — Comparison venue fields

**Command (CLI debug):**
```powershell
python fpl_cli.py "compare Salah and Saka" --debug
```

**Look for:**
- `comparison.player_a.is_home` — `true` or `false` (not null; null = no venue data)
- `comparison.player_a.effective_fdr` — numeric; lower for home teams (home: raw_fdr − 0.5)
- `comparison.reasons` contains a venue-tagged FDR phrase such as `"easier fixture (FDR 4H vs 5A)"`
- `comparison.player_a.captain_score` uses raw FDR (Layer 1 frozen — unchanged by venue)

**Captured — player_a.is_home, effective_fdr, captain_score:**
```
player_a (Salah): is_home=... effective_fdr=... captain_score=...
player_b (Saka):  is_home=... effective_fdr=... captain_score=...
```

**Captured — venue-tagged reason phrase (from comparison.reasons):**
```
[paste the FDR reason string here]
```

**Status P8B-01:** ☐ Pass  ☐ Fail  ☐ N/A
**Status P8B-02:** ☐ Pass  ☐ Fail  ☐ N/A
**Status P8B-03:** ☐ Pass  ☐ Fail  ☐ N/A
**Status P8B-04:** ☐ Pass  ☐ Fail  ☐ N/A

---

### P8B-05 — Differential picks is_home (HTTP only)

> **Asymmetry note:** `is_home` is in HTTP differential JSON but NOT in CLI debug JSON for differential picks.

**Command (HTTP):**
```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType 'application/json' `
  -Body '{"question":"good differentials this week"}'
```

**Look for:** Each entry in `differential.picks` has `is_home` = `true`, `false`, or `null`. Key is never missing.

**Captured — first pick is_home value:**
```
picks[0].web_name=... picks[0].is_home=...
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

### P8B-06 to P8B-07 — HTTP and REPL comparison venue fields

**Commands:**
```powershell
# HTTP
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType 'application/json' `
  -Body '{"question":"compare Salah and Saka"}'

# REPL --debug (inline metadata)
python fpl_repl.py --debug
compare Salah and Saka
```

**Look for:**
- HTTP: `comparison.player_a.is_home` and `effective_fdr` in JSON
- REPL debug: metadata line shows `efdr=N.N(H)` or `efdr=N.N(A)` for each player

**Captured — HTTP player_a.is_home and effective_fdr:**
```
[paste]
```

**Captured — REPL debug metadata line:**
```
[paste the [comparison] metadata line from REPL output]
```

**Status P8B-06:** ☐ Pass  ☐ Fail  ☐ N/A
**Status P8B-07:** ☐ Pass  ☐ Fail  ☐ N/A

---

### P8B-08 — Differential REPL plain text (no venue tags expected)

**Command (REPL):**
```
good differentials this week
```

**Look for:** Plain text pick lines show `score N.N, N.N% owned, £N.Nm`. No `H`/`A`/`?` venue tags in pick lines. Absence is expected and correct — venue-awareness is in ranking only.

**Captured — first pick line:**
```
[paste pick line here]
```

**Status:** ☐ Pass (no venue tags present, as expected)  ☐ Fail (venue tags unexpectedly present)  ☐ N/A

---

## Phase 8c: Free Hit Signal Label (P8C-01 to P8C-05)

### P8C-01 to P8C-03 — Signal label, value, and recommendation

**Command (CLI debug):**
```powershell
python fpl_cli.py "should I free hit this week" --debug
```

**Look for:**
- `chip.chip` = `"free_hit"`
- `chip.signal_label` = one of: `"double gameweek teams"`, `"blank gameweek teams"`, `"normal gameweek"`
- `chip.signal_value` = 0.0 for normal; positive N for DGW/BGW
- `chip.recommendation` = `"conditions_unfavorable"` (normal), `"conditions_favorable"` (DGW ≥6 teams), `"conditions_marginal"` (BGW)

**Captured — `chip` JSON:**
```json
[paste chip block here]
```

**Status P8C-01:** ☐ Pass  ☐ Fail  ☐ N/A
**Status P8C-02:** ☐ Pass  ☐ Fail  ☐ N/A
**Status P8C-03:** ☐ Pass  ☐ Fail  ☐ N/A

---

### P8C-04 — HTTP signal_label

**Command:**
```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType 'application/json' `
  -Body '{"question":"should I free hit this week"}'
```

**Look for:** `chip.signal_label` present and matches one of the three valid strings.

**Captured — chip.signal_label from HTTP:**
```
[paste]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

### P8C-05 — Validation runner (DGW/BGW/normal corpus coverage)

**Command:**
```powershell
python run_validation.py --no-artifacts
```

**Look for:** Scenarios `chip_advice_fh_dgw`, `chip_advice_fh_bgw`, `chip_advice_fh_normal` all show PASS.

**Captured — validation summary line:**
```
[paste the PASS/FAIL summary line]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

## Phase 8e: Squad Context Constraints (P8E-01 to P8E-12)

### P8E-01 and P8E-02 — Budget constraint on/off

**Commands (CLI debug):**
```powershell
# Should trigger budget_constraint (£2.0m < upgrade cost)
python fpl_cli.py "should I sell Saka for Salah" --itb 2.0 --debug

# Should not trigger budget_constraint (no constraint)
python fpl_cli.py "should I sell Saka for Salah" --debug
```

**Look for:**
- With `--itb 2.0`: `transfer.budget_constraint` = `true`; `final_text` contains a budget constraint message
- Without flag: `transfer.budget_constraint` = `false`; advice proceeds normally

**Captured — itb path transfer.budget_constraint:**
```
[paste]
```

**Captured — no-flag path transfer.budget_constraint:**
```
[paste]
```

**Status P8E-01:** ☐ Pass  ☐ Fail  ☐ N/A
**Status P8E-02:** ☐ Pass  ☐ Fail  ☐ N/A

---

### P8E-03 — Budget constraint via HTTP

**Command:**
```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType 'application/json' `
  -Body '{"question":"should I sell Saka for Salah","squad_context":{"itb":20}}'
```

**Look for:** `transfer.budget_constraint` = `true`.

**Captured:**
```
transfer.budget_constraint: [paste]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

### P8E-04 and P8E-05 — Chip unavailable on/off

**Commands (CLI debug):**
```powershell
# Should trigger chip_unavailable (triple captain not in list)
python fpl_cli.py "should I use triple captain" --chips-remaining "wildcard,bench_boost,free_hit" --debug

# Should not trigger (no constraint)
python fpl_cli.py "should I use triple captain" --debug
```

**Look for:**
- With `--chips-remaining`: `chip.chip_unavailable` = `true`; `final_text` contains unavailable message
- Without flag: `chip.chip_unavailable` = `false`

**Captured — with flag chip.chip_unavailable:**
```
[paste]
```

**Status P8E-04:** ☐ Pass  ☐ Fail  ☐ N/A
**Status P8E-05:** ☐ Pass  ☐ Fail  ☐ N/A

---

### P8E-07 and P8E-08 — Hit warning

**Command (CLI debug):**
```powershell
python fpl_cli.py "should I sell Saka for Salah" --free-transfers 1 --debug
```

**Look for:**
- `transfer.hit_warning` = `true` **only if** `transfer.recommendation` = `"marginal_transfer_in"`
- `transfer.hit_warning` = `false` if recommendation is `"transfer_in"` (strong recommendation overrides warning)
- `final_text` is unchanged (hit_warning is advisory, not a hard block)

**Captured — transfer.recommendation and transfer.hit_warning:**
```
recommendation: [paste]
hit_warning: [paste]
```

**Status P8E-07:** ☐ Pass  ☐ Fail  ☐ N/A
**Status P8E-08:** ☐ Pass  ☐ Fail  ☐ N/A

---

### P8E-09 — Hit warning via HTTP

**Command:**
```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType 'application/json' `
  -Body '{"question":"should I sell Saka for Salah","squad_context":{"free_transfers":1}}'
```

**Look for:** If `transfer.recommendation` = `"marginal_transfer_in"`, then `transfer.hit_warning` = `true`.

**Captured:**
```
recommendation: [paste]
hit_warning: [paste]
```

**Status:** ☐ Pass  ☐ Fail  ☐ N/A

---

### P8E-11 and P8E-12 — Session statelessness

**Command (HTTP session):**
```powershell
$session = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/session
$id = $session.session_id

# Turn 1: with budget constraint
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/session/$id/ask" `
  -ContentType 'application/json' `
  -Body '{"question":"should I sell Saka for Salah","squad_context":{"itb":20}}'

# Turn 2: no squad_context — constraint must NOT persist
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/session/$id/ask" `
  -ContentType 'application/json' `
  -Body '{"question":"should I sell Saka for Salah"}'

Invoke-RestMethod -Method Delete -Uri "http://127.0.0.1:8000/session/$id"
```

**Look for:**
- Turn 1: `transfer.budget_constraint` = `true`
- Turn 2: `transfer.budget_constraint` = `false` (constraint is per-turn only; not persisted)

**Captured — turn 1 budget_constraint:**
```
[paste]
```

**Captured — turn 2 budget_constraint:**
```
[paste]
```

**Status P8E-11:** ☐ Pass  ☐ Fail  ☐ N/A

---

## Exit Decision Checklist

Complete only after all sections above are filled in.

| Check | Required | Status | Notes |
|---|---|---|---|
| No blocker issues remain | Yes | ☐ | |
| Core CLI capability coverage complete (CLI-01–10) | Yes | ☐ | |
| Follow-up/session coverage incl. SES-06, SES-07 | Yes | ☐ | |
| Structured metadata spot checks complete | Yes | ☐ | |
| Phase 8b venue-aware metadata verified in comparison | Yes | ☐ | |
| Phase 8a1: position_score in comparison JSON; score_delta in transfer; ranking quality in differential | Yes | ☐ | |
| Phase 8c: chip.signal_label correct for current GW type | Yes | ☐ | |
| Phase 8e: budget_constraint, chip_unavailable, hit_warning all exercised | Yes | ☐ | |
| Phase 8e: session statelessness — constraint absent on turn 2 without squad_context | Yes | ☐ | |
| Validation runner shows 44/44 PASS | Yes | ☐ | |
| Findings log written | Yes | ☐ | |
| Go or no-go decision written | Yes | ☐ | |
| Pass Index row added to `UAT_FINDINGS.md` | Yes | ☐ | |
| Compact summary inserted above `<!-- END OF REAL PASS SUMMARIES -->` marker; four sync values confirmed (date, label, recommendation, filenames) — see sync-rules table in `UAT_FINDINGS.md` | Yes | ☐ | |

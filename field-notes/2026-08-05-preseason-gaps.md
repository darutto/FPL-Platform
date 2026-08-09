---
title: Preseason gaps surfaced by a Bench Boost GW1 question
found_via: user asked "¿me conviene el bench boost en la fecha 1?" and the card answered "Condiciones favorables / average FDR (top 10) 2.2"
captured: 2026-08-05
relevant_to: [scoring, chips, preseason, gw-resolution, data-quality]
status: new
---

## What prompted this

A `/chips` turn for Bench Boost in GW1 rendered a card reading **"Condiciones
favorables — average FDR (top 10) 2.2"** and nothing else. Tracing that 2.2 back
to its source turned up four separate defects, three of which are live all season
and not preseason-specific.

All evidence below was reproduced against the **live 2026-27 bootstrap** on
2026-08-05 (GW1 `is_next`, deadline `2026-08-21T17:30:00Z`), by calling existing
engines only — `assemble_captain_context`, `_derive_scoring_inputs`,
`compute_position_score`, `calculate_captain_score`. No product code was changed.

---

## Findings

### 1. `_advise_bench_boost` reports a selection-biased FDR — severity: high

**What happens:** The Bench Boost signal averages the FDR of the top 10 MID/FWD
*by captain score*. But FDR is 30% of that very score, so ranking by score
**selects for low FDR**, and the resulting average is then reported as evidence
about the gameweek's difficulty. It is circular.

**Evidence** (live GW1, reproduced exactly):

| population | mean FDR |
|---|---|
| top 10 by captain score (what we report) | **2.20** |
| all 292 eligible MID/FWD | 3.06 |
| all 20 teams | **3.10** |

**This flips the verdict.** `_BB_FAVORABLE_FDR = 2.5`, `_BB_MARGINAL_FDR = 3.0`.
The biased 2.20 yields `conditions_favorable`; the unbiased 3.10 yields
`conditions_unfavorable`. The bias is the *only* reason the card said favorable.

**Where:** `packages/fpl-grounded-assistant/fpl_grounded_assistant/chip_advisor.py:381-383`

**Fix direction:** Average FDR over a population that was not selected using FDR
— all 20 teams, or all eligible players. Note this is a **threshold-semantics
change**: the existing `_BB_*` cutoffs were tuned against the biased
distribution and would need re-picking against the unbiased one. Not a one-line
fix.

**Related:** the same "rank by score, then report a component of that score as
independent evidence" shape is worth auditing wherever else we summarise a
top-N. Not yet checked elsewhere.

---

### 2. `form` is 0 for every player in preseason — severity: high

**What happens:** The scoring engine's heaviest input is dead between seasons,
so scores collapse to fixture + xGI/90 and rankings become mostly "who has an
easy fixture this week".

**Evidence:** across all **570 elements** in the live bootstrap, `form` is
non-zero for **0**. It carries weight **0.40** for MID/FWD and **0.30** for
GKP/DEF (`position_score.py:46-54`). Consequence, visible in the top 10 above:
**6 of 10 are Arsenal** — not a judgement about Arsenal, just that they draw
FDR 2 in GW1 and with `form` zeroed the fixture term dominates.

Other bootstrap stats *are* populated, carrying **last season's** totals
(`minutes` max 3420, `starts` max 38, `total_points` max 239) — so there is real
signal available, just not through `form`.

**Where:** `position_score.py:36-54`, `captain_score.py:82-95`,
`transfer_advisor.py::_derive_scoring_inputs`

**Fix direction:** Detect the zero-form state and either re-weight onto
last-season per-90s, or have the surface say the engine is running degraded
rather than emitting a confident number. Overlaps
[V2_ROADMAP.md](../V2_ROADMAP.md) Season Launch item #1 ("Zero-minutes /
fresh-season safety"), which anticipated the divide-by-zero risk but not the
silent-confident-answer risk.

---

### 3. Per-90 rates have no minutes floor — severity: high

**What happens:** `xgi_per_90 = expected_goal_involvements / (minutes / 90)`
with no sample-size guard, so a player with a handful of minutes and one lucky
involvement outranks established starters.

**Evidence:** the current **#1 ranked MID/FWD in the entire game** is
**Dasilva (BRE), with 2 minutes played last season** — `xgi/90 = 3.60`,
score 48.0, ahead of B.Fernandes (3065 min), Saka (2218), Gyökeres (2217).
Also in the top 10: Nyoni (21 min), Dowman (152 min), Nelson (118 min).
**12 of the top 50** played under 450 minutes.

**Where:** `transfer_advisor.py::_derive_scoring_inputs` (xGI derivation);
same untrusted rates flow into `position_score.py` for `saves_per_90`,
`clean_sheets_per_90`, `dc_per_90`.

**Fix direction:** A minutes floor, or shrink rates toward a positional prior
proportional to sample size. Affects every surface that ranks players, **all
season**, not just preseason — a January signing with 60 minutes hits this too.

---

### 4. The current-GW resolver migration is half-finished — severity: med

**What happens:** A canonical resolver exists that handles the preseason /
between-GW state, three modules use it, and **five do not** — so some intents
work before GW1 kickoff and others silently return "unknown gameweek", with no
visible reason for the difference.

**Evidence:** GW1 is `is_current: False, is_next: True` right now. Canonical
`get_current_gameweek` (`fpl-api-client/fpl_api_client/fpl_client.py:165`) does
`is_current` → `is_next` → `None` and resolves GW1 correctly.

| status | module |
|---|---|
| ✅ delegates to canonical | `comparison.py:209`, `differential_picks.py:96`, `transfer_advisor.py:182` |
| ❌ bare `is_current` → `None` | `chip_advisor.py:122`, `fixture_outlook.py:79`, `transfer_suggestion.py:148`, `player_fixture_run.py:113`, `team_fixture_calendar.py:100` |
| ⚠️ third behaviour | `get_team_snapshot.py:108` — never returns `None`; falls back to last finished GW, else `min(events)`, else `1`. **Invents a gameweek** rather than admitting it doesn't know. |

This is the predicted failure mode of the duplicate-resolver sprawl already
deferred in [V2_ROADMAP.md](../V2_ROADMAP.md) ("≥9 current-GW impls ... deferred
to a dedicated cleanup track") — the 2026-07-23 season-launch fix patched the
three modules where the symptom was noticed, not the cause.

**Fix direction:** Point the five stragglers at the canonical resolver; decide
deliberately what `get_team_snapshot` should do when the GW is genuinely unknown
(almost certainly: return `None` and let callers handle it, not fabricate `1`).

---

## Also confirmed, already tracked

- **Bench Boost *is* legal in GW1.** `bootstrap["chips"]` gives
  `bboost start_event=1 stop_event=19` and `3xc start_event=1`, while
  `wildcard` and `freehit` both start at `event=2`. Matches the two-window
  chip work in Season Launch item #2, which is still open — `chip_advisor.py`
  still reasons over four chip names statically and never reads this array.
- **`chip_advisor` never checks for blank gameweeks when advising Bench Boost.**
  Whether all 15 of your players actually have a fixture is *the* precondition
  for the chip, and it is not consulted. The data is right there —
  `ctx["meta"]["blank_gw_teams"]` was `[]` for GW1 — and `_classify_gameweek_type`
  in the same file already computes exactly this for Free Hit.
- **`python` package collision is real and bites.** Both `fpl-data-core` and
  `fpl-captain-engine` ship a top-level `python` package; importing in the wrong
  sys.path order fails with
  `ImportError: cannot import name 'CaptainCandidate' from 'python'`.
  Already logged as the pending PR-2 of the import-order cleanup.

---

## Open questions

*Hunches and unknowns — not findings, not evidence-backed.*

- `ep_next` maxes at **4.0** across all 570 players. Looks like a preseason
  placeholder rather than a real projection, but I did not verify what FPL
  populates it with mid-season, or whether anything of ours reads it.
- **We cannot detect transfers.** `starts` and `minutes` are last season's, at a
  possibly different club — e.g. Dubravka shows `starts=35` but is now at TOT,
  presumably as a backup. Any "proven starter" heuristic built on these fields
  is unreliable for exactly the players who moved. Unclear whether a free signal
  for this exists in the bootstrap.
- Whether the selection-bias shape in finding #1 appears in other top-N
  summaries. Suspected, unchecked.

# i39 follow-up: did `get_my_squad` actually move Group A? (2026-08-26)

Measurement only. No product code touched — see suite count at the bottom.

## Method

- 12 questions (7 Group A + 2 Group B control + 3 negative-fire control) x
  2 conditions (`team_connected` / `no_team`) x 5 reps = **120 calls**.
- `provider="openai"`, `model="gpt-5.6-luna"` passed explicitly to
  `ask_orchestrated()` on every call (never via env). Confirmed independently
  from the `fpl_provider_event` log line, not just the harness's own recorded
  field: 120/120 log lines say `provider=openai, model=gpt-5.6-luna`.
- Frozen bootstrap reused: `field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json`.
  `team_connected` = a **shallow copy** of that bootstrap with
  `bootstrap["_my_team_id"] = 1` injected, reproducing exactly the one
  mutation `harness.ask_v2(team_id=...)` makes (see `get_my_squad.py`'s
  docstring) — this script calls `ask_orchestrated()` directly, same as the
  original 2026-08-23 measurement did, bypassing `ask_v2()`/`decision_router`
  entirely, so the bootstrap shape is the only thing that needed reproducing.
  `no_team` = the original bootstrap object, untouched.
- **Frozen-bootstrap-vs-live-fetch caveat**, stated rather than hidden:
  `get_my_squad` hits the real FPL API regardless of the bootstrap being a
  static snapshot. The frozen bootstrap has no `is_current` event (pre-season
  freeze), so its GW resolution falls back to GW1 — which has long finished
  on the live API, so every fetch succeeds and returns team id 1's real GW1
  picks. A "fecha 2/3" question still resolves against that frozen GW1, and
  any explicit `gw=2/3` the model passes gets clamped back down to GW1 by
  `get_my_squad`'s own future-gw guard — so nothing in this run 404s on a GW
  mismatch. Team id `1` was live-verified beforehand (15 real picks for
  gw=1); a deliberately bad id (`999999999`) was verified separately to 404
  (used only for the failure-mode check below, not in the main sweep).
- Every observation appended to disk and flushed immediately, before any
  aggregate was computed (`measure_squad_tool_routing.py`, reusing
  `measure_tool_routing.run_one()` unchanged).

## Raw per-question counts (out of 5 reps)

| id | family | condition | no_tool | get_my_squad | other tools called |
|---|---|---|---|---|---|
| sb-02 | squad_building | team_connected | **5** | 0 | — |
| sb-02 | squad_building | no_team | **5** | 0 | — |
| sb-13 | squad_building | team_connected | **5** | 0 | — |
| sb-13 | squad_building | no_team | **5** | 0 | — |
| cvg-02 | chip_vs_gameweek | team_connected | 0 | **5** | — |
| cvg-02 | chip_vs_gameweek | no_team | 0 | **5** | — |
| cvg-11 | chip_vs_gameweek | team_connected | 0 | 3 | get_gameweek_context x5 |
| cvg-11 | chip_vs_gameweek | no_team | 0 | 4 | get_gameweek_context x4, get_chip_advice x1 |
| cvg-12 | chip_vs_gameweek | team_connected | 0 | **5** | get_chip_advice x4, get_gameweek_context x1 |
| cvg-12 | chip_vs_gameweek | no_team | 0 | **5** | get_chip_advice x2, get_gameweek_context x1 |
| cvg-03 | chip_vs_gameweek | team_connected | 0 | **5** | get_chip_advice x2 |
| cvg-03 | chip_vs_gameweek | no_team | 0 | **5** | — |
| ad-05 | advice | team_connected | **5** | 0 | — |
| ad-05 | advice | no_team | 2 | 1 | get_gameweek_context x3 |
| gw-05 | gameweek_state (control) | team_connected | **5** | 0 | — |
| gw-05 | gameweek_state (control) | no_team | **5** | 0 | — |
| gw-09 | gameweek_state (control) | team_connected | **5** | 0 | — |
| gw-09 | gameweek_state (control) | no_team | **5** | 0 | — |
| neg-defensas | negative_control | team_connected | 0 | 0 | get_transfer_suggestion x5 |
| neg-defensas | negative_control | no_team | 0 | 0 | get_transfer_suggestion x5 |
| neg-comparar | negative_control | team_connected | 0 | 0 | compare_players x5 |
| neg-comparar | negative_control | no_team | 0 | 0 | compare_players x5 |
| neg-jornada | negative_control | team_connected | 2 | 0 | get_current_gameweek x1, get_gameweek_context x2 |
| neg-jornada | negative_control | no_team | 0 | 0 | get_current_gameweek x2, get_gameweek_context x3 |

0 exceptions across 120 calls. Total cost: **$0.3747**.

## The three answers that matter

**Did the 21 move? Partially — 10 of 21 resolved cleanly, 10 of 21 did not
move at all, 1 of 21 is ambiguous.**

Splitting the original 21 no-tool instances by question:

- **Resolved (10 of 21):** `cvg-02` (5), `cvg-11` (2), `cvg-12` (2), `cvg-03`
  (1). All four now show 0/5 no-tool in *both* conditions, with `get_my_squad`
  firing reliably (3–5 of 5 reps) and correctly chaining with
  `get_gameweek_context`/`get_chip_advice` in the same turn. This is the
  chip_vs_gameweek family — the pinned failure class the task brief is built
  around — and it moved as expected.
- **Did not move at all (10 of 21):** `sb-02` (5) and `sb-13` (5) — both
  `squad_building` questions shaped as "N more players that fit the budget I
  have left" (`select_players_within_budget`'s territory). **Both stayed at
  5/5 no_tool even with a team connected.** Sample answers (one extra
  ad-hoc call per question, not part of the 5-rep counts above, so not
  double-counted in the table):
  - sb-02 ("Necesito 4 medios que me permita el presupuesto, ya tengo el
    resto del equipo armado."): asks the user to specify total budget and
    whether it's a swap or a hypothetical squad — never touches
    `get_my_squad`.
  - sb-13 ("...el presupuesto que me queda después de estas ventas."): asks
    for total budget, locked players, and per-player max — same pattern.
  - Neither question uses the words "mi equipo" / "mi plantilla" — they say
    "ya tengo el resto del equipo armado" / "el presupuesto que me queda" —
    phrasing `get_my_squad`'s schema description doesn't obviously cover.
    (One extra ad-hoc sample of sb-02 alone *did* call `get_my_squad`, so this
    is not a hard 0% — it is a low-rate case the 5-rep sample happened to
    miss entirely, consistent with the task's own warning that single runs,
    and even 5-run samples near a boundary, are noisy. The finding stands:
    the measured rate is far lower than the chip_vs_gameweek family's.)
- **Ambiguous / worse (1 of 21):** `ad-05` ("¿Me conviene hacer un transfer
  esta semana o mejor guardo el chip?") — 5/5 no_tool **with** a team
  connected (worse than the 1/5 baseline, though n=5 either way), 2/5 no_tool
  **without** one (roughly matches the 1/5 baseline within noise). This
  question was already genuinely underspecified between two advice tools
  before `get_my_squad` existed (see its corpus note); adding a squad tool
  did not resolve that ambiguity and, on this sample, connecting a team did
  not help at all.

This is not a prompt problem to fix here (out of scope) — it is reported so
the next step is evidence-based: the resolved half is concentrated in
questions that name "mi equipo"/"mi plantilla"/a GW number; the unmoved half
is concentrated in "fill N budget-constrained slots" phrasing that implies an
existing squad without naming it.

**Did Group B stay put? Yes, exactly.** `gw-05` and `gw-09` are 5/5 no_tool
in both conditions, identical to the 2026-08-23 baseline. No contamination
from #167 — the real i40 (these two questions) is untouched by this change.

**Does `get_my_squad` over-fire? No — 0 fires across 30 calls.**
`neg-defensas`, `neg-comparar`, `neg-jornada` (no personal reference) never
called `get_my_squad` in either condition, 0/5 each x 2 conditions = 0/30.
The tool reaches for itself only on squad-referencing phrasing, matching the
design intent behind #167.

## Two secondary observations (not asked for, but visible in the data)

1. **`get_my_squad` also fires with no team connected**, on the resolved
   Group A questions (`cvg-02/11/12/03` all show `get_my_squad` calls in the
   `no_team` column too, correctly returning `status=no_team_connected`, at
   zero network cost — the tool's own early-return, confirmed by
   `test_no_network_call_made` in the existing suite). This is a **behavior
   change from before #167** for anonymous users asking these specific
   questions: previously the model asked the user to paste 15 players by
   hand; now it (via the tool) says to connect a team from the Squad tab.
   That reads as an improvement, not a regression, and it does not violate
   the "zero cost for unrelated questions" principle — it only fires because
   the *question* mentions the squad, exactly the intended trigger.
2. **Full-pipeline failure-mode check** (not part of the 120-call sweep):
   ran the pinned chip_vs_gameweek question 3x with `_my_team_id=999999999`
   (a 404 team id, verified live beforehand). All 3 runs: `get_my_squad`
   called, returned `status=not_found`, and the model relayed a clear
   Spanish message ("No encontré ningún equipo FPL con el ID 999999999...")
   — never an exception, never an empty answer, and (on one run) still
   answered the chip half of the question from general fixture signals while
   being explicit that it couldn't evaluate the bench because no team was
   found. The unit-level failure modes (404/500/connection/timeout/exception)
   were already covered by PR #167's own test suite
   (`tests/test_get_my_squad.py`); this confirms the same degrade holds at
   the full `ask_orchestrated()` level, not just the tool function in
   isolation.

## New real size of i40

Unchanged by this measurement — i40 is the `gameweek_state` family
(`gw-05`/`gw-09`), confirmed still failing 5/5 in both conditions here. This
task did not re-measure i40's accuracy (correct-vs-fabricated); it only
confirmed #167 did not accidentally move or fix it. i40 stays exactly as
sized in `chore/board-i40-partition` (10/450 ≈ 2.2%).

## Regression instrument

No product code changed on this branch (only a new measurement script +
observation artifacts), so the F1 render-harness's 112 fixed renders (which
already cover `get_my_squad`'s renderer, added when #167 merged) ran
unchanged as part of the full suite below — there is no separate "no-team
path" regression to re-prove here; nothing in the no-team code path was
touched.

## Suite

Run from this worktree (`.claude/worktrees/squad-tool-verify`):
`packages/fpl-grounded-assistant`: **1352 passed, 1 skipped** (1353
collected). `packages/fpl-api-client`: **45 passed**. Matches the worktree
baseline expected post-#167 (root-checkout vs worktree difference is
`packages/fpl-tactical/data/`, gitignored — not run from root for this
task).

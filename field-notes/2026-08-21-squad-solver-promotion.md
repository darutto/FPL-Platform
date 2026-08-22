# Squad solver promoted from the measurement harness to the product

**Date:** 2026-08-21
**Branch:** `exp/agentic-loop`
**Bootstrap:** `field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json`
(sha256 `4cbb9fa18a5852c73a54fbe24a03b34e0c33ae5b3c549171cbcb02568d8b2aae`, verified)

---

## What moved

| Before | After |
| --- | --- |
| `experiment_measurement._min_cost_flow`, `_add_edge`, `_Edge`, `exact_completion`, `SQUAD_QUOTAS`, `POSITION_LABELS`, `_player_index`, `_cost`, `_minutes`, `_duplicates` | `fpl_grounded_assistant/squad_solver.py` |
| — | `fpl_grounded_assistant/build_squad_tool.py` (tool-runner spec + handler) |
| — | `BUILD_SQUAD_SCHEMA` in `tool_schema_registry.py`, tool name `build_squad` |
| — | `renderer._RENDERERS["build_squad"]` |

`experiment_measurement.py` now **imports** those names rather than owning them, and
re-exports them so the harness and its tests keep their import surface. A test asserts
`experiment_measurement.exact_completion is squad_solver.exact_completion`, so the two can
never drift into a second duplicate-resolver situation. The measurement harness's own tests
(15 in test_experiment_measurement.py, 16 in test_class2_grader.py) pass unchanged.

`BUILD_SQUAD_SPEC` takes its `description` and `parameters` **from** `BUILD_SQUAD_SCHEMA`
rather than restating them. Two hand-maintained copies of a tool description drift, and a
drifted description is exactly what `7a05a96` fixed.

---

## Scoring basis: `total_points` by default, `points_per_game` offered, `form` refused

This was decided against the data, not by preference.

`form` reads **0.0 for all 592 elements** in the frozen bootstrap. A form objective makes
every squad tie on score, so the solver returns whichever squad the tie-break happens to
reach — an arbitrary answer wearing the shape of a computed one. It is not offered at all;
passing `objective="form"` returns `invalid_argument` / `unknown_objective` rather than a
plausible-looking squad. `points_per_game` and `total_points` are populated for 400 of 592
and are the honest pre-season basis.

Between the two, run both and look at the goalkeepers:

| Player | Minutes | Total points | Points per game | Price |
| --- | ---: | ---: | ---: | ---: |
| Benitez (CRY) | 90 | 7 | **7.0** | 4.5 |
| Ellborg (SUN) | 270 | 16 | 5.3 | 4.5 |
| Raya (ARS) | 3330 | **162** | 4.4 | 6.0 |
| Kelleher (BRE) | 3330 | 143 | 3.9 | 5.0 |

Maximising `points_per_game` buys **Benitez and Ellborg** — one 90-minute appearance and
three appearances respectively. Benitez has the best points-per-game of any keeper in the
game off a single match. Maximising `total_points` buys **Raya and Kelleher**, two keepers
who played every minute of the season. `total_points` is the default because it is an
additive season quantity: summing it across 15 players means something, and it prices in
durability instead of rewarding small samples.

`points_per_game` stays available because it is the right basis once minutes are
comparable, and `min_minutes` exists to make it safe — `min_minutes=1000` drops Benitez and
returns a sane per-game squad. All three behaviours are pinned by tests, including a test
that re-reads Benitez's and Raya's raw stats out of the frozen bootstrap, so a change to
the basis shows up as a failing test rather than a quietly different squad.

Every result carries `ranking_basis`, from the same `ranking_provenance.get_ranking_basis`
the ranking tools use. On this bootstrap it reads `prior_season_carryover`, which is the
honest label: these are last season's numbers.

---

## The Q6 illegal squad is now unreachable

The failure, from `anthropic/B/Q6/1`:

```
Raya ARS 6.0 · Gabriel ARS 8.0 · Guéhi MCI 6.0 · O'Reilly MCI 6.5 · B.Fernandes MUN 12.0
Semenyo MCI 8.5 · Bruno G. ARS 7.0 · Gibbs-White NFO 8.0 · Rice ARS 7.5 · Haaland MCI 15.5
João Pedro CHE 7.5 · Senesi TOT 6.0 · Dewsbury-Hall EVE 6.5 · Thiago BRE 8.0 · Benitez CRY 4.5
```

Every price and club is correct against this bootstrap. It totals **117.5** against a 100.0
budget, puts **4 in ARS** and **4 in MCI**, and the answer stated *"Coste total: £100.0m"*.

Those 15 element ids are pinned in `tests/test_squad_solver.py` as `Q6_ARM_B_SQUAD_IDS`, and
`validate_squad` is asserted to report `budget:1175>1000` plus exactly two `club_cap:` errors
for them. The same test file then asserts the solver's answer to the same question is legal.

It is unreachable rather than merely unlikely because the club cap and the positional quotas
are **structural, not checked**: they are edge capacities in the
`source → position → player → club → sink` network. An over-capacity squad is not a flow in
that graph, so there is no code path that produces one and forgets to check it. On top of
that, `validate_squad` independently re-derives legality from the bootstrap before any result
leaves the module, and if that ever failed the module falls back to the cheapest legal squad
or returns `error` — never a squad.

Money is integer `now_cost` tenths end to end. `total_cost`, `budget` and `remaining` in
millions are computed as `tenths / 10`, so a stated total cannot drift from the squad that
produced it. A test asserts exactly that.

---

## Optimality, stated honestly

| Property | Claim |
| --- | --- |
| Legality of any returned squad | **Guaranteed**, and independently re-verified |
| Infeasibility | **Exact** — reported only when the cheapest legal squad provably exceeds the budget |
| The score maximum | **Near-optimal, not proven optimal** |

Maximising a score subject to both a budget and the club/position structure is a
multi-dimensional knapsack. The search is a Lagrangian bisection on the budget multiplier λ
(each λ is an exact min-cost flow on `λ·price − score`) followed by a single-swap
improvement pass to a fixpoint. The result declares this as
`objective_optimality: "lagrangian_plus_single_swap_fixpoint"`.

Measured, not assumed: a 45-second randomised **two-swap** search failed to improve any of
the four shipped squads (`total_points` and `points_per_game`, with and without Haaland
locked) by a single point. Solve time is 0.2–0.4s per squad.

---

## What the tool deliberately does not do

Stated first in the tool description, ahead of the capability, following `7a05a96`:

* **No fixtures.** No opponents, no schedule difficulty, no future gameweek. Season-to-date
  bootstrap only.
* **No captaincy, price changes or rotation risk.** Availability filtering is only
  `status == "a"` and `minutes >= min_minutes`.
* **No bench discount.** It maximises the total across all 15. That is exactly right for a
  bench-boost question (Q6 is one) and slightly bench-heavy otherwise.

Three existing squad-shaped tools now point at it, because a model asked to build a squad
currently reaches for one of them:

* `get_chip_advice` — "does NOT build or price a squad; for 'is bench boost viable if I build
  a team from scratch' call `build_squad` for the squad and its totals, then this tool for
  the chip verdict."
* `get_transfer_suggestion` — "does not check squad legality, the three-per-club cap or a
  total budget."
* `rank_players_by_metric` — "a ranked list is not a squad."

---

## The division of labour

The model interprets the Spanish question, picks the objective, and explains the result. It
never does the arithmetic. `build_squad`'s numbers are authoritative, and the tool
description tells the model to quote the totals verbatim rather than restate them in a form
that can drift.

One misuse is called out explicitly in the `budget` parameter description, because the Q7
phrasing invites it: *"Haaland es un lock in, así que mi presupuesto arranca con un -15.5"*
means `budget=100.0` **and** `locked_players=["Haaland"]`, **not** `budget=84.5`. Passing
84.5 alongside the lock double-charges him and returns a legal but much poorer squad.

---

## Verification

All deterministic, offline, no API calls. `tests/test_squad_solver.py`, 44 tests:

1. Generated squads are legal for both objectives, across five budgets and five formations:
   15 unique players, 2/5/5/3, ≤3 per club, ≤ budget, all available with minutes.
2. The Q6 squad is pinned as illegal; the same inputs now produce a legal squad that is not
   117.5 and has no club at 4.
3. Haaland locked at 15.5 reconciles to the penny in integer tenths, for both 4-5-1 and
   5-4-1, by name through the tool as well as by id.
4. Infeasibility is explicit in four separate ways (budget too small, locked club-cap
   violation, locked players alone over budget, a synthetic pool with one keeper) and never
   returns a partial or illegal squad.
5. The greedy counterexample passes from the new home, and also defeats the generator.
6. The objective choice is pinned against Benitez and Raya, including a test that re-reads
   their raw stats from the frozen bootstrap.

Full package suite: **1018 passed, 1 skipped**. Registry size moved 33 → 34 (27 offered
without FI, 31 with).

Two gaps were caught by the existing suite rather than by inspection, and both were real:
`build_squad` had no entry in `renderer._RENDERERS` (prod would have surfaced
`"No renderer for tool"` as `final_text`), and a tool count was pinned inside a subprocess
source string as well as in the assertions around it.

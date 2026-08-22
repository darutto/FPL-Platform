# Partial selection under a budget: how completability is enforced

*2026-08-21 · branch `exp/agentic-loop` · follows `0fdaa15` (squad solver) and `22b9c6b` (reach)*

## Why a second solver tool

`build_squad` solved the full-15 case and is reached reliably: Q6 goes to it 3/3 in both
Anthropic and gpt-5.6-luna, and every returned squad audits clean against the frozen
bootstrap.

Q7 and Q9 never call it, and that is correct discrimination rather than a defect. Q7 asks for
*"4 medios con mejores 5 fechas y precio que permita el budget"*; Q9 for *"dos buenos
delanteros"*. A 15-man squad builder is the wrong tool for a four-player question, and the
model was right to decline it.

But both questions still carry budget arithmetic, and nothing deterministic served it. The
human Axis 3 read of Q7 was literally *"solo devuelve una lista"* — because a list was all the
tools could produce. That shape is the common one: users ask "which 4 mids fit my budget?" far
more often than "build me the whole team".

`select_players_within_budget` covers it.

## The failure it removes, stated precisely

**Picking the N highest-scoring players inside a price band is not the answer.** The naive
selection can be individually affordable and collectively impossible, in two distinct ways:

1. **Stranding.** The picks consume so much of the budget that the remaining slots have no
   legal, affordable filling. On the frozen bootstrap: Haaland locked at 15.5 with 80.0 to
   spend, the four best midfielders cost 36.0 — and `exact_completion` proves no legal 15-man
   squad containing them exists. `test_stranding_on_the_frozen_bootstrap_too` pins it.
2. **The club cap.** The locked players already hold two of a club; the top-N adds two more,
   making four. `test_the_club_cap_premise_holds_the_naive_answer_breaks_the_cap` pins the
   synthetic version, where `exact_completion` returns `fixed_club_cap_exceeded`.

Both naive answers look right. That is the failure mode this module exists to remove: the
stated arithmetic reconciles, so nobody checks.

## How completability is enforced

Three independent layers, in order. Nothing is returned unless all three agree.

### 1. It is the search space, not a post-check

`_SelectionSpec` splits one position's slots inside the *same* min-cost flow network
`build_squad` already uses. The source feeds a dedicated `("select", position)` node of
capacity `count`, and the ordinary position node with the remainder:

```
source ──cap=count──▶ ("select", MID) ──cost=−d·score──▶ player ──cost=λ·price──▶ club ──cap=3−locked──▶ sink
source ──cap=5−count─▶ ("position", MID) ──cost=0───────▶ ┘
```

Because the split is a capacity in a network whose club edges are already capped at
`3 − |locked from that club|` and whose positional quotas are already edge capacities, **a
selection that strands the budget or breaks the club cap is not a flow in this graph at all.**
There is no repair step that can be forgotten.

The score moves onto the sub-quota entry edges, so what is maximised is the *selection's*
score while every other slot is filled at minimum cost — which is what makes "the best N you
can afford" the best N rather than the best whole squad.

`_lagrangian_search` is unchanged apart from carrying the spec through: the same bisection on
the budget multiplier λ, the same exactness for each λ.

### 2. `exact_completion` proves the final selection, and returns the witness

The search's answer is then handed to `exact_completion` — the same oracle `build_squad`
trusts, the same object (`test_the_two_tools_share_one_candidate_pool_and_one_oracle` asserts
identity). It returns the cheapest legal completion, which becomes the `witness_squad` in the
payload. There is no second search: `select_players` reuses `_min_cost_flow`,
`_build_flow_graph`, `_saturated_ids`, `_lagrangian_search`, `_candidate_pool`,
`_objective_scorer`, `_player_payload` and `validate_squad`.

`_candidate_pool` is newly factored out of `build_squad`, so the two tools cannot disagree
about who is available.

### 3. `validate_squad` re-derives legality from the bootstrap

The witness goes through `validate_squad` — 15 unique ids, exact positional counts, ≤3 per
club, total ≤ budget — before anything is returned. If it fails, the tool returns
`selection_failed_completion_check` with an empty selection. A near-miss is never dressed up
as valid.

**A stranding selection is unreachable.** It is not a flow (1), it fails the oracle (2), and
its witness fails validation (3). `test_a_stranding_selection_is_unreachable` asserts all
three on a fixture where the naive top-4 costs 60.0 against a 56.0 ceiling; the tool returns
2 stars + 2 seconds at exactly 56.0, which an exhaustive search over the same pool confirms is
the optimum.

## Search quality, declared rather than claimed

`objective_optimality` says which search produced the answer, the way `build_squad`'s does.

The multiplier sweep is exact for each λ, but the budget-constrained maximum can sit in a
concavity no λ reaches, so a single-substitution hill-climb follows — **gated on
`exact_completion`**, so an improving-but-stranding swap is rejected rather than taken.

Measured, not assumed. Across 45 position × count × budget cases on the frozen bootstrap:

| | |
|---|---|
| cases where the swap pass improved the answer | 5 of 45 |
| largest improvement | MID ×5 @ 80.0m: 594 → 644 |
| worst-case oracle calls in one solve | 133 (ceiling 200) |
| cases that hit the ceiling | 0 |
| worst-case solve time | 0.61s (`build_squad` is 0.29s) |

The pass is load-bearing, and `test_the_completability_gated_swap_pass_is_load_bearing` fails
if it ever stops being so, rather than letting it rot into decoration. Hitting the ceiling
reports `lagrangian_plus_selection_swap_truncated` instead of hiding it.

## Infeasibility

Exact in the direction that matters. At the top of the multiplier sweep the flow is the
cheapest way to field `count` eligible players of that position alongside a full legal squad,
so an overshoot there is a proof that no such selection exists.

The answer then names what *would* be affordable: the best selection with the price band
dropped, and the priciest one that still fits — both produced by the same search and both
themselves completable, asserted in the tests. Two extra flow solves, only on the infeasible
path (0.66s worst case).

One invariant fell out of writing this and shaped the code: **once a legal completion of the
locked set exists, only a price band can refuse a request.** Any legal squad holds the full
positional quota, and `count` is validated to be within the remaining part of it, so dropping
the band always leaves a selection available. The count-scan branch that used to search for a
smaller feasible count was therefore dead code, and is now a documented guard.
`test_dropping_the_price_band_always_leaves_a_selection` sweeps every position × count and
would fail if that guard ever became reachable.

## Tool description

Commit `7a05a96` fixed a real failure caused by `rank_players_by_metric` claiming "use for
every top/best/most-by-metric query" while being blind to fixtures. Models obeyed and reached
for the wrong tool. So the description states both halves:

* **What it does** — one position, N players, budget and club cap enforced, completion proved.
* **The boundary** — "build_squad returns the WHOLE 15, this returns a SLICE of one." Asking
  here for all 15 is wrong; asking `build_squad` for four midfielders is wrong.
* **What it does not consider** — fixtures, opponents, schedule difficulty, any future
  gameweek; no captaincy, price-change or rotation view; `form` not offered because it reads
  0.0 for all 590 elements pre-season. One position per call.
* **The witness is not a bench.** It is the cheapest legal completion, included as proof, and
  the payload, the renderer and the description all say so.

`get_transfer_suggestion` — which is where Q7 and Q9 currently land — now points at it, the
way `rank_players_by_metric` points at `get_transfer_suggestion`. Its description also now
says plainly that its price filter is a *per-player* ceiling and not a combined one, which is
the specific misreading that made a list look like an answer. `rank_players_by_metric` and
`build_squad` point at it too. `test_the_description_states_the_boundary_and_the_blind_spots`
pins all four.

## Renderer

`build_squad` shipped without a `renderer._RENDERERS` entry and production would have surfaced
"No renderer for tool" as `final_text`; the existing suite caught it. Same trap, same slice:
`select_players_within_budget` is registered, and the coverage guard in
`test_renderer_zonal.py` covers it too.

The renderer prints the solver's own totals and re-adds no column. That is asserted rather
than asserted-about: `test_the_renderer_is_registered_and_prints_the_tools_own_totals` feeds
it a payload whose stated total disagrees with its rows and checks the payload's number is
what appears.

## Verification

`tests/test_select_players.py`, 64 tests, deterministic and offline against the frozen
bootstrap (sha256 `4cbb9fa1…`) and small synthetic fixtures. Integer `now_cost` tenths
throughout; millions asserted to be exactly `tenths/10` and never rounded independently.

Full package suite: **1080 passed, 1 skipped**.

`build_squad` is unchanged, verified in both directions rather than by a green suite: its
pre-patch module was loaded from `HEAD` alongside the patched one and the two were compared
output-for-output across 14 argument shapes — squads, both objectives, five budgets, four
formations, `min_minutes`, non-standard `position_counts`, and three invalid-argument paths.
**14/14 identical**, as were four `exact_completion` calls. (`ranking_basis` is excluded: a
standalone module load cannot reach the relative import, which is a harness artifact and not a
difference.) The generated squad is additionally pinned by id in
`test_build_squad_still_returns_the_same_squad`.

## Still unproven

That the orchestrator actually **reaches** this tool when asked Q7 or Q9 in Spanish, rather
than reaching for `get_transfer_suggestion` and doing the arithmetic itself. The tool existing
and the model choosing it are different claims — the same gap `22b9c6b` closed for
`build_squad`, and it closes the same way: a live run, which is out of scope here.

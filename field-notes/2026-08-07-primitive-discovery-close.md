---
title: Closing the primitive-discovery pass — two hard exercises, and the 4 categories everything collapses into
found_via: two deliberately hard manager questions (low-cost defensive rotation over GW1-8; a GW6 mini-wildcard fixture swing) run as capability probes
captured: 2026-08-07
relevant_to: [contracts, fixtures, historical, scoring, orchestrator, gw-resolution]
status: new
---

## Why this note exists

Two more probes were run after
[2026-08-06-query-primitives-gap.md](2026-08-06-query-primitives-gap.md), using
the protocol proposed there: *take a real manager question, answer it with tools
only, log where you fall off.*

**Conclusion up front: the discovery pass has converged. Stop probing, start
scoping.** Evidence for that claim is in the final section — the ~14 findings
across three sessions collapse into 4 categories, and the third session opened
only one new one.

---

## Exercise 2 — low-cost defensive rotation, GW1-8

> *"A pair of defenders at ≤£4.5m each such that, by rotating them, the starting
> one is always home against a bottom-6 side from last season or a promoted
> side. If no perfect pairing exists, give the 3 best that satisfy it in ≥7 of 8
> gameweeks."*

**The premise was arithmetically impossible, and saying so was the answer.**

### Findings

**2.1 — Last season's league table does not exist as a concept — severity: high**

The live bootstrap resets it: `position: 0`, `played: 0`, `points: 0` for all 20
teams. Had to rebuild the 2025-26 table by reading 380 fixture results from
`data/historical/seasons/2025-2026/parquet_merged/fixtures.parquet` and
recomputing points, GD and rank.

Reconstructed bottom 6: **CRY (45), NFO (44), TOT (41), WHU (39), BUR (22),
WOL (20)**.

The sharper point: **the historical store is already wired** —
`get_player_season_points`, `historical_gameweek_top_scorer`,
`owned_store_fallback` and `owned_store_sync` all read it — but **only at player
granularity**. Team-season aggregates are not exposed even though the results
that produce them sit in the same parquet directory. Ten seasons (2016-17 →
2025-26, 22MB) are owned, and the assistant cannot answer "who finished last".

**2.2 — Promotion/relegation is not modelled — severity: high**

Derived by diffing the current 20 against 2025-26's. Promoted for 2026-27:
**COV, HUL, IPS**. Relegated: **WHU, BUR, WOL**.

This is what made half the user's condition unreachable — three of the bottom 6
are no longer in the league. A system that modelled this would have said so in
the first line instead of silently returning a thinner result.

**2.3 — Opponent classification is not expressible — severity: med**

"Versus a bottom-6 side", "versus a promoted side" — no team labels of any kind
beyond FDR exist as a filter anywhere.

**2.4 — Venue is not a filter — severity: med**

`is_home` exists inside `team_fixtures` and `_resolve_venue` consumes it for
home/away-adjusted FDR, but no tool lets you filter fixtures by venue.

**2.5 — No joint-coverage / rotation reasoning — severity: med**

Combinatorial search over *pairs* with a per-gameweek coverage condition.
Distinct from the squad solver already logged: this optimises **temporal
coverage**, not a budget.

**2.6 — Nothing can detect and report an impossible premise — severity: med**

The most useful output of the exercise was the ceiling, not the answer:

```
Home-vs-target fixtures league-wide, GW1-8:  24
Best any single club achieves:                2
Theoretical ceiling for a pair:               4/8
User asked for:                               7/8
```

A tool returning "0 results" would have left the user thinking they searched
wrong. The value was in showing that 7/8 required 3.5 qualifying home games per
club when the league record is 2.

*Best real answer, for the record:* **Mitchell (CRY) + Tete (FUL)**, 4/8
(GW3,4,6,7), exactly £9.0m, both nailed starters (36 and 21 starts). Note the
trap avoided: the highest-coverage pairing on fixtures alone included Chelsea,
whose ≤£4.5m defenders (Hato 12 starts, Tosin 8, Acheampong 8) are cheap
*because they do not play*.

---

## Exercise 3 — GW6 mini-wildcard, fixture swing GW1-5 → GW6-10

> *Find the premium mid (≥£10.0m) with the best GW1-5 fixtures whose team
> deteriorates most into GW6-10; sell him plus a £7.5m forward; buy a MID+FWD
> from different teams, both in the top-5 fixture improvement, both ≥25 starts,
> maximising expected GW6-10 points within the exact budget.*

### Findings

**3.1 — Fixture windows are anchored to the present — severity: high**

This is the headline. `get_team_fixture_calendar` computes exactly the block-FDR
this question needs, but:

```python
fixtures_in_window = [f for f in team_fixtures[team]
                      if current_gw <= f.gameweek < current_gw + horizon]
```

It can do "the next 5". **It cannot do GW6-10.** There is no offset window, and
therefore no way to compare two windows. The entire premise of the exercise — a
swing between blocks — is inexpressible with the tool that comes closest.

**3.2 — No block comparison / swing metric — severity: high**

Follows directly from 3.1. Computed by hand:

```
Worst deterioration  LEE +0.80 · BHA +0.60 · LIV +0.60 · MUN +0.40 · TOT +0.40
Best improvement     FUL −1.20 · COV −1.00 · BOU −0.80 · SUN −0.60 · ARS −0.40
```

Caveat worth carrying: integer FDR over 5 fixtures makes swings land in 0.20
steps. FUL (−1.20) vs COV (−1.00) is **one FDR point spread across five games**.
The "top 5" is a band, not a ranking.

**3.3 — No real expected points, and the repo's names mislead — severity: high**

The question referenced "the repo's projections". They do not exist:

- `fpl_historical/projections.py` is **parquet promotion logic**, not player projections.
- `get_expected_minutes` declares itself in its own schema: *"FI-7b1 exposes a non-operational shell only."*
- `ep_next` from the API maxes at 4.0 across all 570 players — a preseason placeholder.

So any "optimise by xP" is a proxy. Used `ppg_last_season × 5`. This is the
heaviest prerequisite in the whole backlog and **is a modelling project, not a
tool** — see scoping warning below.

**3.4 — Team-list as a filter — severity: med**

"Players from these 5 clubs" is not expressible. Extends the combinable-filter
finding already logged, with a dimension not previously noted.

**3.5 — No constrained transfer optimiser, and no budget-feasibility report — severity: med**

Sibling of the squad solver but a different problem: optimise a bounded swap,
not build 15. Critically it must **report when the budget cannot be deployed** —
the most useful result here:

```
Sale:      B. Fernandes £12.0m + João Pedro £7.5m  =  £19.5m available
Ceiling under the constraints (top-5 improvement + ≥25 starts + distinct clubs):
           most expensive eligible MID  Saka £9.5m
           most expensive eligible FWD  Gyökeres £7.5m  (same club as Saka)
           max deployable                £15.5m
STRANDED:  £4.0m — the user asked for £0.0m in the bank; unreachable
```

**3.6 — Degenerate filter tiers go unreported — severity: low**

Only **one** midfielder in the entire game costs ≥£10.0m (B. Fernandes, £12.0m).
"Identify which premium mid…" had nothing to identify, and he is the optimum of
neither axis he was selected for. Nothing warns that a filter returned a
single-element universe.

*Recommended transaction, for the record:* buy **Rice (ARS, £7.5m, 35 starts)** +
**Evanilson (BOU, £6.0m, 32 starts)**. Rice dominates Saka on every available
column — same ppg (5.1), £2.0m cheaper, 10 more starts — while Saka only just
clears the ≥25 threshold the anti-rotation filter existed to enforce. Net swing
captured: **0.90 FDR points per fixture** (outgoing +0.30 → incoming −0.60).

---

## Synthesis — everything collapses into 4 categories

Across three sessions, ~14 distinct findings:

| Category | Findings | Character |
|---|---|---|
| **A. Query / filtering** | price filter, per-90 metrics, combinable filters, team-list filter, venue filter, opponent classification | **One coherent piece of work** |
| **B. Windows** | arbitrary GW window, block comparison / swing | Small; folds into A |
| **C. Optimisation** | squad solver, transfer optimiser, pair coverage | **Three different problems** |
| **D. Derived data** | season table, promotion/relegation, real xP, expected minutes | **Mixed sizes — danger** |

**Discovery has converged.** Session 1 opened three categories, session 2 opened
one, session 3 opened one. Further probes will yield variations inside A, not
new categories. The recommendation is to stop probing.

**The missing primitives are not football-domain — they are relational algebra:**
windows, differences, composite filters, and constrained optimisation. That is
encouraging: a well-designed query layer covers most of A and B at once, rather
than needing one tool per question.

### Scoping warning — two projects are hiding as tools

This is the part most likely to blow up a roadmap:

- **Category C is not one item.** Squad solver, transfer optimiser and pair
  coverage share the word "optimise" and nothing else — different constraints,
  different objective functions. Scheduling them together is how this overruns.
- **"Real expected points" (D) is not a primitive.** It is a modelling project
  requiring outcome backtesting. The Phase 8a assessment already concluded that
  hand-tuned coefficients need calibration against outcomes before being
  trusted. If it sits in a list next to "add a price filter", it will be
  underestimated by an order of magnitude.

**Suggested split:** A+B as one bounded query-layer piece. C as three separate,
individually-scoped problems, none urgent. D as its own track with backtesting,
explicitly not a tools sprint.

---

## Open questions

- Still unanswered from the previous note, and the one worth answering before
  committing to any of this: **does the LLM orchestrator with today's tools get
  further than the deterministic path?** Note `fix/gemini-orchestrator-empty-tool-call`
  is sitting unmerged and may be what blocks testing it locally.
- Whether the historical store can serve team-season aggregates cheaply, or
  whether the parquet layout makes that awkward. Not investigated.
- Whether `derive_role_signals` (penalties, free kicks) reaches any user-facing
  surface — carried over, still unchecked.

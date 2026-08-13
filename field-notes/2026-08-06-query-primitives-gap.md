---
title: Query-primitive coverage gap — what a real squad-building question needs vs. what the tools expose
found_via: attempted to answer "armá el mediocampo de mi equipo de J1 con Haaland fijo, 5-4-1, mejores 5 fechas" using only platform tools, then audited what actually got used
captured: 2026-08-06
relevant_to: [contracts, scoring, fixtures, preseason, orchestrator, routing]
status: new
---

## What prompted this

A concrete manager question — build a GW1 squad, Haaland locked at £15.5m,
5-4-1 shape, pick 4 midfielders on the best GW1–5 fixture run within budget —
was answerable with good grounding, but **the answer was produced almost
entirely outside the platform**. Auditing why turned into a capability map.

**The audit that started it:** the two scripts that produced the final
recommendation imported exactly one piece of platform code —
`fpl_pipeline.context.assemble_captain_context`, the *data loader*. The 5-GW
FDR aggregation, minutes floor, xGI/90 computation, price banding, budget
arithmetic, 3-per-club check and transfer flags were all written ad-hoc. The
platform served as a data source, not as an analysis engine.

---

## Capability map (verified live, 2026-08-06)

### Works today

| Need | Tool | Notes |
|---|---|---|
| Fixture run per team over N GWs | `get_team_fixture_calendar(horizon=1–10)` | ✅ returned LIV best over 8 |
| Fixtures for an arbitrary GW | `get_fixtures_for_gw(gw_number=1–38)` | ✅ GW3 and GW5 both fine |
| Rank players by a metric, filtered | `rank_players_by_metric(metric, position, min_minutes, top_n)` | ✅ position accepts Spanish (`medio`, `centrocampista`) |
| A player's fixture run | `get_player_fixture_run(query)` | ✅ but horizon fixed at 5 |
| Best fixture runs by position | `get_position_fixture_run(horizon, mode)` | ✅ |

Notable: **`rank_players_by_metric` already has `min_minutes`** — the sample-size
floor called out as missing in
[2026-08-05-preseason-gaps.md](2026-08-05-preseason-gaps.md#3) exists here. It
lives in one query tool and not in the scoring engine.

### Does not exist

| Missing | Evidence |
|---|---|
| **Price as a filter or sort key** | `rank_players_by_metric(metric="now_cost")` → `status: invalid_argument`, `Metric 'now_cost' not recognized`. No price filter on any ranking surface. `get_transfer_suggestion` has `max_price` but is dead in preseason (see below). |
| **Per-90 rates as queryable metrics** | Only cumulative totals are aliased (`expected_goal_involvements`, not `_per_90`). So "who has the best rate" is unaskable; only "who has the biggest pile", which just favours whoever played most minutes. |
| **Budget** | Nothing models £100.0m across 15, a locked player, or remaining spend. `squad_context.itb` exists but only gates transfer advice — it is not a construction input. |
| **Formation / squad structure** | Nothing knows 5-4-1 starts 5 DEF, that a squad is 2/5/5/3, or that bench = squad − XI. |
| **3-per-club limit** | Absent everywhere. |
| **Cross-tool composition** | Fixtures and player quality exist as separate tools; nothing joins them. The only join in the codebase is `composite = form / avg_fdr` in `transfer_suggestion.py:293`. |
| **Transfer / club-change awareness** | Last season's output is shown against the player's *current* badge with no flag. Live example: Semenyo reads `MCI, 202 pts, 5.5 ppg` — earned at Bournemouth as first option, now at Man City with unknown role. |
| **Degradation disclosure** | With `form=0` for all 570 players, no surface says "this is a fixture-and-history pick, not a form pick". |

### Full metric vocabulary of `rank_players_by_metric`

```
points · points_per_game/ppg · expected_goals/xg · expected_assists/xa
expected_goal_involvements/xgi · ict_index/ict · selected_by_percent/popularity/
ownership · minutes · goals_scored/goals · assists · clean_sheets · bonus · bps
```

Absent from the vocabulary: **price, any per-90 rate, form, saves, defensive
contribution, clean_sheets_per_90** — several of which the scoring engine
already consumes internally via `position_score.py`.

---

## Missing primitives — the implementation backlog

Ordered by leverage-to-effort as assessed on 2026-08-06.

### 1. Price as a first-class filter — size: small, leverage: highest
`min_price` / `max_price` on every ranking surface, plus `now_cost` as a sort
key. Unblocks roughly half of squad-building search on its own.

**The reason it ranks first is a safety argument, not a convenience one.** A
model that cannot query price during a search will invent prices. Every table
of recommendations becomes confidently wrong if that column lies, and it is the
hardest error for a user to catch — prices look plausible.

### 2. Per-90 rates as computed metrics — size: small
`*_per_90` variants for xGI, xG, xA, saves, defensive contribution. The
normalisation already happens inside `_derive_scoring_inputs`; it just is not
exposed as something you can rank by. Pairs with the existing `min_minutes`
floor, which is what makes rates trustworthy.

### 3. Combinable filters returning a table — size: medium
Today's tools return a top-N with a single sort. What the squad question needed
was a *view*: position + price band + minutes floor + fixture horizon, several
metrics projected, sorted. One such call would have replaced most of the ad-hoc
work.

### 4. Squad construction as a solver — size: large, and deliberately not an LLM job
Budget + formation + 3-per-club is constrained optimisation (a knapsack over
integer prices), not a query. Should be a deterministic tool the orchestrator
*invokes* — with the arithmetic outside the model.

**Evidence it must not be freehand:** the greedy builder written during the
2026-08-05 session put **B. Fernandes on the bench**. Careful ad-hoc code, still
wrong. A solver would not be.

### 5. Horizon on `get_player_fixture_run` — size: trivial
Currently pinned at 5 with no parameter, declared deferred on purpose at
`player_fixture_run.py:76`. Cannot ask for a player's next 3 or next 8.

### 6. Revive `get_transfer_suggestion` for zero-form states — size: small
Returns `status: empty` for every query in preseason, verified for both
midfielders and defenders, because `composite = form / avg_fdr` and
`if composite <= 0: continue` drops all 570 players. The only multi-GW player
recommendation tool is fully dead right now.

---

## Architectural position

*This section is a considered direction, not a verified finding. Recorded so the
reasoning survives; revisit rather than assume.*

**The framing "more tools vs. raw data access to the orchestrator" is a false
binary.** The axis that actually explains what worked is different:

```
get_chip_advice(chip)          → returns a verdict         [answer-shaped]
get_transfer_suggestion(...)   → returns a recommendation  [answer-shaped]
rank_players_by_metric(...)    → returns data              [query-shaped]
```

Only the query-shaped tool was useful for an unanticipated question. Every
answer-shaped tool **bakes a judgement inside** — which threshold, which formula,
which top-N — and that judgement becomes wrong the moment the question shifts.
The Bench Boost selection bias is exactly this failure: "top 10 by score" was a
decision buried inside a tool, and burying it is what made it a bug rather than
a parameter.

**On giving the orchestrator raw bootstrap access.** The 2026-08-06 session is
weaker evidence for this than it appears. What happened was not *reading data* —
it was **writing and executing code** over 570 elements × ~100 fields, which
does not fit in context. So the proposal splits in two:

- *Bootstrap data into context* — impossible at full size; requires pre-filtering,
  which is what a tool is. Collapses back into "build better primitives".
- *Orchestrator writes and runs code* — a code interpreter. Sandbox, resource
  limits, timeouts, a new audit surface. An order of magnitude larger.

Costs of the second that the current architecture currently gets for free:
**determinism** (`chip_advisor.py` docstring: *"Pure deterministic logic — no LLM
calls"*), **validation** (126 scenarios can check a tool against a fixture; they
cannot check generated code), and **predictable cost** (quota/audit was built
around bounded calls).

**Proposed shape** — keys to the kingdom exist, but off the critical path:

1. Deterministic tools for known high-traffic questions (what exists, minus the buried judgements)
2. **Query primitives** — the real gap, highest leverage
3. Squad solver — deterministic, no LLM in the arithmetic
4. Escape hatch — sandboxed, read-only, rate-limited, **off by default**, always shows the generated code

**On Sportmonks ordering.** More data first makes this worse, not better. If
"midfielders under £7m by xGI/90" is inexpressible over 570 players and ~100
fields today, adding positional and event data multiplies the field space
without a way to query it — and the predictable result is another wave of
bespoke tools with judgements baked in, one per question someone thought of on
the day. Primitives should come first and be designed so Sportmonks fields
arrive as **more columns, not more tools**. Worth checking
[FOOTBALL_INTELLIGENCE_IMPLEMENTATION_PLAN.md](../FOOTBALL_INTELLIGENCE_IMPLEMENTATION_PLAN.md)
defines a generic query surface rather than per-use-case tools.

---

## Protocol for finding the rest

The method that produced this map is repeatable: **take a real manager question,
try to answer it with only the tools, log where you fall off.** One pass turned
up price, per-90 rates, budget, formation and club limits.

Archetypes that would probe axes not yet touched:

- **Value** — "the best £5.5m defender" (price as the *primary* axis, not a filter)
- **Differential over a horizon** — crosses ownership × fixtures, two axes that never meet today
- **Rotation risk** — expected minutes, barely touched
- **Set pieces** — `derive_role_signals` exists in the engine; no tool appears to expose it
- **Squad-relative** — "who do I sell", needs the squad as context rather than as a filter
- **Trajectory** — form rising vs. falling; impossible now, central once the season runs

Recommend two or three more passes before freezing the query-layer design, so it
falls out of real cases rather than intuition.

---

## Open questions

- Does the LLM orchestrator, with today's tool set, get further than the
  deterministic path on this question? Untested. Estimate is partial — it could
  assemble the fixture table and a ppg ranking, but stays blind on price,
  rates, budget, formation and club limits. **Worth actually running** rather
  than assuming; note the local orchestrator failure logged separately may block
  testing it locally.
- Whether `derive_role_signals` (penalties, free kicks) reaches any user-facing
  surface at all, or is computed and discarded.
- Whether the buried-judgement pattern in finding-shape above appears in other
  answer-shaped tools beyond `chip_advisor` and `transfer_suggestion`.

---
title: "«¿quién es el mejor jugador del Newcastle?» — respuesta de equipo sin tarjeta, con dos etiquetas falsas y sin la GW1"
found_via: user noticed the answer was a Newcastle team dump instead of an answer to the question, and that it rendered as plain text with no specific card
captured: 2026-08-12
relevant_to: [contracts, ui, gw-resolution, data-quality, preseason, orchestrator]
status: new
---

## What prompted this

Live query in the V2 UI (Spanish): **«¿quién es el mejor jugador del Newcastle?»**

The reply was the `get_team_snapshot` plain-text dump inside a generic
orchestrator bubble (`IA ACTIVA` pill, "Seguir conversación →"), not a card:

```
**Newcastle (NEW)** — racha media (FDR medio: 2.6)
  Próximos partidos:
    GW2: TOT (V) FDR 3
    GW3: BOU (L) FDR 3
    GW4: LEE (V) FDR 3
    GW5: HUL (L) FDR 2
    GW6: COV (V) FDR 2
  Mejores jugadores (por puntos):
    Thiaw (DEF) — 126pts | forma 0.0 | £5.0m
    Woltemade (FWD) — 108pts | forma 0.0 | £6.0m
    Barnes (MID) — 106pts | forma 0.0 | £6.0m
    Pope (GKP) — 96pts | forma 0.0 | £5.0m
    Burn (DEF) — 93pts | forma 0.0 | £5.0m
  Máximo goleador: Thiaw | Mejor forma: Thiaw
```

Two user-visible complaints (no card; answered *about* Newcastle rather than
*the question*) turned out to sit on top of three further defects visible in
that same screenshot.

Live bootstrap re-fetched 2026-08-12 for every number below.

---

## Findings

### 1. Card coverage is gated by `_TOOL_TO_INTENT`, and 13 orchestrator-callable tools are not in it — severity: med

**What happens:** any tool the orchestrator can pick but that has no entry in
`_TOOL_TO_INTENT` resolves to `intent = INTENT_UNSUPPORTED`. No structured
metadata is projected, `build_generic_card` has no branch, so the UI gets
`answer_text` only. The tool ran fine (`outcome="ok"`, `supported=True`) — the
card is simply unreachable. There is no warning anywhere that adding a tool
without a map entry silently costs it its card.

**Evidence:** `get_team_snapshot` is registered in `tool_schema_registry.py:790`
and rendered at `renderer.py:1423`, but absent from the map at
`dispatcher.py:177-203`. Tools in the schema registry with no intent mapping:

```
find_players            get_gameweek_context     get_tactical_role
get_expected_minutes    get_player_history       get_team_snapshot
get_fixture_context     get_player_intelligence  get_zonal_weakness
get_fixtures_for_gw     get_player_zonal_outlook rank_players_by_metric
                                                 web_fetch
```

(`search_web` is also unmapped but deliberately — it has its own carve-out at
`harness_adapter.py:193-208`.)

**Where:** [dispatcher.py:177](../packages/fpl-grounded-assistant/fpl_grounded_assistant/dispatcher.py#L177),
[harness_adapter.py:228](../packages/fpl-grounded-assistant/fpl_grounded_assistant/harness_adapter.py#L228),
[generic_card.py:476](../packages/fpl-grounded-assistant/fpl_grounded_assistant/generic_card.py#L476)

**Why it happens:** the map was built for the deterministic classifier's
intents. Tools added later for the orchestrator to call were registered in the
tool registry + renderer, but the map was never treated as a required step.

**Fix direction:** make the coupling explicit rather than adding one more entry.
Either derive the map from the schema registry with an explicit
`card: none` opt-out per tool, or add a test that fails when a registered tool
is neither mapped nor listed in an intentional-exclusion set.

Note this is the same shape as the `get_player_snapshot` renderer asymmetry in
[2026-08-09](2026-08-09-user-armado-dogfooding.md) — that one *is* mapped but
still has no card composer, so the two failures need one combined answer.

---

### 2. «Máximo goleador» is not the top scorer of goals — severity: high

**What happens:** the footer prints `summary.top_scorer_web_name`, which is
`top_players[0]` after sorting by **total_points**, under the Spanish label
*máximo goleador* (top goalscorer). The two are different players and the card
states the wrong one as fact.

**Evidence (live, 2026-08-12):** Newcastle by goals scored last season —
Woltemade **8**, Barnes **7**, Thiaw **4**. The card says *Máximo goleador:
Thiaw*, and Woltemade is listed right below him on the same card with a higher
goal count not shown. A user reading only the footer gets a false statement.

**Where:** [renderer.py:1049](../packages/fpl-grounded-assistant/fpl_grounded_assistant/renderer.py#L1049),
field built at [get_team_snapshot.py:350](../packages/fpl-grounded-assistant/fpl_grounded_assistant/get_team_snapshot.py#L350)

**Why it happens:** the field name `top_scorer_web_name` means "top points
scorer"; the Spanish translation read it as goals.

**Fix direction:** relabel to *Máximo anotador de puntos* / *Más puntos*, or
compute a real `top_goals_web_name` from `goals_scored` and print both. The
label is cheaper and correct; the extra field is what the question usually
means.

---

### 3. «Mejor forma» degenerates to "first by points" when every form is 0.0 — severity: med

**What happens:** `sorted(top_players, key=-form)` over an all-zero list is
stable, so it returns `top_players[0]` — the top points scorer — and the card
presents it as a distinct finding. Hence *Máximo goleador: Thiaw | Mejor forma:
Thiaw*: one player, two labels, neither computed.

**Evidence:** all 5 listed Newcastle players read `form 0.0` live (all 20+
squad members do; the season has not started).

**Where:** [get_team_snapshot.py:353](../packages/fpl-grounded-assistant/fpl_grounded_assistant/get_team_snapshot.py#L353)

**Fix direction:** when the max form is 0, omit the field (or emit
`top_form_web_name: None`) and have the renderer drop the segment rather than
print a meaningless winner. Same class as the `form=0` blind engine in
[2026-08-05](2026-08-05-preseason-gaps.md).

---

### 4. GW1 is missing from «Próximos partidos» — severity: high

**What happens:** the card lists GW2–GW6 as the upcoming run. GW1 has not been
played — its deadline is **2026-08-21**, nine days after this query. The single
most decision-relevant fixture is dropped, and `avg_fdr_next_5` (2.6, driving
the *racha media* verdict) is computed over GW2–GW6 instead of GW1–GW5.

**Evidence (live, 2026-08-12):**

```
GW1: is_current=False  is_next=True  finished=False  deadline 2026-08-21T17:30:00Z
```

No event has `is_current` and none has `finished`.
`_current_gw_from_events` checks `is_current` → none; then `finished` → none;
then falls back to `min(event id)` = **1**. `_build_upcoming_fixtures` then
starts its scan at `current_gw + 1` = **2**.

**Where:** [get_team_snapshot.py:108-121](../packages/fpl-grounded-assistant/fpl_grounded_assistant/get_team_snapshot.py#L108-L121)
and [get_team_snapshot.py:286](../packages/fpl-grounded-assistant/fpl_grounded_assistant/get_team_snapshot.py#L286)

**Why it happens:** the resolver never consults `is_next`. Its pre-season
fallback returns the first GW as if it had already been played, and the caller's
`+1` then skips it. This is another instance of the half-migrated GW resolver
noted in [2026-08-05](2026-08-05-preseason-gaps.md) and of the duplicate-resolver
backlog — this tool has its own private copy.

**Fix direction:** consult `is_next` before the min-id fallback and return a
"first unplayed GW" rather than a "current GW", so callers do not have to add 1.
Best folded into the resolver consolidation rather than patched here — a local
patch adds a tenth private implementation.

---

### 5. Last-season totals are presented as current with no disclosure — severity: high

**What happens:** `126pts`, `108pts`, `£5.0m` are printed with no time frame.
Before a ball is kicked in 2026-27 these are **2025-26** totals, and nothing on
the card says so. Combined with `forma 0.0` the card reads as "a season is
underway and nobody is in form".

**Evidence (live, 2026-08-12):** Thiaw shows `total_points=126` with
`minutes=2963` — a full previous season — while no 2026-27 event has started.

**Where:** [renderer.py:1039-1046](../packages/fpl-grounded-assistant/fpl_grounded_assistant/renderer.py#L1039-L1046)

**Why it happens:** upstream carries prior-season aggregates until GW1 data
lands; the renderer passes them through unlabelled.

**Fix direction:** when no GW has finished, label the block *(temporada
2025-26)*. This is the degradation-disclosure gap from
[2026-08-06](2026-08-06-query-primitives-gap.md) with a concrete user-facing
instance. It also carries the club-change trap named there — these points were
earned at whatever club the player was at last season.

---

### 6. The question was never answered — a team overview stood in for it — severity: med

**What happens:** «¿quién es el mejor jugador del Newcastle?» is a
single-entity question. The reply contains no sentence naming a best player;
it is a team dump the reader must reduce themselves. The two labels that *do*
attempt an answer are both wrong (findings 2 and 3).

**Evidence:** `get_team_snapshot`'s own docstring names this exact query class
as the one it was built for — *"quien es el mejor jugador de wolves?"*
([get_team_snapshot.py:7](../packages/fpl-grounded-assistant/fpl_grounded_assistant/get_team_snapshot.py#L7))
— so the routing is working as designed. The design assumed the LLM would read
the snapshot and compose an answer; in the observed turn the rendered tool text
was surfaced verbatim instead.

**Why it happens:** the tool is answer-shaped for a *different* question
("tell me about Newcastle"). "Best player" needs a ranking with a stated
criterion, which `rank_players_by_metric` could serve — except it has no team
filter and is itself unmapped (finding 1).

**Fix direction:** two candidates, and this note does not pick between them —
(a) add a team filter to `rank_players_by_metric` and let the superlative route
there, or (b) keep the snapshot and require a lead sentence that answers the
superlative on a stated criterion. Option (a) is the query-primitive direction
argued in [2026-08-06](2026-08-06-query-primitives-gap.md); option (b) bakes
another judgement into an answer-shaped tool, which that note argues against.

---

## Open questions

*Hunches, not findings.*

- Whether the verbatim tool text is the intended orchestrator behaviour for
  unmapped tools or a fallback that fired because the answer synthesis step was
  skipped. Not traced — the local orchestrator failure logged in memory blocks
  reproducing the turn locally.
- Whether findings 2–5 also reach users through the `/equipo`-style
  deterministic surfaces, or only through the orchestrator path.
- How many of the 13 unmapped tools are actually reachable in production —
  the count is from the schema registry, not from traffic.

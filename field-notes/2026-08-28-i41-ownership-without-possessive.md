# i41 — `get_my_squad` did not fire on ownership expressed without a possessive

**2026-08-28.** Base `20db558`. Provider/model passed explicitly:
`openai` / `gpt-5.6-luna`. Team connected (`_my_team_id=1`) for every call.
Total spend $0.367 across 84 calls.

## The defect

After i39 (PR #167) gave `get_my_squad` to ten of the twelve squad-building
turns that previously had no tool, two stayed at **no tool 5/5 even with a team
connected**:

```
sb-02  "Necesito 4 medios que me permita el presupuesto, ya tengo el resto del equipo armado."
sb-13  "Necesito dos delanteros y un defensa que me entren en el presupuesto que me queda
        después de estas ventas."
```

Neither says *mi equipo* or *mi plantilla*. They express ownership **without a
possessive** — "el resto del equipo", "el presupuesto que me queda", "estas
ventas". The description enumerated literal trigger phrases (`'mi equipo'`,
`'mi plantilla'`, `'mis suplentes'`, `'evalúa mi equipo'`) and neither question
matched any of them.

## Decision rule, written before any call was made

Recorded in the brief and encoded in
`scripts/measure_i41_ownership_triggers.py` before the first measurement, so it
could not be adjusted after seeing results:

| | criterion |
|---|---|
| **Target** | `sb-02` ≥ 4/5 and `sb-13` ≥ 4/5 calls to `get_my_squad` |
| **Guard** | `neg-defensas`, `neg-comparar`, `neg-jornada` each **0/5** |
| **Observation, no gate** | `ad-05` reported, never used as a criterion |

**The guard outranks the target.** One over-fire rejects the change even at 5/5
on both targets: a false fire injects someone's squad into a general question,
dirtying the context, costing more, and potentially biasing the answer. Failing
to call is cheaper than calling wrongly.

## Result

6 questions × 5 reps, `team_connected`, before and after the change. 0
exceptions in either run.

```
                     PRE          POST
sb-02   (target)     0/5   -->    5/5     no-tool 5/5 -> 0/5
sb-13   (target)     0/5   -->    5/5     no-tool 5/5 -> 0/5

neg-defensas (guard) 0/5   -->    0/5
neg-comparar (guard) 0/5   -->    0/5
neg-jornada  (guard) 0/5   -->    0/5

ad-05   (observe)    1/5   -->    2/5     no-tool 2/5 -> 2/5
```

**ACCEPT** — guard held, both targets reached.

## What fires now that did not before

Widening a trigger obliges an audit of what it newly reaches, not just a check
that the target finally fires — a count that goes up does not rule out a
regression. Full tool-sequence diff, pre vs post:

| question | pre | post |
|---|---|---|
| `sb-02` | 5× no tool | 5× `get_my_squad` |
| `sb-13` | 5× no tool | 5× `get_my_squad` |
| `neg-defensas` | 5× `rank_players_by_metric` | 4× `rank_players_by_metric`, 1× `get_transfer_suggestion` |
| `neg-comparar` | 5× `compare_players` | 5× `compare_players` |
| `neg-jornada` | 3× `get_gameweek_context`, 2× `get_current_gameweek` | 5× `get_gameweek_context` |

`neg-defensas` and `neg-jornada` moved, but **within their own acceptable-tool
sets** — not over-fires, and `neg-jornada` was already split 3/2 across two
acceptable tools before the change, so run-to-run variation is the simpler
explanation than an effect of a description this question never sees matched.
The only genuinely new tool anywhere is `get_my_squad` on the two targets.

### Wider over-fire audit

The pre-registered guard is 15 negative calls; the asset being protected is PR
#171's *0 over-fires in 30 negative calls*, so the audit was extended by 8
further questions × 3 reps, observation-only, in
`scripts/measure_i41_overfire_audit.py`. Chosen to stress the specific wording
that was added rather than to pad the count:

* `tf-09`, `pv-09` open with **"Necesito saber…"** — the new description names
  *"necesito 4 medios"* as a trigger, so an over-generalisation on the verb
  alone would surface here first.
* `pv-01` asks about a player's **ownership** — a possession word pointing at
  the market, not the user.
* `pv-10` asks about **injury availability**, a field this tool returns.

```
tf-09 0/3   pv-09 0/3   pv-01 0/3   pv-10 0/3
tf-02 0/3   pv-13 0/3   cp-01 0/3   tf-12 0/3
total over-fires: 0/24
```

**0 over-fires across 39 negative calls** (15 gate + 24 audit), above the 30
that #171 established.

## The change

One description, `GET_MY_SQUAD_SCHEMA` in `tool_schema_registry.py` — verified
to be the definition that actually reaches the model (`orchestrator.py:859`
serialises `_ALL_SCHEMAS`; the `ToolSpec` in `get_my_squad.py` is execution-side
only). No system prompt, router or other tool description touched.

Adding four more literal phrases would have failed on the fifth phrasing, so
the description now **names the condition**: call it when answering correctly
requires knowing what the user already owns, with or without a possessive. The
second half is load-bearing and is what held the guard — it states explicitly
what does *not* trigger it (general market question, player comparison,
gameweek state), with the three guard questions as the counter-examples. Two
tests pin both halves; the negative one carries the instruction to re-measure
before trusting the trigger is bounded if it is ever trimmed.

## `ad-05`, reported not gated

*"¿Me conviene hacer un transfer esta semana o mejor guardo el chip?"* went 1/5
→ 2/5 on `get_my_squad`, no-tool flat at 2/5. Underdetermined between two advice
tools since before `get_my_squad` existed, and one question at five reps
separates nothing. Not evidence for or against this change; a fix, if wanted, is
a separate card.

## Reviewer probe — the gap this audit missed

Run independently by the reviewer on the PR head, not by the author. Recorded
here because it is the measurement that found the hole in the audit above, and
leaving it outside the repo while the author's own 84 observations sit in
`artifacts/` would archive the weaker half of the evidence.

**The gap.** The over-fire audit stressed the *verb* the new wording
generalises ("Necesito saber…"), but not the **literal noun phrases written
into the description itself** — `'necesito 4 medios'`, `'dos delanteros y un
defensa'`. Those carry no ownership on their own; in sb-02 and sb-13 the
ownership comes from the surrounding clause. So the audit was aimed at the risk
that was imagined rather than the one the new text most directly created. The
right negative is the quoted phrase with the ownership stripped out of the rest
of the sentence — which is what "desde cero" does below.

Same conditions as the gate: `gpt-5.6-luna`, provider passed explicitly,
`_my_team_id` injected the same way. `max_tokens=2048`.

| id | question | per-rep tool |
|---|---|---|
| `g1` | "Necesito 4 medios baratos para armar un equipo desde cero." | `select_players_within_budget` · **no tool** · `select_players_within_budget` |
| `g2` | "Estoy armando un equipo nuevo desde cero. Necesito dos delanteros y un defensa que entren en 20 millones." | `select_players_within_budget` ×3 |
| `g3` | positive control, sb-02 verbatim | `get_my_squad` ×3 |

```
get_my_squad on g1+g2:  0/6
positive control g3:    3/3
```

The trigger held even where the positive phrasing matches word for word, and
the two negatives routed to `select_players_within_budget`, which is the right
tool for them. The negative half of the description is what did that work.
**Combined with the gate and the author's audit: 0 over-fires across 45
negative calls**, against the 30 that PR #171 established.

Two observations alongside, both data rather than decoration:

* `g1` rep 1 called **no tool at all**. That is i40 territory (a turn no tool
  serves), not this card's, and it is the same question class the gate scores
  as a *negative* — so it costs nothing here, but it is a real no-tool turn.
* **Three of these nine calls hit the empty-synthesis bug** — the tool ran and
  the synthesis turn returned no text, so the raw tool output was rendered.
  Now tracked as board card **i46**. It surfaced sideways, out of a measurement
  aimed at something else, which is part of the argument for the fixed golden
  battery (**i25**): a standing suite would have been counting
  `synthesis_turn=False` all along instead of waiting for it to fall out of an
  unrelated probe.

Raw JSONL is not archived for these nine: they were run outside the author's
harness, so token counts, latency and cost were never captured in the same
shape. The per-rep tool choices above are the full record — no reconstructed
rows, because inventing the missing fields to match the other artifacts would
make them look like the same instrument.

## Artifacts

`field-notes/artifacts/i41-ownership-triggers-{pre,post}-2026-08-28.jsonl`
(30 rows each), `i41-overfire-audit-2026-08-28.jsonl` (24 rows). Every row
carries the question, tool sequence, outcome, token counts and cost.

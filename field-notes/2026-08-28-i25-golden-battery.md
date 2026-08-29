# i25 — golden battery: a fixed acceptance run for "can this model ship?"

**2026-08-28/29.** Base `ca23280`. Reference row against `gpt-5.6-luna`, tier
`controls`: 70 distinct cases × 3 reps = **210 calls, 0 exceptions, ~$1.01 per
run**. Three runs were made and all three are archived — superseded rows are
kept, not deleted, because a before/after pair across an instrument correction
is information, and because the third run is what showed that two readings taken
from the first two were wrong.

## Why fixed rather than improvised

The apparatus was rebuilt four times in one week and **three times the
instrument was the bug**: a `.get(...) or ''` that manufactured empty turns, a
hash script that compared two tracebacks and reported "IDENTICAL", and a probe
that read `minutes` instead of `minutes_played_season` and reported every row as
zero. **A fourth was written while building this battery** (see below), which is
the strongest argument for the card there is.

The sharper argument came out of i41: i46 was found **sideways**, three of nine
calls in a measurement aimed at something else. Without a standing battery,
finding a defect depends on somebody measuring something adjacent by luck, and
that does not scale with the number of tools.

## The blocking finding: the corpus expires and nothing says so

Noticed by reading one case — `pv-11` asks about Gordon, who left in this
window. Nine of the 90 corpus questions name entities that no longer resolve,
concentrated in captaincy (4 of 12).

**Staleness does not merely lose a case, it manufactures findings.** The first
reference row reported `pv-11` failing synthesis 3/3 and called it a
deterministic reproduction of i46. It was not: there was nothing to synthesise,
because `get_player_snapshot('Gordon')` returns `not_found`. And the reason it
*looked* like a repro is instructive — a stale case fails **deterministically**,
which is exactly the signature a real reproduction has.

The fix is the check, not a patch of today's names, which buys nothing because
this degrades again every window. `scripts/golden_preflight.py` resolves every
pinned player and team against the bootstrap **offline, before a cent is spent**,
and aborts (exit 4) naming the expired cases. `--allow-stale` proceeds while
**excluding them from scoring with the reason recorded**, and both denominators
are reported.

The questions are deliberately **not** rewritten here: #171, i38 and i41 were
scored against that exact text, and changing it in the commit that records a
reference row would mix two things. Substitution is separate work.

**The check found six cases a manual audit missed:** `Palmer` now returns **two
exact matches**, so `ad-01`, `ad-11`, `cp-06`, `cp-11`, `pv-04` and `pv-06` no
longer measure what they were written to measure either — nobody left, but the
name stopped identifying one player.

**Two exemptions, both deliberate:**

* The **over-fire guard is not stale-sensitive** (`stale_sensitive=False`).
  `neg-comparar` names Salah and no longer measures "a comparison of two current
  players", but it is still a question that must not pull the user's squad, so
  it still counts as a guard. Excluding it would silently shrink the very
  zero-fire record being protected (i41: 0 in 45). The guard scores 0/33, not
  0/27.
* Stale cases are still **called**, only excluded at scoring, so the raw
  denominator survives in the JSONL and a fixed question can be re-scored later
  without paying again.

## A fourth instrument bug, written inside the tool meant to prevent them

The first preflight filtered matches with `(m.get("match_rank") or 99) <= 1`.
**`match_rank` 0 is the exact match and is falsy**, so the idiom discarded every
exact hit and reported Haaland — and every live player — as departed. It was
caught only because the output was absurd on its face.

Pinned by `test_an_exact_match_is_not_discarded_by_a_falsy_zero_rank`, named
after the bug so it cannot come back quietly.

## `invented_metric_relay` — loosened, then briefly over-tightened, then reverted

**The gate is i15's decided criterion:** no gameweek tool *answers* a question
about a metric that does not exist. Reference 0/10, verified and settled. The
answering tool is the last one called, not `tool_chosen`, which is the primary.
That part is a genuine loosening of the original "no gameweek tool anywhere in
the sequence", justified by i15's own note of 2026-08-26 — which recorded that
reading before this battery existed, not by the run it failed.

**A stricter gate was held briefly and reverted.** It required the relay to have
*happened* (a call, plus `unknown_metric` in the trace) and put luna at 9/15.
Reverting it is not fitting the instrument to the result, and the reason matters
more than the number: *"the model must refuse rather than reinterpret"* is a
**product policy nobody had decided**, and a gate encodes decided policy — it
does not invent it. It is now card **i48**.

Reading the answers rather than the counts is what exposed it. Three different
behaviours were collapsed into one failing number, and only the last is a defect:

| behaviour | what the model actually said |
|---|---|
| declared reinterpretation | *"Si por «hambre de gol» entendemos el xG acumulado, el líder es Haaland: 25,5 xG, 2.953 minutos…"* — names the substitution, in the user's language, and grounds it |
| clarification requested | *"¿Te refieres a quién es el mejor capitán esta jornada? Dime 2–5 jugadores y los comparo."* |
| **silent adoption** | *"La mejor vibra esta fecha: Haaland 🧢"* with scores, adopting an invented metric as if it existed — over a candidate list pulled from memory, Salah included, who is not in the dataset |

Only the third is the fluent-lie class. The first two are good behaviour that the
stricter gate was failing.

**So the split is reported every run and gates nothing.** The strict figure is
not discarded — it is the companion, beside the gated one, the same double-count
discipline used elsewhere. The declared/silent split is the one thing here that
cannot be read from the trace, so it uses documented cues over the answer text:
acceptable for a reported number, explicitly **not** acceptable for a gate. Every
answer is archived in the JSONL so any classification can be re-derived. A turn
with no synthesis gets its own bucket rather than being scored as silent
adoption — counting a raw dump as model behaviour would attribute i46 to the
model.

### The finding that survives the revert

On *"¿Quién tiene más hambre de gol esta temporada?"* the model rewrote the
invented metric, emitting `metric='goles esta temporada'`, which resolves to
`goals_scored`.

**That path was opened by our own i18 work.** `goles` was not an alias before PR
#181; today `goles esta temporada` resolves by token containment. `hambre de gol`
itself still correctly refuses — the change is on the *paraphrase* path, where a
broader alias map lets the model's rewrite succeed where it used to fail. This is
[[feedback_relaxation_can_hide_failure]] in a direction neither of us audited:
what newly resolves was checked for the *field* being right, not for whether it
should have been **refused** as invented. Whether that is a defect or better UX is
precisely what i48 decides — recorded here as a mechanism, not as a verdict.

## `synthesis_present` is ours, not the model's

It fails on i46. While i46 is open every candidate fails it identically, and a
gate that rejects everyone stops discriminating — the first thing that happens
when Sonnet fails it the same way in i22 is that someone starts ignoring the
verdict. Not removed and not lowered; the axis carries `blocked_by="i46"` and
the verdict separates the lines:

```
REJECT — 0 model axes; 1 blocked (synthesis_present blocked by i46).
```

## Reference row — `gpt-5.6-luna`, controls tier, run 3 (2026-08-29)

| axis | kind | result | threshold | verdict |
|---|---|---|---|---|
| routing | target | 103/117 (88%) | >= 80% | PASS |
| metric_resolution | target | 30/30 (100%) | >= 95% | PASS |
| invented_metric_relay | target | 15/15 (100%) · companion (strict) 9/15 (60%) | = 100% | PASS |
| order_direction | target | 12/12 (100%) | = 100% | PASS |
| ownership_no_possessive | target | 6/6 (100%) | >= 80% | PASS |
| overfire_guards | **guard** | 0/33 fires | <= 0 | PASS |
| synthesis_present | target | 170/183 (93%) | = 100% | **FAIL (i46)** |

```
REJECT — 1 blocked (synthesis_present blocked by i46).
```

**Zero model axes fail.** On every axis whose policy is actually settled, luna
passes; the only thing between it and an ACCEPT is a defect of ours. That says
considerably more than the previous `REJECT — 1 model axis; 1 blocked`, which
was an artefact of a gate encoding an undecided policy.

Three runs are archived: `-2026-08-28-SUPERSEDED` (instrument had no preflight
and a mis-specified relay gate), `-2026-08-29-r2-SUPERSEDED` (gate since
reverted), `-2026-08-29-REFERENCE` (this row).

### The behaviour breakdown, three runs — and why it is not yet a decision

Reported every run, gating nothing. Feeds card **i48**.

| behaviour | r1 | r2 | r3 |
|---|---|---|---|
| clean relay | 9 | 9 | 9 |
| declared reinterpretation | 1 | 3 | 1 |
| clarification requested | 1 | 1 | 1 |
| **silent adoption** | 2 | 2 | 3 |
| no synthesis (i46) | 2 | 0 | 1 |

The totals look stable. The per-turn detail says otherwise:

| turn | r1 | r2 | r3 |
|---|---|---|---|
| gi-02 rep0 | declared | declared | **silent** |
| gi-02 rep1 | clarify | declared | clarify |
| gi-02 rep2 | **silent** | declared | declared |
| gi-03 rep0 | no-synth | clarify | no-synth |
| gi-03 rep1 | **silent** | **silent** | **silent** |
| gi-03 rep2 | no-synth | **silent** | **silent** |

**Five of six turns changed behaviour across the three runs.** Two readings that
looked reasonable on two runs do not survive the third, and both are corrected
here because i48 would otherwise start from them:

* *"Silent adoption is 2 in both runs — gi-03 rep1 and rep2, stable."* The
  **count** repeats; the **composition** does not. In r1 it is `gi-02 rep2` +
  `gi-03 rep1`; `gi-03 rep2` was a raw dump, not an adoption. And r3 moves it to
  3.
* *"Declared 1 → 3 is explained by r1's two no-synthesis turns."* Those two were
  in `gi-03`, while the movement was in `gi-02`, whose three reps all declared in
  r2 and then split again in r3. Different questions entirely.

**What actually holds:** `clean relay` is rock solid at 9/9/9 — `gi-01`, `gi-04`
and `gi-05` relay every time, including the two deliberate gameweek baits. All
the variance lives in `gi-02` and `gi-03`, the two vaguest phrasings. The one
genuinely stable case is **`gi-03 rep1`, silent adoption in all three runs** —
that is i48's usable repro.

So the honest input to i48 is not "silent adoption is stable at 2". It is: the
behaviour is **not stable per turn at 3 reps**, and a product policy should not
be decided on 6 observations per question. i48 should start by asking for more
reps on `gi-02`/`gi-03`, not by settling the question with what is here.

### i46, three runs

| | r1 | r2 | r3 |
|---|---|---|---|
| raw failures / tool turns | 11/205 | 12/206 | 19/205 |
| **clean** (stale excluded) | 7/178 (3.9%) | 8/179 (4.5%) | 13/178 (7.3%) |

Combined clean rate **28/535 = 5.2%**, with real run-to-run spread — r3 is
almost double r1, which is itself an argument for a standing battery over a
one-off probe.

**`gw-04` is confirmed as the repro at 6/9 across three runs** — *"¿Qué fecha es
la próxima y cuándo cierra el mercado de fichajes?"*, on clean data, 2/3 in
every run. Next best are `gi-03`, `sb-02`, `cvg-09` and `cp-12` at 3/9, and
`cp-12` is worth a look on its own: 0/3, 0/3, then **3/3 in r3**, which is either
a new regression or evidence that 3 reps is too few to tell. The confounded set
(`pv-11` ×3, `cp-03` ×1) is identical in all three runs, because a missing
entity fails deterministically — which is exactly why it impersonated a repro.

## Corrections to the brief, and one of my own

* **The 8 direction cases do not exist** as 8 questions — 4 distinct, now all
  wired: the three from `probe_direction.json` plus the xGC one. It shares the
  id `gm-04` with the metric axis on purpose, so one call is scored twice
  (resolved field *and* applied direction).
* **Tier sizes:** `controls` = 70 distinct cases → **210 calls**; `full` = 111 →
  **333**. The ~140/~270 estimate counted the routing axis alone.
* **A threshold of mine was looser than its own reference.**
  `metric_resolution` at 0.90 against a 96% reference let an entirely broken
  case out of ten pass. Raised to 0.95 — from a synthetic mutation **before the
  first live call**, with the reason beside the number.
* **The routing corpus does not know `get_my_squad`** (zero mentions) and its
  stale `sb-02`/`sb-13` labels would score i41's shipped behaviour as a routing
  regression. Patched in `golden_axes`, **not** in the corpus, so #171, i38 and
  i41 keep their meaning.

## Verification

**54 battery + preflight tests**, no credentials, no network — `golden_axes` and
`golden_preflight` hold no I/O, which is what lets CI run them while the battery
that spends money stays off CI. 13 are mutations that must be rejected: wrong
tool, no tool, missing `order`, metric resolved to the wrong field while
`status=ok`, invented metric answered from a gameweek tool, missing synthesis
turn, and a negative control firing. Others pin the asymmetries: one over-fire
rejects the model **even with every target passing**; a guard's zero ceiling
cannot be met by averaging; a stale case is counted neither as a pass nor a
failure; the guard is not shrunk by staleness; a blocked axis is named
separately in the verdict.

Package suite **1506 passed / 1 skipped**.

## Artifacts

`golden-battery-gpt-5.6-luna-controls-2026-08-29.{jsonl,md}` — the current
reference row. `…-2026-08-28-SUPERSEDED.{jsonl,md}` — the first row, kept with a
banner explaining what its instrument got wrong.

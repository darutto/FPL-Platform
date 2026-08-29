# i25 — golden battery: a fixed acceptance run for "can this model ship?"

**2026-08-28/29.** Base `ca23280`. Reference row against `gpt-5.6-luna`, tier
`controls`: 70 distinct cases × 3 reps = **210 calls, 0 exceptions, $1.01**.

Two rows are archived. The first is kept and marked **SUPERSEDED** rather than
deleted: a before/after pair across an instrument correction is information, not
rubbish, and the corrections below are most legible against it.

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

## `invented_metric_relay`, changed in both directions at once

Changed together in one commit, so this is not a loosening taken alone after
seeing what made it fail.

**Loosened** (reported, not gated): from "no gameweek tool anywhere in the
sequence" to "no gameweek tool **answered**" — the answering tool being the last
one called, not `tool_chosen`, which is the primary. Justified by i15's own note
of 2026-08-26, which recorded that reading before this battery existed.

**Tightened** (the gate): the relay must have **happened** — at least one call
*and* `unknown_metric` present in the trace.

The tightening caught more than expected. It is not only `gi-02` answering from
memory in 1 of 3 reps:

> On *"¿Quién tiene más hambre de gol esta temporada?"* the model **rewrote the
> invented metric**, emitting `metric='goles esta temporada'`, which resolves to
> `goals_scored`. The tool returned `status=ok` and the user got a top-scorers
> list without ever learning that "hambre de gol" is not a metric.

**That path was opened by our own i18 work.** `goles` was not an alias before PR
#181; today `goles esta temporada` resolves by token containment. `hambre de
gol` itself still correctly refuses — the regression is on the *paraphrase*
path, where a broader alias map lets the model's rewrite succeed where it used
to fail. This is [[feedback_relaxation_can_hide_failure]] biting in a direction
neither of us audited: what newly resolves was checked for the *field* being
right, not for whether it should have been **refused** as an invented metric.

Thresholds now come from the figure each check actually measures: the gate from
i15's relay rate (8/10 = 80%), the companion from i15's gameweek-fallback rate
(0/10 = 100%). They are different quantities and were previously conflated under
one 100% bar.

## `synthesis_present` is ours, not the model's

It fails on i46. While i46 is open every candidate fails it identically, and a
gate that rejects everyone stops discriminating — the first thing that happens
when Sonnet fails it the same way in i22 is that someone starts ignoring the
verdict. Not removed and not lowered; the axis carries `blocked_by="i46"` and
the verdict separates the lines:

```
REJECT — 1 model axis (invented_metric_relay); 1 blocked (synthesis_present blocked by i46).
```

## Reference row — `gpt-5.6-luna`, controls tier, 2026-08-29

| axis | kind | result | threshold | verdict |
|---|---|---|---|---|
| routing | target | 105/117 (90%) | >= 80% | PASS |
| metric_resolution | target | 29/30 (97%) | >= 95% | PASS |
| invented_metric_relay | target | **9/15 (60%)** · companion 15/15 (100%) | >= 80% | **FAIL** |
| order_direction | target | 12/12 (100%) | = 100% | PASS |
| ownership_no_possessive | target | 6/6 (100%) | >= 80% | PASS |
| overfire_guards | **guard** | 0/33 fires | <= 0 | PASS |
| synthesis_present | target | 175/183 (96%) | = 100% | **FAIL (i46)** |

9 stale cases excluded, 0 exceptions, $1.01.

### i46, corrected

The first row said 5.2%. Corrected:

| | run 1 | run 2 |
|---|---|---|
| raw failures / tool turns | 11/210 (5.2%) | 12/206 (5.8%) |
| **clean** (stale excluded) | **7/183 (3.8%)** | **8/183 (4.4%)** |
| confounded | pv-11 ×3, cp-03 ×1 | pv-11 ×3, cp-03 ×1 |

Combined clean rate **15/366 = 4.1%**. The confounded set is **identical across
both runs**, because a missing player fails deterministically — which is why it
impersonated a reproduction.

**The real reproducible case is `gw-04`, not `pv-11`:** *"¿Qué fecha es la
próxima y cuándo cierra el mercado de fichajes?"* fails **2/3 in both runs**, on
clean data. Every other clean failure scatters between 0 and 2 of 3, consistent
with a ~4% stochastic rate. `gw-04` is the lead i46 should start from.

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

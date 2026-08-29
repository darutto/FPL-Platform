# i25 — golden battery: a fixed acceptance run for "can this model ship?"

**2026-08-28.** Base `ca23280`. First reference row recorded against
`gpt-5.6-luna`, tier `controls`: 70 distinct cases × 3 reps = **210 calls, 0
exceptions, $1.01**.

## Why fixed rather than improvised

The apparatus was rebuilt four times in one week and **three times the
instrument was the bug**: a `.get(...) or ''` that manufactured empty turns that
never happened, a hash script that compared two tracebacks and reported
"IDENTICAL", and a probe that read `minutes` instead of `minutes_played_season`
and reported every row as zero.

The sharper argument came out of i41. The empty-synthesis defect (i46) was found
**sideways** — three of nine calls in a measurement aimed at something else.
Without a standing battery, the chance of finding a defect depends on somebody
happening to measure something adjacent, and that does not scale with the number
of tools. This run is the demonstration: it put a rate and a reproducible case
on i46 without anyone going looking.

## What was built

No new corpus. `tool_routing_corpus` (90 labelled cases, 47 control),
`measure_tool_routing.run_one`, the `_my_team_id` injection and the
pre-registered-rule-inside-the-script pattern from i41 are reused as they stand.
The work is the runner, the assertions and the report.

* `scripts/golden_axes.py` — cases, assertions, thresholds. **No I/O**, which is
  what lets CI test the battery while the battery itself stays off CI.
* `scripts/golden_battery.py` — running and reporting only. Adding an axis (i32)
  never touches it.
* `tests/test_golden_battery.py` — 23 tests, 13 of them mutations.

`run_one` was extended **additively** (`tool_args`, resolved metric/status/order,
`synthesis_turn`) rather than forked, so a golden row and a one-off measurement
stay directly comparable. Forking it would have re-created the exact failure
mode this card exists to remove.

Guarantees the runner enforces, each from a failure already paid for: provider
and model **asserted** against every `fpl_provider_event` and aborting on
mismatch; bootstrap pinned by sha256 in the report header with model,
`max_tokens`, temperature and reps; cost estimated and confirmed before
spending; **exceptions invalidate the run** rather than being averaged over;
cases deduplicated across axes so a question in two axes is called once and
scored twice.

## Reference row — `gpt-5.6-luna`, controls tier

| axis | kind | result | threshold | verdict |
|---|---|---|---|---|
| routing | target | 129/141 (91%) | >= 80% | PASS |
| metric_resolution | target | 30/30 (100%) | >= 95% | PASS |
| invented_metric_relay | target | 14/15 (93%) | = 100% | **FAIL** |
| order_direction | target | 9/9 (100%) | = 100% | PASS |
| ownership_no_possessive | target | 6/6 (100%) | >= 80% | PASS |
| overfire_guards | **guard** | 0/33 fires | <= 0 | PASS |
| synthesis_present | target | 199/210 (95%) | = 100% | **FAIL** |

**REJECT — guards held; two targets below threshold.**

The battery rejects the current production model. That is the correct first
result to get: a battery whose first run passes everything has not been shown to
be able to fail.

### `synthesis_present` — i46, now with a rate and a repro

11 of 210 tool-calling turns returned `synthesis_turn=False` (**5.2%**), across 7
distinct questions. Previously i46 was known only as "3 of 9 calls" in an
unrelated probe.

```
pv-11  3/3   "Dame el detalle fecha por fecha de Gordon en lo que va de temporada."
gw-04  2/3   "¿Qué fecha es la próxima y cuándo cierra el mercado de fichajes?"
gi-03  2/3   cp-01 1/3   cp-03 1/3   sb-05 1/3   ad-07 1/3
```

`pv-11` fails **3 of 3** — a deterministic reproduction, which is worth more to
i46 than the rate is. Both repeatable cases ask for a long enumeration
(per-gameweek detail; next fixture plus deadline), which is a lead, not a
conclusion.

### `invented_metric_relay` — one call, and an open question about the assertion

14/15. The single failure is `gi-03` rep 2 — *"¿Quién tiene mejor vibra esta
fecha?"* — which called `get_gameweek_context` **alongside**
`rank_captain_candidates`. The other two reps of the same question called
`rank_captain_candidates` alone and passed.

This needs a decision that is **not the author's to make after seeing the
result**. The assertion is "no gameweek tool anywhere in the sequence". i15's
failure mode was a gameweek tool *answering* a question about a metric that does
not exist. Here the question literally contains "esta fecha", and the gameweek
tool appears next to the answering tool rather than instead of it. Two readings:

* the assertion is right and luna genuinely regressed against i15's 0/10; or
* the assertion is too strict for questions that name the gameweek explicitly,
  and should require the gameweek tool to be the *only* tool.

**Left as measured.** Loosening a threshold or an assertion after seeing the
number it failed is the thing this whole card exists to prevent. i15's own
verification contains a precedent for the narrower reading — it recorded
`rank_captain_candidates` on this exact question as defensible and did not count
it as a breach — but acting on that now, after the fact, would be fitting the
instrument to the result.

A second, smaller one on the same axis: `gi-02` called **no tool at all** in 1 of
3 reps and passed, because no gameweek tool was present. A turn answering about a
metric that does not exist from memory is arguably worse than the fallback the
axis tests for. Also left as measured.

## Two findings from the mutation tests — the battery testing itself

**1. The routing corpus does not know `get_my_squad`.** Zero mentions: it
predates the tool, and labels `sb-02`/`sb-13` as `select_players_within_budget`
alone. Scored against that label, the behaviour i41 shipped and measured at 5/5
reads as a **routing regression**, and the routing and ownership axes contradict
each other on the same turn. Patched in `golden_axes`, **not** in the corpus:
#171, i38 and i41 were all scored against the corpus as it stands, and editing it
would retroactively change what those published numbers mean. The patch adds
`get_my_squad` to the acceptable set without removing the original label, and a
test pins both halves.

**2. A threshold was looser than its own reference.** `metric_resolution` was
first written at 0.90 against a measured reference of 25/26 ≈ 96%. The mutation
test showed that at 0.90 an *entirely broken* case out of ten still passed.
Raised to 0.95 — which tolerates a single flaky rep (29/30) and fails a
consistently broken case (27/30). Stated plainly because adjusting a threshold
after seeing results is exactly what this card forbids: this change came from a
synthetic mutation **before the first live call**, and the reason sits next to
the number.

## Tier sizes differ from the brief's estimate

Measured: `controls` = 70 distinct cases -> **210 calls**; `full` = 111 -> **333**.
The brief estimated ~140 and ~270 because that count was the routing axis alone
(47 and 90); the other six axes add 23 distinct cases. Nothing was trimmed to
match the estimate — the runner prints the real number before spending.

## Not done, deliberately

Not wired to CI: it needs credentials and costs money, and the two required
checks must keep running without either. The mutation tests are the part CI
runs. No LLM judge. No new questions. No other models — that is i22/i26, and the
point of this card is that they now cost one run each.

## Artifacts

`field-notes/artifacts/golden-battery-gpt-5.6-luna-controls-2026-08-28.jsonl`
(210 rows) and the diffable report `.md` beside it, with the bootstrap sha256
`4cbb9fa1...` pinned in its header.

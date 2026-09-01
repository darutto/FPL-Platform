# i46 — one bounded extra round (b) + a marked fallback (c)

**2026-08-31.** Base `94d14b3` (origin/main). Provider/model pinned and asserted
per call: `openai` / `gpt-5.6-luna`. Bootstrap frozen:
`agentic-loop-bootstrap-2026-08-18.json`, sha256
`4cbb9fa18a5852c73a54fbe24a03b34e0c33ae5b3c549171cbcb02568d8b2aae`.
Production settings — `max_tokens=1024`, bounded loop OFF.
40 turns, **$0.2121**, **0 exceptions**.

Script: `scripts/measure_i46_fix_paired.py`. Data:
`field-notes/artifacts/i46-fix-paired-2026-08-31.jsonl`.

## The two paired figures

Both arms ran **inside one session, interleaved rep by rep on the same
questions**. The historical 5.2% is not the "before" number and is not used as
one: it came from a different corpus on a different date, and two rates
gathered that far apart differ for reasons unrelated to this change.

| arm | n | `synthesis_turn=False` | rate |
|---|---|---|---|
| before | 10 | 7 | **70%** |
| after | 9 | 1 | **11%** |

Pre-registered success criterion — `rate_after <= 1/3 * rate_before`, paired —
**MET** (11% against a 23% threshold).

The after-arm denominator is 9, not 10, because one after-arm rep called no
tool at all (`outcome="no_tool"`). A turn that ran no tool cannot fail
synthesis, and the pre-registered rule excludes it rather than letting it
dilute the denominator. It is in the JSONL.

### The tighter estimate, immune to cross-arm noise

70% → 11% slightly overstates the treatment effect, because the two arms differ
by the model's own nondeterminism as well as by the fix. The within-arm
counterfactual is cleaner, and it is paired by construction:

Of the 9 scored after-arm turns, **5 reached the exact pre-fix failure point** —
a synthesis call with no text carrying a tool call. Without the fix all 5 would
have been failures. **4 of the 5 recovered into model-written prose; 1 still
landed on the marked render.** So the after-arm's failure count without the fix
would have been 5/9 (56%), against the 1/9 (11%) actually observed.

Both numbers say the same thing. 56% is the honest ceiling on what the fix was
asked to remove, and 70% is what the paired before-arm happened to produce.

## The guard held, which mattered more than the success criterion

`sb-04` — a ranking question whose synthesis has never failed (0/52 across the
i18/i19/i42 probes) — was measured in both arms as the population where a wrong
fix would cost money on every healthy answer:

```
sb-04 before:  n=10   synthesis_turn=True 10/10   extra rounds 0   provider calls: 2 on every turn
sb-04 after:   n=10   synthesis_turn=True 10/10   extra rounds 0   provider calls: 2 on every turn
```

**Zero extra calls on turns that did not need one**, and the token means barely
move (21,836 → 22,187, ordinary between-call variance). A turn whose synthesis
already returns text never reaches the new code path, and that is pinned by
test across all three providers, not only observed here.

## Cost, on the turns that actually paid it

| | mean tokens | mean cost |
|---|---|---|
| before-arm turn | 21,418 | $0.00511 |
| after-arm turn where the round fired | 32,622 | $0.00763 |
| **delta per affected turn** | **+11,205** | **+$0.00252** |

After-arm turns where the round did *not* fire: 21,543 tokens — level with the
before-arm, which is the guard restated in tokens.

The extra round fired on 5 of 9 after-arm turns here, but gw-04 is the worst
case by selection: it is the confirmed repro. On a healthy question (`sb-04`)
it fired on 0 of 10, and the population-wide cost is whatever the real defect
rate is, not this one.

## (b) and (c) are reported apart, and (c) is not evidence for (b)

A turn that still ends on a marked render is **not** a success for (b). The
measurement isolates them: the before-arm stub suppresses only the extra round,
while (c)'s notice prefixes the fallback in *both* arms. Since `synthesis_turn`
is never set by the notice, the entire rate difference between arms is
attributable to (b).

(c) is a presentation change with no rate of its own: 1 turn in this run still
reached it, and it shipped the tool's output behind a line saying the model did
not write it, instead of passing a raw dump off as an answer.

## What was built

**(b)** `_run_synthesis_extra_round()` in `orchestrator.py`. When the synthesis
call returns no text but does carry tool calls, it executes them, accumulates
the turn with the same `_build_multi_tool_follow_up` the first round uses, and
makes one more call.

The cap is **structural, not a counter**: the extra round's own reply is never
re-parsed for tool calls, so no sequence of model responses can reach a fourth
call. It reads no `FPL_ORCH_MAX_ROUNDS`, honours no configuration, and does not
enable the bounded loop. A test sets `FPL_ORCH_MAX_ROUNDS=5` and asserts the
call count stays 3.

**(c)** The fallback render is prefixed with `orchestrator.raw_render_notice`
from `catalogue.py`, in both locales, tuteo — not a hardcoded string. A test
asserts neither rendering appears literally in `orchestrator.py`.

### Wording decision worth flagging

The notice first read "Here is the raw data". A test caught that the same
notice also fronts an already-readable tool error (`Metric 'x' not recognized.
Try: ...`), where calling it raw data makes a good message read like a second
failure. The alternative — marking only *some* renders — would mean deciding
which renders are good enough to pass as answers, which nobody has decided and
which does not belong in a fallback string. The wording became "Here is what
the tool returned", which is accurate for a table and an error alike.

### A pre-existing under-count, fixed alongside

The fallback path dropped the synthesis call's tokens entirely: every degraded
turn reported fewer tokens than it cost — exactly the population whose cost this
change had to measure. Tokens are now accumulated before the branch, so both
the synthesis call and the extra round are billed.

This is a real behaviour change beyond (b) and (c), named rather than folded
in. It cannot inflate the delta reported above: those figures are summed from
the instrument's own per-call `usage` capture, independent of the orchestrator's
accounting.

## Knock-on worth knowing

`tool_call_count` now reads 2 instead of 1 on turns where the extra round ran a
tool — correct by its documented semantics ("executed tool calls underlying the
retained payload"), since a tool really did run twice. Three existing tests
asserted the old count and were updated with the reason. The harness cards only
a genuinely single-call turn, so those turns no longer card.

**This is a trade, not a free win.** An earlier draft of this note said those
turns "never carded usefully anyway". That was wrong: they had
`tool_call_count == 1`, so they *did* card. What the user actually gets is
`[raw dump + working card]` replaced by `[good prose + no card]` — the bad half
swapped for the good one, at the cost of the half that already worked. Worth
accepting on a broken turn, where prose beats a card, but the card UI is a
deliberate product direction and this quietly spends some of it.

The finding underneath: **this is the second time `tool_call_count` has stood in
for something it does not mean.** The first was reading it as "did the model
speak", where the real signal turned out to be `synthesis_turn` — a mistake that
cost a biconditional hypothesis false in both directions (see
`test_synthesis_turn_instrumentation.py`'s module docstring). The real question
for carding is not how many calls a turn made, but whether there is a tool
output fit to build a card from. Tracked as its own card; measure before
promising anything.

## Verification

- **Four paths × three providers**, driven through the existing
  `test_multi_provider_follow_up.py` wire-shape helpers: synthesis returns text
  (no extra call — the guard); returns a tool call (rescued); the extra round
  asks again (capped, marked); no text and no tool call (no extra call,
  marked). Plus the catalogue test in both locales and a token-billing test.
- Full package suite: **1479 passed, 1 skipped**, against a **1465 passed, 1
  skipped** baseline on `main` — +14, exactly the new tests. The 72 errors are
  identical in both runs (`PermissionError` on the parquet store, environmental,
  almost certainly concurrent worktrees) and are not attributable to this change.

## What this does not settle

- **Tool identity is still confounded.** Unchanged and untouched: nothing here
  explains why `get_gameweek_context` failed 2/4 in the captaincy track.
- **One question, one model, one session.** The 5.2% population rate is not
  re-derived. gw-04 is also heavily `web_fetch`-confounded — several turns are a
  404 followed by a sensible retry — so its 70% before-rate is not the product's.
- **The remaining (c) turns are unexplained.** 1 of 5 rescues failed; why the
  extra round sometimes still returns no text is not answered here.

# Arms A/B recorded only their first tool call — two published readings are unsafe

Date: 2026-08-22. Branch: `exp/agentic-loop`.

## What was broken

`tool_calls_trace` was populated only on the bounded-loop path (arms C/D).

`_apply_evaluator()` took `tool_calls_trace` as a parameter and used it twice — to
build the evaluator's prompt, and as `tool_call_count = len(trace)` — but not one of
its eight return sites copied it onto the `OrchestratorResult`. The loop path masked
that: `_run_bounded_loop._result_with_observability()` overwrote the field with
`replace(result, tool_calls_trace=tuple(trace), ...)` after the call returned. The
legacy single-round path (arms A and B) called `_apply_evaluator` directly, so the
trace it had already built was discarded and every arm-A/B row shipped `[]`.

Measured across the two stored runs:

    field-notes/PARTIAL-reach.json                       12/12 arm-B rows, empty trace
    field-notes/2026-08-18-agentic-loop-experiment.json  30/30 arm-B rows, empty trace

For those rows the only surviving record of tool use is `tool_chosen`, which is
`executed[0]` — the **first** tool of the round. `tool_output` is that same first
call's output. A turn that batched several tool calls into one round reports one of
them; the rest left no trace at all.

## The reading that exposed it

`anthropic/Q7/rep2` in `PARTIAL-reach.json` records `tool_chosen:
get_gameweek_context`, whose output carries only gameweek metadata — `current_gw`,
`next_gw`, deadlines, no player data — and an empty trace. Its answer nonetheless
cites four players with prices and season points that are exactly correct against the
frozen bootstrap:

    B.Fernandes 12.0m/235   Semenyo 8.5m/202   Gibbs-White 8.0m/188   Rice 7.5m/184

Those figures are not in the initial message (`{"role": "user", "content": question}`,
with no bootstrap context) and not in the gameweek metadata. Another tool almost
certainly ran in the same round and was never recorded.

## Two claims that must not be restated

Both were derived from `tool_chosen` alone and cannot be supported by the stored data:

1. **"Q7 and Q9 never call `build_squad`"** — commit `22b9c6b`.
2. **"Anthropic reaches `select_players_within_budget` 0/6"** — the `PARTIAL-reach`
   run. (Its 6 anthropic arm-B rows show `get_gameweek_context` ×4 and
   `get_current_gameweek` ×2 as `tool_chosen`.)

The most either run supports is the weaker statement: **the FIRST tool of the round
was not X.** A second call in the same round would have been invisible.

**These questions cannot be re-derived from the stored artifacts.** The calls were
never recorded — there is nothing to re-parse, re-aggregate, or recover. Answering
them requires re-running those observations against the fixed instrumentation, which
costs live API calls and is the operator's call, not something this change does.

Until such a re-run exists, treat arm-A/B tool-selection statistics in
`22b9c6b`, `PARTIAL-reach.{md,json}` and
`2026-08-18-agentic-loop-experiment.{md,json}` as first-tool-only. Arm C/D
(loop) tool statistics in those same artifacts are unaffected — the loop always
recorded its full trace.

## What changed

Instrumentation only. No change to tool selection, descriptions, prompts, loop
behaviour, or arm definitions.

- `_trace_entry()` — one shared record builder (`round`, `tool_call_id`, `name`,
  `args`, `output`, `success`), used by both the loop and the legacy path. The legacy
  single round records as `round: 1`, exactly as the loop records its first round.
- `@_attaches_tool_calls_trace` on `_apply_evaluator` — attaches the supplied trace to
  whatever result the function returns, so no present or future return site can drop
  it again.
- The legacy path's tool-execution `except` branch now records the raising call (as
  `status: error` / `code: tool_exception`, the loop's shape) plus everything already
  executed in that round, instead of returning with nothing.

Unchanged by design: `tool_chosen`, `tool_args`, `tool_output` keep their exact
current values and meaning (`harness.py`'s success gate and the `tool_call_count == 1`
atomic-card gate depend on them); `tool_calls_trace` still defaults to `()`; loop
traces are byte-identical to before; an evaluator retry's own tool calls are still not
appended to the trace, matching what the loop has always reported.

## Verification

`tests/test_tool_calls_trace_all_arms.py`, 11 tests, deterministic, no API calls —
fake provider clients reused from `tests/test_multi_provider_follow_up.py`. Covers the
one-entry non-loop trace, the multi-tool non-loop trace across all three providers
(the case that was invisible: 7 of these failed before the fix), non-ok statuses and
raising handlers staying visible, the evaluator-enabled non-loop path in both verdict
branches (arms A/B run verdict-only), and a recorded literal pinning the loop trace.

Full `packages/fpl-grounded-assistant` suite: **1093 passed, 1 skipped**.

---
title: Agentic-loop experiment — implementation complete; paid matrix awaiting provider credentials
captured: 2026-08-18
relevant_to: [orchestrator, tools, preseason, measurement, squad-building]
status: blocked-live-run
---

## Status

The four-arm experiment and deterministic measurement harness are implemented.
The credential-free package and focused tests pass. The 72-observation paid
matrix (4 arms × 2 providers × Q6/Q7/Q9 × 3 repetitions) has not been run in
this environment because neither `ANTHROPIC_API_KEY` nor `GOOGLE_API_KEY` is
available. No answers, rates, semantic scores, or cost totals are inferred in
their absence.

## Frozen input

- Bootstrap: `field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json`
- Capture: `2026-08-18T04:10:27.877492+00:00`
- SHA-256: `7aa080698e42adc0b8e70e2d59077fae32db940c67c210ed01d8c53efde63a9a`
- Elements: 590; events: 38; non-zero form: 0

This is a fresh 2026-08-18 capture. The plan refers to an earlier
`9fbfa93d…` 2026-08-17 snapshot, but that file is not present in the repository
or local worktrees. The new snapshot preserves the experiment's relevant data
invariants, but it is a documented reproducibility deviation and must not be
reported as the earlier capture.

## Pinned execution

- Arms A/B/C/D use the normalized baseline worktree and treatment worktree
  described in the plan.
- `max_tokens=4096`; temperature `0.0` for both providers.
- Anthropic `top_p` is omitted because its API recommends varying one sampling
  control at a time; Gemini `top_p=1.0`.
- Anthropic extended thinking is off; Gemini uses its model default thinking
  level (`medium` for the pinned Flash model).
- Evaluator runs verdict-only; structured-output instructions are enabled in
  all arms; loop maximum is three tool-execution rounds.
- The driver uses direct `ask_orchestrated` calls, so this is an answer-quality
  and cost experiment, not an end-to-end UI acceptance test.

## Run command

From the agentic-loop worktree, with both provider keys supplied:

```powershell
$env:FPL_RUN_AGENTIC_EXPERIMENT = '1'
uv run --with-requirements packages/fpl-grounded-assistant/requirements.txt `
  python packages/fpl-grounded-assistant/scripts/run_agentic_loop_experiment.py `
  --bootstrap field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json `
  --baseline-root C:\Users\thera\fpl-platform\.claude\worktrees\loop-baseline `
  --agentic-root C:\Users\thera\fpl-platform\.claude\worktrees\agentic-loop `
  --output field-notes/2026-08-18-agentic-loop-experiment.md
```

The driver replaces this status note with the completed pinned-config report,
including answers side by side, Axis 1 classifications, Axis 2 legality,
separate Axis 3 human-score columns, failure rates, token/cost totals, complete
tool traces, rounds, and evaluator verdicts.

## Pre-live audit corrections

The paid run remains intentionally unopened until the review findings are
covered by tests. Before running it, the implementation was corrected so that:

- Spanish fallbacks and the exact Q6/Q7/Q9 prompts are valid Unicode;
- `ambiguous`, `not_found`, and other usable tool observations survive the
  loop instead of becoming generic no-tool failures;
- `tool_call_count` counts all calls behind the retained primary payload, so a
  mixed success/failure synthesis cannot pass the atomic-card single-call gate;
- two consecutive fully failing rounds stop before an unnecessary provider
  call; and
- raw-tool fallback legality is reported separately from model JSON, with its
  bootstrap-synthesized price and arithmetic checks marked non-comparable.

A second review pass found two further Axis 1 biases, both fixed before the
paid run:

- **The canonical failure string scored as a success.** `content_free_stub`
  matched the literal `"no available midfielders found"`, but the message is
  interpolated (`f"No available {pos}{team}{price} found with positive
  form..."`), so the price-filtered variant — the exact Q8 response that
  motivated this experiment — was not a substring and classified as
  `substantive_answer`. Markers now match the invariant tail
  (`"found with positive form in the current bootstrap"`).
- **`outcome` was not comparable across arms.** Axis 1 flagged any
  `outcome != "ok"`, but the loop reports `ok` plus `rounds_exhausted` for
  grounded partials (so the harness delivers them rather than collapsing to
  `unsupported`), while the legacy single-round path reports
  `tool_result_error` for the same tool status. Identical answer text was
  therefore catastrophic in arms A/B and substantive in arms C/D — a
  systematic advantage to the loop on the headline churn metric, unrelated to
  answer quality. Axis 1 now reads orchestration-level failures from `outcome`
  (where both paths agree) and tool-level quality from the tool's own
  `status` (which both paths populate identically).

Both corrections are pinned by tests that were verified to **fail** against the
previous implementation, so they cannot silently regress.

## Decision boundary

Passing Q8-style ranking is not season readiness. If loop arms C/D still fail
legality or the semantic rubric on Q6/Q7/Q9, the next P0 is the deterministic
player-query and squad-decision layer. It is not a reason to buy Sportmonks data
or move to a more expensive model.

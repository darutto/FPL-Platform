# Captaincy scoring inputs — Codex continuation handoff

**Prepared:** 2026-09-04 (America/New_York)  
**Reason for handoff:** Codex weekly/session usage limit interrupted all three
Wave 1 subagents before they could commit. Preserve their worktrees exactly.

## Source of truth and non-negotiable rules

Read `CAPTAINCY_SCORING_INPUTS_HANDOFF.md` in full before continuing. It remains
the product/source-of-truth document. This file records execution state only.

- Never work in the shared checkout `C:\Users\thera\fpl-platform`.
- Never touch `roadmap-board/data.json`; the shared checkout still contains
  another session's uncommitted board/data work.
- One worktree per lane. Do not stash, reset, or checkout another lane's branch.
- A local passing count is not CI evidence.
- Measurement decisions must be written in the script before the first call.
- Never expose scoring coefficients or internal thresholds in user-visible copy.
- No lane declares product success from its own test or ranking movement.

## Git truth at interruption

- Remote base last fetched: `origin/main` at `3865b7b`.
- Local integration worktree:
  `C:\Users\thera\fpl-platform\.worktrees\captaincy-integration`
- Local integration branch: `main` at `87c7e46`, ahead of `origin/main` by the
  commits listed below.
- Publishing was attempted and rejected by the environment's approval reviewer:
  there is **no authorization to push repository code and ~2 MB artifacts to the
  remote**. Everything described as integrated is integrated into local `main`,
  not `origin/main`. Obtain explicit user authorization before any push.

Local `main` commits, oldest first:

1. `4a9eb5e` — failing regression tests for both stale-current resolvers. This
   is intentionally the first commit.
2. `e13f582` — original frozen bootstrap, measurement script and pre rows.
3. `ef08755` — fixes both `fpl_client.get_current_gameweek()` and
   `scoring_core.captain_time_context()` to ignore finished current/next events.
4. `29ab298` — bootstrap-driven chip windows and contract fields.
5. `e072821` — passes `team_fixtures` from chip captain ranking into shared
   scoring, needed when Wave 1 B is integrated.
6. `0600fc6` — fixture-aware immutable measurement companion and its first pre.
7. `87c7e46` — official all-fixtures denominator snapshot and definitive
   fixture-aware pre measurement.

The integration worktree was clean immediately after `87c7e46`.

## Completed locally

### Wave 0 — complete on local `main`

Both resolver paths are fixed together:

- `packages/fpl-api-client/fpl_api_client/fpl_client.py`
- `packages/fpl-tool-contract/fpl_tool_contract/scoring_core.py`

Acceptance behavior covered:

- stale `is_current=True, finished=True` yields the unfinished `is_next` GW;
- a genuine unfinished current GW remains current;
- when every flagged event is finished, the result is `None` in both paths.

Observed red before implementation:

- API suite: `1 failed, 45 passed`, returning 28 instead of 29.
- Tool-contract suite: `1 failed, 57 passed`, returning 28 instead of 29.

Observed after implementation:

- `packages/fpl-api-client/tests/test_fpl_client.py`: **47 passed**.
- `packages/fpl-tool-contract/tests/test_tools.py`: **59 passed**.
- `packages/fpl-grounded-assistant/tests/test_captaincy_surface.py`:
  **19 passed**.

Direct consumers reviewed for the future PR description: query-tools wrapper;
pipeline context; grounded-assistant chip advisor, comparison, context builder,
differential picks, fixture outlook, player fixture run, team fixture calendar,
transfer advisor, transfer suggestion and zonal weakness; tool-contract current
GW tool; tool-runner dispatch.

### Wave 1 lane A — complete on local `main`

Contract decision was made before implementation:

- every recognized chip verdict carries `window_status`, `active_window`,
  `gameweeks_remaining`, and `window_notice`;
- remaining GWs include the evaluated GW;
- missing/malformed `chips[]` returns null window/remaining fields with
  `window_status="unavailable"` and an explicit notice;
- a known but non-active window is `inactive`, not silently treated as a
  single-season window;
- wildcard timing is relative to the active window. No absolute 19/20/38
  production constants were added.

Files:

- `packages/fpl-grounded-assistant/fpl_grounded_assistant/chip_advisor.py`
- `packages/fpl-grounded-assistant/tests/test_chip_windows.py`

Verification:

- New + adjacent pytest selection: **48 passed**.
- Historical `run_phase6b_tests.py`: **129/141** on both lane A and untouched
  Wave-0 main, with the exact same 12 known failures. This comparison is
  evidence that those failures predate lane A; it is not a green gate.
- GW29 with ten GWs remaining in the active wildcard window is marginal and is
  no longer called late season.

## Slice 0 instrumentation correction — important

The original immutable script
`measure_captaincy_scoring_inputs.py` was correctly left unchanged after its
pre run, but it calls the old two-argument base primitive. After Slice 3 that
call intentionally exercises the no-fixture degradation path, so it cannot
observe the participation change. Do **not** edit it.

Before seeing any post result, two more immutable assets were added:

- `measure_captaincy_scoring_inputs_with_fixtures.py` — measures through
  `_derive_scoring_inputs(..., team_fixtures, evaluated_gameweek)` and reuses
  the original script's already-frozen comparison rule.
- `freeze_captaincy_fixture_context.py` — fetches the official all-fixtures
  endpoint once and marks normalized team fixtures complete.

Definitive baseline inputs:

- Bootstrap + complete fixture snapshot:
  `field-notes/artifacts/captaincy-scoring-bootstrap-complete-fixtures-2026-09-03.json`
- Pre rows:
  `field-notes/artifacts/captaincy-scoring-inputs-pre-complete-fixtures-2026-09-03.jsonl`
- SHA recorded in every definitive pre row:
  `2f2d43540f3b30b7de92569f914cfd87340854372dd6bc8488cd0d0a9720bd33`
- 282 derived-pool rows. Before Slice 3, Haaland is rank 13 in this full pool.
  That rank is a snapshot check only.

The complete-fixture pre values were byte-for-value identical to the earlier
fixture-aware pre (ignoring the bootstrap SHA), proving that merely attaching
history did not change the old scoring behavior.

Run the post **after B is merged and before E opens the pool to all positions**:

```powershell
$env:UV_CACHE_DIR='C:\Users\thera\fpl-platform\.uv-cache'
uv run --with requests --with rapidfuzz python packages/fpl-grounded-assistant/scripts/measure_captaincy_scoring_inputs_with_fixtures.py --bootstrap field-notes/artifacts/captaincy-scoring-bootstrap-complete-fixtures-2026-09-03.json --out field-notes/artifacts/captaincy-scoring-inputs-post-complete-fixtures-2026-09-03.jsonl
uv run --with requests --with rapidfuzz python packages/fpl-grounded-assistant/scripts/measure_captaincy_scoring_inputs.py compare --before field-notes/artifacts/captaincy-scoring-inputs-pre-complete-fixtures-2026-09-03.jsonl --after field-notes/artifacts/captaincy-scoring-inputs-post-complete-fixtures-2026-09-03.jsonl
```

Commit the post artifact without modifying either measurement script. Expected
verdict is `PROCEED`; if Haaland moves from rank 13, stop and inspect.

## Wave 1 interrupted worktrees — preserve and finish

All three subagents hit the usage limit and returned no final report or commit.
Their tracked diffs are present and valuable, but must be reviewed and tested.

### Lane B — Slice 3, uncommitted

Worktree: `C:\Users\thera\fpl-platform\.worktrees\captaincy-b`  
Branch: `fix/captaincy-minutes-risk` (still based on Wave-0 commit `ef08755`)

Modified files:

- `packages/fpl-tool-contract/fpl_tool_contract/scoring_core.py`
- `packages/fpl-tool-contract/fpl_tool_contract/tools.py`
- `packages/fpl-tool-contract/tests/test_scoring_core.py`
- `packages/fpl-tool-contract/tests/test_captain_tier_integration.py`
- `packages/fpl-grounded-assistant/fpl_grounded_assistant/scoring_shared.py`
- `packages/fpl-grounded-assistant/tests/test_scoring_shared_consolidation.py`
- `packages/fpl-pipeline/fpl_pipeline/context.py`
- `packages/fpl-pipeline/tests/test_context.py`

The inspected implementation follows the pre-decided denominator contract:

- official completed fixture minutes per team;
- restrict fixtures to kickoff dates on/after `element.team_join_date`;
- complete-context marker prevents partial future-only schedules from being
  mistaken for history;
- availability/status risk and participation risk combine with `max`;
- explicit degradation reasons for missing/incomplete fixtures, invalid join
  date/minutes, no completed fixtures, and player minutes exceeding available;
- returns auditable minutes context (played, available, starts, fixture count,
  participation, source, degraded/reason);
- pipeline reuses one official all-fixtures fetch for rolling strength and the
  minutes context.

Do not touch `chip_advisor.py` in B. Commit `e072821` on local main already
passes `team_fixtures` into its ranking path.

Next action: inspect `git diff`, run focused tool-contract/pipeline/grounded
suites, run `git diff --check`, then commit on the B branch. Merge into local
main with a normal merge (branch is behind local main), then immediately run
the definitive Slice 0 post/compare above.

### Lane C — prose + card coexistence, uncommitted

Worktree: `C:\Users\thera\fpl-platform\.worktrees\captaincy-c`  
Branch: `feat/captaincy-prose-card`

Modified tracked files:

- `packages/fpl-ui/components/chat/MessageList.tsx`
- `packages/fpl-ui/__tests__/message-list-atomic-card.test.tsx`

Untracked `.npm-cache/` was created by this lane because AppData/npm network
access was blocked. It belongs to the lane and must **not** be committed. Remove
only that exact directory after confirming the resolved worktree path.

Inspected design state:

- FPL structured turns render one outer answer surface;
- `final_text` is retained as the visible verdict band;
- `IntentRenderer` is the data section underneath;
- child card chrome is flattened to avoid bubble + nested-card duplication;
- World Cup card behavior remains separate;
- tests assert verdict and data live in the same surface and no assistant bubble
  wraps a second card.

Before commit, decide/document the addendum's collapsible footer. The visible
conclusion and nuance must remain at the top; do not hide all `final_text` inside
the footer. If a separate explanation payload does not yet exist, explicitly
leave `Por qué esta recomendación` for lane F rather than fabricating content.

Run focused UI tests, remove `.npm-cache/`, `git diff --check`, commit, merge.

### Lane D — i53 provenance contract, uncommitted

Worktree: `C:\Users\thera\fpl-platform\.worktrees\captaincy-d`  
Branch: `feat/captaincy-provenance-contract`

Modified tracked files:

- `packages/fpl-grounded-assistant/fpl_grounded_assistant/final_response.py`
- `packages/fpl-grounded-assistant/fpl_grounded_assistant/harness_adapter.py`
- `packages/fpl-grounded-assistant/fpl_server.py`
- `packages/fpl-grounded-assistant/tests/test_captaincy_surface.py`
- `packages/fpl-ui/lib/types.ts`
- `packages/fpl-ui/__tests__/contract.test.ts`

Untracked `.npm-cache/` is test cache only; never commit it.

The agent found that `FinalResponse` already had `squad_source`, but lacked
`pool_source`/`pool_size`. It also found that explicit field lists in
`harness_adapter.py` and `fpl_server.AskResponse` would silently discard the
new fields over HTTP, so expansion to those files was authorized. The current
diff appears to propagate/test `pool_source`, `pool_size`, and
`synthesis_turn`; inspect exact optionality before committing. Do not touch
orchestrator behavior or fallback rendering in this lane.

Run backend + UI contract tests, remove `.npm-cache/`, `git diff --check`, commit,
merge. i52 remains blocked until these fields are demonstrably present at the
external response boundary.

## Decisions already closed before code

### Slice 3 denominator

Source: official completed fixtures, summing actual fixture minutes for the
player's current team from `team_join_date`. This handles doubles, blanks,
postponements, and recent signings. If the all-fixtures snapshot is incomplete,
join date is absent/invalid, or fixture/player minutes are unreliable, degrade
explicitly to availability/status risk. Do not infer the denominator from GW.

### Slice 2 window contract

Fields and degradation are described under completed lane A above. Do not
replace them with prose-only output or hardcoded season boundaries.

### Haaland expectation

Only a check of the frozen 2026-09-03 complete-fixture snapshot. Never turn it
into a permanent product invariant.

## Remaining waves after Wave 1 integration

### Wave 2 lane E — Encargo 3

Start only after B is merged and the Slice 0 post measurement is committed.
Create a fresh worktree from updated local main.

- Remove positional exclusion in `captain_pool_elements`; GKP/DEF are eligible.
- `squad_excluded` must stop emitting `not_eligible_position`.
- Keep the full auditable payload; presentation only is 3 + 1 owned and 5 + 1
  global.
- Hipster is based on `selected_by_percent`, never the current `differential`
  tier. It must clear the documented score/minutes-risk floor; if none qualifies,
  say so rather than filling with a bad low-owned player.
- Show position in the card because defenders/keepers will now appear.
- Do not add a ceiling term or alter scoring weights.

Read the complete `Encargo 3` section in `CAPTAINCY_SURFACE_HANDOFF.md`.

### Wave 2 lane F — visible factors

Start only after C and D are merged. Fresh worktree from updated local main.

- Show minutes played/available and starts in plain language.
- Show penalty-taking status/order as a visible adjacent axis, never as a new
  hidden score term.
- Explain that triple captain multiplies risk as well as points.
- Positive/context framing; no alarm-red treatment.
- If score order conflicts with a visible factor, say so.
- Named-player questions anchor the note to that player's row.
- Text and card must use the same data and figure.
- Never mention coefficients or internal thresholds.

The i46 synthesis zone is now allowed, but read current behavior first: commit
`3dcdb7e`/PR #204 added one bounded extra round when synthesis asks for a tool
and marks fallback. The remote branch
`origin/claude/tournament-start-responses-is2af8` was inspected. Its useful
piece is the explicit FPL_RECO steering pattern that prevents
`get_gameweek_context` from winning merely because a recommendation mentions a
season/calendar. Do **not** cherry-pick the old branch wholesale: it is highly
diverged and its exact hunk targets value/calendar requests, not these captaincy
factors. Reuse/adapt the proven steering pattern only if current tests show the
same attractor.

### Wave 3 lane G — i52 probe

Start last, only after D/i53 is merged and externally visible. The existing
probe is `scripts/measure_captain_pool_variance.py`. Count `caller` vs `derived`
from structured provenance; never parse Spanish prose. Write any changed
decision rule inside the script before the first call. Do not attribute causes
from tiny/non-deterministic samples.

## Final integration gate

After B, E and F are all merged, inspect the **entire resulting player list**
once as a product, not just as unit outputs. These three lanes independently
change risk, eligible positions, presentation, and order. Specifically look for
partial-minute keepers/defenders displacing attacking choices, contradictions
between the verdict and rows, missing position labels, and hipsters that are
merely weak players.

Then run proportional clean-checkout suites. Report local counts as local only;
wait for/inspect CI after publication before claiming CI green.

## Publication status

No branch or local-main commit from this execution was pushed. Once the user
explicitly authorizes publishing repository code and the two ~2 MB snapshots:

1. fetch `origin/main`;
2. compare by **content**, not branch SHA (squash merges exist in this history);
3. rebase/merge carefully in a fresh integration worktree if remote advanced;
4. push a review branch or main only as explicitly authorized;
5. include the resolver consumer list and the duplicate-resolver provenance
   (introduced by PR #195) in the PR description.

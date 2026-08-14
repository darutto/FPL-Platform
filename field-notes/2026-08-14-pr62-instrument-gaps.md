---
title: Reviving PR #62 (Cluster A) after FI-8 — two instruments that read green without measuring what they claim
found_via: rebasing a 10-day-old PR onto main and asking, before merging, whether its test and its CI job actually validated it
captured: 2026-08-14
relevant_to: [instruments, falsifiability, tooling, gw-resolution, packaging]
status: new
---

## What prompted this

PR #62 (Cluster A: delegate six current-GW resolvers to the canonical
`get_current_gameweek`) sat open from 2026-08-04 while FI-8 worked in the same
modules. Before merging it we checked two things that were *assumed* rather than
observed: whether its regression test still exercises what it says, and whether CI
had ever actually run against its 427 lines.

Both checks came back fine for the merge — the test does fire, the job did run and
passed (664 passed / 1 skipped). But both instruments have a silent gap that the
green reading hides. Same shape as the
[2026-08-13 note](2026-08-13-instruments-failing-silently.md): the failure mode is
silence, and it took a second measurement by a different mechanism to see it.

PR #62 merged as `afc0d46`. Neither finding below blocks it; both outlive it.

## Findings

### 1. `test_current_gameweek_delegation.py` cannot see a call site abandoning the resolver — severity: med

**What happens:** The test pins the six resolver *functions*. It says nothing about
whether anything still calls them. A call site that stops using its resolver and
re-inlines the `is_current`-only loop — i.e. reintroduces the exact bug PR #62
fixed — leaves all 25 cases green.

**Evidence:** Reproduced on `afc0d46`. Rewired one call site,
`chip_advisor._classify_gameweek_type:166`, to bypass the resolver:

```python
current_gw = next((e.get('id') for e in bootstrap.get('events',[]) if e.get('is_current')), None)
```

`_get_current_gameweek` is left intact and correct below it, now dead for that
caller. Result:

```
25 passed in 0.71s
```

Compare the control: seeding the failure *inside* the resolver body (reverting it
to the `is_current`-only loop) is caught precisely —
`FAILED test_is_next_fallback_pre_season[chip_advisor.py]`, one case, one module.
So the test discriminates well on the axis it covers and not at all on this one.
Experiment reverted; tree clean.

**Where:** `packages/fpl-grounded-assistant/tests/test_current_gameweek_delegation.py`
— `_extract_resolver` (:39) parses the module source with `ast`, pulls the single
function by name, and `exec`s it in a clean namespace.

**Why it happens:** That standalone-exec design is deliberate and buys something
real — behavioural coverage of all six without importing their heavy module graphs
(`fpl_tool_runner` / captain engine / package `__init__`). The cost is that the
module is never imported, so no call graph exists to inspect. The test's own
docstring frames the fix as "each resolver body is now a thin delegation", which is
true and is what it checks; the property we actually care about is "GW resolution in
these six modules goes through the canonical resolver", which is strictly larger.

Renames and deletions *are* caught — `_extract_resolver` raises
`AssertionError: <name> not found in <file>`. It's specifically call-site drift that
is invisible.

**Fix direction:** A cheap static companion check, not a rewrite: walk each module's
AST for `is_current` reads outside the delegating resolver, or assert each module has
exactly one GW-resolution site and that it's a call to the local resolver. Keeps the
no-import property. Natural to fold into Cluster B (PR B) since that PR touches these
same modules, or into the `/abstraction-police` routine, which is already in the
business of finding re-inlined duplicates.

### 2. `package-test-suites.yml` justifies its no-`paths:` design with a runtime that is 50× stale — severity: low

**What happens:** The workflow's `DESIGN RULE -- NO paths: FILTER` block argues that
always running is cheaper than engineering around the doc-only-PR trap, on the
grounds that "the suites take ~30-40s total". The job now takes **33 minutes**. The
stated cost-benefit no longer holds, but the comment still reads as current.

**Evidence:** Job `94652126309` (merge run for #62), per-step:

| step | duration |
|---|---|
| fpl-captain-engine suite | 1s |
| fpl-tool-contract suite | 1s |
| fpl-tool-runner suite | 1s |
| fpl-grounded-assistant suite | 8s |
| sportmonks-client suite | 14s |
| **sportmonks-client falsifiability probe** | **32m 06s** |

Total 33m 08s. Recent `main` runs agree: 29–34 min (`31759090712`, `31757698590`,
`31754993601`). Note the comment is *literally* accurate — the suites really are
~25s. It's the sentence built on top of it that has gone false.

**Where:** `.github/workflows/package-test-suites.yml:32-36` (the claim),
`:118-130` (the probe step that now dominates, added by FI-8 S0).

**Why it happens:** The comment was written when the job was only pytest suites. FI-8
S0 appended the falsifiability probe, which is ~77× the cost of everything above it,
without revisiting the reasoning the earlier comment had already banked. The comment
is load-bearing — it is the written argument against a future `paths:` filter — so it
misinforms exactly the person it was written for.

**Cost this actually imposes:** every PR, including doc-only ones, now pays 33 min.
That was an easy trade at 40s and is a real one at 33 min.

**Fix direction:** Two separable questions, and the note is not asserting which way
either goes. (a) Correct the comment to state the true split (suites ~25s, probe
~32m) so the no-`paths:` argument is re-decided on real numbers rather than
inherited. (b) Ask whether the probe belongs in the same job as the suites at all —
splitting it would let the suites keep the always-run property cheaply while the
probe gets its own name and cadence. Job names are required checks, so (b) touches
branch protection and is not a drive-by.

## Open questions

- Does any *other* module outside the six already read `is_current` directly at a
  call site? Not measured — finding 1 was a seeded experiment, not a sweep. The
  sweep is what a static companion check would automate.
- Is the probe's 32 min inherent to the experiment or incidental (network waits,
  retries)? Not investigated; it's FI-8 territory and S5b is still open.

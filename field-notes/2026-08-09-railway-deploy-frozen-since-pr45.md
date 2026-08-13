---
title: Railway fpl-backend deploys have failed 161/161 times since PR #45
found_via: user asked why every deploy since PR #45 has failed
captured: 2026-08-09
relevant_to: [contracts, packaging, data-quality]
status: fixed
---

## What prompted this
User asked for an investigation into why fpl-backend deploys on Railway have
failed since PR #45. Confirmed via `railway deployment list`/`railway logs`
and git history — root-caused and fixed same day (PR pending at time of
writing, see below).

## Findings

### 1. Missing sys.path entry crashed every deploy since PR #45 — severity: high — status: fixed
**What happens:** `final_response.py:75` does a module-level
`from football_data_contract import ...` (added in PR #45, FI-7a). The
Dockerfile copies `packages/football-data-contract/` into the image, but
`fpl_server.py`'s sys.path setup list (lines 59-71) never included it — so
the interpreter can't see a package that's physically present. `uvicorn`
crashes at import time, before binding, on every single deploy.
**Evidence:** `railway deployment list --limit 1000` — 161 deployments since
2026-07-26T03:25:57Z, **0 successes**. `railway logs` on the latest failed
deployment shows `ModuleNotFoundError: No module named 'football_data_contract'`
at `fpl_server.py:79 → fpl_grounded_assistant/__init__.py:106 →
final_response.py:75`.
**Where:** `packages/fpl-grounded-assistant/fpl_server.py:59-71`
**Fix:** add `_SIB("football-data-contract")` to the sys.path list. One line.

### 2. Production has been silently frozen on pre-PR-45 code for 2+ weeks — severity: high
**What happens:** Railway doesn't take a service down when a deploy fails —
it keeps serving the last container that started successfully. The last
successful deploy was `8fb34e4` (PR #47), the commit immediately before PR
#45 merged. **44 merges to `main` since then never reached production** —
the entire FI-7 series, season-launch work, zonal tactical go-live, and
today's two PRs (#104/#106 compare-wizard fix, #110 preseason score
reweight) were all sitting unmerged-in-effect on the live backend.
**Evidence:** `railway deployment list --limit 1000 --json`, filtered to
`status != FAILED`, most recent non-failed entry: `SUCCESS`,
`2026-07-26T03:25:57.642Z`, `commitHash: 8fb34e4...`. `git log --oneline
8fb34e4..origin/main --merges | wc -l` → 44. The public URL
(`/ready`, `/health`) returned 200 the entire time — neither endpoint can
distinguish "alive and correct" from "alive and frozen two weeks in the
past."
**Where:** operational, not a code defect in the traditional sense.
**Fix direction:** the `/version` endpoint added alongside the sys.path fix
(reports `APP_COMMIT_SHA`, baked in from Railway's build-time
`RAILWAY_GIT_COMMIT_SHA` arg) closes the detection gap — comparing it to
`main`'s HEAD after any deploy is now one request instead of an assumption.
A durable next step (not done here): an automated check (post-deploy CI
step, or an uptime-monitor rule) that fails loudly when `/version`'s commit
doesn't match the branch that was supposed to deploy, rather than relying on
someone thinking to check.

## Open questions
- Should `/version` also report `deployed_at` (Railway deployment creation
  timestamp) so staleness is visible without cross-referencing
  `railway deployment list`? Not added — kept the endpoint to exactly what
  the immediate gap needed.
- Is there a way to make a future import-time crash in this file *fail the
  Railway build*, not just the running container's first start? (It already
  does — Railway's healthcheck against `/ready` fails and the deploy is
  marked FAILED — the actual gap was that this signal wasn't surfaced
  anywhere a human would see it, and the old container kept serving
  regardless.)

## Related, not fixed here (filed, not touched)
`fpl_cli.py:30-46` and `fpl_repl.py:30-46` have their own, independently
maintained copies of the same sys.path sibling list — both stop at
`fpl-pipeline`, missing the same four entries `fpl_server.py` has
(`fpl-historical`, `fpl-tactical`, `football-intelligence`, and now
`football-data-contract`). Same defect class, just never noticed because
nothing exercises these two entry points as continuously as the deployed
server. This is an instance of the duplicate-resolver drift already on the
backlog (`project_duplicate_resolvers_audit.md`) — worth consolidating into
one shared sibling-list constant the day someone touches either file again,
not urgent enough to justify touching two more entry points in the same
hotfix as a live production outage.

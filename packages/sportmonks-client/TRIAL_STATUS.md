# TRIAL_STATUS.md — Sportmonks trial dashboard

**Template.** Created by FI-8 S1. Updated **daily** during the FI-9 trial
(2026-10-11 to 2026-10-25) and closed out with the go/no-go decision.

This file is the §14.1 trial-dashboard artifact. It is the single place a reader
looks to answer "how is the trial going, and what do we still not know?"

| | |
|---|---|
| Trial start | 2026-10-11 |
| Trial end | 2026-10-25 03:09 UTC (Starter `Trialing until`, from the API's own subscription block); decision 23–24 Oct |
| Days elapsed | 0 |
| Last updated | 2026-10-11 (day 0, after plan activation) |
| Current verdict | **undecided** — see [TRIAL_GO_NO_GO.md](TRIAL_GO_NO_GO.md) |

## How to use this file

1. Run the owning script for an objective (all scripts default to `--mock`; the
   live path requires **both** `--live` and `--i-understand-this-is-live`, and
   must not be used before FI-9).
2. Set the objective's **Status** from the script's report.
3. Put a path or URL in **Evidence** — a report artifact, a raw snapshot, a
   support-ticket reply. An objective with a status but no evidence pointer is
   not observed; it is asserted.
4. Never mark an objective observed because the script exited 0 in `--mock`.
   Mock mode proves the script runs, not that the provider supplies the data.

**Status values** — the four the scripts emit, plus `not_started`, which is
dashboard-only. The scripts' report schema is frozen at exactly four
(`observed`, `unmet`, `degraded`, `not_applicable`); do not widen it to include
`not_started`, which describes this table's state rather than a run's outcome.

| Status | Meaning |
|---|---|
| `blocked` | live run done but the token/plan cannot supply the data — **dashboard-only, not a script status**; script emitted `unmet`/`degraded` |
| `not_started` | no run yet — **dashboard-only, not a script status** |
| `observed` | present in a live payload, with evidence |
| `degraded` | present but not in the documented shape, or incomplete — record what was found |
| `unmet` | absent, or below the bar |
| `not_applicable` | cannot be measured in the current mode (e.g. update timing outside a live match) |

## The 20 trial acceptance objectives

Verbatim from `FOOTBALL_INTELLIGENCE_PLANNING_BRIEF.md` §11.3. Do not reword
them — the wording is the acceptance bar.

| # | Objective | Owning script | Status | Evidence |
|---|---|---|---|---|
| 1 | Competition and season identifiers | `trial_entities.py` | `observed` | Premier League = league 8; 2026/27 = season 28083 (current, 20 clubs); UCL 2, UEL 5, UECL 2286, FA Cup 24, Carabao Cup 27 also visible. 15 of 15 families reachable in a 49-request live sweep after the route remap (4 truncated by the explicit page bound). Live evidence: [trial-reports/live/2026-10-11-routes.md](trial-reports/live/2026-10-11-routes.md). *Earlier day-0 block (free-plan token) is in the daily log and [day0.md](trial-reports/live/2026-10-11-day0.md).* |
| 2 | Premier League fixtures | `trial_fixtures.py` | `not_started` | mock rehearsal only: [trial-reports/examples/trial_fixtures.json](trial-reports/examples/trial_fixtures.json) — **not** a live observation |
| 3 | Cross-competition fixtures for Premier League clubs | `trial_fixtures.py` | `not_started` | mock rehearsal only: [trial-reports/examples/trial_fixtures.json](trial-reports/examples/trial_fixtures.json) — **not** a live observation |
| 4 | Team and squad completeness | `trial_squads.py` | `not_started` | |
| 5 | Current player records | `trial_squads.py` | `not_started` | |
| 6 | Confirmed starters and substitutes | `trial_lineups.py` | `not_started` | |
| 7 | Formation strings | `trial_lineups.py` | `not_started` | |
| 8 | Formation-grid or lineup-position fields | `trial_lineups.py` | `not_started` | |
| 9 | Detailed position identifiers | `trial_lineups.py` | `not_started` | |
| 10 | Substitution relationships and minutes | `trial_lineups.py` | `not_started` | |
| 11 | Injuries and suspensions | `trial_injuries.py` | `not_started` | mock rehearsal only: [trial-reports/examples/trial_injuries.json](trial-reports/examples/trial_injuries.json) — **not** a live observation |
| 12 | Coaches and manager records | `trial_injuries.py` | `not_started` | mock rehearsal only: [trial-reports/examples/trial_injuries.json](trial-reports/examples/trial_injuries.json) — **not** a live observation |
| 13 | Fixture-level team statistics | `trial_stats.py` | `not_started` | mock rehearsal only: [trial-reports/examples/trial_stats.json](trial-reports/examples/trial_stats.json) — **not** a live observation |
| 14 | Player match statistics | `trial_stats.py` | `not_started` | mock rehearsal only: [trial-reports/examples/trial_stats.json](trial-reports/examples/trial_stats.json) — **not** a live observation |
| 15 | Data update timing before, during, and after matches | `trial_stats.py` | `not_applicable` | *requires live observation — see below* |
| 16 | Post-match corrections | `trial_stats.py` | `not_applicable` | *requires live observation — see below* |
| 17 | API rate limits and pagination | `trial_auth.py` | `observed` | `x-ratelimit-limit: 2500`, `x-ratelimit-remaining` on every response (per entity, hourly; body also carries `rate_limit.resets_in_seconds`); no `x-ratelimit-reset`, no `Retry-After`, no 429 seen (retry pacing still unmeasured). Pagination walked 3 pages (`leagues?per_page=3`), `next_page` is a URL (#408). Evidence: [trial-reports/live/2026-10-11-routes.md](trial-reports/live/2026-10-11-routes.md) |
| 18 | Stable provider IDs | `trial_mapping.py` | `not_started` | |
| 19 | FPL identity-match rate | `trial_mapping.py` | `not_started` | |
| 20 | Raw-data storage and derived-data licensing | *document, not script* — [TRIAL_LICENSING_CHECKLIST.md](TRIAL_LICENSING_CHECKLIST.md) | `not_started` | |

Every objective has an owning script or document. Per the FI-8 S1 DoD, an
objective with no owner is a blocker — if a future edit adds one, give it an
owner in the same change.

### Objectives 15 and 16 are different in kind

Update timing and post-match corrections **cannot be measured in `--mock` mode at
all**. They require repeated live observation of the same fixture across a real
match. `trial_stats.py` ships only the recording scaffold: a stable pre/during/post
sample schema and a diff between successive snapshots.

Before opening weekend they are legitimately `not_applicable`. Marking them
`observed` from mock runs would be false. They are the objectives most likely to
be quietly skipped, because the window to measure them is the narrowest — the
2026-08-22 opening weekend.

## Daily log

One row per trial day. Keep it short; the detail belongs in the report artifacts.

| Date | Objectives moved | Blockers | Notes |
|---|---|---|---|
| 2026-10-11 | 1, 17 observed | none | Token now sees the trial plan (Starter + Euro Club Tournaments); 7 leagues. Found: `next_page` is a URL (#408) and 8 of 15 families are includes/nested routes, not root endpoints (remap in #409). 15/15 families reachable. ~440 calls used by end of day 0 (limit 2500/h per entity). #126 rescue merged (#407). |
| 2026-10-11 (earlier, superseded) | none (1, 17 blocked) | Token saw only 4 free-plan leagues (no PL); 14 of 15 endpoint families unavailable | Historical: diagnosis was the token plan, resolved by Leo activating Starter + Euro Club Tournaments. See [day0.md](trial-reports/live/2026-10-11-day0.md). |

## Open questions raised during the trial

Payload-shape mismatches are **plan-revision requests**, fixed only inside
`sportmonks-client` (plan §17). Do not answer an open question by assumption in
code — record it here and stop.

| # | Question | Raised | Status | Resolution |
|---|---|---|---|---|
| | | | | |

## Partial-fallback decision

Per §14.4: if only lineups are weak, a lineups-only cheaper source may be
reconsidered. **That decision is recorded here**, not in a commit message or a
chat log.

*No decision recorded.*

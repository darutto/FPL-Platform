# TRIAL_STATUS.md — Sportmonks trial dashboard

**Template.** Created by FI-8 S1. Updated **daily** during the FI-9 trial
(2026-10-11 to 2026-10-25) and closed out with the go/no-go decision.

This file is the §14.1 trial-dashboard artifact. It is the single place a reader
looks to answer "how is the trial going, and what do we still not know?"

| | |
|---|---|
| Trial start | 2026-10-11 |
| Trial end | 2026-10-25 03:09 UTC (Starter `Trialing until`, from the API's own subscription block); decision 23–24 Oct |
| Days elapsed | 1 |
| Last updated | 2026-10-11 (day 1) |
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
| 2 | Premier League fixtures | `trial_fixtures.py` | `observed` | 380 fixtures for 2026/27 (season 28083, league 8). [day1](trial-reports/live/2026-10-11-day1.md) |
| 3 | Cross-competition fixtures for Premier League clubs | `trial_fixtures.py` | `observed` | 20 clubs, 874 fixtures; outside PL: UCL, UEL, UECL, Carabao. [day1](trial-reports/live/2026-10-11-day1.md) |
| 4 | Team and squad completeness | `trial_squads.py` | `observed` | 20 clubs, 544 squad rows, required fields 544/544. [day1](trial-reports/live/2026-10-11-day1.md) |
| 5 | Current player records | `trial_squads.py` | `observed` | 544 players, 544/544 squad rows resolve (via squads include, #410). [day1](trial-reports/live/2026-10-11-day1.md) |
| 6 | Confirmed starters and substitutes | `trial_lineups.py` | `observed` | GW6: 198 starters (`type_id` 11) + 108 bench (12). [day1](trial-reports/live/2026-10-11-day1.md) |
| 7 | Formation strings | `trial_lineups.py` | `observed` | 18 formation rows over 9 fixtures, 3 distinct strings. [day1](trial-reports/live/2026-10-11-day1.md) |
| 8 | Formation-grid or lineup-position fields | `trial_lineups.py` | `observed` | 198/198 starters carry `formation_field` (1100/1100 over GW1–5); bench has none, reported apart as expected (denominator = starters, decided by review, #412). Column is absolute along the touchline, mirrored for the away team; 420/420 starters the provider labels Right/Left Back or Midfield sit in the predicted cell (GW1–6, 59 matches). Left/right of central roles is inference. **Partial human validation (criterion b):** Leo checked Arsenal's side assignments for Arsenal–Leeds (2026-10-10) against a Sofascore line-up screenshot (source: Leo's capture): Konsa centre-right, Gabriel centre-left, Rice right, Lewis-Skelly left, Saka right, Madueke left — all as inferred. Liverpool and City pending. [grid check for Leo](trial-reports/live/2026-10-11-grid-check-for-leo.md); [day1](trial-reports/live/2026-10-11-day1.md) |
| 9 | Detailed position identifiers | `trial_lineups.py` | `observed` | detailed position found under `lineups.detailedPosition`: 198/198 starters, 9 distinct values (Goalkeeper, Centre Back, Right/Left Back, Central/Attacking Midfield, Right/Left Midfield, Attacker); bench none. `position_id` stays the 4-way family. #412. [day1](trial-reports/live/2026-10-11-day1.md) |
| 10 | Substitution relationships and minutes | `trial_lineups.py` | `observed` | 58 substitution events, 58 complete (on/off/minute). [day1](trial-reports/live/2026-10-11-day1.md) |
| 11 | Injuries and suspensions | `trial_injuries.py` | `degraded` | fixtures-level: 42 injuries + 3 suspensions in window, 0/42 freshness field (the script still reports `degraded`). Club-level current list wired as `trial_sidelined.py` (#412): baseline pass 64 open rows over 19 clubs (54 injury, 10 suspended); polling for first-seen latency (criterion c) under way. [day1](trial-reports/live/2026-10-11-day1.md) |
| 12 | Coaches and manager records | `trial_injuries.py` | `observed` | root `coaches` answers; not club-filtered (bounded read). [day1](trial-reports/live/2026-10-11-day1.md) |
| 13 | Fixture-level team statistics | `trial_stats.py` | `not_started` | mock rehearsal only: [trial-reports/examples/trial_stats.json](trial-reports/examples/trial_stats.json) — **not** a live observation |
| 14 | Player match statistics | `trial_stats.py` | `not_started` | mock rehearsal only: [trial-reports/examples/trial_stats.json](trial-reports/examples/trial_stats.json) — **not** a live observation |
| 15 | Data update timing before, during, and after matches | `trial_stats.py` | `not_applicable` | *requires live observation — see below* |
| 16 | Post-match corrections | `trial_stats.py` | `not_applicable` | *requires live observation — see below* |
| 17 | API rate limits and pagination | `trial_auth.py` | `observed` | `x-ratelimit-limit: 2500`, `x-ratelimit-remaining` on every response (per entity, hourly; body also carries `rate_limit.resets_in_seconds`); no `x-ratelimit-reset`, no `Retry-After`, no 429 seen (retry pacing still unmeasured). Pagination walked 3 pages (`leagues?per_page=3`), `next_page` is a URL (#408). Evidence: [trial-reports/live/2026-10-11-routes.md](trial-reports/live/2026-10-11-routes.md) |
| 18 | Stable provider IDs | `trial_mapping.py` | `observed` | 544 players in two reads of the 20 squads, 0 provider_id changes (same run, seconds apart). Across days: snapshot saved; repeat scheduled 24–48 h later (2026-10-12/13). [mapping](trial-reports/live/2026-10-11-mapping.md) |
| 19 | FPL identity-match rate | `trial_mapping.py` | `observed` | gate over FPL 2026/27 elements with minutes>0: 413/430 = 96.0465% (≥95%) after the guarded display-name second pass (#418): 405 full name+birth date, 87 surname+birth date, 2 full name unique, 26 display name+birth date; 0 first-pass pairs changed, 0 rejected. Aside: all FPL 520/667, Sportmonks pool 520/544. 17 left for the manual queue (post-queue target ≥99%). [mapping](trial-reports/live/2026-10-11-mapping.md) |
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
| 2026-10-11 (day 1) | 2, 3, 4, 5, 6, 7, 9, 10, 12 observed; 8, 11 degraded | none | Live runs of fixtures, squads, lineups, injuries. 8 degraded is a denominator effect (grid on every starter, none on the bench). Grid semantics: col is absolute along the touchline (home col 1 = right, away mirrored). Found and fixed: players root returned the whole database (#410). ~215 requests today, ~650 in total. |
| 2026-10-11 (day 1, later) | 8, 9 observed | none | Decisions applied (#412): grid/position measured over starters; `lineups.detailedPosition` found (198/198 starters); `current_sidelined` polling wired, baseline 64 rows. Grid rule cross-checked 420/420 against the provider's own side-labelled positions; human check of central roles awaiting Leo. |
| 2026-10-11 (day 1, human check) | 8 (partial human validation) | none | Leo confirmed Arsenal's inferred sides for Arsenal–Leeds against Sofascore (his screenshot); Liverpool and City pending. Sidelined polling continues on the builder session's cron; extension after 18 Oct is Leo's call. |
| 2026-10-11 (day 1, mapping) | 18 observed (same run), 19 unmet | none | Candidates moved to the current FPL bootstrap; gate denominator = FPL elements with minutes>0. 19 at 90.4651%; causes classified; relaxation proposal (display-name second pass, 96.05%) awaits the review chat. ~40 Sportmonks requests per run. |
| 2026-10-11 (day 1, mapping pass) | 19 observed | none | Display-name second pass approved and shipped with its guards (#418); 413/430 = 96.0465%. 17 elements in the manual queue (local file with causes); no automatic resolution of them. |

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

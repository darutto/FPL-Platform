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
| 4 | Team and squad completeness | `trial_squads.py` | `observed` | 20 clubs, 544 squad rows, required fields 544/544. [day1](trial-reports/live/2026-10-11-day1.md) **Caveat:** at least 2 FPL players with PL minutes are in lineups but in no squad (5 more left on deadline day and are correctly absent); licensing question 15. [mapping](trial-reports/live/2026-10-11-mapping.md) |
| 5 | Current player records | `trial_squads.py` | `observed` | 544 players, 544/544 squad rows resolve (via squads include, #410). [day1](trial-reports/live/2026-10-11-day1.md) **Caveat:** at least 2 FPL players with PL minutes are in lineups but in no squad (5 more left on deadline day and are correctly absent); licensing question 15. [mapping](trial-reports/live/2026-10-11-mapping.md) |
| 6 | Confirmed starters and substitutes | `trial_lineups.py` | `observed` | 9 completed GW6 fixtures: 360 lineup rows, 198 starters (`type_id` 11) + 162 bench (12). **Corrected 2026-10-11:** the first figure (306 rows) counted three fixtures not yet played, whose provisional lineups carry the same `type_id`. [provisional lineups](trial-reports/live/2026-10-11-provisional-lineups.md); [day1](trial-reports/live/2026-10-11-day1.md) |
| 7 | Formation strings | `trial_lineups.py` | `observed` | 18 formation rows over 9 completed fixtures, 3 distinct strings. [provisional lineups](trial-reports/live/2026-10-11-provisional-lineups.md); [day1](trial-reports/live/2026-10-11-day1.md) |
| 8 | Formation-grid or lineup-position fields | `trial_lineups.py` | `observed` | 198/198 starters carry `formation_field` (1100/1100 over GW1–5); bench has none, reported apart as expected (denominator = starters, decided by review, #412). Column is absolute along the touchline, mirrored for the away team; 420/420 starters the provider labels Right/Left Back or Midfield sit in the predicted cell (GW1–6, 59 matches). Left/right of central roles is inference. **Partial human validation (criterion b):** Leo checked Arsenal's side assignments for Arsenal–Leeds (2026-10-10) against a Sofascore line-up screenshot (source: Leo's capture): Konsa centre-right, Gabriel centre-left, Rice right, Lewis-Skelly left, Saka right, Madueke left — all as inferred. Liverpool and City pending. [grid check for Leo](trial-reports/live/2026-10-11-grid-check-for-leo.md); [day1](trial-reports/live/2026-10-11-day1.md) |
| 9 | Detailed position identifiers | `trial_lineups.py` | `observed` | detailed position found under `lineups.detailedPosition`: 198/198 starters, 9 distinct values (Goalkeeper, Centre Back, Right/Left Back, Central/Attacking Midfield, Right/Left Midfield, Attacker); bench none. `position_id` stays the 4-way family. #412. [day1](trial-reports/live/2026-10-11-day1.md) |
| 10 | Substitution relationships and minutes | `trial_lineups.py` | `observed` | 85 substitution events over the 9 completed fixtures, 85 complete (on/off/minute). **Corrected:** first figure 58 (three unplayed fixtures counted). [provisional lineups](trial-reports/live/2026-10-11-provisional-lineups.md); [day1](trial-reports/live/2026-10-11-day1.md) |
| 11 | Injuries and suspensions | `trial_injuries.py` | `degraded` | fixtures-level: 42 injuries + 3 suspensions in window, 0/42 freshness field (the script still reports `degraded`). Club-level current list wired as `trial_sidelined.py` (#412): baseline pass 64 open rows over 19 clubs (54 injury, 10 suspended); polling for first-seen latency (criterion c) under way. [day1](trial-reports/live/2026-10-11-day1.md) |
| 12 | Coaches and manager records | `trial_injuries.py` | `observed` | root `coaches` answers; not club-filtered (bounded read). [day1](trial-reports/live/2026-10-11-day1.md) |
| 13 | Fixture-level team statistics | `trial_stats.py` | `not_started` | mock rehearsal only: [trial-reports/examples/trial_stats.json](trial-reports/examples/trial_stats.json) — **not** a live observation |
| 14 | Player match statistics | `trial_stats.py` | `not_started` | mock rehearsal only: [trial-reports/examples/trial_stats.json](trial-reports/examples/trial_stats.json) — **not** a live observation |
| 15 | Data update timing before, during, and after matches | `trial_stats.py` | `not_applicable` | *requires live observation — see below* |
| 16 | Post-match corrections | `trial_stats.py` | `not_applicable` | *requires live observation — see below* |
| 17 | API rate limits and pagination | `trial_auth.py` | `observed` | `x-ratelimit-limit: 2500`, `x-ratelimit-remaining` on every response (per entity, hourly; body also carries `rate_limit.resets_in_seconds`); no `x-ratelimit-reset`, no `Retry-After`, no 429 seen (retry pacing still unmeasured). Pagination walked 3 pages (`leagues?per_page=3`), `next_page` is a URL (#408). Evidence: [trial-reports/live/2026-10-11-routes.md](trial-reports/live/2026-10-11-routes.md) |
| 18 | Stable provider IDs | `trial_mapping.py` | `observed` | 544 players in two reads of the 20 squads, 0 provider_id changes (same run, seconds apart). Across days: snapshot saved; repeat scheduled 24–48 h later (2026-10-12/13). [mapping](trial-reports/live/2026-10-11-mapping.md) |
| 19 | FPL identity-match rate | `trial_mapping.py` | `observed` | official gate (minutes>0 and still in a PL club, rule from data, #421): 413/425 = 97.1765% (≥95%). Beside it, not counted: previous gate 413/430 = 96.0465%, all FPL 520/667, Sportmonks pool 520/544. 5 departed excluded by rule; 12 unresolved (10 resolvable by hand + 2 no squad holds); post-queue ceiling 423/425 = 99.5294%. [mapping](trial-reports/live/2026-10-11-mapping.md) |
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
| 2026-10-11 (day 1, close) | none moved | none | The 7 FPL players with minutes missing from squads: 5 departed on deadline day, 2 are squad completeness (question 15 added). Post-queue ≥99% of the identity gate is capped at 423/430 = 98.4% by data. Sidelined series: baseline pass 2026-10-11T04:07Z (64 rows). Sportmonks requests so far ≈ 870 (estimate; limit 2500/h per entity, no 429). |
| 2026-10-11 (denominator) | 19 observed | none | Official gate redefined by the review chat to minutes>0 and still in a PL club (rule from data): 413/425 = 97.1765%; ceiling 423/425 = 99.5%; manual queue 12. ~55 more Sportmonks requests (≈ 925 in total, estimate). |
| 2026-10-11 (criterion f) | M1-M3 run on live data | none | Live-trial store built (88 clubs, 483 fixtures, 6 competitions; all `live_trial_local`, nothing published). Hold-out GW6 (6 fixtures): M2 role agreement 90.5% (86/95, 31 abstain), Arsenal sides Leo confirmed 6/6 actual and 5/5 predicted; M1 Brier 0.178 vs 0.229 base rate vs 0.185 raw share, covers 57% of squad members (abstains on players with no starts, 12/126 starters), miscalibrated in the 0.1-0.3 band; M3 matches the recomputed calendar 140/140 and congestion is higher with a continental fixture (5.90 vs 4.49). Review sample of 27 built; 10-player table awaits Leo. [report](trial-reports/live/2026-10-11-m1-m3.md) |
| 2026-10-11 (M2 baseline) | criterion f: M2 vs baseline | none | "Same position as his last start" beats M2 on the GW6 hold-out: role 94.7% vs 90.5%, flank 79.4% vs 73.5% on the same 95 starters (baseline right and module wrong 4, the reverse 0; baseline answers for 114 of 126). Reported as such; M2 is not changed during the trial; recency weighting and a shorter window are proposals for FI-10. [report](trial-reports/live/2026-10-11-m1-m3.md) |
| 2026-10-11 (human review, criterion f) | 10-player table answered | none | Leo, with Sofascore captures: 8 of 10 without objection; Ballard did not play (FPL: hamstring injury, unknown return) so the M1 miss is explained by availability, which the hold-out assumed for everyone: the D5 availability input is necessary; Lewis-Potter: the module's left full-back matches Sofascore, the provider's label (Attacking Midfield) is the discrepant one, a possible `detailedPosition` inaccuracy in one case; Meunier and De Cuyper are FPL defenders who play as wing-backs (the v3 map calls them half out of position; the label "winger" is not right). FI-10 proposal: DEF + Right/Left Midfield → `wing-back`. [report](trial-reports/live/2026-10-11-m1-m3.md) |
| 2026-10-11 (grid validation, partial negative) | criterion b | none | Leo checked Liverpool-City against Sofascore and the table did NOT match: lineups, central-defender and midfield sides, one winger pair. Cause: the table was built from provisional lineups (the fixture had not been played); Sportmonks serves them before kickoff with the same `type_id` 11 as confirmed ones, no marker and no bench, and rewrites them on confirmation. With the final lineups every side Leo listed matches the rule (Liverpool, Man City) and Arsenal-Leeds had matched. Day-1 lineup figures corrected (they counted three unplayed fixtures); `trial_lineups` now counts only completed fixtures (#433). Criterion (b)'s "confirmed lineups available pre-kickoff" is now measured by a watcher on how long before kickoff the final eleven appears. [provisional lineups](trial-reports/live/2026-10-11-provisional-lineups.md) |
| 2026-10-11 (manual confirmations) | mechanism ready | none | Human confirmations of mapping pairs are applied as explicit manual corrections: a file `--out/mapping/manual_pairs.json` (each entry: Sportmonks id, FPL id, who confirmed, date, evidence), validated, guarded (unknown id, player already paired, element already resolved or ambiguous, birth dates absent or different are all refused with a reason), method `manual_confirmation`, an append-only log of what each did, and the report shows the automatic rate and the rate with confirmations separately against the 95% gate and the 99% post-queue target. Of the 12 unresolved with minutes, one (the loanee in R10) is not a mapping case. |

## Risks and ceilings

| # | Risk | Evidence | State |
|---|---|---|---|
| R1 | The squad feed omits 2 active PL players with minutes (in lineups, in no squad); they stay in the identity gate's denominator, so the post-queue ceiling is **423 / 425 = 99.5 %** (≥ 99 % reachable, but only by resolving at least 8 of the 10 resolvable by hand). Five departed players are excluded by rule. | [mapping](trial-reports/live/2026-10-11-mapping.md) | Open: licensing question 15; the manual queue (12) awaits a human. |
| R2 | Injury latency (criterion c) has a resolution of one polling interval (8 h) because the sidelined rows carry no `updated_at`; a restart widens the bound for an absence first seen after a gap (`appeared between X and Y`). | `trial_sidelined.py`, `passes.ndjson` | Open: a session-scoped cron runs the passes; it expires after 7 days and must be relaunched on 18 Oct; no Windows task. |
| R3 | Left/right of central roles in the grid is inference, not a provider field. 420 / 420 side-labelled starters agree with the rule; Arsenal checked by Leo against Sofascore, Liverpool and City pending. | [grid check](trial-reports/live/2026-10-11-grid-check-for-leo.md) | Partially validated. |
| R4 | Provider-id stability across days is measured only within one run so far. | `trial_mapping.py` | Reads scheduled 2026-10-12 and 2026-10-13. |
| R5 | Several lists are read with an explicit page bound and are floors, not censuses (coaches, referees; fixtures only on the season sweep). | `CONTRACT.md` | Known. |
| R6 | Scheduling knowledge is assumed: fixture lists taken as published 2026-06-01 and results as known kickoff + 3 h, because the provider keeps no history of what was known when. Postponements are invisible; M1/M2 windows and M3 congestion can include a result a few hours before it was really known. | [m1-m3](trial-reports/live/2026-10-11-m1-m3.md) | Declared in the adapter docstring, CONTRACT and the PR; open. |
| R7 | M1 abstains for 43% of squad members (132 of 309), all with zero starts in the window, including 12 of 126 actual starters; availability in the hold-out is "available" for everyone; one gameweek of six fixtures. | [m1-m3](trial-reports/live/2026-10-11-m1-m3.md) | Re-run on 10 fixtures, then GW7. |
| R8 | A full-season feature build takes 936 s (the engine re-filters pandas frames per target). Correct, slow; every re-run after a new capture pays it. | PR #427 | Left alone; optimise only if the cadence needs it. |
| R9 | Provisional lineups: before kickoff the provider serves lineups with the same `type_id` as confirmed ones, no marker, no bench (22 rows), rewritten on confirmation (at 72 minutes before kickoff one fixture still differed from its final version). A consumer cannot tell them apart by the row; fixture state and the 40-row shape are the only signals found. When the final eleven appears before kickoff, and how often starters change, is being measured on every fixture watched. Question 16 to support. | [provisional lineups](trial-reports/live/2026-10-11-provisional-lineups.md) | Open; measured on Coventry-Newcastle (12 Oct) and GW7. |
| R10 | A departure the rule cannot see: a player confirmed gone by FPL ("Has joined Como on loan for the rest of the season", status unavailable) but not locatable in Sportmonks, so `departed_from_pl` finds no team history and does not exclude him. Today one such goalkeeper stays in the identity gate's denominator and in the manual queue. The rule is **not** changed during the trial; whether an FPL news line is enough evidence of a departure is a decision to take with Leo. | [mapping](trial-reports/live/2026-10-11-mapping.md) | Open; recorded as a case the rule does not cover. |

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

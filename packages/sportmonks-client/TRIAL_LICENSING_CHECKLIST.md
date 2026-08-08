# TRIAL_LICENSING_CHECKLIST.md — questions for Sportmonks support

**Send on trial day 1.** Created by FI-8 S1. This file satisfies the §14.1 gate
item *"Licensing question list (§14.3) ready to send to Sportmonks support on
day 1"*.

Fourteen questions: the twelve from `FOOTBALL_INTELLIGENCE_PLANNING_BRIEF.md`
§11.5, plus two audit-derived additions from the implementation plan §14.3.

## Why day 1 and not later

Questions 3–7 gate **§14.4 GO criterion (d)** — *licensing answers permit raw
storage + derived scores + subscriber display*. A NO on any of them is a NO-GO
regardless of how good the data turns out to be. Sending them on day 14 means
discovering a blocker after the engineering is spent.

Question 13 is the one most likely to decide the subscription: if formation-grid
semantics are undocumented or unstable, M2 collapses to `detailed_position` only,
which §14.4 lists as a NO-GO / re-evaluate condition. Support may answer it faster
than the trial can.

## Rules for filling this in

- **Answer** records what support actually said, quoted or closely paraphrased.
  Do not summarise a "yes" out of a hedge.
- An unanswered question is `answered: no`. It is never a tacit yes.
- Where an answer changes what we may build or store, note the consequence in the
  **Consequence** column and reflect it in [TRIAL_STATUS.md](TRIAL_STATUS.md)
  objective 20.
- If an answer contradicts something already built, that is a plan-revision
  request (plan §17) — stop and raise it, do not adapt the code silently.

## Questions

### From brief §11.5

| # | Question | Sent | Answered | Answer | Consequence |
|---|---|---|---|---|---|
| 1 | Does the trial include complete 2025/26 Premier League fixtures, lineups, formations, substitutions, injuries, suspensions, and player/team statistics? | no | no | | |
| 2 | May trial responses be persisted for integration testing after the trial ends? | no | no | | Governs whether FI-9 raw snapshots may remain checked in as fixtures |
| 3 | Does the Starter Football API license permit storing raw API data internally? | no | no | | **GO criterion (d)** — gates the owned raw store (§7) |
| 4 | May the platform combine Sportmonks data with FPL and Understat data? | no | no | | **GO criterion (d)** — the entire identity-crosswalk design assumes yes |
| 5 | May the platform calculate proprietary derived scores and contextual insights? | no | no | | **GO criterion (d)** — gates M1–M3 |
| 6 | May those derived insights be displayed to paying subscribers? | no | no | | **GO criterion (d)** — gates the product |
| 7 | What restrictions apply to exposing raw fields or provider identifiers? | no | no | | Design already exposes derived-only, no raw fields in contracts (§17); confirm that is sufficient |
| 8 | What are the retention rules if the subscription is cancelled? | no | no | | Determines whether the `purge` CLI must run on cancellation |
| 9 | Which exact competitions count toward the Starter plan? | no | no | | **GO criterion (e)** |
| 10 | Are FA Cup and EFL Cup separately selectable competitions? | no | no | | **GO criterion (e)** — Starter+1 must cover PL + UCL + FA Cup + EFL Cup |
| 11 | What recent historical seasons are included without the historical-data add-on? | no | no | | Determines whether owned history must be back-filled from other sources |
| 12 | Are confirmed lineups, detailed positions, injuries, suspensions, coaches, substitutions, and match statistics included in Starter? | no | no | | Distinguishes "the trial has it" from "the plan we would buy has it" |

### Audit-derived additions (plan §14.3)

| # | Question | Sent | Answered | Answer | Consequence |
|---|---|---|---|---|---|
| 13 | Are formation-grid coordinates documented semantics (slot indices vs pitch coordinates), and are they stable across competitions? | no | no | | **GO criterion (b) / NO-GO.** Every checked-in grid fixture carries `"status": "unverified_against_live"`; the docs do not say. If undocumented, M2 degrades to `detailed_position` only |
| 14 | What is the actual per-hour/per-entity rate limit on the trial vs the Starter plan? | no | no | | A trial limit that differs from Starter's makes trial pacing measurements non-transferable. Current strategy is controlled serialized scheduling plus reactive 429 handling; a proactive token bucket is conditional on this answer |

## Answer summary

Fill in once replies arrive. This is what feeds
[TRIAL_GO_NO_GO.md](TRIAL_GO_NO_GO.md) criterion (d) and (e).

| | |
|---|---|
| Questions sent | 0 / 14 |
| Questions answered | 0 / 14 |
| Raw storage permitted (Q3) | *unanswered* |
| Data combination permitted (Q4) | *unanswered* |
| Derived scores permitted (Q5) | *unanswered* |
| Subscriber display permitted (Q6) | *unanswered* |
| Grid semantics documented (Q13) | *unanswered* |

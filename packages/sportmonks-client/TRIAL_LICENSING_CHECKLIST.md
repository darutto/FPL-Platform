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
| 1 | Does the trial include complete 2026/27 Premier League fixtures, lineups, formations, substitutions, injuries, suspensions, and player/team statistics? | no | no | | |
| 2 | May trial responses be persisted for integration testing after the trial ends? | yes | partial | Reply covers data lawfully retrieved **while subscribed**: it may be retained after cancellation (subject to ToS). It does not say anything specific about responses captured during the *trial* (source: Sportmonks support, written reply 2026-10-21) | Retention of data pulled under a paid subscription is fine; trial captures stay local-only as before (no raw payloads in git) until the vendor says otherwise for trial data *(before: Governs whether FI-9 raw snapshots may remain checked in as fixtures)* |
| 3 | Does the Starter Football API license permit storing raw API data internally? | yes | yes | Yes: we may store Sportmonks data in our own database and use it in the app (source: Sportmonks support, written reply 2026-10-21) | **GO criterion (d): passes.** The owned raw store (§7) is allowed *(before: **GO criterion (d)** — gates the owned raw store (§7))* |
| 4 | May the platform combine Sportmonks data with FPL and Understat data? | yes | yes | Yes: we may combine it with other sources (e.g. FPL public data) and compute our own scores, models and insights (source: Sportmonks support, written reply 2026-10-21) | **GO criterion (d): passes.** The identity-crosswalk design stands *(before: **GO criterion (d)** — the entire identity-crosswalk design assumes yes)* |
| 5 | May the platform calculate proprietary derived scores and contextual insights? | yes | yes | Yes: we may compute our own scores, models and insights from it (source: Sportmonks support, written reply 2026-10-21) | **GO criterion (d): passes.** M1–M3 are allowed *(before: **GO criterion (d)** — gates M1–M3)* |
| 6 | May those derived insights be displayed to paying subscribers? | yes | yes | Yes: we may show derived insights to paying subscribers (source: Sportmonks support, written reply 2026-10-21) | **GO criterion (d): passes.** Subscriber display is allowed *(before: **GO criterion (d)** — gates the product)* |
| 7 | What restrictions apply to exposing raw fields or provider identifiers? | yes | yes | We may display individual Sportmonks fields and Sportmonks IDs inside the product. We must NOT resell or redistribute the raw feed as a standalone data product or service, expose the API, or let customers reconstruct and redistribute the underlying feed (source: Sportmonks support, written reply 2026-10-21) | Derived-only contracts are more than sufficient. Design rules that follow: no endpoint (public or authenticated) passes raw Sportmonks payloads through, and no bulk export of Sportmonks-sourced tables *(before: Design already exposes derived-only, no raw fields in contracts (§17); confirm that is sufficient)* |
| 8 | What are the retention rules if the subscription is cancelled? | yes | yes | Data lawfully retrieved while subscribed may be retained after cancellation (subject to ToS) (source: Sportmonks support, written reply 2026-10-21) | The `purge` CLI does not have to run on cancellation by licence; keep it for hygiene, not obligation *(before: Determines whether the `purge` CLI must run on cancellation)* |
| 9 | Which exact competitions count toward the Starter plan? | yes | yes | Starter is the Premier League plan. Champions League, Europa League and Conference League need the separate Euro Club Tournaments add-on (Regular/Advanced), which carries full Football API features for those competitions (source: Sportmonks support, written reply 2026-10-21) | **GO criterion (e) as written is NOT met by Starter alone** (it asks PL + UCL + FA Cup + EFL Cup). Leo decided on 2026-10-21 not to buy Euro Club Tournaments and to cover the other competitions with public data (see `trial-reports/live/2026-10-21-otras-competiciones-fuentes-publicas.md`); criterion (e) is replaced by that decision in `decision-draft.md` (TRIAL_GO_NO_GO.md, the pre-registered rule, stays untouched) *(before: **GO criterion (e)**)* |
| 10 | Are FA Cup and EFL Cup separately selectable competitions? | yes | partial | FA Cup and Carabao Cup can return the same lineup/fixture data types, but coverage varies by fixture and season with no completeness guarantee. The reply does not say they are selectable as separate competitions or that they are included in the Starter price (source: Sportmonks support, written reply 2026-10-21) | Treat cup fixtures, lineups, formations and grids as best-effort and degrade gracefully when missing; do not build anything that needs a cup row to exist. Cup calendar comes from public data (same proposal as Q9) *(before: **GO criterion (e)** — Starter+1 must cover PL + UCL + FA Cup + EFL Cup)* |
| 11 | What recent historical seasons are included without the historical-data add-on? | yes | yes | The latest 3 seasons are included by default; older seasons need the Historical Data add-on (source: Sportmonks support, written reply 2026-10-21) | Owned history older than 3 seasons has to come from other sources (or the add-on, not bought) *(before: Determines whether owned history must be back-filled from other sources)* |
| 12 | Are confirmed lineups, detailed positions, injuries, suspensions, coaches, substitutions, and match statistics included in Starter? | yes | partial | Starter includes, with no add-on: PL lineups, formations, `formation_field`/grid, detailed player positions, predicted lineups, `lineup_confirmed` metadata, sidelined players (injuries and suspensions) and squads. The reply does not mention coaches, substitutions or match statistics. Match Facts, Pressure Index & xG, Predictions and Odds are trial add-ons and are NOT part of Starter (source: Sportmonks support, written reply 2026-10-21) | What we would buy has what M1–M3 use (positions, grid, lineups, injuries/suspensions). Coaches, substitutions and match statistics stay unanswered (= not assumed). Code must not depend on includes from the removed add-ons *(before: Distinguishes "the trial has it" from "the plan we would buy has it")* |

### Audit-derived additions (plan §14.3)

| # | Question | Sent | Answered | Answer | Consequence |
|---|---|---|---|---|---|
| 13 | Are formation-grid coordinates documented semantics (slot indices vs pitch coordinates), and are they stable across competitions? | no | yes| yes| **Answered 2026-10-13 (support), documented partially.** Guide (https://docs.sportmonks.com/v3/tutorials-and-guides/tutorials/lineups-and-formations): `formation_field` = "line:line_position", a grid coordinate; `formation_position` 1 to 11, bottom to top. The away-side mirror is not written as a rule, but the guide's own example shows it (Real Madrid away: right-back 2:4, left-back 2:1) and agrees with our rule (420/420 side-labelled starters). Q13 closes as "documented partially; the mirror is an inference confirmed by their example and by our data". |
| 14 | What is the actual per-hour/per-entity rate limit on the trial vs the Starter plan? | yes | yes | 2,000 calls per entity per hour on Starter. The 2,500/hour seen in the trial applies only to special packages such as Euro Club Tournaments and International Tournaments (source: Sportmonks support, written reply 2026-10-21) | Trial pacing measurements transfer conservatively (Starter's limit is 20% lower, our planned runs are ~250 calls). Controlled serialized scheduling plus reactive 429 handling stays enough; the proactive token bucket is not motivated by this answer *(before: A trial limit that differs from Starter's makes trial pacing measurements non-transferable. Current strategy is controlled serialized scheduling plus reactive 429 handling; a proactive token bucket is conditional on this answer)* |
| 15 | How often are team squads updated, and why do players who have already played minutes in the Premier League this season not appear in their club's squad (`squads/teams/{id}`)? | no | yes| yes| **Answered 2026-10-13 (support).** The 2 missing are academy players: by design a youth player who plays with the first team is not in `squads/teams/{id}`; Sportmonks recommends identifying them from fixture lineups or livescores. Consequence: the 2 "unreachable" players can be matched by a mapping level that reads players from lineups (proposal with relaxation audit pending, not implemented). |
| 16 | Is a lineup distinguishable as predicted vs confirmed before kickoff, and when are official lineups published? | yes | yes | **Answered 2026-10-13 (support + guide https://docs.sportmonks.com/v3/tutorials-and-guides/tutorials/lineups-and-formations).** The guide says an include `metadata` carries a "lineup_confirmed" element: false while the lineup is the predicted one (from previous matches, suspensions and injuries), true when the club publishes it; "Official lineups are published approximately 1 hour before kickoff". Checked live the same day (2 calls, shapes only): `metadata` contains a `type_id 572` element `{confirmed: bool}`: false on a future fixture (22 lineup rows, no bench), true on a finished one (40 rows). The 22-row predicted lineup arrives without the "Expected Lineups" add-on, which we have not bought. | Criterion (b) is measured with the provider's own flag: the GW7 watcher logs it in every read (#455); the 40-row/state signals stay secondary. |

## Answer summary

This is what feeds [TRIAL_GO_NO_GO.md](TRIAL_GO_NO_GO.md) criterion (d) and (e).

| | |
|---|---|
| Questions sent | see the Sent column (the 2026-10-21 reply answers 2–12 and 14; Q1 is not addressed) |
| Questions answered | technical 13, 15, 16 answered 2026-10-13; licensing/plan/limits 2–12 and 14 answered 2026-10-21 (Sportmonks support, written reply); Q1 unanswered; Q10 and Q12 only partly |
| Raw storage permitted (Q3) | **yes** (2026-10-21) |
| Data combination permitted (Q4) | **yes** (2026-10-21) |
| Derived scores permitted (Q5) | **yes** (2026-10-21) |
| Subscriber display permitted (Q6) | **yes** (2026-10-21); individual fields and IDs may be shown; raw feed resale/redistribution is forbidden (Q7) |
| **Criterion (d)** | **passes** |
| Criterion (e) as written | **not met by Starter alone** (Starter = Premier League; UCL/UEL/UECL need Euro Club Tournaments, not buying; cups best-effort, Q9, Q10); **replaced by Leo's decision of 2026-10-21**: PL with Starter, other competitions from scheduled public data |
| Starter price / rate limit | €29/month (annual = recurring −20%); 2,000 calls/entity/hour (Q14) |
| Retention after cancellation (Q8) | allowed for data retrieved while subscribed (subject to ToS) |
| Grid semantics documented (Q13) | partially (2026-10-13): grid coordinate documented, away mirror shown by their example only |

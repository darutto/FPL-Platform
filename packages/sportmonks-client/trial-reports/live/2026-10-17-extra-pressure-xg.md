# Extra "Pressure Index & xG": what arrives for the Premier League 2026/27 (2026-10-17)

Field names, type names, counts and match-level aggregates only; no payloads. Raw responses in `trial-output/extras/`
(git-ignored). User-facing use depends on licensing questions 2–11 (unanswered).

**Premise check passed**: `include=pressure`, `include=xGFixture`, `include=lineups.xGLineup`, `expected/fixtures` and
`expected/lineups` all answer 200 with data (403 before the add-on).

## The short answer

1. **Pressure is a per-minute, per-team integer 0–100.** Rows `{id, fixture_id, participant_id, minute, pressure}`;
   exactly two rows per minute (one per team), minutes 1 to 95–108 (stoppage time included). 12 of 12 finished Premier
   League fixtures probed returned it, from the opening day (21 Aug) to today's GW7 matches. Future fixtures: 0 rows.
2. **xG is complete at team level** for **64 of 64** finished 2026/27 Premier League fixtures (bulk endpoint
   `expected/fixtures`, see below), and **at player level only for players who took a shot** (11–19 of ~40 lineup rows).
3. **There is no xG per shot and no coordinates.** `include=shots` answers 404 ("include does not exist"); xG rows carry
   only `type_id`, `data.value`, and (team level) `location`/`participant_id`. Events carry no xG. Shot maps with
   xG are not possible from this extra. The earlier ballCoordinates have no team or player (inventory #457).
4. **Player-level types are three only**: `5304 EXPECTED_GOALS`, `5305 EXPECTED_GOALS_ON_TARGET`,
   `9685 SHOOTING_PERFORMANCE`. No xA, no npxG, no xGChain at player level. (FPL season totals give xA already; per-match
   xA would have been the new thing, and it is not there.)
5. Player xG adds up to the team xG (Liverpool–Man City: players 1.27 and 1.06, team rows 1.27 and 1.06), so a
   per-player split of the team figure is consistent.

## Team-level xG types (`xGFixture`, two rows per type: home and away)

| type_id | developer_name | on |
|---|---|---|
| 5304 | EXPECTED_GOALS | every fixture |
| 5305 | EXPECTED_GOALS_ON_TARGET | every fixture |
| 7939 | EXPECTED_POINTS | every fixture |
| 7941 / 7942 | EXPECTED_GOALS_FREE_KICKS / CORNERS | every fixture |
| 7943 | EXPECTED_NON_PENALTY_GOALS | every fixture |
| 7944 / 7945 | EXPECTED_GOALS_SET_PLAY / OPEN_PLAY | every fixture |
| 9685 | SHOOTING_PERFORMANCE | every fixture |
| 9687 | EXPECTED_GOALS_AGAINST | every fixture |
| 7940 | EXPECTED_GOALS_PENALTIES | optional: 4 of 10 fixtures probed (all four GW7 matches, none of GW1–6) |
| 9684 | EXPECTED_GOALS_DIFFERENCE | optional: same 4 of 10 |
| 9686 | EXPECTED_GOALS_PREVENTED | optional: 5 of 10 (the four GW7 matches and one GW3 match) |

The three optional types may be new since GW7 (none on GW1–6 probes except one); re-probe before building on them.

Rows per fixture: 20 (10 types), 22 or 26 where the three optional types appear. All types appear only after the
match; a future fixture returns 0 rows.

## Coverage

- `expected/fixtures` (bulk, 50 rows per page, no working league filter: it returned 152 fixtures across leagues for
  `filters=fixtureLeagues:8`, 64 of them our Premier League 2026/27 finished matches): **64 of 64 finished have team xG.**
  No unfinished fixture has any.
- Pressure and player xG, 12 fixtures probed (6 spread evenly across GW1–GW6, 4 from GW7, plus Liverpool–City and
  Arsenal–Leeds): **12 of 12**. Not exhaustive: the check over all 64 was skipped to save calls; at this hit rate the
  90 % bar (criterion 1) is met for finished matches. Bulk `expected/lineups` exists (fields `fixture_id, lineup_id,
  player_id, team_id, type_id, data`), 50 rows per page, not paged through.
- **Nothing before kickoff.** A pre-match "expected" use (projected xG for the next game) does not exist here; that is
  the predictions extra.

## Pressure: shape and values (for the dominance chart)

| Fixture (finished) | Rows | Minutes | Mean pressure A / B | Minutes ≥ 50 A / B | Strongest 10-min window |
|---|---|---|---|---|---|
| Liverpool – Man City (11 Oct) | 190 | 1–95 | 7.2 / 21.7 | 2 / 16 | City, min 71–80, mean 75.8 |
| Arsenal – Leeds (10 Oct) | 198 | 1–99 | 15.2 / 10.3 | 7 / 6 | Arsenal, min 71–80, mean 36.4 |

Across the 12 fixtures: team mean per minute 11–15, per-minute max 62–100, never a missing minute, never a duplicate
minute. The series is spiky (most minutes low, a few near 100), so a chart should smooth (rolling 5–10 minutes) before
drawing; the raw line is noisy. "Dominated from 71' to 80'" is computable directly.

## Examples for layout (match-level, finished)

| Fixture | xG home – away | xGOT home – away | xPTS home – away | open-play xG home – away |
|---|---|---|---|---|
| Liverpool – Man City | 1.27 – 1.06 | 1.37 – 1.60 | 1.51 – 1.21 | 0.46 – 1.00 |
| Arsenal – Leeds | 2.13 – 0.72 | 3.08 – 1.21 | 2.28 – 0.53 | 2.06 – 0.63 |

- Player level, Liverpool–Man City: 15 players with xG, 11 with xGOT and shooting performance, out of 40 lineup rows.
  Value shape: `data.value`, a float with four decimals (e.g. one player at 0.46).
- "Bad luck" signal (xGOT high, no goal) is computable from `5305` minus actual goals, per player and per match.
- Last 5 matches per player means 5 fixture calls per player today (or paging `expected/lineups`, which carries
  no kickoff date: join to fixtures by `fixture_id`).

## Verdict for criterion 1

Finished Premier League matches: **yes** (64/64 team xG, 12/12 pressure and player xG). Pre-match: **no** (by design).
The visible, new-to-FPL pieces are the pressure chart and per-match player xG/xGOT; there is no per-shot data, so
no shot map. Cost question for criterion 3: these two uses must carry €24/month on their own.

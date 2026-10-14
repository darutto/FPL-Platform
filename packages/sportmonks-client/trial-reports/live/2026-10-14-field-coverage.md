# Sportmonks field coverage on finished Premier League fixtures (2026-10-14)

Aggregate only: counts and percentages, no names, no ids, no payload values. Raw reads stay local
(`trial-output/coverage/`, gitignored). **The coverage was measured with a separate read, not from the capture**: the
`gw6-final` capture keeps only one player stat (`MINUTES_PLAYED`) and no team statistics, trends, ball coordinates,
referees or weather, so one read of the 60 finished Premier League fixtures (GW1 to GW6) was made with
`lineups.details`, `statistics`, `trends`, `ballCoordinates`, `referees.referee` and `weatherReport`
(8 requests, plus 6 to resolve 12 stat names the first inventory had not met: 14 in total). Companion to
[the data inventory](2026-10-14-data-inventory.md), which listed what exists; this says how often it is there.

## How to read the percentages

- **A player appearance** is a start or a substitute with minutes: 1,853 appearances (1,320 starts, 533 substitute
  appearances; 120 goalkeeper, 584 defender, 768 midfielder, 381 forward appearances). Position is the lineup row's
  `position_id` (24 to 27: goalkeeper, defender, midfielder, attacker).
- **The provider sends only the stats that are not zero.** Every stat that is present is non-zero in 100 % of its rows
  (except a few team-level counters), so *present* means "happened at least once" and **absent means zero, not
  missing**. A 41 % on key passes is a real distribution (59 % of appearances had none), not a hole. Cross-check: the sum
  of the player `GOALS` stat equals the goal events in 53 of 60 fixtures (the other 7 were not examined one by one;
  own goals are the likely difference); assists stat total 127 against 125 goal events with an assister. Nothing here
  can tell a zero from a stat the provider failed to compute, so a stat's *accuracy* is not measured.
- Where a percentage is low only because the stat does not apply (saves for outfield players), read the column of the
  position it applies to.

## The stats for the mockups

Share of appearances where the stat is recorded, by position (GK goalkeeper, DEF, MID, FWD), for starters and for
substitutes. Last column: share of the present rows that are non-zero.

﻿| Stat | All % | GK % | DEF % | MID % | FWD % | Starters % | Subs % | Non-zero % of present |
|---|---|---|---|---|---|---|---|---|
| RATING | 97 | 100 | 96 | 98 | 93 | 100 | 88 | 100 |
| KEY_PASSES | 41 | 4 | 31 | 55 | 39 | 50 | 20 | 100 |
| CHANCES_CREATED | 41 | 4 | 31 | 55 | 39 | 49 | 19 | 100 |
| BIG_CHANCES_CREATED | 11 | 2 | 6 | 16 | 11 | 14 | 4 | 100 |
| BIG_CHANCES_MISSED | 10 | 0 | 5 | 11 | 20 | 13 | 4 | 100 |
| TOUCHES | 100 | 100 | 100 | 100 | 99 | 100 | 99 | 100 |
| SUCCESSFUL_DRIBBLES | 31 | 6 | 21 | 39 | 37 | 36 | 18 | 100 |
| DRIBBLED_ATTEMPTS | 47 | 7 | 34 | 59 | 58 | 54 | 32 | 100 |
| DUELS_WON | 84 | 46 | 90 | 88 | 79 | 92 | 64 | 100 |
| TACKLES_WON | 40 | 1 | 50 | 48 | 20 | 48 | 20 | 100 |
| INTERCEPTIONS | 37 | 1 | 55 | 41 | 10 | 45 | 15 | 100 |
| BALL_RECOVERY | 82 | 100 | 85 | 86 | 65 | 94 | 54 | 100 |
| PASSES_IN_FINAL_THIRD | 80 | 96 | 88 | 84 | 53 | 91 | 51 | 100 |
| MINUTES_PLAYED | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |

What this means for a design:

- **Rating is the dependable one**: 100 % of starters and 88 % of substitute appearances (the 63 unrated substitutes
  played a median of 2 minutes; the 470 rated ones a median of 18). 1,790 ratings, between 4.84 and 10.0, mean 6.82.
- **Touches, minutes, passes, possession lost and duels won** are there for practically everyone (84 to 100 %).
  **Ball recoveries (82 %) and passes in the final third (80 %)** are good for outfield players and a little lower for
  forwards (65 % and 53 %).
- **Key passes and chances created have the same coverage in every column (41 % of appearances, 55 % of midfielders)**; whether their values are equal was not checked, so check before showing both.
  **Big chances created (11 %) and missed (10 %)** are rare events: a per-player card can show a season total, not a
  match-by-match bar. Dribbles (31 % successful, 47 % attempted), tackles won (40 %) and interceptions (37 %) are
  moderate, and strongly position-dependent (interceptions 55 % of defenders, 10 % of forwards).
- Match-by-match series for a single player are dense only for rating, touches, passes, duels and recoveries.

## All other player stats

| Stat | All % | GK % | DEF % | MID % | FWD % | Starters % | Subs % | Non-zero % of present |
|---|---|---|---|---|---|---|---|---|
| CUMULATIVE_MINUTES_PLAYED | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| PASSES | 99 | 100 | 99 | 100 | 97 | 100 | 97 | 100 |
| ACCURATE_PASSES | 98 | 100 | 98 | 99 | 94 | 100 | 93 | 100 |
| ACCURATE_PASSES_PERCENTAGE | 98 | 100 | 98 | 99 | 94 | 100 | 93 | 100 |
| POSSESSION_LOST | 96 | 99 | 96 | 97 | 94 | 100 | 87 | 100 |
| TOTAL_DUELS | 93 | 52 | 96 | 96 | 94 | 95 | 86 | 100 |
| DUELS_LOST | 84 | 8 | 87 | 92 | 88 | 89 | 72 | 100 |
| BACKWARD_PASSES | 84 | 0 | 90 | 93 | 83 | 89 | 72 | 100 |
| LONG_BALLS | 67 | 100 | 82 | 70 | 31 | 82 | 32 | 100 |
| GOALS_CONCEDED | 58 | 73 | 62 | 57 | 46 | 69 | 30 | 100 |
| CLEARANCES | 57 | 69 | 84 | 49 | 30 | 70 | 26 | 100 |
| TACKLES | 54 | 2 | 66 | 64 | 32 | 63 | 32 | 100 |
| LONG_BALLS_WON_PERCENTAGE | 52 | 98 | 65 | 51 | 21 | 66 | 18 | 100 |
| LONG_BALLS_WON | 52 | 98 | 64 | 51 | 20 | 66 | 17 | 100 |
| AERIALS_LOST | 51 | 2 | 62 | 47 | 58 | 58 | 34 | 100 |
| AERIALS_WON | 49 | 32 | 67 | 43 | 41 | 59 | 24 | 100 |
| DUELS_WON_PERCENTAGE | 49 | 18 | 60 | 46 | 50 | 58 | 28 | 100 |
| SHOTS_TOTAL | 48 | 0 | 37 | 58 | 62 | 56 | 31 | 100 |
| FOULS | 48 | 2 | 50 | 54 | 46 | 55 | 31 | 100 |
| FOULS_DRAWN | 44 | 18 | 40 | 50 | 47 | 53 | 22 | 100 |
| TOTAL_CROSSES | 43 | 0 | 38 | 58 | 37 | 49 | 29 | 100 |
| TACKLES_WON_PERCENTAGE | 40 | 1 | 50 | 48 | 20 | 48 | 20 | 100 |
| DISPOSSESSED | 35 | 1 | 20 | 46 | 45 | 39 | 23 | 100 |
| DRIBBLED_PAST | 33 | 2 | 33 | 42 | 24 | 39 | 16 | 100 |
| AERIALS | 31 | 0 | 47 | 23 | 33 | 39 | 11 | 100 |
| AERIALS_WON_PERCENTAGE | 31 | 0 | 47 | 23 | 33 | 39 | 11 | 100 |
| SHOTS_OFF_TARGET | 26 | 0 | 20 | 31 | 33 | 32 | 12 | 100 |
| SHOTS_ON_TARGET | 23 | 0 | 13 | 28 | 36 | 27 | 13 | 100 |
| SHOTS_BLOCKED | 21 | 0 | 14 | 27 | 27 | 25 | 11 | 100 |
| BLOCKED_SHOTS | 19 | 0 | 34 | 16 | 6 | 24 | 6 | 100 |
| ACCURATE_CROSSES | 19 | 0 | 15 | 28 | 12 | 23 | 8 | 100 |
| SUCCESSFUL_CROSSES_PERCENTAGE | 19 | 0 | 15 | 28 | 12 | 23 | 8 | 100 |
| TURN_OVER | 13 | 1 | 11 | 15 | 15 | 14 | 10 | 100 |
| YELLOWCARDS | 12 | 3 | 15 | 14 | 9 | 15 | 6 | 100 |
| OFFSIDES | 10 | 0 | 7 | 9 | 21 | 12 | 5 | 100 |
| GOALS | 8 | 0 | 4 | 9 | 16 | 10 | 4 | 100 |
| ASSISTS | 7 | 1 | 5 | 9 | 7 | 8 | 2 | 100 |
| CAPTAIN | 6 | 2 | 11 | 6 | 2 | 9 | 0 | 100 |
| SAVES | 6 | 94 | 0 | 0 | 0 | 9 | 0 | 100 |
| SAVES_INSIDE_BOX | 6 | 87 | 0 | 0 | 0 | 8 | 0 | 100 |
| ERROR_LEAD_TO_SHOT | 5 | 12 | 6 | 5 | 1 | 7 | 1 | 100 |
| GOALKEEPER_GOALS_CONCEDED | 5 | 73 | 0 | 0 | 0 | 7 | 0 | 100 |
| PUNCHES | 3 | 52 | 0 | 0 | 0 | 5 | 0 | 100 |
| GOOD_HIGH_CLAIM | 3 | 50 | 0 | 0 | 0 | 5 | 0 | 100 |
| HIT_WOODWORK | 2 | 0 | 1 | 3 | 3 | 3 | 1 | 100 |
| ERROR_LEAD_TO_GOAL | 1 | 4 | 2 | 1 | 0 | 2 | 1 | 100 |
| LAST_MAN_TACKLE | 1 | 1 | 4 | 0 | 0 | 2 | 0 | 100 |
| OFFSIDES_PROVOKED | 1 | 0 | 3 | 0 | 0 | 1 | 0 | 100 |
| CLEARANCE_OFFLINE | 1 | 0 | 3 | 0 | 0 | 1 | 0 | 100 |
| THROUGH_BALLS | 1 | 0 | 1 | 1 | 1 | 1 | 0 | 100 |
| MAN_OF_MATCH | 1 | 0 | 1 | 1 | 1 | 1 | 0 | 100 |
| PENALTIES_COMMITTED | 1 | 2 | 1 | 0 | 0 | 1 | 0 | 100 |
| PENALTIES_WON | 1 | 0 | 0 | 1 | 1 | 1 | 0 | 100 |
| PENALTIES_SCORED | 0 | 0 | 0 | 1 | 0 | 1 | 0 | 100 |
| OWN_GOALS | 0 | 1 | 1 | 0 | 0 | 1 | 0 | 100 |
| REDCARDS | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 100 |
| THROUGH_BALLS_WON | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 100 |
| YELLOWRED_CARDS | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 100 |
| PENALTIES_MISSES | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 100 |
| PENALTIES_SAVED | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 100 |

Stats the provider defines but this sample never sent: none of the 62 listed in the inventory; 12 more appear
(penalties won, committed, scored, missed and saved, hit woodwork, own goals, red card, yellow-red card, clearance off the
line, error leading to a goal, **man of the match**). Man of the match appears in 1 % of appearances.

## Team statistics

| Stat | Sides with the stat % | Non-zero % of present |
|---|---|---|
| CORNERS | 100 | 99 |
| SHOTS_OFF_TARGET | 100 | 99 |
| SHOTS_TOTAL | 100 | 100 |
| ATTACKS | 100 | 100 |
| DANGEROUS_ATTACKS | 100 | 100 |
| BALL_POSSESSION | 100 | 100 |
| BALL_SAFE | 100 | 100 |
| SHOTS_INSIDEBOX | 100 | 100 |
| SHOTS_OUTSIDEBOX | 100 | 98 |
| GOAL_KICKS | 100 | 100 |
| GOAL_ATTEMPTS | 100 | 100 |
| FREE_KICKS | 100 | 100 |
| FOULS | 100 | 100 |
| SAVES | 100 | 94 |
| SHOTS_BLOCKED | 100 | 95 |
| SUBSTITUTIONS | 100 | 100 |
| THROWINS | 100 | 100 |
| LONG_PASSES | 100 | 100 |
| TACKLES | 100 | 100 |
| PASSES | 100 | 100 |
| SUCCESSFUL_PASSES | 100 | 100 |
| SUCCESSFUL_PASSES_PERCENTAGE | 100 | 100 |
| SHOTS_ON_TARGET | 100 | 97 |
| TOTAL_CROSSES | 100 | 100 |
| ACCURATE_CROSSES | 100 | 99 |
| INTERCEPTIONS | 100 | 100 |
| DUELS_WON | 100 | 100 |
| DRIBBLED_ATTEMPTS | 100 | 100 |
| SUCCESSFUL_DRIBBLES | 100 | 100 |
| KEY_PASSES | 100 | 100 |
| SUCCESSFUL_DRIBBLES_PERCENTAGE | 100 | 100 |
| SUCCESSFUL_LONG_PASSES | 100 | 100 |
| SUCCESSFUL_LONG_PASSES_PERCENTAGE | 100 | 100 |
| TACKLES_WON | 100 | 100 |
| OFFSIDES | 98 | 82 |
| YELLOWCARDS | 97 | 88 |
| BIG_CHANCES_CREATED | 97 | 97 |
| BIG_CHANCES_MISSED | 97 | 88 |
| GOALS | 92 | 80 |
| ASSISTS | 83 | 70 |
| SUCCESSFUL_HEADERS | 82 | 100 |
| INJURIES | 67 | 60 |
| HIT_WOODWORK | 53 | 53 |
| PENALTIES | 15 | 56 |
| REDCARDS | 15 | 50 |
| YELLOWRED_CARDS | 5 | 50 |

40 of the 42 team stats of the inventory are present in 83 to 100 % of the 120 team sides (60 fixtures times two), so team
cards can lean on them; the exceptions are successful headers (82 %) and injuries (67 %). Four more types appear, sparse by
nature: hit woodwork 53 %, penalties 15 %, red cards 15 %, yellow-red cards 5 %. Possession, shots in and out of the box,
big chances, corners, passes and attacks are in practically every side.

## Trends, ball coordinates, referee, weather

| Source | Fixtures with data | Detail |
|---|---|---|
| `trends` | 60 / 60 | median 1,138 rows per fixture, 42 stat types per fixture (48 types in all), minutes up to a median of 95 |
| `ballCoordinates` | 60 / 60 | between 132 and 1,040 points per fixture (median 898); both periods present in 60 / 60; `x` lies between 0.01 and 1.01 (8 of 49,027 points fall just outside 0 to 1, `y` within a small margin of 0 to 1). One fixture has only 132 points: check it before drawing a heat map from every match |
| `referees` | 60 / 60 | always 4 officials (types 6 to 9), each with a name record |
| `weatherReport` | 60 / 60 | temperature, wind speed, humidity and description in 60 / 60 |

## Limits

- Six gameweeks, 60 fixtures, one season: percentages move as the season grows, and goalkeepers are only 120
  appearances. Positions are the lineup's position at the match, not a player's usual position.
- "Present" is presence in the response, not correctness. No stat was compared with a second source.
- This used a separate, one-off read; the capture and the trial's published numbers are unchanged.
- Whether a rating or a derived figure may be shown to subscribers is still licensing questions 5 and 6 (unanswered).

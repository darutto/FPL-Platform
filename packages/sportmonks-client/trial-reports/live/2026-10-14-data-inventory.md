# Sportmonks data inventory against FPL: what the Starter plan can show users (2026-10-14)

Field names, type names and counts only; no payload values. Read on the trial token (Starter + Euro Club Tournaments),
about 150 requests, shape-only probes: **2 finished Premier League fixtures** (Arsenal–Leeds, 10 Oct, and a second one the
same weekend) and **1 future fixture** (Everton–Chelsea, 17 Oct), plus one player and one club for the player and team
routes. Type names come from the `.type` includes (`statistics.type`, `lineups.details.type`, `events.type`, `trends.type`,
`metadata.type`); `core/types` and `types/{id}` answer 404 on this token. Nothing here is published and nothing is stored:
any user-facing use depends on the licensing questions 2–11, still unanswered (criterion d).

**How to read "Starter?"**: *yes* = the call returned data on our token. *403* = refused with "authentication failed"
(the plan does not include it; the message does not name an add-on, so that these are paid add-ons is read from the
provider's catalogue, not from the API). *empty* = accepted but nothing for that fixture (typically a future match).

## The short answer

1. **Per-player match statistics are rich and on Starter**: 62 player stat types per match (touches, key passes, big
   chances created, duels, dribbles, tackles, interceptions, clearances, possession lost, passes in the final third,
   through balls, **a match rating**, and more). FPL gives none of these per player and match.
2. **Per-team match statistics (42 types) and minute-by-minute "trends" (43 types, about 1,250 rows per match)** are on
   Starter. This is what a match-momentum chart is made of.
3. **ballCoordinates is on Starter** (about 900 ball positions per match, normalised x and y between 0 and 1). It has
   **no team, no player and no event type**, so it draws where the ball was, not who shot or passed.
4. **No shot map, no pass map, no xG on Starter.** Events carry only goals, substitutions, cards and VAR (no shot events,
   no coordinates). `xGFixture`, `lineups.xGLineup`, `expected/*`, `pressure`, `predictions`, `odds` and `premiumOdds` all
   answer 403.
5. **Predicted lineups arrive without any add-on** (22 rows, no bench) with the provider's own `LINEUP_CONFIRMED` flag
   (`metadata` type 572), a visible "the lineup is out" signal for the podcast.

## Fixture includes

| Include | Finished | Future | What it carries (fields) |
|---|---|---|---|
| `statistics` (+`.type`) | yes, 84–88 rows | empty | per team: `type_id`, `participant_id`, `location`, `data.value` |
| `events` (+`.type`) | yes, 14–19 | empty | `type_id`, `player_id`, `related_player_id`, `minute`, `result`, `info`, `addition`, `sub_type_id`, `period_id`. Types seen: GOAL, SUBSTITUTION, YELLOWCARD, REDCARD, VAR_CARD. No coordinates |
| `lineups.details` (+`.type`) | yes, 40 rows | 22 rows, `details` empty | per player: `formation_field`, `formation_position`, `position_id`, `jersey_number`, `details[]` = `type_id` + `data` (the 62 player stats) |
| `lineups.player` | yes | yes | the player record next to the lineup row |
| `metadata` (+`.type`) | yes, 12 | yes, 6 | NEUTRAL_VENUE, KICKOFF (who kicked off), FORMATION (home/away), HOME/AWAY_PARTICIPANT_COLORS, **LINEUP_CONFIRMED**, ATTENDANCE, HASHTAG, HAS_EXTRA_TIME, and four status flags (PREDICTION, PRESSURE, LIVE_PREDICTION; `PRESSURE_STATUS` and `PREDICTION_STATUS` describe the add-ons) |
| `formations` | yes | yes | formation string per side (the future one is the predicted formation) |
| `scores` | yes, 8 | empty | 1ST_HALF, 2ND_HALF, 2ND_HALF_ONLY, CURRENT per side |
| `periods` | yes | empty | `started`, `ended`, `minutes`, `time_added`, `period_length` (stoppage time) |
| `trends` (+`.type`) | yes, ~1,250 | empty | `type_id`, `participant_id`, `minute`, `value`, `period_id` |
| `ballCoordinates` | yes, ~900 | empty | `x`, `y` (0–1), `timer`, `period_id` only |
| `comments` | yes, ~130 | empty | text commentary: `minute`, `is_goal`, `is_important` |
| `venue` | yes | yes | name, `capacity`, `surface`, `latitude`, `longitude`, `city_name` |
| `weatherReport` | yes | empty | temperature, feels like, wind speed and direction, humidity, clouds, description, icon |
| `referees` (+`.referee`) | yes, 4 | yes, 4 | four officials per fixture (role in `type_id`), with the referee record (name, country) |
| `sidelined` | yes | yes | players out for the fixture (`player_id`, `sideline_id`, `type_id`) |
| `coaches`, `participants`, `round`, `stage`, `state`, `tvStations` | yes | yes | `tvStations`: broadcaster ids per country (71–179 rows) |
| `group` | empty | empty | not used in the league |
| `xGFixture`, `lineups.xGLineup` | **403** | **403** | expected goals (paid) |
| `pressure` | **403** | **403** | pressure index (paid) |
| `predictions`, `odds`, `premiumOdds` | **403** | **403** | probabilities and odds (paid) |
| `ratings` | 404 | 404 | not an include (the player rating is inside `lineups.details`, type RATING) |

## Other families

| Family | Result | Fields / notes |
|---|---|---|
| `players/{id}` | yes | name, birth date, height, weight, nationality, position and detailed position ids, image |
| player `statistics` (+`details.type`) | yes, 12 season rows | 36 types per season and team, among them RATING, KEY_PASSES, DRIBBLES, DUELS, TACKLES, SAVES, CLEANSHEET, MINUTES_PLAYED, APPEARANCES, LINEUPS, BENCH |
| player `transfers`, `teams`, `trophies`, `latest`, `lineups`, `metadata` | yes | career path, trophies, last matches (`latest`: 32 rows), full lineup history (629 rows) |
| player `sidelined` | 404 as an include | use `sidelined` by club (below) |
| `teams/{id}` `statistics` (+`details.type`) | yes, 45 rows | 49 types, among them POSSESSION, SHOTS, SHOT_CONVERSION_RATE, SHOT_ON_TARGET_PERCENTAGE, SCORING_MINUTES, HIGHEST_RATED_PLAYER, MOST_INJURED_PLAYERS, AVERAGE_PLAYER_HEIGHT, CLEANSHEET, BTTS, FAILED_TO_SCORE |
| team `upcoming`, `latest`, `rankings`, `coaches`, `players`, `sidelined` | yes | calendar across competitions (39 upcoming), last 40 results, current coach with start date |
| `squads/teams/{id}` (+`player`) | yes, 24 rows | `jersey_number`, `captain`, `start`, `end` (academy players are not listed, by design) |
| club `sidelined` (`teams/{id}?include=sidelined`) | yes | `category` (injury, suspension), `start_date`, `end_date`, `games_missed`, `completed` |
| `transfers`, `transfers/latest` | yes | from/to club, date, `amount` always empty on the rows seen |
| `standings/seasons/28083`, `standings/live/leagues/8` | yes, 20 rows | position, points, `details` rows keyed by `type_id` (not decoded) |
| `topscorers/seasons/28083` | yes | leaderboard rows keyed by `type_id` (which boards exist was not decoded) |
| `coaches`, `referees`, `venues/seasons` | yes | coach and referee records, stadium list with coordinates and capacity |
| `rounds/seasons`, `schedules/seasons` | yes | calendar by round (38 rounds) |
| `livescores/inplay` | accepted, empty (no match was live) | untested while live; the GW7 watcher can try it |
| `fixtures/head-to-head`, `statistics/rounds` | accepted, empty with the ids tried | not conclusive |
| `expected/fixtures`, `expected/lineups` | **403** | xG routes |
| `predictions/probabilities`, `predictions/value-bets` | **403** | paid |

## Resolved type names

**Per-team match statistics (42):** corners, shots total, on target, off target, blocked, inside and outside the box, goal
attempts, offsides, attacks, dangerous attacks, possession, "ball safe", fouls, free kicks, goal kicks, throw-ins, saves,
tackles, tackles won, interceptions, passes, successful passes (and %), long passes (and successful, %), successful
headers, crosses (total, accurate, %), duels won, dribble attempts, successful dribbles (and %), key passes, **big chances
created**, **big chances missed**, assists, goals, yellow cards, injuries, substitutions.

**Per-player match statistics (62):** minutes played, **rating**, touches, passes, accurate passes (and %), key passes,
chances created, big chances created and missed, assists, goals, shots total, on target, off target, blocked, offsides,
crosses (total, accurate, %), dribble attempts, successful dribbles, dribbled past, dispossessed, possession lost,
turnovers, duels (total, won, lost, %), aerials (total, won, lost, %), tackles (total, won, %), last-man tackle,
interceptions, clearances, ball recoveries, fouls, fouls drawn, offsides provoked, long balls (total, won, %), through
balls (total, won), backward passes, passes in the final third, saves, saves inside the box, punches, good high claims,
goals conceded, goalkeeper goals conceded, **error leading to a shot**, captain flag, yellow cards, cumulative minutes.

**Minute series (`trends`, 43 types):** the same team statistics sampled per minute (possession, dangerous attacks, shots
inside the box, key passes, passes, crosses, tackles, fouls, corners, goals and more).

## Coordinates: the answer

| Source | On Starter? | What it can and cannot draw |
|---|---|---|
| `ballCoordinates` | **yes** | About 900 points per match, `x` and `y` between 0 and 1 (a pitch scaled to the unit square), a `timer` (mm:ss) and the period. Draws **where the match was played** (ball territory, a heat map of the ball, thirds of the pitch). Cannot say which team had the ball, who touched it, or which events happened where: there is no `participant_id`, `player_id` or event type on the rows |
| `events` | yes | no coordinates; no shot events |
| `lineups.details` | yes | counts per player, no locations |
| `formation_field` / `formation_position` | yes | the starting grid (line:position), i.e. a drawable **starting XI on a pitch** with the formation |
| Shot map, pass map, xG | **no (403 / not present)** | `xGFixture`, `lineups.xGLineup`, `expected/*` are refused. Shots exist only as counts |

Pitch drawings available today: starting XI with formation (confirmed or predicted), ball territory map, a momentum line
chart from `trends`. Not available today: shot maps, pass networks, xG maps, pressure maps (all need paid add-ons or data
the provider does not publish at this level).

## Output table: field or family → FPL? → Starter? → visible use

| Field / family | FPL gives it? | Starter? | Visible idea (surface) |
|---|---|---|---|
| Player match **rating** (RATING) | no | yes | "Form that FPL points hide": last 5 ratings next to FPL points (player card, comparison) |
| Key passes, chances created, big chances created / missed | partly (ICT creativity and threat, indices) | yes | Creator ranking and "unlucky" list: big chances missed with no goal (player card, captain candidates) |
| Shots, on target, inside/outside box | partly (shots in bootstrap totals) | yes | Shot-quality bar per player, last 5 matches (player card) |
| Touches, passes, passes in final third, long balls, through balls | no | yes | Involvement profile: who the team plays through (comparison, chat answers) |
| Dribbles, duels, aerials, dispossessed, possession lost | no | yes | Style tags per player: dribbler, aerial threat, loses the ball a lot (player card) |
| Tackles, interceptions, clearances, recoveries, blocked shots | partly (defensive contributions, clearances-blocks-interceptions in FPL) | yes | Defender floor: how often a defender reaches the bonus-style threshold (comparison, captaincy for defenders) |
| Saves, saves inside the box, punches, high claims, goals conceded | partly (saves) | yes | Goalkeeper workload and shot-stopping (player card, chat) |
| Error leading to a shot / goal | no | yes | "Defensive errors" alert for a defender before a double gameweek (player card) |
| Team match stats: possession, attacks, dangerous attacks, corners | no | yes | Team style card: who dominates and who counters (calendar / FDR, tactical cards) |
| `trends` (per-minute series) | no | yes | Match momentum chart for the weekend recap and live podcast (chat, match card) |
| `ballCoordinates` | no | yes | Ball-territory heat map per match (match card); not shots or passes |
| `events` goals, substitutions, cards, VAR, minutes | partly (goals, cards in event feed) | yes | Substitution timeline and "when does he come off" (minutes risk, captaincy) |
| `lineups` predicted + `LINEUP_CONFIRMED` | no | yes | "Lineup confirmed" badge and predicted XI with formation, before the deadline (home screen, captain candidates) |
| `formations`, `formation_field` | no | yes | XI on a pitch with the formation (match card, comparison of two sides) |
| `sidelined` by club (injury, suspension, `games_missed`) | partly (status and news text) | yes | Absences with expected games missed and the provider's dates (player card, calendar) |
| `fixtures` calendar across competitions (`upcoming`, `team_fixtures`) | no (league only) | yes | Calendar with cups and European dates, rest days, rotation risk (Leo's first ask; calendar / FDR) |
| `weatherReport`, `venue` (capacity, surface, coordinates) | no | yes | Weather and pitch chip on the match card (podcast, match card) |
| `referees` (assigned referee names) | no | yes | Referee of the match, with cards given per game if we aggregate it ourselves (match card) |
| `periods.time_added`, `scores` by half | no | yes | "Late goals" and stoppage-time tendencies (chat, recap) |
| `comments` (text commentary, `is_important`) | no | yes | Source for a live "key moments" feed (podcast); text rights need the licence answer |
| `coaches` (current coach and start date) | no | yes | New-manager flag on a club (calendar / FDR, chat) |
| `transfers` (club moves, dates) | partly | yes | "New arrivals" and loans, a check on identity mapping (player card) |
| Season stats: `statistics` of players and teams (36 and 49 types) | partly | yes | Season profile next to FPL totals (player card, comparison) |
| `standings` (live), `topscorers` | partly | yes | Table and leaderboards with goals, assists, cards (home, chat) |
| `tvStations` | no | yes | Where to watch, by country (calendar); low value for an FPL audience |
| **xG / xA** (`xGFixture`, `xGLineup`, `expected/*`) | **yes** (FPL has expected goals and assists) | **403** | Do not buy for this: FPL already gives xG and xA per player |
| **Pressure index** | no | **403** | would feed momentum; the free `trends` give a cruder version |
| **Predictions, value bets, odds** | no | **403** | out of scope for a points game |
| Shot map, pass map | no | **not available** | needs a different data provider |

## Limits

- Counts and names come from two finished fixtures, one future fixture, one player and one club. **Coverage across all 380
  fixtures and all players, and how often a stat is empty for a given player, was not measured.** Before any design
  promises a stat, run the per-field coverage over the captured season (no new requests are needed for the fixtures
  already captured).
- The "FPL gives it?" column reflects what the FPL API is known to expose (bootstrap, live and element-summary feeds); it was not re-probed for this note.
- Statistics values are not checked for correctness against a second source; the rating is the provider's own model.
- Whether a rating, a statistic or a derived figure may be shown to subscribers is licensing question 6 (display) and 5
  (derived scores), both still unanswered. This inventory proves availability, not permission.
- `livescores`, `head-to-head` and `statistics/rounds` returned empty with the ids tried; they were not exhausted.
- "Add-on" for the 403 includes is the provider's catalogue naming (xG, pressure index, predictions, odds, expected
  lineups); the API message does not say it.

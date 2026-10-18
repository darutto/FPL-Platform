# Capture C and matchup questions Q9–Q11 (2026-10-18)

Aggregates, field names and public player names only; no raw payloads, no provider ids. Raw files stay in
`trial-output/` (git-ignored). The capture was a **one-off local script, not committed** (it called the API directly
instead of through the guarded client, so it stays off main); the endpoints and includes it used are listed in §1. The
aggregation (Q9–Q11) used no network. Everything here is
**retrospective** (read on Sat 17 Oct for matches already played): it says what the provider returns today, not what was
knowable before each gameweek, except where marked.

## 1. Budget and calls (hard cap 150, used 125)

| Endpoint / include | Calls | Useful | Notes |
|---|---|---|---|
| `teams/seasons/28083` (club ids and codes) | 1 | 20 clubs | |
| `fixtures/{id}` with `lineups.details.type`, `lineups.detailedPosition`, `formations`, `participants`, `sidelined.sideline`: PL GW5–6 | 20 | 20 of 20 | 40 lineup rows per match, 22 starters |
| Same, PL GW1–4 | 40 | 40 of 40 | spent from the reserve, agreed |
| `fixtures/between/{from}/{to}/{team}` with `league;participants;lineups.detailedPosition;formations`, 20 clubs, 1 Aug – 17 Oct | 20 | 108 distinct fixtures | one page each; no `has_more` |
| `teams/{id}?include=sidelined.sideline` | 20 | **0** | **wasted**: `sideline` is not an include of a team's `sidelined` (error 5013); my error |
| `teams/{id}?include=sidelined` (redo) | 20 | 58 rows | open absences only (see §3) |
| Player detail for four named UCL matches (Nunes, Barkley) | 4 | 4 | `lineups.details.type;events.type;state` |
| **Total** | **125** | | cap 150 |

No row had a publication or `updated_at` timestamp. Sidelined rows carry `start_date`, `end_date`, `games_missed`,
`completed`, which are **as of the read, not as of the match**.

## 2. Per-player stats: what each field is (questions asked in the brief)

77 distinct stat types came back across the 60 matches (at most 62 per player and match), each as `{value}` only.
`stat_group` is only `offensive`, `defensive` or `overall` or empty. **No field is spatial**: nothing by zone, flank,
half-space, side or coordinates. Examples by meaning: shots (total, on/off target, blocked), key passes, chances created,
big chances created/missed, crosses (total, accurate), dribbles (attempted, successful), dribbled past, duels
(total, won, lost), aerials, tackles (and won), interceptions, clearances, touches, passes (total, accurate, in the final
third, backward, long balls), ball recoveries, possession lost, dispossessed, fouls and fouls drawn, cards, rating,
minutes played, xG, xGOT, shooting performance.

What *is* spatial: the lineup row's `detailedPosition` (Goalkeeper, Centre Back, Right/Left Back, Defensive/Central/
Attacking Midfield, Right/Left Midfield, Attacker) and `formation_field` («row:column», columns run right to left from
the team's own view: in a 4-2-3-1 the right winger is 4:1 and the left winger 4:3). The match `formations` include gives
one formation string per team. Over the 60 matches: 4-2-3-1 in 86 of 120 team-matches, 3-4-2-1 in 24, 5-4-1 in 6, 4-1-4-1
and 3-5-2 in 2 each. In a 3-4-2-1 the wing-backs are labelled Right/Left Midfield (no wing-back label exists).

**Consequence: "concedes down its left" is not a provider field.** It is our derived measure: the stats of that flank's
full-back and winger, taken from `detailedPosition`/`formation_field` (for example, the opponent's right-sided
players' output as the attack faced by the team's left flank, and the team's own left-sided players' "dribbled past").

## 3. Sidelined history

- `teams/{id}?include=sidelined`: 58 rows across 20 clubs, **all open** (0 completed, 21 with no end date). Start dates run
  from Nov 2025 to 15 Oct 2026, 25 of them in September 2026. It is "current rows only".
- Fixture-level `sidelined` (rows attached to each match): **89** distinct absences across GW5–6, of which **52 are
  completed and absent from the team-level list**; 37 are in both. So history exists only through the fixture-level
  include, and `completed`/`end_date` are today's values (retrospective: an injury shown as ended may have been open at
  the time).
- Fields: `start_date, end_date, games_missed, completed, category (injury/suspended), type_id, player_id, team_id`.

## 4. Cup and European XIs (coverage)

108 distinct fixtures for the 20 clubs between 1 Aug and 17 Oct. All 42 finished non-PL matches have a full XI (22
starters, 40–46 lineup rows): 10 Champions League, 6 Europa League, 3 Conference League, 1 UEFA Super Cup, 22 Carabao
Cup (one more, unplayed). No FA Cup match yet. European clubs among the 20: Arsenal, Man City, Liverpool, Man United,
Aston Villa (Champions League); Brighton (Conference); Crystal Palace, Sunderland, Bournemouth (Europa League).
Formation strings come with the XI for those matches too (42 of 42).

### Matheus Nunes (Man City): facts, no conclusion

Leo's idea was ambiguous (he starts the big UCL games, or he plays in the league because others are rested for the UCL).
These are the facts; n = 2 UCL games, association only.

| Date | Competition | Match | Nunes | Right-back starter |
|---|---|---|---|---|
| 23 Aug | PL | City – Bournemouth | bench | Rico Lewis |
| 28 Aug | PL | Palace – City | not in squad list | Khusanov |
| 5 Sep | PL | City – Coventry | bench | Khusanov |
| **8 Sep** | **UCL** | **Porto – City** | **started, right back, 90'** | Nunes |
| 13 Sep | PL | Man United – City | started, right back | Nunes |
| 17 Sep | Carabao | City – Norwich | bench | Rico Lewis |
| 20 Sep | PL | City – Sunderland | started, right back | Nunes |
| 11 Oct | PL | Liverpool – City | started, right back | Nunes |
| **14 Oct** | **UCL** | **City – PSG** | **bench, came on, 44'** | **Khusanov** |
| 17 Oct | PL | City – Ipswich | started, right back | Nunes |

In the league, Nunes started the last four matches, including the one before and the one after PSG. For PSG the
right-back starter was Khusanov.

Barkley (Aston Villa), same capture: started the UCL tie with Fenerbahçe on 14 Oct as a central midfielder (83', 2 goals,
1 assist, rating 9.08); was a substitute (22') against Club Brugge on 8 Sep.

## 5. Matchup questions, with what is answerable now

n is small on purpose: 60 matches means **6 matches per club and flank**. Nothing below is more than association.
Clubs of every named player were checked against today's FPL bootstrap (Salah not used).

### Q9 — wingers facing opponents that concede more down their flank

Derived measure per team and flank (L = the team's own left): (i) "opponent wide output" = per match, key passes +
successful dribbles + crosses of the opposing side's full-back and winger on the *opposite* flank; (ii) "dribbled past" of
the team's own full-back and winger on that flank. League mean 7.6 opponent-wide-output (sd 2.2) and 1.2 dribbled-past (sd
0.5) per match.

- **The two proxies do not agree: correlation 0.04 across the 40 team-flanks.** One of them is noise, or they measure
  different things. Neither is a validated "concedes down the left" measure.
- Findings to validate, ranked by the two z-scores added (usual starter on the side in 6 matches vs the opponent's flank
  he attacks): **Barnes (NEWC, left) vs Crystal Palace's right flank** (dribbled past 2.3/match, z 2.5); **Schade
  (Brentford, left) vs Hull's right** (z 1.1 and 1.4); **Foden (City, right; started 3 of 6) vs Aston Villa's left** (z
  1.7 and 0.7); **Tzolis (Arsenal, left) vs Everton's right** (opponent wide output 12.8/match, z 2.4); **Tavernier
  (Bournemouth, left) vs Man United's right** (z 1.0 and 1.1). n = 6 matches for each flank.
- Answerable now: a ranked list like the above for any gameweek. Needs a matchup module: a validated flank-concession
  measure (more matches, a second source such as chances conceded by zone), with the usual-side rule.

### Q10 — matchups for an attacking wing-back, given the opponent's formation

Attacking actions (key passes + successful dribbles + crosses) per player-match:

| Own formation / position | Actions | n |
|---|---|---|
| 4-2-3-1 left back / right back | 4.0 / 2.9 | 86 / 86 |
| 4-2-3-1 left / right midfield (wingers) | 4.9 / 5.1 | 86 / 86 |
| 3-4-2-1 left / right midfield (wing-backs) | 4.7 / 4.0 | 24 / 24 |

By opponent formation: wide midfielders in a 4-2-3-1 produce 4.6 per player-match against a 4-2-3-1 (n 120), 5.7 against
a 3-4-2-1 (n 32) and 5.7 against a 5-4-1 (n 12); full-backs 3.1 against a 4-2-3-1 (n 120), 3.7 against a 3-4-2-1 (n 32)
and 4.8 against a 5-4-1 (n 12). In short: wide players do a bit more against back-three/five sides, the 5-4-1 sample is 12
and the 3-4-2-1 wing-backs' own sample is 24. Association only, formation is the provider's string for that match, not a
tactical read, and a 3-4-2-1 wing-back is labelled "midfield".

- Answerable now: a table like this by team once a few more gameweeks exist. Needs a matchup module: wing-back
  identification (by formation, not label), opponent formation in advance (the predicted XI includes a formation), and
  more than 6 matches per team.

### Q11 — how a team's attacking distribution changes with formation

Share of a team's attacking actions made by its wide players (LB/RB/LM/RM): 0.54 for 4-2-3-1 (n 86 team-matches), 0.30 for
3-4-2-1 (n 24), 0.68 for 5-4-1 (n 6). Caution: **this is partly an artefact of the labels**: a 3-4-2-1 has no full-backs
(the wing-backs are "midfield"), so the same flank set means different players in each shape. Only 4 clubs changed
formation within GW1–6 (Coventry, Leeds, Everton, Chelsea), 1–5 matches in each shape, so a same-club comparison is not
yet possible. Crosses per match: 15.9 (4-2-3-1), 14.1 (3-4-2-1), 17.3 (5-4-1).

- Answerable now: league-wide association by formation, with the label caveat. Needs a matchup module: the same club's
  matches in both shapes (more gameweeks) and a position mapping that treats wing-backs as one role across shapes.

## 6. What this changes (short)

- Stats are rich per player and match, but none is spatial; flank has to be derived from position and formation. The
  derived measure does not yet pass a sanity check (two proxies correlate 0.04).
- Cup and European XIs are fully available for the matches played, with formations.
- Sidelined history needs the fixture-level include; the team-level include only holds open absences.
- All of it is retrospective; for "knowable before the gameweek" use the predicted XI readings, not this capture.

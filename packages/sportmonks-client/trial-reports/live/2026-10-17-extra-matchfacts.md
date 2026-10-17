# Extra "Match Facts Basic": what arrives for the Premier League 2026/27 (2026-10-17)

Field names, type names, counts and categories only; no fact text, no payloads. Raw responses in `trial-output/extras/`
(git-ignored). User-facing use depends on licensing questions 2–11 (unanswered).

**Premise check passed**: `include=matchfacts` (and `matchfacts.type`) answers 200 with data (403 before the add-on).

## The short answer

1. **Facts arrive before the match, but only about 2 days ahead.** GW7 fixtures of 18–19 Oct have 396–682 fact rows; GW8
   (23–25 Oct, 6–8 days out) and later have **0**. Finished matches carry 577–743 rows. A "what you need to know"
   card for a fixture is therefore only available at the end of the preceding week.
2. **English only.** Every `natural_language` string checked is English (0 Spanish hits). Only about 20–25 % of rows
   have a sentence at all (62–161 of 396–743); the rest are structured numbers in `data` and have no text. Sentences
   average ~110 characters. A Spanish product needs templates over the structured rows (as in i151) or a translation.
3. **Very many rows per fixture** (≈135–140 distinct type ids, ≈480–510 distinct type × side × scope combinations),
   so the work is selection, not volume: choose 2–3 per match.
4. **Fact sentences are present where the plan asked**: unbeaten/loss/draw/BTTS/clean-sheet streaks, head-to-head,
   coach records, referee tendencies, missing key players. None is written for a specific "storyline"; they are
   generic statistic rows.

## Row shape

`{id, fixture_id, type_id, category, scope, basis, participant, data, natural_language, sport_id}` (+ `type`
with `matchfacts.type`, which works).

| Field | Values seen |
|---|---|
| `category` | statistics, streaks, statistic_comparisons, players, coaches, referees |
| `scope` | all_matches, league_matches |
| `basis` | team, h2h, global (referee rows) |
| `participant` | home, away, both, referee |
| `data` | an object; keys vary: `all/home/away` splits, `streak`, `matches`, `count`, `percentage`, `average`, `over/under`, `coach_id`, `value`, `related_player`, interval buckets `0-15 … 75-90` |

## Rows per category (Liverpool–City, finished) and type counts

| Category | Rows | Distinct types | With a sentence |
|---|---|---|---|
| statistics | 542 | 91 | 86 |
| streaks | 93 | 22 | 29 |
| statistic_comparisons | 52 | 13 | 20 |
| players | 26 | 4 | 13 |
| coaches | 26 | 7 | 13 |
| referees | 4 | 4 | 0 |

Examples of type names (developer names): `MATCH_FACT_CLEANSHEET`, `MATCH_FACT_UNBEATEN_STREAK`,
`MATCH_FACT_LOSS_STREAK`, `MATCH_FACT_BTTS_STREAK`, `MATCH_FACT_NO_LATE_GOAL_STREAK`, `MATCH_FACT_LAST_10_BTTS`,
`MATCH_FACT_GOALS_CONCEDED`, `MATCH_FACT_HISTORIC_OUTCOMES`, `MATCH_FACT_MISSING_KEY_PLAYERS`,
`MATCH_FACT_EXPECTED_GOALS_COMPARISON`, `MATCH_FACT_SHOTS_ON_TARGET_COMPARISON`, `MATCH_FACT_WIN_COACH`,
`MATCH_FACT_YELLOWCARDS_PER_FOUL_REF_COMPARISON`.

## Coverage before kickoff (Premier League, probed Sat 17 Oct)

| Kickoff | Fixtures | Matchfacts rows | Rows with a sentence |
|---|---|---|---|
| 18 Oct (4 fixtures) | 4 | 561 – 682 | 123 – 145 |
| 19 Oct (Spurs – Coventry) | 1 | 396 | 62 |
| 23–25 Oct (GW8) | 10 | **0** | 0 |
| 31 Oct – 2 Nov (GW9) | 10 | **0** | 0 |
| Champions League, finished (City – PSG) | 1 | 567 | 142 |

The Coventry match has fewer rows (396; the head-to-head rows are 78 against 232 for Forest–Arsenal), so row counts vary by fixture.
Champions League matches also carry facts when finished; the one future Champions League fixture probed (PSG – Barcelona, 20 Oct) had 0.
Re-probe the GW8 fixtures Sunday, Monday and Wednesday to find the actual lead time.

## What this means for the plan's uses

- **Calendar card "Lo que hay que saber"**: usable only for the current gameweek (≤2 days out). For the next gameweek
  the card would be empty. Streak rows carry `streak` and `matches` fields; whether a "no clean sheet in 8 home matches" fact is among
  them was not checked (not read at value level, to keep the report free of payloads): confirm in step 2.
- **Chat**: structured rows can be cited with the provider's own numbers; English sentences cannot be shown to a
  Spanish user as they are.
- **Podcast**: the previa for Saturday works; a Thursday previa for the following weekend does not.

## Verdict for criterion 1

Current gameweek: yes (5 of 5 probed). Next gameweek: no, today (0 of 10). Language: English only, so criterion 2
(a visible use) needs a Spanish template layer. Cost question for criterion 3: €29/month for a card that is empty
more than half the week unless the lead time grows.

# Extra "Odds & Predictions": what arrives for the Premier League 2026/27 (2026-10-17)

Field names, type names, counts and match-level model probabilities only; no payloads, no bookmaker prices. Read on the
trial token the day the add-on was switched on. Raw responses stay in `trial-output/extras/` (git-ignored). Any
user-facing use still depends on licensing questions 2–11 (unanswered).

**Premise check passed**: `predictions/probabilities/fixtures/{id}`, `predictions/predictability/leagues/{id}` and
`odds/pre-match/fixtures/{id}` answer 200 (they answered 403 before the add-on). No 403 anywhere.

## The short answer

1. The model gives, per fixture, **25 probability markets** (all type_ids resolved below), all with the fields
   `{id, fixture_id, type_id, predictions{...}}`. Everything the plan asked for exists, though two of them need a
   one-line derivation:
   - **Both teams score**: `231 BTTS_PROBABILITY` → `yes` / `no`. Direct.
   - **Over/under goals**: `234/235/236/1679` = 1.5 / 2.5 / 3.5 / 4.5 total goals. Direct.
   - **"Team scores"**: `334/331/330/326` = home over/under 0.5 / 1.5 / 2.5 / 3.5 and `333/332/328/327` = the same for
     away. `home_over_under_0_5.yes` is "home scores at least once"; `1_5.yes` is "scores 2+".
   - **Clean sheet per team: no market of its own.** It is the complement of the *opponent's* 0.5 line: home keeps a
     clean sheet = `333` (away over/under 0.5) `.no`; away keeps one = `334` (home over/under 0.5) `.no`.
     This is a derivation, not a provider field: label it as such.
   - **Correct score** (`240`, key `scores`), **1X2** (`237`), **double chance** (`239`), **half-time/full-time**
     (`232`), **first-half result** (`233`), **team to score first** (`238`; keys home/away/draw=no goal).
   - Corners over/under 4–9 (`1690, 1683, 1685, 1686, 1689, 1687`), keys yes/no/equal. Not in the plan; noted.
2. **Coverage of future fixtures is patchy, not a clean "N days ahead" window** (see table). Finished fixtures keep
   their predictions.
3. **Champions League: no predictions at all** (0 of 6 fixtures probed, finished and future; also no pre-match odds).
   Predictability by league returns nothing for the Champions League (league 2).
4. **Predictability for the Premier League is published** (5 metrics × 13 markets), and it says the model is weakest
   exactly where the plan wants to lean (see below).
5. **Odds** are broad (≈137 markets, 17–20 bookmakers on a played / GW7 fixture) but thin for a fixture a week out
   (77 markets, 12 bookmakers). Not needed for the plan: probabilities arrive pre-computed.

## Type ids → market (all 25 rows seen on a full fixture)

| type_id | developer_name | prediction keys |
|---|---|---|
| 237 | FULLTIME_RESULT_PROBABILITY | home, draw, away |
| 231 | BTTS_PROBABILITY | yes, no |
| 234 / 235 / 236 / 1679 | OVER_UNDER_1_5 / 2_5 / 3_5 / 4_5_PROBABILITY | yes, no |
| 334 / 331 / 330 / 326 | HOME_OVER_UNDER_0_5 / 1_5 / 2_5 / 3_5_PROBABILITY | yes, no |
| 333 / 332 / 328 / 327 | AWAY_OVER_UNDER_0_5 / 1_5 / 2_5 / 3_5_PROBABILITY | yes, no |
| 239 | DOUBLE_CHANCE_PROBABILITY | draw_home, draw_away, home_away |
| 238 | TEAM_TO_SCORE_FIRST_PROBABILITY | home, draw, away |
| 233 | FIRST_HALF_WINNER_PROBABILITY | home, draw, away |
| 232 | HTFT_PROBABILITY | nine combinations (`home_draw`, …) |
| 240 | CORRECT_SCORE_PROBABILITY | `scores` (a map) |
| 1690, 1683, 1685, 1686, 1689, 1687 | CORNERS_OVER_UNDER_4…9_PROBABILITY | yes, no, equal |

Values are percentages (0–100) with one-decimal precision. The type names come from `include=type` on the
probabilities call (it works; `core/types` does not).

## How far ahead do they arrive? (Premier League, probed Sat 17 Oct ≈14:00 UTC)

| Kickoff | Fixtures probed | With 25 rows |
|---|---|---|
| 17–19 Oct (GW7, 0–2 days; includes 5 already kicked off or finished) | 10 | **10** |
| 23–25 Oct (GW8, 6–8 days) | 10 | **6** |
| 31 Oct – 2 Nov (GW9, 14–16 days) | 10 | **2** |
| Champions League 20–21 Oct | 6 | **0** |

Reading: the provider's "up to 21 days" is a ceiling, not a guarantee. Which fixtures get a row looks arbitrary (not
by kickoff time, not by club), so it may be the model's batch job filling in. **Re-check on Sunday and Monday** to see
whether GW8 fills up to 10 of 10; until then the Premium calendar cannot assume a probability for every future cell.
Fallback needed when the row is missing: show the FPL FDR cell as today.

## Model quality, Premier League (`predictability/leagues/8`, include `type`)

Five metrics per market: `241 HISTORICAL_LOG_LOSS`, `242 MODEL_HIT_RATIO`, `243 MODEL_PREDICTABILITY` (poor / medium /
good / high), `244 MODEL_PREDICTIVE_POWER` (up / down / unchanged), `245 MODELS_LOG_LOSS`.

| Market | Hit ratio | Predictability label | Power trend |
|---|---|---|---|
| Fulltime result | 0.43 | medium | down |
| Both teams to score | 0.61 | medium | down |
| Over/under 2.5 | 0.52 | medium | unchanged |
| Over/under 1.5 | 0.80 | medium | down |
| Home scores (0.5) | 0.79 | high | down |
| Away scores (0.5) | 0.75 | **poor** | up |
| Home scores 2+ (1.5) | 0.54 | **poor** | unchanged |
| Away scores 2+ (1.5) | 0.64 | medium | down |
| Team to score first | 0.50 | high | down |
| Correct score | 0.14 | high | unchanged |

What it means for the plan's examples: "team scores 2+" (`1_5`) is rated **poor** for the home side, and the hit ratio of
a coin-flip market like 1X2 is 0.43. Hit ratio for "scores at least once / over 1.5" is high mostly because those
events are common. The clean-sheet derivation inherits the quality of the 0.5 lines (home 0.79 high, away 0.75 poor).
Safe to show as a ranking; not safe to word as a promise. Predictability for the Champions League: empty.

## Examples for layout (model output, GW7–GW9 fixtures, percentages)

| Fixture | Home CS | Away CS | Home 2+ | Away 2+ | BTTS | Over 2.5 | 1X2 H/D/A |
|---|---|---|---|---|---|---|---|
| Nottingham Forest – Arsenal (18 Oct) | 19.8 | 44.9 | 22.3 | 48.9 | 49.1 | 48.7 | 21 / 25 / 55 |
| Tottenham – Coventry (19 Oct) | 35.6 | 22.4 | 47.2 | 31.7 | 56.4 | 54.5 | 47 / 25 / 28 |
| Brighton – Crystal Palace (18 Oct) | 45.1 | 15.4 | 57.4 | 23.7 | 53.6 | 57.3 | 59 / 23 / 18 |
| Aston Villa – Man City (24 Oct) | 15.5 | 42.2 | 26.6 | 58.9 | 57.8 | 60.7 | 20 / 21 / 59 |
| Man United – Bournemouth (25 Oct) | 38.8 | 20.3 | 50.2 | 28.8 | 56.9 | 54.9 | 51 / 25 / 24 |

Spread: across the 13 fixtures with data, a team's clean-sheet probability runs from 15 % to 45 % and "scores 2+" from
22 % to 59 %, so the ranking the calendar would use does separate cells (a streak of CS > 35 % exists but is rare).

## Odds (counts only)

| Fixture | Rows | Markets | Bookmakers |
|---|---|---|---|
| Finished (Liverpool–Man City) | 3,884 | 137 | 20 |
| GW7 (Forest–Arsenal) | 3,630 | 136 | 17 |
| GW8 (Arsenal–Everton, Oct 24) | 1,018 | 77 | 12 |
| Champions League (PSG–Barcelona, Oct 20) | 0 | 0 | 0 |

Row fields: `fixture_id, market_id, bookmaker_id, label, value, name, market_description, probability, dp3, fractional,
american, winning, stopped, total, handicap, participants, created_at, original_label, latest_bookmaker_update`. The
largest markets by row count are correct score, shots, fouls, tackles, goals over/under, goalscorers, Asian handicap,
corners. Per the plan, odds are never shown; the provider's `probability` field means odds add nothing the
predictions endpoint does not already give.

## Verdict for criterion 1 ("arrives for ≥90 % of the matches that matter")

- Premier League, current gameweek (≤2 days): 10 of 10. **Yes.**
- Next gameweek (6–8 days): 6 of 10. **No, today.** Re-check Sunday/Monday and again Wed 21 Oct before judging.
- Champions League: 0. **No.** Any "Champions League" use of this extra is dead.

Open: why GW8 fixtures differ, and when the missing rows appear. One probe a day until the 23rd answers it.

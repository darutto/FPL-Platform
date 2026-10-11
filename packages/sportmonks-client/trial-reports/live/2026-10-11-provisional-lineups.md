# Provisional lineups, and what Leo's Liverpool-City check found (2026-10-11)

Aggregate only. Leo's validation of the grid table against Sofascore was a **partial negative**: the
table delivered for Liverpool-City did not match. The cause is not the grid rule; it is that the data the
table was built from was a provisional lineup. Both parts are recorded as they happened.

## What did not match

On the Liverpool-City table Sofascore differed in the eleven (a different striker and attacking midfielder
on one side; a different left-back and a swapped pair of wingers on the other) and in the sides of the
centre-backs and the two central midfielders of both teams. Wingers and full-backs agreed with the rule.

## Why: the provider serves provisional lineups with no marker

The same fixture was read three times:

| Read | Fixture state | Lineup rows | Compared with the final |
|---|---|---|---|
| Morning, when the table was built | not started | not recorded (only the table built from it survives) | different eleven |
| 14:18 UTC, 72 minutes before kickoff | NS | 22 | still different; 21 of the final 40 row ids shared |
| After the match | FT | 40 (starters and bench) | final |

- The provisional rows have **`type_id` 11, the same as confirmed starters**; the lineup row has no
  field that tells them apart (keys: id, fixture_id, player_id, team_id, position_id, formation_field,
  formation_position, jersey_number, player_name, type_id). The only signals found are the fixture state and,
  as an indication, the absence of a bench.
- The provider rewrites the rows on confirmation (row ids change).
- **Which measures were touched:** the grid table for Leo (Liverpool-City, and the by-hand reading of the
  grid on the unplayed fixtures) and the day-1 lineup figures for objectives 6, 7 and 10, whose window
  contained three unplayed fixtures (306 rows, 18 formations, 58 substitutions; completed fixtures only:
  360 rows, 18 formations, 85 substitutions). **Not touched:** M1, M2 and the hold-out (the adapter only
  accepts lineups of completed fixtures and needs the provider's minutes, which exist only after the match),
  the 420-of-420 side check (recomputed today on completed fixtures only: 420 of 420 in 59 fixtures), the
  58-of-58 check in other competitions (all completed), and the Arsenal-Leeds table (a finished match,
  confirmed by Leo).

## With the final lineup, the rule reproduces Sofascore

Recomputed from the finished fixture with the unchanged rule (home: column 1 is the team's right; away
mirrored):

- Liverpool (home): right-back right, the two centre-backs centre-right and centre-left in the order
  Sofascore gives, left-back left, the two central midfielders right and left as Sofascore gives them.
- Manchester City (away): the left-back (a different player from the provisional one), the two centre-backs
  and the two central midfielders on the sides Sofascore gives, and both wingers on theirs.

All eleven sides Leo listed for Liverpool and City match. So it was not a case of the centre-back column
being ordered differently from the full-back column, nor of Sofascore placing them loosely: the provisional
lineup had swapped them, and the rule holds on the final one. The evidence that remains outside our
sample is one source: Sofascore through Leo, on three teams. Two more matches (one with a back three, one
with a visiting side) would widen it.

## What changes in how criterion (b) is measured

- **Only completed fixtures validate semantics.** `trial_lineups` now counts only lineups whose fixture is
  completed (#433), and says how many rows it left out.
- **"Confirmed lineups available before kickoff" cannot be answered from a row.** The decisive question is
  when the provisional lineup becomes the final one before kickoff, and how a consumer knows. It is measured
  per fixture: the minutes before kickoff at which the final eleven appears (signal: the 40-row shape or the
  fixture state, and which of them is reliable), and how many starters change between the last provisional
  version and the final one. A watcher polls Coventry-Newcastle (Monday 12 October, 19:00 UTC) every 20
  minutes until four hours before kickoff and every five minutes after, and the same is done on GW7.
- **Support question 16:** "How can a client tell a predicted/provisional lineup from the confirmed one before
  kickoff (lineup rows have `type_id` 11 in both)?"

## Results of the watchers

*(to be filled in with the 12 October and GW7 observations)*

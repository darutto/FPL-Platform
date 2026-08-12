# trial_lineups — trial report

Mode: `mock`

| # | Objective | Status | Evidence |
|---|---|---|---|
| 6 | Confirmed starters and substitutes | `observed` | lineups: 2 record(s); partition field type_id with 2 distinct value(s) |
| 7 | Formation strings | `observed` | formations: 1 record(s); field formation; 1 distinct value(s) |
| 8 | Formation-grid or lineup-position fields | `observed` | grid field formation_field; shape(s) str; 2/2 record(s) |
| 9 | Detailed position identifiers | `observed` | detailed-position field detailed_position_id; 2/2 record(s); 2 distinct value(s) |
| 10 | Substitution relationships and minutes | `observed` | substitutions: 1 triple(s) (player_off, player_on, minute); 1 complete |

## Observed shapes

| Name | Shape as found |
|---|---|
| lineups | `2 record(s); record{id,fixture_id,player_id,formation_field,type_id,detailed_position_id}` |
| formations | `1 record(s); record{id,fixture_id,formation}` |
| substitutions | `1 record(s); record{id,fixture_id,player_in_id,player_out_id,minute}` |
| starter_marker | `field=type_id; values{11:1,12:1}; 2/2 record(s)` |
| formation_grid | `field=formation_field; shape=str; documented=str; 2/2 record(s)` |
| detailed_position | `field=detailed_position_id; 2/2 record(s); 2 distinct value(s)` |
| substitution_direction | `off=player_out_id; on=player_in_id; first=(101,102,70)` |

## Warnings

- the mock lineup records carry a synthesized starter marker and detailed position; the checked-in corpus has neither, and which fields Sportmonks actually uses is unverified until FI-9
- mock mode: shapes are documentation-derived and carry "status": "unverified_against_live" until FI-9
- grid semantics are not decided here: §14.3 question 13 is open, and this report describes the value's structure only

# trial_squads — trial report

Mode: `mock`

| # | Objective | Status | Evidence |
|---|---|---|---|
| 4 | Team and squad completeness | `observed` | teams: 1 record(s) [id 1/1,name 1/1,short_code 1/1]; squads: 1 record(s) [id 1/1,team_id 1/1,player_id 1/1,position_id 1/1] |
| 5 | Current player records | `observed` | players: 1 record(s) [id 1/1,name 1/1,date_of_birth 1/1]; 1/1 squad row(s) resolve to a player record |

## Observed shapes

| Name | Shape as found |
|---|---|
| teams | `1 record(s); record{id,name,short_code}; required[id 1/1,name 1/1,short_code 1/1]` |
| squads | `1 record(s); record{id,team_id,player_id,position_id}; required[id 1/1,team_id 1/1,player_id 1/1,position_id 1/1]` |
| players | `1 record(s); record{id,name,display_name,date_of_birth}; required[id 1/1,name 1/1,date_of_birth 1/1]` |
| squad_player_coverage | `1/1 squad row(s) resolve; 1 player record(s) held` |

## Warnings

- mock mode: shapes are documentation-derived and carry "status": "unverified_against_live" until FI-9

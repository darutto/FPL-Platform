# trial_sidelined — trial report

Mode: `mock`

| # | Objective | Status | Evidence |
|---|---|---|---|
| 11 | Injuries and suspensions | `observed` | current_sidelined: 2 open row(s) over 1 club(s); injury 1, suspended 1 |

## Observed shapes

| Name | Shape as found |
|---|---|
| current_sidelined | `2 record(s); record{id,player_id,type_id,category,team_id,season_id,start_date,end_date,games_missed,completed}` |
| poll_pass | `pass 1: baseline of 2 row(s); no earlier pass to diff` |

## Warnings

- the rows carry no updated_at: first-seen is the earliest pass that contained the id, so latency has a resolution of one polling interval
- mock mode: shapes are documentation-derived and carry "status": "unverified_against_live" until FI-9

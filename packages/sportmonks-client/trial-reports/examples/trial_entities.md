# trial_entities — trial report

Mode: `mock`

| # | Objective | Status | Evidence |
|---|---|---|---|
| 1 | Competition and season identifiers | `observed` | Premier League resolved to league_ids=(8,); season_ids=(23614,); swept 15 families: 15 reachable, 0 empty, 0 unavailable |

## Observed shapes

| Name | Shape as found |
|---|---|
| family:leagues | `reachable; 1 record(s); provider_ids={8}` |
| family:seasons | `reachable; 1 record(s); provider_ids={23614}` |
| family:fixtures | `reachable; 1 record(s); provider_ids={1001}` |
| family:teams | `reachable; 1 record(s); provider_ids={1}` |
| family:squads | `reachable; 1 record(s); provider_ids={11}` |
| family:players | `reachable; 1 record(s); provider_ids={101}` |
| family:lineups | `reachable; 1 record(s); provider_ids={21}` |
| family:formations | `reachable; 1 record(s); provider_ids={31}` |
| family:substitutions | `reachable; 1 record(s); provider_ids={41}` |
| family:injuries | `reachable; 1 record(s); provider_ids={51}` |
| family:suspensions | `reachable; 1 record(s); provider_ids={61}` |
| family:coaches | `reachable; 1 record(s); provider_ids={71}` |
| family:referees | `reachable; 1 record(s); provider_ids={81}` |
| family:team_statistics | `reachable; 1 record(s); provider_ids={91}` |
| family:player_statistics | `reachable; 1 record(s); provider_ids={1011}` |

## Warnings

- mock mode: shapes are documentation-derived and carry "status": "unverified_against_live" until FI-9

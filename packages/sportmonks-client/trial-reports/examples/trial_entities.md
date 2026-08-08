# trial_entities — trial report

Mode: `mock`

| # | Objective | Status | Evidence |
|---|---|---|---|
| 1 | competition and season identifiers | `observed` | leagues: reachable (1 records, ids={8}); seasons: reachable (1 records, ids={23614}) |

## Observed shapes

| Name | Shape as found |
|---|---|
| family:leagues | `status=reachable records=1 provider_ids={8}` |
| family:seasons | `status=reachable records=1 provider_ids={23614}` |
| family:fixtures | `status=reachable records=1 provider_ids={1001}` |
| family:teams | `status=reachable records=1 provider_ids={1}` |
| family:squads | `status=reachable records=1 provider_ids={11}` |
| family:players | `status=reachable records=1 provider_ids={101}` |
| family:lineups | `status=reachable records=1 provider_ids={21}` |
| family:formations | `status=reachable records=1 provider_ids={31}` |
| family:substitutions | `status=reachable records=1 provider_ids={41}` |
| family:injuries | `status=reachable records=1 provider_ids={51}` |
| family:suspensions | `status=reachable records=1 provider_ids={61}` |
| family:coaches | `status=reachable records=1 provider_ids={71}` |
| family:referees | `status=reachable records=1 provider_ids={81}` |
| family:team_statistics | `status=reachable records=1 provider_ids={91}` |
| family:player_statistics | `status=reachable records=1 provider_ids={1011}` |

## Warnings

- mock mode: family payloads are documentation-derived and carry "status": "unverified_against_live" until FI-9

# trial_injuries — trial report

Mode: `mock`

| # | Objective | Status | Evidence |
|---|---|---|---|
| 11 | Injuries | `observed` | 2 injury record(s); fields observed: id, player_id, type_id, expected_return, updated_at; 2 carry a 'updated_at' freshness timestamp, 0 do not (reported degraded, never defaulted to fresh) |
| 11 | Suspensions | `observed` | 1 suspension record(s); fields observed: id, player_id, type_id, games_remaining |
| 12 | Coaches and manager records | `observed` | 1 coach/manager record(s); fields observed: id, name, team_id |

## Observed shapes

| Name | Shape as found |
|---|---|
| injury_record_fields | `id, player_id, type_id, expected_return, updated_at` |
| injury_freshness_field | `updated_at` |
| suspension_record_fields | `id, player_id, type_id, games_remaining` |
| coach_record_fields | `id, name, team_id` |

## Warnings

- mock mode: shapes are documentation-derived and carry "status": "unverified_against_live" until FI-9

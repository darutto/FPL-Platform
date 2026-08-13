# trial_injuries — trial report

Mode: `mock`

| # | Objective | Status | Evidence |
|---|---|---|---|
| 11 | Injuries and suspensions | `observed` | injuries: 1 record(s), 1 with a freshness field [updated_at]; suspensions: 1 record(s) |
| 12 | Coaches and manager records | `observed` | coaches: 1 record(s) |

## Observed shapes

| Name | Shape as found |
|---|---|
| injuries | `1 record(s); record{id,player_id,type_id,expected_return,updated_at}` |
| suspensions | `1 record(s); record{id,player_id,type_id,games_remaining}` |
| coaches | `1 record(s); record{id,name,team_id}` |
| injury_freshness | `field=updated_at; 1/1 record(s) stamped` |

## Warnings

- injury freshness timestamps were synthesized for the rehearsal; the field name the provider actually uses is unverified until FI-9
- mock mode: shapes are documentation-derived and carry "status": "unverified_against_live" until FI-9

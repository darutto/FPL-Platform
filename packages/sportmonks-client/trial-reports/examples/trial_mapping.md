# trial_mapping — trial report

Mode: `mock`

| # | Objective | Status | Evidence |
|---|---|---|---|
| 19 | FPL identity-match rate | `observed` | 20/20 matched automatically = 100.0% against a 841-candidate registry (gate ≥95.0%) |
| 18 | Stable provider IDs | `observed` | 20 entit(ies) in both snapshots; 0 provider_id change(s) |

## Observed shapes

| Name | Shape as found |
|---|---|
| provider_player_pool | `20 record(s); record{id,name,display_name,date_of_birth,team}` |
| match_tiers | `full_name_birth_date 19,full_name_team 1` |
| unresolved_reasons | `none unresolved` |
| provider_id_stability | `20 compared; 0 changed; 0 appeared; 0 disappeared` |

## Warnings

- the mock provider pool is synthesized from the identity registry's own candidates, so it matches by construction; its rate is a property of the rehearsal and is not evidence about Sportmonks. The rate that counts against the ≥95% gate is the one FI-9 computes on a real provider pool
- mock mode: shapes are documentation-derived and carry "status": "unverified_against_live" until FI-9

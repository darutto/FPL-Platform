# trial_fixtures — trial report

Mode: `mock`

| # | Objective | Status | Evidence |
|---|---|---|---|
| 2 | Premier League fixtures | `observed` | requested league_id=8, season_id=23614; 1 fixture(s); season_ids returned=(23614,); league_ids returned=(8,) |
| 3 | Cross-competition fixtures for Premier League clubs | `observed` | swept 1 team(s) by team_id with no competition filter; 2 fixture(s); competitions inside=(8,), outside=(9,) |

## Observed shapes

| Name | Shape as found |
|---|---|
| season_fixtures | `data; record{id,league_id,season_id,starting_at}` |
| cross_competition_fixtures | `data; record{id,league_id,season_id,starting_at}` |

## Warnings

- cross-competition fixtures were synthesized for the rehearsal; objective 3 is unverified against live until FI-9
- mock mode: shapes are documentation-derived and carry "status": "unverified_against_live" until FI-9

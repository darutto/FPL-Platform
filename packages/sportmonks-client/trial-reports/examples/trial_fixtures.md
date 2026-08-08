# trial_fixtures — trial report

Mode: `mock`

| # | Objective | Status | Evidence |
|---|---|---|---|
| 2 | Premier League fixtures | `observed` | 2 fixture(s), all league_id=8 season_id=23614 |
| 3 | cross-competition fixtures for Premier League clubs | `observed` | 2 fixture(s) for club id 1 across leagues [2, 24] |

## Observed shapes

| Name | Shape as found |
|---|---|
| season_fixtures | `fixture{id,league_id,participants,season_id,starting_at}` |
| cross_competition_leagues | `2,24` |

## Warnings

- mock mode: fixture payloads are documentation-derived and carry "status": "unverified_against_live" until FI-9

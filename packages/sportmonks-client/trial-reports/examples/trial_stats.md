# trial_stats — trial report

Mode: `mock`

| # | Objective | Status | Evidence |
|---|---|---|---|
| 13 | Fixture-level team statistics | `observed` | 2 record(s); field presence: fixture_id=2/2, team_id=2/2, type_id=2/2, value=2/2 |
| 14 | Player match statistics | `observed` | 2 record(s); field presence: fixture_id=2/2, player_id=2/2, type_id=2/2, value=2/2 |
| 15 | Data update timing before, during, and after matches | `not_applicable` | requires FI-9 live observation |
| 16 | Post-match corrections | `not_applicable` | requires FI-9 live observation |

## Observed shapes

| Name | Shape as found |
|---|---|
| team_statistics_fields | `fixture_id, team_id, type_id, value` |
| player_statistics_fields | `fixture_id, player_id, type_id, value` |

## Warnings

- mock mode: shapes are documentation-derived and carry "status": "unverified_against_live" until FI-9
- objectives 15 and 16 are a recording scaffold only in FI-8; see StatSample/diff_samples and tests/test_trial_health_stats.py

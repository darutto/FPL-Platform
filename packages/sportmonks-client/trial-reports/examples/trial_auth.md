# trial_auth — trial report

Mode: `mock`

| # | Objective | Status | Evidence |
|---|---|---|---|
| 17 | API rate limits and pagination | `observed` | walked 2 pages, 2 records; rate-limit headers observed |

## Observed shapes

| Name | Shape as found |
|---|---|
| pagination | `envelope.meta.pagination{current_page,has_more,next_page}` |
| rate_limit_headers | `x-ratelimit-limit, x-ratelimit-remaining, x-ratelimit-reset` |

## Warnings

- mock mode: shapes are documentation-derived and carry "status": "unverified_against_live" until FI-9

# trial_auth — trial report

Mode: `mock`

| # | Objective | Status | Evidence |
|---|---|---|---|
| 17 | API rate limits and pagination | `observed` | walked 2 pages, 2 records; pagination at: pagination; rate-limit fields seen: x-ratelimit-limit, x-ratelimit-remaining, x-ratelimit-reset; throttled responses: 1 (with Retry-After: 1) |

## Observed shapes

| Name | Shape as found |
|---|---|
| pagination | `envelope.pagination{current_page,has_more,next_page}` |
| rate_limit_headers | `x-ratelimit-limit, x-ratelimit-remaining, x-ratelimit-reset` |
| retry_after | `HTTP 429 retry-after=2` |

## Warnings

- mock mode: shapes are documentation-derived and carry "status": "unverified_against_live" until FI-9

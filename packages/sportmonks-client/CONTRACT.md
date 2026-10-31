# Sportmonks client contract — FI-3

## Ownership and boundary

This package is the sole owner of Sportmonks URLs, authentication, query/include
syntax, pagination, provider IDs and fields, response envelopes, errors, and
documentation-derived normalization assumptions. No provider type may cross
into canonical contracts, identity, intelligence, assistant, or UI packages.
FI-3 performs no canonical normalization, persistence, R2 publication, runtime
integration, identity mapping, feature computation, or recommendation work.

## Configuration and authentication

`SPORTMONKS_API_TOKEN` has no default and is required only for live client
construction. `SPORTMONKS_BASE_URL` defaults to the v3 football URL;
`SPORTMONKS_TIMEOUT_SECONDS=15`, `SPORTMONKS_MAX_RETRIES=3`, and
`SPORTMONKS_BACKOFF_SECONDS=0.5`, and `SPORTMONKS_MAX_RESPONSE_BYTES=4194304`.
The body cap must be an integer in the inclusive range 1â€“67108864 bytes.
Invalid values fail before any request.
The token is placed only in the assumed `api_token` query location and is
removed from snapshots, errors, logs, fixtures, and test output. Offline clients
require neither token nor network.

## Transport

`Transport.request(method, url, params, timeout) -> TransportResponse` is the
injection boundary. `RequestsTransport` is the only production network owner
and uses the repository's existing `requests` dependency. Endpoint/model code
never performs HTTP. Responses are streamed in 64 KiB chunks and closed on
every successful or exceptional path. A declared oversize `Content-Length`
fails before reading; missing, malformed, chunked, or misleading lengths are
still bounded during iteration. Exceeding the cap raises
`SportmonksResponseSizeError`, is not retried, and never includes a URL or
token. Transport responses preserve status, headers, and parsed JSON;
malformed JSON raises `SportmonksResponseError`.

Authenticated requests set `allow_redirects=False`. Any 3xx response becomes a
non-retryable typed request failure; credentials are never forwarded to another
origin or redirect target.

All `requests.RequestException` subclasses are converted at this boundary.
Raw causes are discarded after safe retry classification and the typed error is
raised outside the catch block with no `__cause__` or `__context__`; authenticated
URLs therefore cannot leak through tracebacks, exception logging, or telemetry.
This also applies after response headers: streamed `RequestException` failures
are converted to secret-safe `SportmonksRequestError` only after the response
closes and the raw exception context is discarded. Timeout, connection, and
`ChunkedEncodingError` stream failures are retryable under the existing bounded
GET policy; `ContentDecodingError` is non-retryable. Size-limit errors remain
typed response errors and are never retried.

## Endpoint interfaces

The typed client exposes leagues, seasons, fixtures, teams, squads, players,
lineups, formations, substitutions, injuries, suspensions, coaches, referees,
team fixture statistics, and player fixture statistics. Paths and provider
fields are governed in `client.ENDPOINTS` and remain unverified against live.
Provider entities are immutable, preserve integer provider ID, source endpoint,
and unknown raw fields, and never produce canonical entities.

## Family routes — live v3 is not the documentation-derived layout

Added 2026-10-11 after FI-9 day 0. The fifteen "families" were written against
mocks taken from the documentation, as if each were a root endpoint. Live
disagrees for eight of them (`404` at the root, measured one call each). Live
wins: `ENDPOINTS` in `client.py` now maps each family to a `Route`
(`path`, `model`, and for derived families `include`, `extract`, `where`,
`unwrap`). `ENDPOINTS[family][0]` is still the mock key; it may carry
`{placeholders}` that `scope` fills (`route_path`).

| Family | Route | Include → nested list | Why this and not the root |
|---|---|---|---|
| leagues, seasons, coaches, referees | `GET /<family>` | – | root works (200). `seasons` is filtered with `filters=seasonLeagues:<id>` |
| players | `squads/teams/{team_id}` | `player` → `player` | root `/players` is the whole database and unfiltered; the squad route with the include gives the clubs' players in the same 20 requests as `squads`. `players/multi/{ids}` answers 404. Each player also carries `squad_team_id`, the Sportmonks club of the squad row it came from (`Route.inherit`) |
| teams | `teams/seasons/{season_id}` | – | root `/teams` is every club in the database; this is the 20 PL clubs |
| squads | `squads/teams/{team_id}` | – | root `/squads` is 404; one request per club |
| fixtures | `GET /fixtures`, `filters=fixtureSeasons:<id>;fixtureLeagues:<id>` | – | root works; ordered newest/future first |
| (extra) `current_sidelined` | `teams/{team_id}` (`data` is one object) | `sidelined` → `sidelined` | a club's open absences, independent of any match; 20 requests per pass. Polled by `trial_sidelined.py` |
| (extra) `team_fixtures` | `fixtures/between/{start}/{end}/{team_id}` | – | one club across every covered competition in one call; not one of the fifteen |
| (extra) `licensed_pl_fixtures` | `fixtures/between/{start}/{end}`, `filters=fixtureLeagues:8` | `participants;lineups.detailedPosition;formations;state;metadata`, records kept whole | production ingestion: one call per window carries every PL fixture's predicted/confirmed lineup (`metadata` type 572), formation, state and home/away. Each include was read live on the trial; the combination is first exercised by the production live smoke |
| (extra) `licensed_pl_fixtures_stats` | `fixtures/between/{start}/{end}`, `filters=fixtureLeagues:8` | `participants;lineups.detailedPosition;lineups.details;formations;state;metadata`, records kept whole | R6: the same window with each player's per-match statistics (`lineups.details`: `type_id` + `data.value`). Only finished matches carry details; ~100 KB per fixture, so callers page by 10 |
| (extra) `player_stat_types` | `fixtures/{fixture_id}` (one object) | `lineups.details.type`; extracts `lineups.details`, lifts `type.developer_name` to `type_name` | R6: the provider's own statistic names, because `core/types` answers 404 on the trial token. 1 call |
| (extra) `licensed_team_fixtures` | `fixtures/between/{start}/{end}/{team_id}` | `participants;state`, records kept whole | production ingestion: a club's fixtures in every competition the plan returns (FA Cup / Carabao best effort, Q10), with home/away |
| (extra) `licensed_squads` | `squads/teams/{team_id}` | `player`, records kept whole (the player nested under `player`) | production ingestion: squad row (jersey number) and the player record for identity in one request per club |
| lineups | `fixtures/between/{start}/{end}` | `lineups.detailedPosition` → `lineups`, lifting `detailedposition.{id,name}` to `detailed_position_id` / `detailed_position` | `/lineups` is 404. Starters carry a detailed position (GK, Centre Back, Right/Left Back, Right/Left Midfield, Central/Attacking Midfield, Attacker); the bench carries none, like the grid |
| formations | same | `formations` → `formations` | `/formations` is 404 |
| substitutions | same | `events` → `events`, keep `type_id == 18` | substitutions are events; `/substitutions` is 404 |
| injuries | same | `sidelined.sideline` → `sidelined`, keep `category == "injury"` | `/injuries` is 404 |
| suspensions | same | `sidelined.sideline`, keep `category == "suspended"` | `/suspensions` is 404 |
| team_statistics | same | `statistics` → `statistics` | `/statistics/fixtures/teams` is 404 |
| player_statistics | same | `lineups.details` → `lineups[].details` | `/statistics/fixtures/players` is 404 |

Rules that follow from this:

- `fixtures/between` is capped by the provider: a 2026-08-01..2027-06-30 window
  answers `422`. The trial scripts use a 14-day window (`WINDOW_DAYS`).
- **Shared includes are shared requests.** injuries and suspensions both ride
  `sidelined.sideline`; if that request fails, both are absent. They are no
  longer independent observations and the mocks no longer pretend they are
  (`routes_transport`).
- Sideline rows repeat on every fixture they span; `unwrap` hoists the nested
  `sideline` object over the row and the client de-duplicates by its id, so an
  injury's `provider_id` is the sideline id, not a row id.
- `next_page` arrives as a URL (`…?page=2`), not an int (#408).
- Every live list walk takes an explicit page bound (`LIVE_MAX_PAGES = 4`,
  `per_page=50`). Hitting it is reported as `truncated`, never as a census:
  `fixtures`, `players`, `coaches`, `referees` are truncated in a day-0 sweep.
- A `404` cannot tell "not in the plan" from "no such route/include": both
  answer the same. Day 0 separated them by finding the same data under a
  different route (the eight families above), not by the status code.
- Mock fixtures: `tests/fixtures/endpoint_payloads.json` was re-shaped to what
  live returned for lineups, formations, substitutions, injuries, suspensions
  and both statistics families. Where a mock contradicted live, live won
  (substitution direction is `player_id` = on, `related_player_id` = off; stat
  rows carry `participant_id` and a nested `data.value`). Families not yet
  observed live keep `status: unverified_against_live`.
- Team-level sidelined is also reachable: `teams/{id}?include=sidelined`
  answers 200 with the club's current rows (`category`, `start_date`,
  `end_date`, `games_missed`, `completed`). It is not wired as a family yet.
  `players/{id}?include=sidelined` and `sidelined/…` answer 404.

## Envelope and pagination

Documented `data` collections and optional `pagination` (direct or under
`meta`) are supported. `current_page` and boolean `has_more` are required when
pagination exists; `next_page` is optional. Iteration is deterministic, empty
sets work, repeated pages fail, disappearing/malformed pagination fails, and
`max_pages` (default 100) bounds traversal.

## Retry, rate limit, and errors

Only GET is used. Transient connection/timeout errors, HTTP 429, and 5xx retry
up to the configured bound with injectable exponential backoff. Numeric
`Retry-After` wins only when finite and non-negative and is clamped to
`MAX_RETRY_AFTER_SECONDS=60.0`. Negative, non-finite, missing, malformed, and
HTTP-date values fall back to bounded exponential backoff. Every sleep is in
the inclusive range 0–60 seconds. HTTP 400 and other non-retryable 4xx fail immediately;
401/403 fail as authentication errors. No retry loop is unbounded.

Closed hierarchy: `SportmonksError`, `SportmonksConfigurationError`,
`SportmonksAuthenticationError`, `SportmonksRateLimitError`,
`SportmonksRequestError`, `SportmonksResponseError`, `SportmonksResponseSizeError`,
`SportmonksPaginationError`, and `SportmonksSchemaError`. Context may include
endpoint/status, never credentials.

## Raw response and cache hook

`RawResponseSnapshot` preserves endpoint, redacted parameters, UTC fetch time,
status, provider metadata, raw JSON, and schema version for an injected hook.
FI-3 supplies no filesystem cache and writes nothing under `data/football`.

## Fixtures and assumptions

Every checked fixture labels itself documentation-derived or manually
constructed, `unverified_against_live`, and sanitized. Coverage includes every
endpoint family, one/multiple/empty pages, absent optional fields, malformed
envelopes/JSON, 401/403, 429 with/without Retry-After, 4xx/5xx, and loops.

The assumption registry governs base URL/API version, query authentication,
paths/includes, pagination, lineup/formation/grid/detailed positions,
injury/suspension shapes, statistics nesting, rate headers, and correction
behavior. Every entry starts `unverified_against_live` with source, fixture,
and mandatory live-validation flag. No public example is claimed as live proof.

## Running the suite locally on Windows — pass `--basetemp`

```
PYTHONIOENCODING=utf-8 python -m pytest --basetemp=<a writable dir>
```

Without `--basetemp`, every `tmp_path` test errors with
`PermissionError: [WinError 5]` on `%LOCALAPPDATA%\Temp\pytest-of-<user>`. The
suite is not broken and the count is not wrong — the fixture cannot create its
directory. **A test that errors cannot falsify anything**, so any seeding probe
or falsification check run without this flag silently over-reports survivors.
`PYTHONIOENCODING=utf-8` separately avoids `cp1252` `UnicodeEncodeError` on
console output containing non-ASCII.

**A seeding probe needs both controls.** Score a seed as killed only from a run
that *failed*, never one that *errored*, and include two controls in every
probe: a no-op edit that must survive, and a known-bad edit that must be
killed. An FI-8 probe scored all twelve of its seeds as "killed" while
measuring nothing — the `--basetemp` parent directory did not exist, so every
run errored out and returned non-zero. The no-op control is what exposed it.
Also verify the seed was applied: a probe whose search string does not match
silently tests the unmodified tree.

## Directory naming — non-package directories are hyphenated

Directories inside a package root that are **not** Python packages get
hyphenated names (`trial-output/`, `trial-reports/`, and `audit-reference/` in
`fpl-data-core` and `fpl-api-client`), because the package root is on
`pythonpath` and a hyphen cannot be imported — not as a package, and not as a
PEP 420 namespace package either. Deleting `__init__.py` is **not** sufficient:
without it the directory becomes an implicit namespace package that also merges
with same-named directories on other path entries. This is the third use of the
trick; write nothing new as `trial_output/`.

## Live guard and change rules

FI-8's trial scripts are guarded twice. At runtime, `--mock` is the default and
a live run requires both `--live` and `--i-understand-this-is-live`, mirroring
the smoke CLI's `REFUSED` path and exit code 2. In tests, an autouse fixture in
`tests/conftest.py` patches every HTTP entry point the package's dependencies
expose (`requests.Session.request`, `requests.adapters.HTTPAdapter.send`) to
raise. That guards the boundary rather than `RequestsTransport`, which is a
wrapper around it — patching the wrapper was measured at 18 failed / 49 passed
because the transport's own tests legitimately construct it with injected fake
sessions. If an HTTP client is ever added to `requirements.txt`, its entry point
joins the guard in the same change.

`python -m sportmonks_client.cli smoke` refuses without explicit opt-in and a
token. It is excluded from ordinary tests/CI and must remain the smallest safe
request: it uses `fetch_page` and performs exactly one authenticated HTTP call,
even when page one reports more results. Provider-shape changes are contained here. Canonical conversion begins
in FI-4 only after the approved pre-FI-4 reconciliation checkpoint.

## Pre-live checkpoint decisions

- Missing configuration for live client construction remains
  `SportmonksConfigurationError`. `ProviderUnavailable` is not a transport
  exception. Future runtime capability discovery may expose disabled/unavailable
  status without constructing a live client or throwing through a request path.
- A proactive token bucket is not required for offline FI-4a. Any later live
  ingestion must be serialized, deliberately paced, observe sanitized rate
  headers, and retain the bounded reactive 429 policy. Revisit only if trial
  measurements show scheduling is insufficient.
- The FI-4a streaming response-body cap is implemented and tested, but this
  does not authorize live ingestion. Post-download `len(response.content)` is
  not used as a resource cap. Live trial authorization remains FI-4b work.
- Snapshot metadata preserves only case-folded `content-type`, `date`,
  `retry-after`, `x-ratelimit-limit`, `x-ratelimit-remaining`,
  `x-ratelimit-reset`, and `x-request-id`. Cookies, authorization, URLs, and
  unapproved headers are discarded. Persistence remains FI-4a work.
- A non-object `meta`, malformed pagination object, or invalid pagination field
  raises `SportmonksSchemaError` before FI-4 replay consumes it.

Breaking changes include error semantics, retry safety, endpoint signatures,
pagination interpretation, or removal/reinterpretation of provider fields.
Assumption statuses may change only with recorded live evidence.

## Lineup grid semantics (live, 2026-10-11)

`formation_field` is `"row:col"`: row 1 is the goalkeeper and rows rise towards
the attack; `formation_position` is a 1–11 running index. `col` is **absolute
along the touchline, not relative to the team**: for the home team col 1 is its
right and the highest col its left; for the away team the numbering is mirrored.
Checked against the provider's own detailed position over GW1–GW6 (59 matches):
420 of 420 Right Back / Left Back / Right Midfield / Left Midfield starters sit
in the predicted cell. Only starters (`type_id` 11) carry a grid cell and a
detailed position; the bench (`type_id` 12) carries neither, which is expected
and is reported apart from the objective's denominator. Home/away comes from
`formations[].location`. Left/right for central roles is inference, not a
provider field.

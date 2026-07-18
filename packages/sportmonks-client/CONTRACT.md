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

## Live guard and change rules

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

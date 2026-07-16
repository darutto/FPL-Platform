# sportmonks-client

FI-3 provides the offline-tested, provider-owned Sportmonks client boundary.
It owns configuration, authentication, endpoint paths, provider models,
response envelopes, pagination, retries, errors, and raw snapshot hooks. It
does not normalize into canonical contracts or write data stores.

```python
client = SportmonksClient.offline(fake_transport)  # no token, no network
players = client.players(include="team")
```

Live construction requires `SPORTMONKS_API_TOKEN`. Defaults are base URL
`https://api.sportmonks.com/v3/football`, timeout 15 seconds, 3 retries, and
0.5-second exponential backoff. All are documentation-derived and remain
`unverified_against_live`.

The explicit smoke command refuses to run without both a token and opt-in:

```bash
python -m sportmonks_client.cli smoke --i-understand-this-is-live
```

Do not run it in FI-3, tests, or CI. See `CONTRACT.md` and
`sportmonks_client.assumptions.assumption_registry()` for trial obligations.
The command fetches exactly one page/request. Raw `requests` causes are
discarded at the transport boundary. Numeric `Retry-After` is clamped to 60
seconds; invalid, non-finite, negative, HTTP-date, or missing values use bounded
exponential backoff.

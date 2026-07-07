# fpl-tactical — Decisions

## T1a — Ingest client: adopt `soccerdata` (2026-07-07)

**Decision:** use `soccerdata` (v1.9.0, `soccerdata.Understat`) as the Understat ingest client for the tactical store. Its reader is **not** broken by Understat's move to gzip AJAX endpoints — it already targets them (`getLeagueData`/`getMatchData` with `X-Requested-With: XMLHttpRequest`, via `tls_requests`). No internal client needed; `understatapi` stays retired.

**Verified** (scratch venv, Python 3.13, live pull): `Understat(leagues="ENG-Premier League", seasons="2025-2026").read_shot_events()` returned **9,524 shots across all 380 games / 20 teams of 2025/26**, with per-shot `location_x`, `location_y` (0–1), `xg`, `situation`, `result`, `body_part`, `minute`, plus `team` and `player` in the index. Reproduce with `scripts/t1a_spike.py`.

**Caveats found (T1b must handle):**
1. **Penalties arrive as `situation = NA`** — soccerdata's `SHOT_SITUATIONS` map omits `"Penalty"`. Verified: all 92 NA-situation rows sit at the penalty-spot signature (x=0.885, y=0.5, xG≈0.761). Ingest must re-label `NA → "Penalty"` so the T2 engine can exclude them from zonal aggregation.
2. **Situation/result strings are normalized** ("Open Play", "Missed Shot"), not raw Understat camel-case ("OpenPlay", "MissedShots"). The parquet schema will store soccerdata's normalized values; the T2 engine must match them.
3. **No `conceding_team` / `is_home_shot` columns** — derive by joining `read_schedule()` (home/away per `game_id`) at ingest time, per the plan's schema.
4. **Runtime deps:** first run downloads a `tls-client` DLL/binary (~internet access needed once per environment) and caches raw pulls under `~/soccerdata/data/Understat`. Relevant for CI/Railway; ingest runs in the weekly workflow, never in a request handler.

## T1c — R2 publish under a distinct `tactical/` prefix (2026-07-07)

Publish/sync lives in `fpl_tactical/publish.py`, reusing the FPL owned store's
`OWNED_STORE_R2_*` env vars under a distinct `tactical/<season>/` key segment
so it can never collide with the owned store's `seasons/...` namespace.
Weekly refresh: `.github/workflows/tactical-store-refresh.yml` (Mondays
06:30 UTC, offset from owned-store-refresh; `workflow_dispatch` for manual
runs). The serving side pulls via `python -m fpl_tactical.publish sync`
(fail-soft) — soccerdata is a weekly-workflow dependency only and never
ships to the server.

**TODO (flagged):** R2 secrets were not available in this environment, so the
publish step is untested against a live bucket. Local parquet + pointer are in
place; a `workflow_dispatch` run of `tactical-store-refresh.yml` (secrets
already wired for owned-store-refresh) is the remaining verification. Also
wire `python -m fpl_tactical.publish sync` into the server's startup (mirror
`OWNED_STORE_SYNC_ENABLED` gating) when a consumer needs the store in prod.

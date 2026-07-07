# fpl-tactical — Decisions

## T1a — Ingest client: adopt `soccerdata` (2026-07-07)

**Decision:** use `soccerdata` (v1.9.0, `soccerdata.Understat`) as the Understat ingest client for the tactical store. Its reader is **not** broken by Understat's move to gzip AJAX endpoints — it already targets them (`getLeagueData`/`getMatchData` with `X-Requested-With: XMLHttpRequest`, via `tls_requests`). No internal client needed; `understatapi` stays retired.

**Verified** (scratch venv, Python 3.13, live pull): `Understat(leagues="ENG-Premier League", seasons="2025-2026").read_shot_events()` returned **9,524 shots across all 380 games / 20 teams of 2025/26**, with per-shot `location_x`, `location_y` (0–1), `xg`, `situation`, `result`, `body_part`, `minute`, plus `team` and `player` in the index. Reproduce with `scripts/t1a_spike.py`.

**Caveats found (T1b must handle):**
1. **Penalties arrive as `situation = NA`** — soccerdata's `SHOT_SITUATIONS` map omits `"Penalty"`. Verified: all 92 NA-situation rows sit at the penalty-spot signature (x=0.885, y=0.5, xG≈0.761). Ingest must re-label `NA → "Penalty"` so the T2 engine can exclude them from zonal aggregation.
2. **Situation/result strings are normalized** ("Open Play", "Missed Shot"), not raw Understat camel-case ("OpenPlay", "MissedShots"). The parquet schema will store soccerdata's normalized values; the T2 engine must match them.
3. **No `conceding_team` / `is_home_shot` columns** — derive by joining `read_schedule()` (home/away per `game_id`) at ingest time, per the plan's schema.
4. **Runtime deps:** first run downloads a `tls-client` DLL/binary (~internet access needed once per environment) and caches raw pulls under `~/soccerdata/data/Understat`. Relevant for CI/Railway; ingest runs in the weekly workflow, never in a request handler.

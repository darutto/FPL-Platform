# fpl-tactical CONTRACT

## §1 Source + endpoints

Ingest client is `soccerdata.Understat` (T1a decision — DECISIONS.md). It
targets Understat's current gzip AJAX endpoints (`getLeagueData/EPL/<yyyy>`,
`getMatchData/<match_id>`); we own none of that surface — soccerdata tracks
upstream churn. Network is touched **only** by `understat_client.fetch_raw`
(CLI/workflow path). Never scrape inside a request handler.

## §2 `understat_shots` parquet schema

| column | type | notes |
|---|---|---|
| `season` | str | `"2025-2026"` (fpl-historical season key style) |
| `match_id` | int64 | Understat match id (soccerdata `game_id`) |
| `date` | str | ISO `YYYY-MM-DDTHH:MM:SS` |
| `shooting_team` | str | Understat title, e.g. `"Manchester City"` |
| `conceding_team` | str | opponent — precomputed at ingest (schedule join) |
| `player` | str | shooter |
| `is_home_shot` | bool | shot by home side |
| `minute` | int64 | |
| `x`, `y` | float64 | Understat coordinates, 0–1 |
| `xg` | float64 | Understat xG |
| `situation` | str | soccerdata-normalized: `Open Play` / `From Corner` / `Set Piece` / `Direct Freekick` / `Penalty` |
| `shot_type` | str | soccerdata `body_part` |
| `result` | str | soccerdata-normalized: `Goal` / `Saved Shot` / `Missed Shot` / `Blocked Shot` / `Shot On Post` / `Own Goal` |

## §3 Penalty invariant

`fpl_tactical.PENALTY_SITUATION == "Penalty"` is the **single shared
constant**; the ingest re-label and the zonal engine's exclusion both use it.
soccerdata delivers penalties as `situation = NA`; ingest re-labels NA rows
only when they match the penalty signature (x≈0.885, y≈0.5, xG≈0.76) and
**fails loudly** otherwise (upstream mapping drift).

## §4 Provenance pointer `_tactical_latest.json`

`{season, ingested_at (UTC ISO Z), source, source_version, n_matches,
n_shots}` — rewritten atomically on every ingest.

## §5 Idempotency

Re-running `ingest` for a season fully replaces that season's parquet via
temp-write → `os.replace` (atomic) and refreshes the pointer. Same-source
re-runs yield identical row counts; no duplication.

## §6 R2 layout

`r2://<bucket>/<OWNED_STORE_R2_PREFIX>tactical/<season>/{understat_shots.parquet,_tactical_latest.json}`
— same `OWNED_STORE_R2_*` credentials as the FPL owned store, distinct
`tactical/` segment so the namespaces can never collide. Publish is loud;
sync is fail-soft (server degrades to `missing_context`).

## §7 Refresh cadence

Weekly (`30 6 * * 1`, offset from owned-store-refresh) + manual
`workflow_dispatch`. Full-league pass ≈ 380 polite requests; soccerdata
caches raw pulls under `~/soccerdata/data/Understat`.

## §8 Consumer invariants (engine/tools)

1. **Relative-to-baseline only** — consumers report `delta_vs_avg` per zone,
   never raw zone totals as a signal.
2. **Zone grid is locked** (PoC-validated): in-box x ≥ 0.84; edge-of-box
   0.70 ≤ x < 0.84; left y < 0.36; right y > 0.64; long-range ignored.
3. **Attacker-frame laterals** — flip to the defending team's side when
   phrasing verdicts (finish-zone, not buildup-flank; T3 upgrades this).
4. **No buy/sell language**; verdicts Spanish, opportunity/weakness-framed.
5. Missing store → `status="missing_context"`, never an exception.

## §9 Dependency boundary

`soccerdata` (and its tls-client binary download) is a weekly-workflow /
build-time dependency only. The serving deployment reads parquet from R2;
`fpl_tactical/__init__.py` stays import-light so `fpl_grounded_assistant`
can import the shared constants at request time.

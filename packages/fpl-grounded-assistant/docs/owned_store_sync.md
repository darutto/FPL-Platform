# Owned-Store R2 Sync — Operator Rollout Notes

Track A H5. Audience: operators deploying `fpl-grounded-assistant` (the
Railway service). This document covers how the deployed server obtains its
owned parquet data, how to keep it fresh, and how to roll the feature back.

## Delivery model

The owned-store data (the merged parquet snapshot that backs the
owned-store *fallback* used when the live FPL API is unavailable) is
delivered to the deployed server by a **startup sync from Cloudflare R2**.

- On boot, if sync is enabled and configured, the server downloads the
  pointer file plus the five merged parquet files from an R2 bucket into the
  local historical store (`FPL_HISTORICAL_ROOT`, set to `/app/owned-data` in
  the Dockerfile).
- The sync is **fail-soft**: if it fails for any reason (missing creds,
  network error, partial download), the server **still starts**. It does not
  crash the process. The owned-store fallback simply stays **inert** until a
  successful sync has landed a complete, valid set of local files.
- The sync is **default-off**. With `OWNED_STORE_SYNC_ENABLED` unset the
  server never contacts R2 and behaves exactly as a live-only deployment.

There is **no automatic refresh** in this slice — no cron, no background
poller. The server syncs once at startup and then serves whatever it pulled
until it is restarted.

## Freshness ownership (read this)

**The operator owns freshness.** The deployed data is only as fresh as the
last `publish`. Because there is no background refresh, the snapshot the
server pulled on its last boot is the snapshot it keeps using.

The refresh pipeline is fully manual:

1. **Capture + merge locally** using `fpl-historical` (produces the merged
   parquet under the local season's `parquet_merged/` plus the
   `_owned_latest.json` pointer).
2. **Publish to R2**:
   ```
   cd packages/fpl-grounded-assistant
   python fpl_grounded_assistant/owned_store_sync.py publish
   ```
   This uploads the local pointer + parquet to the configured R2 bucket.
   (Invoke via the direct file path, not `python -m ...` — the package
   `__init__.py` eagerly imports the full dispatcher graph including
   sibling packages, which fails outside a fully wired environment. The
   sync module itself has no such dependencies.)
3. **Redeploy or restart** the Railway service so it re-runs the startup
   sync and picks up the freshly published files.

If you skip step 3, the running server keeps serving the *old* snapshot even
though R2 now holds newer data.

Staleness is observable in two places:

- `GET /healthz` — `owned_store_sync.staleness_hours` (age of the snapshot
  pulled at startup) and `owned_store_fallback.staleness_hours` (age of the
  snapshot a fallback actually served, when one was used).
- Startup logs — the sync result (ok / files / merged_at / staleness) is
  logged on boot.

## Required environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OWNED_STORE_SYNC_ENABLED` | no | off | Master switch. Truthy (`1`/`true`/`yes`) enables startup sync. Unset/`0`/`false`/`no`/`off` disables it. |
| `OWNED_STORE_R2_ENDPOINT` | yes (when enabled) | — | R2 S3-compatible endpoint, e.g. `https://<accountid>.r2.cloudflarestorage.com`. |
| `OWNED_STORE_R2_BUCKET` | yes (when enabled) | — | R2 bucket name holding the owned store. |
| `OWNED_STORE_R2_ACCESS_KEY_ID` | yes (when enabled) | — | R2 API token access key id. |
| `OWNED_STORE_R2_SECRET_ACCESS_KEY` | yes (when enabled) | — | R2 API token secret access key. |
| `OWNED_STORE_R2_PREFIX` | no | empty | Optional key prefix prepended to all R2 object keys. |

R2 object layout (relative to `OWNED_STORE_R2_PREFIX`):

```
{prefix}seasons/{season}/_owned_latest.json
{prefix}seasons/{season}/parquet_merged/players.parquet
{prefix}seasons/{season}/parquet_merged/teams.parquet
{prefix}seasons/{season}/parquet_merged/events.parquet
{prefix}seasons/{season}/parquet_merged/fixtures.parquet
{prefix}seasons/{season}/parquet_merged/player_gw_stats.parquet
```

Note: `FPL_HISTORICAL_ROOT` is set in the Dockerfile to `/app/owned-data`,
so synced files land there in the deployed container. Do not override it
unless you also relocate the data dir.

## Operational steps

### First-time R2 setup

1. In the Cloudflare dashboard, create an **R2 bucket** (e.g. `fpl-owned`).
2. Create an **R2 API token** scoped to that bucket; record the generated
   **Access Key ID** and **Secret Access Key**.
3. Note the **S3 API endpoint** for your account
   (`https://<accountid>.r2.cloudflarestorage.com`).
4. Set the env vars from the table above in the Railway service (and
   locally if you intend to `publish` from your machine).

### Publish the owned store to R2

```
cd packages/fpl-grounded-assistant
python fpl_grounded_assistant/owned_store_sync.py publish
```

Run this after each local capture+merge. `publish` may raise on a hard
error (so a failed upload is loud for the operator) — unlike the startup
sync, which is fail-soft.

### Enable sync on the deployed service

Set `OWNED_STORE_SYNC_ENABLED=1` (plus the R2 env vars) on the Railway
service and deploy/restart.

## Refresh runbook (recurring)

End-to-end loop for refreshing the deployed owned-store snapshot. Run
this whenever you want the deployed fallback updated (e.g., weekly
during the season, or when FPL data has materially changed).

All commands assume PowerShell from the repo root (`C:\Users\thera\fpl-platform`).

### 1. Capture a fresh baseline (~10 min)

Pulls bootstrap + all fixtures + every player's element-summary from the
live FPL API. Writes a new timestamped dir under
`packages/fpl-historical/data/historical/seasons/2025-2026/raw/`.

```powershell
.\packages\fpl-historical\capture.ps1 capture --season 2025-2026
```

Look for `status=complete` and `failures=0` at the end. If status is
`complete_with_gaps` or `failed`, stop — the merge needs a `complete`
baseline.

### 2. (Optional) Capture incremental gameweeks

Cheap per-GW snapshots (~3 API calls each). `--auto` only writes for
finished+data_checked GWs that don't already have a snapshot — safe to
re-run; no-op when nothing new is finished.

```powershell
.\packages\fpl-historical\capture.ps1 capture-gw --auto
```

Skip this step during the off-season — there are no new finished GWs to
capture and it will no-op anyway.

### 3. Merge baseline + incrementals into parquet (seconds)

Fuses the latest baseline + all incrementals into
`parquet_merged/{players,teams,events,fixtures,player_gw_stats}.parquet`
and updates the `_owned_latest.json` pointer.

```powershell
.\packages\fpl-historical\capture.ps1 merge --season 2025-2026
```

Look for the `rows=` line — should be ~29k+ rows for a full season.

### 4. Publish to R2 (seconds)

Uploads the pointer + 5 parquet files to the configured R2 bucket. The
four `OWNED_STORE_R2_*` env vars must be set in the current PowerShell
session — they don't persist across windows.

If you opened a new PowerShell window, re-set them (substituting your
real values; **never commit secrets to the repo**):

```powershell
$env:OWNED_STORE_R2_ENDPOINT          = "https://<your-account-id>.r2.cloudflarestorage.com"
$env:OWNED_STORE_R2_BUCKET            = "fpl-owned"
$env:OWNED_STORE_R2_ACCESS_KEY_ID     = "<32-char access key id>"
$env:OWNED_STORE_R2_SECRET_ACCESS_KEY = "<64-char secret access key>"
```

Sanity-check (prints lengths, not values):

```powershell
echo "endpoint=$env:OWNED_STORE_R2_ENDPOINT bucket=$env:OWNED_STORE_R2_BUCKET akid_len=$($env:OWNED_STORE_R2_ACCESS_KEY_ID.Length) secret_len=$($env:OWNED_STORE_R2_SECRET_ACCESS_KEY.Length)"
```

Then publish:

```powershell
cd packages\fpl-grounded-assistant
python fpl_grounded_assistant\owned_store_sync.py publish
```

Expected: `SyncResult(ok=True, files_synced=6, merged_at=..., staleness_hours=<small>, error=None)`.

### 5. Redeploy / restart Railway

Railway needs to re-run the container's startup so the sync re-pulls the
new files. Either:

- **Redeploy**: Railway → `fpl-grounded-assistant` service → **Deployments**
  tab → **⋮** on latest → **Redeploy**.
- **Restart**: same place, **Restart** option (faster — no rebuild).

Wait until the deployment status is **Active** (green).

### 6. Verify deployed `/healthz`

```powershell
$URL = "https://fpl-backend-production-4151.up.railway.app/healthz"
Invoke-RestMethod $URL | ConvertTo-Json -Depth 5
```

Look for the `owned_store_sync` block — `ok: true`, `merged_at` matches
what you just published, `staleness_hours` < 1.

## Verifying the deployed path

1. Set the env vars (enabled flag + endpoint + bucket + access key/secret,
   optional prefix) on the service.
2. Deploy / restart.
3. Hit `GET /healthz` and confirm:
   - `owned_store_sync.ok == true`
   - `owned_store_sync.merged_at` is a **recent** timestamp
   - `owned_store_sync.staleness_hours` is small
4. (Optional) Exec into the container and run the smoke script:
   ```
   cd packages/fpl-grounded-assistant
   python scripts/smoke_owned_store_fallback.py
   ```
   With R2 env present and sync enabled, the smoke script runs a leading
   `(0) R2 owned-store sync` step and prints its `SyncResult`; otherwise it
   prints `[SKIP] (0) R2 owned-store sync` and exercises the local parquet
   fallback steps only.

## Rollback / removal

Sync is operator-only and default-off, so disabling it is safe and instant.

- **Disable** (revert to live-only + inert fallback): unset
  `OWNED_STORE_SYNC_ENABLED` (or set it to `0`/`false`) and restart. The
  server stops contacting R2; any previously synced local files remain but
  the fallback only serves them if it was already wired to.
- **Remove entirely**: delete `owned_store_sync.py`, the lifespan sync block
  and the `owned_store_sync` `/healthz` key in `fpl_server.py`, the `boto3`
  line in `requirements.txt`, and this doc. No data migration is needed —
  the R2 bucket can be deleted independently.

## Staleness / drift warning

Because refresh is **manual**, stale owned data can **silently back a
fallback during a live-API outage**. If the server falls back to an owned
snapshot that is days old, consumers may receive outdated data without any
hard failure. Operators MUST:

- Publish on a regular cadence (treat it like a data SLA, not a one-off).
- Watch `owned_store_sync.staleness_hours` and
  `owned_store_fallback.staleness_hours` on `/healthz`.
- Restart the service after each publish so the startup sync re-pulls.

# fpl-historical

Owned historical FPL data capture. Fetches `bootstrap-static`, all-season fixtures, and per-player element summaries from the official FPL API; persists them as gzipped JSON snapshots under a local root and projects them into Parquet tables for downstream analytics. Storage layout, manifest semantics, and CLI behavior are fixed in [CONTRACT.md](CONTRACT.md).

## Subcommands

| Subcommand | Purpose | Speed |
|---|---|---|
| `capture` | Full-season baseline: bootstrap + all-fixtures + N element-summaries | ~11 min |
| `capture-gw` | Per-gameweek anchor: bootstrap + all-fixtures + event-live (3 calls) | ~5 s |
| `merge` | Fuse baseline + complete incrementals into `parquet_merged/` (CONTRACT §10) | ~1 s |
| `import-vaastav` | One-shot seed import of prior seasons from the vaastav community dataset (H6) | varies |

## Running the capture

This package imports `fpl_api_client` as a sibling. Since neither package is pip-installed, you must put both on `PYTHONPATH` before invoking the CLI. The wrapper scripts handle this automatically.

**PowerShell (Windows):**

```powershell
# Full season baseline
packages\fpl-historical\capture.ps1 capture --season 2025-2026
packages\fpl-historical\capture.ps1 capture --skip-if-fresh 24

# Per-gameweek anchor (H2a)
packages\fpl-historical\capture.ps1 capture-gw --current          # pull the live GW
packages\fpl-historical\capture.ps1 capture-gw --current          # second call: skips if data_checked
packages\fpl-historical\capture.ps1 capture-gw --gw 36            # explicit GW number
packages\fpl-historical\capture.ps1 capture-gw --gw 36 --force    # override skip rule
packages\fpl-historical\capture.ps1 capture-gw --auto             # all finished+data_checked GWs
```

**Bash (Linux/macOS/WSL):**

```bash
# from repo root
bash packages/fpl-historical/capture.sh capture --season 2025-2026
bash packages/fpl-historical/capture.sh capture --skip-if-fresh 6

bash packages/fpl-historical/capture.sh capture-gw --current
bash packages/fpl-historical/capture.sh capture-gw --auto
```

**Manual invocation** (sets PYTHONPATH by hand):

```bash
PYTHONPATH="packages/fpl-historical:packages/fpl-api-client" python -m fpl_historical.cli capture-gw --current
```

(Use `;` instead of `:` on Windows.)

## `capture-gw` — incremental gameweek puller (CONTRACT §9)

Writes three gzipped JSON files and a v2 `_manifest.json` under:

```
data/historical/seasons/{season}/incremental/gw{NN}/{captured_at_utc}/
    bootstrap-static.json.gz
    fixtures.json.gz
    event-live.json.gz
    _manifest.json   ← schema_version=2, kind="incremental"
```

### GW selection modes (mutually exclusive)

| Flag | Behaviour |
|---|---|
| `--gw N` | Single explicit GW; fails immediately if N is not in `bootstrap.events[]` |
| `--current` | Pulls `is_current==True`; fallback to most recent `finished` event |
| `--auto` | Iterates all `finished==True AND data_checked==True` events; skip rule applies |
| `--force` | Overrides skip rule; always writes a new snapshot |

### Idempotency skip rule (CONTRACT §9.3)

The puller exits 0 without writing when **all three** conditions hold:
1. A `complete` snapshot already exists under `incremental/gw{NN}/`.
2. That snapshot's `gw_state.data_checked` is `True`.
3. The live bootstrap event (resolved by `event["id"]` lookup, never by array index) also reports `data_checked == True`.

Once a GW is officially `data_checked`, one anchor snapshot is sufficient. Before `data_checked`, every run writes a new snapshot (cheap; captures provisional in-flight scores).

### Running on a schedule

**Windows Task Scheduler** — create a basic task that runs daily or after each GW deadline:

```powershell
# Action: Program/script
powershell.exe
# Arguments
-NonInteractive -File "C:\path\to\repo\packages\fpl-historical\capture.ps1" capture-gw --auto
```

**cron (Linux/macOS)** — add to crontab:

```cron
# Run at 09:00 UTC every day (catches overnight data_checked flips)
0 9 * * * cd /path/to/repo && bash packages/fpl-historical/capture.sh capture-gw --auto >> /var/log/fpl-capture.log 2>&1
```

## Exit codes

### `capture` (CONTRACT §4)

| Code | Meaning |
|---|---|
| 0 | `complete` — parquet promoted, `_latest.json` updated |
| 0 | `complete_with_gaps` **with** `--promote-with-gaps` |
| 1 | `failed` — bootstrap/fixtures non-200, or element-summary failures > `--allow-missing-summaries` |
| 2 | `complete_with_gaps` **without** `--promote-with-gaps` (raw snapshot kept; parquet not promoted) |

### `capture-gw` (CONTRACT §9.4)

| Code | Meaning |
|---|---|
| 0 | `complete` or skip (skip rule fired — existing snapshot is final) |
| 1 | `failed` — any endpoint failed, or `--gw N` not in `bootstrap.events[]` |

## `merge` — owned merge projection (CONTRACT §10)

Fuses the H1 baseline parquet build (`parquet/`) with all H2a complete per-GW
incremental snapshots into a new owned output at `parquet_merged/`, plus a
machine-readable pointer at `_owned_latest.json`.  The baseline `parquet/` and
`_latest.json` are **never mutated**.

**Invoke via the wrapper script:**

```powershell
packages\fpl-historical\capture.ps1 merge --season 2025-2026
```

**Dedup rule (one-liner):** most-recent `captured_at` wins; ties go to incremental.

Full semantics — including which GW snapshots qualify, null fields for
incremental-only rows, and atomicity guarantees — are in [CONTRACT.md §10](CONTRACT.md).

**Output layout (additive):**

```
data/historical/seasons/{season}/
├── parquet/               ← baseline (read-only, untouched by merge)
├── _latest.json           ← baseline pointer (read-only, untouched by merge)
├── parquet_merged/        ← NEW: merged output (5 parquet files)
└── _owned_latest.json     ← NEW: merge pointer with row_counts and provenance
```

## `import-vaastav` — multi-season seed import (H6)

One-shot, operator-driven import of prior FPL seasons from the
[vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League)
community dataset (the live API only serves the current season). Transforms
vaastav's CSVs into our parquet schema and writes each season into
`seasons/{season}/parquet_merged/`. Not automated, not in CI, not a runtime
dependency.

The full operator runbook — cloning vaastav at the pinned SHA, running the
importer, and publishing each season to R2 — lives in
[`packages/fpl-grounded-assistant/docs/owned_store_sync.md`](../fpl-grounded-assistant/docs/owned_store_sync.md)
under **Multi-season seed import (H6)**.

## Convention note

`get_all_fixtures()` and `get_event_live()` were added to `fpl-api-client` as the precedent for narrow client extensions — future FPL endpoint additions should add both a URL constant and a thin wrapper to `fpl_api_client/fpl_client.py` rather than calling endpoints directly from consumer packages.

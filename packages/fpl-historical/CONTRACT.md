# fpl-historical — frozen contract (Track A H1 slice)

This file is the binding contract that Agents A, B, and C all consume.
Source: `C:\Users\thera\.claude\plans\based-on-claude-worktrees-agent-a12372ef-eventual-moth.md`.
Recon-verified deltas from the plan are flagged inline as **[recon]**.

---

## 1. Repo facts (verified before contract freeze)

- **Canonical FPL client module** [recon]:
  `packages/fpl-api-client/fpl_api_client/fpl_client.py` (importable as `fpl_api_client.fpl_client`).
  The `packages/fpl-api-client/python/fpl_client.py` path referenced in the plan is a parallel/legacy copy — **all edits go to `fpl_api_client/fpl_client.py`**.
- **Existing client surface** (do NOT re-implement):
  - `fetch_json(url, timeout=30) -> Any` — HTTP with 3-retry backoff.
  - `BOOTSTRAP_URL`, `FIXTURES_URL` (per-gameweek, `?event={gameweek}`), `ELEMENT_SUMMARY_URL` (`{element_id}`).
  - `get_bootstrap()`, `get_element_summary(element_id)`, `get_fixtures(gameweek)`.
- **Season key** [recon]: exact string `"2025-2026"` in `packages/fpl-data-core/season_registry.yaml` (line 36, under top-level `seasons:` list, entry shape `- season: "YYYY-YYYY"`).
- **Pytest discovery** [recon]: per-package `pytest.ini` with `[pytest]\ntestpaths = tests\npythonpath = .` is auto-discovered when running from repo root. No root config edit needed.
- **pyarrow** [recon]: not currently a dep anywhere. Add to `packages/fpl-historical/requirements.txt` (the repo convention — `packages/fpl-grounded-assistant/requirements.txt` is the only existing example; **no `pyproject.toml` is used in any package**).
- **Client test pattern** [recon]: `packages/fpl-api-client/tests/test_fpl_client.py` uses `unittest.mock.patch("fpl_api_client.fpl_client.requests.get", ...)` with a `MagicMock` response.

---

## 2. Manifest JSON shape (`_manifest.json`)

Frozen. Agent B writes it; Agent C reads `status` to gate promotion.

```json
{
  "schema_version": 1,
  "season": "2025-2026",
  "status": "complete",
  "captured_at_utc": "2026-05-25T14:22:03Z",
  "git_sha": "725d4b4",
  "fpl_endpoints": {
    "bootstrap-static": {"url": "...", "status": 200, "bytes": 412034, "sha256": "..."},
    "fixtures":         {"url": "...", "status": 200, "bytes":  84221, "sha256": "..."},
    "element-summary":  {"count": 712, "failures": [], "sha256_aggregate": "..."}
  },
  "current_event_id": 38,
  "elapsed_seconds": 187.4
}
```

Rules:
- `status` is one of `"complete" | "complete_with_gaps" | "failed"`.
- `fpl_endpoints.element-summary.failures` is a list of `{"element_id": int, "status": int|null, "error": str}` for any non-200 or exception during per-player fetch.
- `sha256` fields are hex strings of the raw response bytes (gzipped or not — hash the uncompressed body bytes so identical FPL responses hash identically across runs).
- `git_sha` is `"unknown"` if not in a git repo.

### Status determination (canonical algorithm)

```
if bootstrap.status != 200 or fixtures.status != 200:
    status = "failed"
elif len(element_summary.failures) == 0:
    status = "complete"
elif len(element_summary.failures) <= allow_missing_summaries:
    status = "complete_with_gaps"
else:
    status = "failed"
```

---

## 3. Directory layout (frozen)

Root (gitignored, configurable via `FPL_HISTORICAL_ROOT`, default `packages/fpl-historical/data/`):

```
data/historical/seasons/2025-2026/
├── raw/
│   └── {captured_at_utc}/                        ← ISO8601, filesystem-safe: "2026-05-25T14-22-03Z"
│       ├── bootstrap-static.json.gz
│       ├── fixtures.json.gz                      ← all fixtures (no event filter)
│       ├── element-summary/
│       │   └── {element_id}.json.gz
│       └── _manifest.json                        ← UTF-8, indent=2
├── parquet/
│   ├── players.parquet
│   ├── teams.parquet
│   ├── events.parquet
│   ├── fixtures.parquet
│   └── player_gw_stats.parquet
└── _latest.json                                  ← {"raw_dir": "2026-05-25T14-22-03Z", "parquet_built_at": "..."}
```

Rules:
- `raw/{captured_at}/` is **immutable**; never mutated by reruns.
- `captured_at_utc` directory name uses `:` → `-` substitution to be Windows-safe.
- Parquet files are overwritten via `.tmp` + `os.replace` (atomic on POSIX and Windows).
- `_latest.json` is updated **only** after a successful parquet build.

---

## 4. CLI behavior table (frozen)

Command: `python -m fpl_historical.cli capture [flags]`

| Flag | Default | Effect |
|---|---|---|
| `--season SEASON` | `2025-2026` | Season key (must exist in `season_registry.yaml`). |
| `--skip-parquet` | off | Capture raw only; do not invoke projection. Exit code follows status (see below). |
| `--skip-if-fresh N` | off | If newest **`complete`** snapshot is < N hours old, exit 0 without writing. `complete_with_gaps` does NOT count as fresh. |
| `--allow-missing-summaries N` | `0` | Tolerance for element-summary failures before downgrading status from `complete_with_gaps` → `failed`. |
| `--promote-with-gaps` | off | Allow parquet promotion when `status == "complete_with_gaps"`. Has no effect on `failed`. |

| `status` | `--promote-with-gaps` | Parquet promoted? | `_latest.json` updated? | CLI exit code |
|---|---|---|---|---|
| `complete` | (n/a) | yes | yes | `0` |
| `complete_with_gaps` | off | no | no | `2` |
| `complete_with_gaps` | on | yes | yes | `0` |
| `failed` | (any) | no | no | `1` |

`--skip-parquet` overrides promotion: parquet is not built, `_latest.json` is not updated, but exit code still follows the status table (treat as if `promote_with_gaps` were off).

---

## 5. Parquet schemas (frozen column lists)

All tables include a `captured_at` column (UTC ISO string, same value across the run, sourced from the manifest).

| Table | Source | Required columns (besides `captured_at`) | PK |
|---|---|---|---|
| `players` | `bootstrap.elements[]` | `player_id` (renamed from `id`), `web_name`, `first_name`, `second_name`, `team` (renamed `team_id`), `element_type`, `now_cost`, `selected_by_percent`, `status`, `total_points`, `form` | `player_id` |
| `teams` | `bootstrap.teams[]` | `team_id` (renamed from `id`), `name`, `short_name`, `strength`, `strength_overall_home`, `strength_overall_away` | `team_id` |
| `events` | `bootstrap.events[]` | `event_id` (renamed from `id`), `deadline_time`, `is_current`, `is_next`, `finished`, `data_checked`, `average_entry_score` | `event_id` |
| `fixtures` | `fixtures.json` (top-level list) | `fixture_id` (renamed from `id`), `event` (renamed `event_id`), `team_h`, `team_a`, `team_h_score`, `team_a_score`, `team_h_difficulty`, `team_a_difficulty`, `finished`, `kickoff_time` | `fixture_id` |
| `player_gw_stats` | for each `element-summary/{id}.json`, iterate `history[]`; inject `player_id` from the filename | `player_id`, `event` (renamed `event_id`), `total_points`, `minutes`, `goals_scored`, `assists`, `clean_sheets`, `goals_conceded`, `bonus`, `bps`, `expected_goals`, `expected_assists`, `expected_goal_involvements`, `value`, `was_home`, `opponent_team` | `(player_id, event_id)` |

Passthrough policy: keep every other top-level field from the source as-is; do not drop unknown columns. The PK and renamed columns above are the only hard guarantees.

**`player_gw_stats` event-field fallback:** the FPL `element-summary` history rows may carry the gameweek number under either `event` or `round` depending on the API variant. Projection logic renames `event` → `event_id` when present; otherwise it falls back to renaming `round` → `event_id`. Either is contract-compliant; the resulting parquet always exposes `event_id`.

---

## 6. Module boundaries (who edits what)

| Agent | Allowed to edit |
|---|---|
| **A** | `packages/fpl-api-client/fpl_api_client/fpl_client.py`; `packages/fpl-api-client/tests/test_fpl_client.py` (additions only). Nothing else. |
| **B** | `packages/fpl-historical/{pytest.ini, requirements.txt, README.md, .gitignore}`; `packages/fpl-historical/fpl_historical/{__init__,paths,manifest,capture,cli}.py`; `packages/fpl-historical/tests/{conftest,test_paths,test_manifest,test_capture}.py`. Root `.gitignore` (one-line addition for `packages/fpl-historical/data/`). |
| **C** | `packages/fpl-historical/fpl_historical/projections.py`; `packages/fpl-historical/tests/{test_projections,test_rerun_idempotency,test_season_key_contract}.py`. May import `manifest.py` and `paths.py` from B; must not modify them. |

---

## 7. Public API B must expose (so C can build against it)

```python
# fpl_historical/paths.py
CURRENT_SEASON: str = "2025-2026"
def historical_root() -> Path: ...
def season_dir(season: str) -> Path: ...
def new_raw_dir(season: str) -> Path: ...        # creates raw/{utcnow_iso_safe}/
def parquet_dir(season: str) -> Path: ...
def latest_pointer_path(season: str) -> Path: ...
def list_raw_dirs(season: str) -> list[Path]: ... # sorted oldest→newest

# fpl_historical/manifest.py
@dataclass
class Manifest:
    schema_version: int
    season: str
    status: Literal["complete", "complete_with_gaps", "failed"]
    captured_at_utc: str
    git_sha: str
    fpl_endpoints: dict
    current_event_id: int | None
    elapsed_seconds: float

def write_manifest(raw_dir: Path, m: Manifest) -> None: ...
def read_manifest(raw_dir: Path) -> Manifest: ...
def sha256_bytes(data: bytes) -> str: ...
```

C consumes `read_manifest`, `list_raw_dirs`, `parquet_dir`, `latest_pointer_path`, and `Manifest.status`.

---

## 8. Done.

Agents A, B, C: read this file, implement your slice, run your tests, and report back. Disputes about contract details escalate to the lead before unilateral changes.

---

## 9. Incremental Captures (H2a)

Per-gameweek anchor snapshots that run cheaply (3 API calls) after every deadline. Strictly additive over §1–§8: the H1 baseline tree (`raw/`, `parquet/`, `_latest.json`) is invisible to this path and vice versa.

### 9.1 Directory layout (additive, sibling to `raw/`)

```
data/historical/seasons/{season}/
├── raw/                                     ← H1 baseline (unchanged)
├── parquet/                                 ← H1 projection (unchanged)
├── _latest.json                             ← H1 pointer (unchanged — baseline only)
└── incremental/                             ← NEW (H2a)
    └── gw{NN}/                              ← gw01 .. gw38, zero-padded
        └── {captured_at_utc}/               ← same ISO8601 filesystem-safe convention as raw/
            ├── bootstrap-static.json.gz
            ├── fixtures.json.gz             ← all fixtures (no event filter)
            ├── event-live.json.gz           ← event/{gw}/live/ — the GW-anchor payload
            └── _manifest.json               ← schema_version=2, kind="incremental"
```

Rules:
- `gw{NN}` is zero-padded so lexicographic sort matches numeric sort (`gw01 < gw02 < ... < gw38`).
- `{captured_at_utc}/` uses the same `:` → `-` substitution as §3 for Windows safety.
- Incremental snapshot dirs are **immutable**; reruns either write a new timestamped sibling or skip per §9.3.

### 9.2 Manifest schema v2 (incremental only)

```json
{
  "schema_version": 2,
  "kind": "incremental",
  "season": "2025-2026",
  "gameweek": 36,
  "status": "complete",
  "captured_at_utc": "2026-05-25T18-22-03Z",
  "git_sha": "...",
  "fpl_endpoints": {
    "bootstrap-static": {"url": "...", "status": 200, "bytes": 412034, "sha256": "..."},
    "fixtures":         {"url": "...", "status": 200, "bytes":  84221, "sha256": "..."},
    "event-live":       {"url": "...", "status": 200, "bytes": 156782, "sha256": "..."}
  },
  "gw_state": {
    "finished": true,
    "data_checked": true,
    "is_current": false,
    "deadline_time": "2026-05-12T17:30:00Z"
  },
  "elapsed_seconds": 4.2
}
```

V1 manifest semantics from §2 remain unchanged on the wire — baseline writes still emit `schema_version=1` with no new fields. `manifest.py` extends the `Manifest` dataclass with optional `kind`, `gameweek`, and `gw_state` (defaulting to `None`); `read_manifest()` dispatches on `schema_version` and parses both v1 and v2 backward-compatibly. A v1 round-trip test is mandatory.

### 9.3 Idempotency skip rule (canonical)

> Skip iff a `complete` snapshot exists under `incremental/gw{NN}/` AND that snapshot's `gw_state.data_checked == true` AND the live bootstrap event whose `id == N` also reports `data_checked == true`.

The target event MUST be resolved by id lookup (`next(e for e in bootstrap["events"] if e["id"] == N)`), never by `events[N-1]` positional indexing. `bootstrap.events[]` is not guaranteed contiguous or ordered; positional indexing is a brittle contract.

This is the only path that exits 0 without writing. The rule is independent of the H1 baseline `--skip-if-fresh` rule (§4) — the two do not interact.

### 9.4 Status semantics (two-state)

| Outcome | Meaning | Manifest written? | Exit code |
|---|---|---|---|
| `complete` | All three endpoints returned 200 with non-empty body. | yes | `0` |
| `failed`   | Any endpoint failed after retries, OR `--gw N` references an event not in `bootstrap.events[]`, OR any response body is empty. | yes (status=`failed`) | `1` |
| (skip)     | §9.3 skip rule fired. | no | `0` |

There is **no `complete_with_gaps`** for incremental — there are no per-player loops to partially fail. Deliberately small state machine, orthogonal to §2.

### 9.5 CLI surface

New subcommand: `python -m fpl_historical.cli capture-gw [flags]`. The existing `capture` subcommand and all v1 flags from §4 are unchanged.

| Flag | Default | Effect |
|---|---|---|
| `--gw N` | (none) | Explicit single gameweek; fails fast (`failed`, exit 1) if `N` is not in `bootstrap.events[]`. |
| `--current` | (none) | Pulls the gameweek where `events[*].is_current == true`; falls back to the most recent `finished` event if none is current. |
| `--auto` | (none) | Iterates every event where `finished == true` and `data_checked == true`; captures unless §9.3 skip rule fires. Bootstrap is fetched once and shared across the loop. |
| `--force` | off | Overrides the §9.3 skip rule. Always writes a new snapshot. |
| `--season SEASON` | `2025-2026` | Season key (must exist in `season_registry.yaml`). |

`--gw`, `--current`, and `--auto` are mutually exclusive; exactly one must be given.

Wrapper scripts (`capture.ps1`, `capture.sh`) will be updated to pass the subcommand through from args rather than hard-coding `capture`. Invocation becomes `capture.ps1 capture --season ...` and `capture.ps1 capture-gw --current`.

### 9.6 Hard boundaries

Incremental captures **never**:
- write under or mutate `raw/`,
- invoke `projections.py`,
- write or update files under `parquet/`,
- update `_latest.json`.

Parquet integration of incremental snapshots (dedup semantics on `(player_id, event_id, captured_at)`, versioned `_latest.json`) is deferred to H2b.

---

## 10. Owned Merge Projection (H2b)

Overlay layer that fuses the H1 baseline parquet build with the H2a per-GW incremental snapshots into a new, owned parquet output. Strictly additive over §1–§9: the H1 baseline tree (`raw/`, `parquet/`, `_latest.json`) and the H2a incremental tree are **read-only inputs** to the merge. `projections.py`'s baseline behavior is unchanged. `fpl_server.py` is not touched. H4 (read-path fallback) will consume the artifacts defined here.

### 10.1 Output layout (additive, never overwrites baseline)

```
data/historical/seasons/{season}/
├── raw/                                     ← H1 baseline (read-only input)
├── parquet/                                 ← H1 projection (read-only input)
├── _latest.json                             ← H1 pointer (read-only input)
├── incremental/                             ← H2a snapshots (read-only input)
├── parquet_merged/                          ← NEW (H2b)
│   ├── players.parquet
│   ├── teams.parquet
│   ├── events.parquet
│   ├── fixtures.parquet
│   └── player_gw_stats.parquet
└── _owned_latest.json                       ← NEW (H2b) pointer for the merged build
```

Rules:
- `parquet_merged/` carries the same 5 tables as §3's `parquet/`, with the additional columns on `player_gw_stats` defined in §10.4.
- Baseline `parquet/` and `_latest.json` are **never mutated** by the merge.
- Incremental `incremental/gw{NN}/...` snapshots are **never mutated** by the merge.

### 10.2 Status gating

Inputs to the merge are selected as follows:

- **Baseline contribution**: the raw dir referenced by `_latest.json` (which is itself only updated by `complete` baseline runs per §3 — `complete_with_gaps` only contributes if it was promoted via `--promote-with-gaps`). If `_latest.json` is missing, the baseline contribution is empty.
- **Incremental contribution**: for each gameweek `N` in `1..38`, the most recent snapshot under `incremental/gw{NN}/` whose manifest has `status == "complete"`. Snapshots with `status == "failed"` are silently ignored. Older `complete` snapshots within the same GW are also ignored — only the most recent timestamped sibling contributes.
- If both the baseline and all incrementals are missing, the merge writes empty tables (zero rows, schema preserved) but `_owned_latest.json` is still updated — the empty state is explicit and discoverable.

`list_incremental_dirs(season, gw)` (sorted oldest→newest) is the canonical iterator; the merge reads the manifest of each candidate and keeps the newest `complete` one.

### 10.3 Per-table merge semantics

- `players`, `teams`, `events`, `fixtures`: sourced from the **latest `captured_at`** snapshot across `{baseline} ∪ {chosen incrementals}`. These are season-state tables — there is no row-level merge, only "newest wins as a whole table." Provenance is preserved by the existing `captured_at` column on every row (§5), which tells the operator which snapshot contributed.
- `player_gw_stats`: the merge target. Dedup key is the composite `(player_id, event_id)`. See §10.4.

### 10.4 `player_gw_stats` dedup rule (canonical)

For each `(player_id, event_id)` pair across baseline rows (from `element-summary[*].history[]`) and incremental rows (from each chosen `complete` incremental's `event-live.elements[*].stats`, with `player_id` taken from `elements[*].id` and `event_id` from the snapshot's `gameweek`), exactly one row survives:

> **Winner is the row with the most recent `captured_at` value.** ISO-8601 lexicographic comparison is well-defined for the `%Y-%m-%dT%H-%M-%SZ` format both layers use (§3 and §9.1). Ties (identical `captured_at` to the second) are broken by preferring the **incremental** row — incremental captures are GW-targeted and run after `data_checked`, so they are the more authoritative source for that single GW.

Two new columns are added to `player_gw_stats` (and only this table) for inspectability:

- `source: str` — one of `"baseline"` or `"incremental"`.
- `source_captured_at: str` — the `captured_at_utc` of the snapshot whose row won. (This is identical to the existing `captured_at` column on the winning row, but is named explicitly so consumers don't have to guess.)

Other columns are passthrough from the winning source. Where field names differ between baseline and incremental — e.g. `event-live.stats` may lack `value`, `was_home`, `opponent_team` — those columns are populated only when the baseline row wins. When the incremental row wins and the field is absent from `event-live.stats`, the value is `null` and that is **contractual**: H2b does not invent values, does not back-fill from baseline, and does not cross-merge fields across sources within a single `(player_id, event_id)` row.

### 10.5 Idempotency

Re-running the merge with no new snapshots produces **byte-identical parquet files** and an updated `merged_at` timestamp in `_owned_latest.json`. Re-running after a new incremental snapshot lands updates only the rows whose `(player_id, event_id)` is now backed by a fresher source — all other rows are byte-identical to the previous merge.

### 10.6 `_owned_latest.json` schema (v1)

```json
{
  "schema_version": 1,
  "season": "2025-2026",
  "merged_at": "2026-05-26T08-15-00Z",
  "baseline": {
    "raw_dir": "raw/2026-05-25T14-22-03Z",
    "captured_at_utc": "2026-05-25T14-22-03Z",
    "manifest_status": "complete"
  },
  "incrementals": [
    {
      "gameweek": 1,
      "raw_dir": "incremental/gw01/2026-05-25T18-22-03Z",
      "captured_at_utc": "2026-05-25T18-22-03Z"
    }
  ],
  "row_counts": {
    "players": 712,
    "teams": 20,
    "events": 38,
    "fixtures": 380,
    "player_gw_stats": 27056
  }
}
```

Rules:
- `baseline` is `null` if no baseline contributed (i.e. `_latest.json` was missing at merge time).
- `incrementals` is a list (possibly empty), sorted by `gameweek` ascending.
- All `raw_dir` paths inside `_owned_latest.json` are **relative to** `data/historical/seasons/{season}/` so the pointer is portable across hosts.
- `merged_at` uses the same `%Y-%m-%dT%H-%M-%SZ` filesystem-safe ISO8601 convention as §3 and §9.1.
- `row_counts` reflects the rows actually written to `parquet_merged/`; consumers may use it as a cheap sanity check without reading the parquet files.

### 10.7 Atomicity

Same pattern as §3:
- Each parquet file in `parquet_merged/` is written to a `.parquet.tmp` sibling and promoted via `os.replace` (atomic on POSIX and Windows).
- `_owned_latest.json` is written to `_owned_latest.json.tmp` and promoted via `os.replace`.
- `_owned_latest.json` is updated **last**, after all 5 parquet files are in place — so a consumer reading the pointer never observes a partially-written merge.

### 10.8 Boundaries

H2b does **not**:
- modify `projections.py`'s baseline behavior,
- write to or mutate `parquet/`,
- write to or mutate `_latest.json`,
- write to or mutate `raw/` or `incremental/`,
- touch `fpl_server.py`,
- add cron or scheduling (invocation cadence is an operational concern, deferred).

H4 (read-path fallback) will consume `_owned_latest.json`; its consumption contract is defined when H4 lands, not here.

## 11. Owned-Store Fallback Reader (H4a)

This section freezes the read contract between the owned-store layer (§10) and its first consumer: the `fpl-grounded-assistant` backend. It is the counterpart to §10 from the consumer side.

### 11.1 Scope

H4a wires owned-store fallback for the **bootstrap fetch only**, at exactly one seam: `_fetch_bootstrap_with_retry()` in `packages/fpl-grounded-assistant/fpl_server.py` (line ~419). Per-tool fallback for `player_form.py`, `get_fixtures_for_gw.py`, `element-summary`, and other live-API call sites is explicitly deferred to **H4b**. The live FPL API remains the primary data source; the owned store is engaged **only** after all existing live-retry attempts in `_fetch_bootstrap_with_retry()` have failed.

H4a is narrow and additive: it does not add new product capabilities, new HTTP routes, auth, or per-tool fallbacks.

### 11.2 New loader module

A new module `packages/fpl-grounded-assistant/fpl_grounded_assistant/owned_store_fallback.py` exposes a single public function and supporting types:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class OwnedStoreProvenance:
    pointer_path: str
    merged_at: str
    baseline_captured_at: str | None
    incremental_count: int
    staleness_hours: float
    row_counts: dict

class OwnedStoreUnavailable(Exception):
    """Raised when the owned store cannot satisfy a bootstrap read."""

def load_bootstrap_from_owned_store(
    season: str = CURRENT_SEASON,
) -> tuple[dict, OwnedStoreProvenance]:
    """Return (bootstrap_dict, provenance). Raises OwnedStoreUnavailable on any failure.

    bootstrap_dict matches the shape returned by fpl_api_client.get_bootstrap():
    keys 'elements', 'teams', 'events', 'element_types' at minimum.
    """
```

Behavior:

- Reads `data/historical/seasons/{season}/_owned_latest.json` first. If the pointer file is missing, raises `OwnedStoreUnavailable("no pointer")`.
- If `baseline` is `null` **and** `incrementals` is empty, raises `OwnedStoreUnavailable("empty store")`.
- Loads `players.parquet`, `teams.parquet`, and `events.parquet` from `parquet_merged/` and reconstructs the bootstrap shape via `df.to_dict(orient="records")` per table, mapping the renamed projection columns back to raw FPL field names so downstream code that expects the live API shape keeps working:
  - `players`: `player_id` → `id`
  - `teams`: `team_id` → `id`
  - `events`: `event_id` → `id`
- `element_types` is reconstructed from a **hardcoded** 4-element list (Goalkeeper, Defender, Midfielder, Forward with `id` 1–4 and the standard FPL `singular_name` / `plural_name` / `singular_name_short` fields). The owned store does not capture `element_types` per §10.2 (only the 5 merged tables exist). This is intentional: FPL's position taxonomy is static and has not changed in the lifetime of the game. The hardcode lives inside `owned_store_fallback.py` and is documented in this contract.
- Returns an `OwnedStoreProvenance` whose `staleness_hours` is computed as `(now_utc - merged_at)` in fractional hours, using the `%Y-%m-%dT%H-%M-%SZ` parse from §10.6.

### 11.3 Integration seam

`_fetch_bootstrap_with_retry()` in `fpl_server.py` is extended as follows:

1. The existing live-retry loop is preserved unchanged. Owned-store fallback is attempted **only after** all live retry attempts have exhausted.
2. After exhaustion, `load_bootstrap_from_owned_store()` is invoked **exactly once** (no retry — owned-store reads are local disk).
3. On success:
   - The returned bootstrap dict is used as if it came from the live API.
   - The `OwnedStoreProvenance` is recorded in a module-level slot `_LAST_BOOTSTRAP_PROVENANCE` in `fpl_server.py` for `/healthz` (and optionally `respond()`) to inspect.
   - A `WARNING` log line is emitted with at least: `season`, `merged_at`, `staleness_hours`, `incremental_count`. This is the operator-visible signal that fallback was engaged.
4. On `OwnedStoreUnavailable`, the current failure behavior is preserved: the existing 503 / startup-degraded path runs unchanged. The `OwnedStoreUnavailable` exception is **not** swallowed silently — it is logged at `ERROR` and the original live-fetch exception is re-raised (or surfaced via the existing 503 path).
5. When a **subsequent** live fetch succeeds (e.g., on a later call after the FPL API recovers), `_LAST_BOOTSTRAP_PROVENANCE` must be cleared to `None`. The slot must never lie about staleness — if the last successful bootstrap came from live, the slot is `None`.

### 11.4 Provenance surface

Two read-only surfaces expose fallback state:

1. **`/healthz`** (existing route at `fpl_server.py:954`) gains an additive JSON key `owned_store_fallback`:
   - `null` when the last bootstrap fetch was served from the live FPL API.
   - Otherwise an object: `{merged_at, baseline_captured_at, incremental_count, staleness_hours, row_counts}` mirroring the `OwnedStoreProvenance` dataclass minus `pointer_path`.
2. **`FinalResponse`** is **not** modified in H4a. Adding a new metadata field would ripple through 14+ existing metadata fields, intent serializers, and snapshot tests for no H4a-required reason. Fallback state remains observable via `/healthz` and the `WARNING` log. H4b may additively thread `data_source: Literal["live", "owned_store"]` into `FinalResponse` if downstream UX needs it.

### 11.5 Tolerated nulls

Per §10.4 (whole-row replacement on incremental merge), any row in `players.parquet` whose canonical key won a whole-row replacement from an incremental snapshot may carry `null` values for fields not present in that snapshot (e.g. `value`, `was_home`, `opponent_team`). The owned-store loader returns these as Python `None` in the reconstructed `bootstrap['elements'][i]` dicts; it does **not** synthesize, backfill, or coalesce values.

Consumers of `bootstrap['elements']` must tolerate `None` for any field not explicitly listed as required by the live FPL API contract. If a downstream call relies on a field that is `None` in fallback mode, that call may degrade — H4a does **not** synthesize values to mask the null. Degradation is preferable to silent fabrication.

### 11.6 Boundaries

H4a does **not**:

- modify `projections.py`, `merge.py`, `paths.py`, or any part of the §1–§10 owned-store write path,
- modify the baseline `parquet/` tree or `_latest.json`,
- modify per-tool data fetches (`player_form.py`, `get_fixtures_for_gw.py`, `element-summary`, etc.) — deferred to H4b,
- modify the `FinalResponse` schema, intent metadata, orchestrator tools, or the LLM router,
- add new HTTP routes (`/healthz` is extended in place, additively),
- add cron, scheduler, auth, infra, or deployment changes,
- change `pyproject.toml` for either package.

### 11.7 Cross-package import

`fpl-grounded-assistant` does not currently import `fpl_historical`. Wiring is done at **runtime via `sys.path` insertion**, mirroring the existing sibling-resolver pattern (`_SIB()`) already used in `fpl_server.py` to consume `fpl-api-client`. Two equivalent placements are acceptable; the implementer picks:

- extend `sys.path` once in `fpl_server.py` startup (alongside the existing `_SIB()` calls), or
- extend `sys.path` locally inside `owned_store_fallback.py` before its `from fpl_historical...` imports.

There are **no changes to `pyproject.toml`**, no new installed package boundaries, and no changes to the existing `fpl-api-client` consumption pattern. This is a path-based dev-time concern, identical to the current sibling-package wiring.

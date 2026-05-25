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

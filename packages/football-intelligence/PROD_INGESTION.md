# Production Sportmonks ingestion (B3): design

Status: **design approved by the brain (2026-10-22) with the conditions folded in below; nothing built.** Task B, step B3. B1 (#500, tier trust) and B2 (#501,
`licensed_starter` provenance) come before it.

## Constraints this design starts from

- **Plan:** Sportmonks Starter, Premier League only, €29/month, from the end of the trial
  (2026-10-25 03:09 UTC). Includes PL lineups, formations, `formation_field` grid, detailed positions,
  predicted lineups with the `lineup_confirmed` flag, sidelined (injuries and suspensions) and squads.
  No add-ons: the job must not depend on Match Facts, Pressure & xG, Predictions, Odds or Euro Club
  Tournaments includes (decision-draft, "Respuestas de Sportmonks").
- **Licence:** storing, deriving and showing to subscribers are allowed. Redistributing the raw feed
  is not (TRIAL_LICENSING_CHECKLIST Q3). Hence: derived data only, no raw payloads in git or behind
  an endpoint.
- **Rate limit:** 2,000 calls per entity per hour (Q14).
- **Trial data never reaches production.** Everything captured with the trial token stays
  `live_trial_local` and refused. The production store starts empty and is filled only by this job,
  under the paid token. The euro pre-load is trial data too (decision-draft says so explicitly).
- **Network only through `sportmonks-client`.** It stays the sole owner of URLs, auth, includes and
  pagination (its CONTRACT.md). The job composes client calls; it never builds a URL.
- **The repo is public, and so are its GitHub Actions logs.** The job logs aggregates only. See
  "Logging" below.
- **Secrets are Leo's config.** `SPORTMONKS_API_TOKEN` is read from the environment and never printed
  (the client already redacts it from errors, logs and snapshots).

## What it fetches

All requests go through existing `sportmonks-client` routes (CONTRACT.md "Family routes"). The
first two rows are already proven by the trial scripts.

| Data | Route (existing) | Include | Per pass |
|---|---|---|---|
| PL fixtures in the next 14 days, with **predicted / confirmed lineups**, formation, grid, detailed position, state | `fixtures/between/{start}/{end}`, `filters=fixtureLeagues:8` | `participants;lineups.detailedPosition;formations;state;metadata` (`metadata` type 572 = `lineup_confirmed`; `participants` gives home/away for the side rule) | 1 call (≤ 4 pages bound; a 14-day PL window is one page today) |
| PL fixtures of the **last 7 days**, final lineups | same route, past window | same include | 1 call |
| **Squads** (and players, for identity) | `squads/teams/{team_id}` | `player` | 20 calls |
| **Sidelined** (open absences per club) | `teams/{team_id}` | `sidelined` | 20 calls |
| **FA Cup / Carabao fixtures**, best effort | `team_fixtures`: `fixtures/between/{start}/{end}/{team_id}` | `participants;state` | 20 calls (one per PL club, covers every competition the plan returns) |

The 14-day window is the provider's cap on `fixtures/between` (a season-long window answers 422).

**Cups are best effort, by the provider's own answer** (Q10: coverage "varies by fixture and season",
no completeness guarantee, and it is not said they are in the Starter price). They go through the F1
module `public_calendar` (#495): a source converter maps the `team_fixtures` rows to `SourceMatch`, and
`convert_matches` produces one `CompetitionSnapshot` per competition (`FA`, `EFL`). The rows don't
prove the fixture list is final, so these snapshots are always **`partial`** (no `complete_as_of`
bound). The consequence `public_calendar` already encodes is that `calendar_complete` stays False and the
rotation notice is not issued from a partial calendar. That is the degrade-without-breaking behaviour the
decision asks for. `UCL/UEL/UECL` are NOT read here: they come from the public-source proposal
(2026-10-21-otras-competiciones-fuentes-publicas.md). If Starter returns them in `team_fixtures` anyway,
the job drops them, so nothing downstream depends on a competition the plan doesn't guarantee.

**Not fetched:** statistics, coaches, referees, substitutions (Q12 left them unanswered, so they are not
assumed), odds, predictions, xG.

## What it stores (derived only)

A new **licensed matchday store**, separate from the FI canonical v1/v2 builds:

- The canonical builds keep only completed fixtures with the provider's minutes. They can't hold a
  predicted lineup, and that's on purpose: M1/M2 rely on it.
- B4 needs exactly what they leave out: pre-match lineups, the confirmed flag, and sidelined.

The tables, all keyed by **FPL ids** (element id, team code, FPL fixture id). Sportmonks ids are kept
only in the crosswalk table, which is stored data the licence allows, never in git:

| Table | Row | Fields |
|---|---|---|
| `lineup_snapshots` | one per (fixture, team, observed_at) | formation, `confirmed` (type 572), state, n_starters, n_bench |
| `lineup_slots` | one per (snapshot, player) | FPL element id, starter/bench, detailed position, grid row/column, **side** (the validated rule: home column 1 = team's right, away mirrored) |
| `sidelined` | one per (player, absence) | FPL element id, category (injury / suspended), start, end, games_missed, completed, observed_at |
| `squad_membership` | one per (team, player, observed_at) | FPL element id, jersey number |
| `crosswalk` | one per provider player | Sportmonks player id ↔ FPL element id, method (the registry's `match_player` tier), observed_at; unmatched players are counted, never guessed |
| `cup_snapshots` | `public_calendar.CompetitionSnapshot` serialized | as F1 defines |

**Identity:** the crosswalk is rebuilt from the licensed squad reads with the same registry matcher
the trial measured (`football_identity_registry.match_player`, no new tier, no fuzzy matching). The trial's
rate was 413/430 = 96.0 % for FPL elements with minutes. The trial's crosswalk is NOT reused (it's
trial data). Unmatched players are dropped from every table and counted in the build report, so a
missing player is visible, not silently absent.

**Format and publication:** parquet plus a manifest stamped `assumption_status: licensed_starter`, with
normalizer `licensed_adapter: licensed-starter-v1` and source kind `licensed-sportmonks-starter` (B2). It is
published to R2 by the shared `distribution` path as its own **build family** (`LICENSED_V1` in
`ingestion/licensed/store.py`, through the family seam of `distribution/family.py`). It reuses the immutable
build, pointer, race guard, bounded reads and trial refusal, but has its own prefix `football-licensed/`, its own
pointer name and its own governed files; the canonical family can't reach them and vice versa. Railway syncs it
the same way. Appending snapshots, not
overwriting them, is what lets B4 answer "what changed between the predicted and the confirmed XI"
and keeps a history the provider doesn't keep.

**R2 location:** the same **private** bucket as the owned store, under its own prefix
`football-licensed/`, read and written only with S3 credentials (`S3ArtifactStore`). The workflow
maps the existing `OWNED_STORE_R2_*` secrets onto the `FPL_FOOTBALL_REMOTE_*` variables that
`distribution.RemoteStoreConfig` reads. The job never creates a public URL, presigned link or
public-bucket binding. Licence rule: no one outside us may be able to reconstruct the feed.
Whether the bucket has public access (r2.dev subdomain or custom domain) **disabled** is Cloudflare
config and can't be checked from code: Leo confirms it before the first `--publish`.

**No raw payloads anywhere:** the job installs no `RawResponseSnapshot` hook, writes no response JSON
to disk, and the served endpoints read only the derived tables. Tests use **synthetic** recorded
fixtures (shapes from CONTRACT.md, hand-made ids and names); no captured payload from the trial or
from production is ever committed.

## Cadence

| Run | When (UTC) | Calls | Purpose |
|---|---|---|---|
| **Daily** | 05:00 every day | ~62 (20 squads + 20 sidelined + 20 team_fixtures + 2 lineup windows) | squads, crosswalk, sidelined, next-14-day predicted lineups, last-7-day finals, cups |
| **Matchday** | every 15 min, but the job exits **without any Sportmonks call** unless a PL kickoff is within [−3 h, +30 min]. It decides this from the free FPL fixtures feed. | 1 per active poll (one `fixtures/between` call covers every fixture of the day) | catch the predicted → confirmed switch (~60 min before kickoff, Q16) |
| **Deadline** | 3 h and 30 min before each FPL deadline (FPL `bootstrap-static` events) | 1 each | freshest predicted XI and sidelined for the deadline view |

A Saturday with three kickoff slots is about 3 × 15 active polls, i.e. ~45 calls. **Peak hour** is
~62 (daily) or ~4 to 8 (matchday), against 2,000. A typical gameweek is ~62 × 7 + ~60 matchday +
2 deadline, i.e. **~500 calls a week**. Every run takes a hard `--max-calls` cap (daily 120,
matchday 10). The daily pass is 64 calls at best (one page per walk) and **112 at most** (`fetch.worst_count`): 2 discovery + 20
squads + 20 sidelined + 20 × 3 club fixtures (240 and 120 days refused, 14 answered) + 1 window ahead + 8 pages of
the last-7-days stats window (`MAX_STATS_PAGES`) + 1 `player_stat_types`. Client retries count against the cap too. A counting wrapper around the client's `Transport` raises before call N+1, so a bug
cannot loop into the quota.

**A timing fact B4 should know:** the FPL deadline is ~90 min before the gameweek's first kickoff,
and confirmed lineups come out ~60 min before each kickoff. So **before the deadline the job has
predicted lineups only**, at least for the first match. Confirmed lineups serve "who replaced whom"
after the fact, not the pre-deadline view.

## Logging (public repo)

GitHub Actions logs of this repo are public. The workflow and the CLI print **aggregates only**:
row counts per table, crosswalk matched/unmatched counts, calls made vs cap, duration, exit status.
They never print, on any path including errors:

- a player, club-opponent or coach name;
- an FPL id or a Sportmonks id;
- a lineup, sidelined or squad row;
- crosswalk content.

Errors print the exception **type only** (as `euro_preload.py` does), and tracebacks are not printed.
The workflow uploads **no artifacts** that contain data. A test runs the CLI in `--dry-run` against the
synthetic recorded fixtures, including a forced error path, and asserts that stdout and stderr contain
none of the names or ids in those fixtures.

## Where it runs: GitHub Actions (recommended) vs Railway cron

| | GitHub Actions | Railway cron service |
|---|---|---|
| Precedent here | `owned-store-refresh.yml` and `tactical-store-refresh.yml` already ingest, publish to R2 and refresh Railway | none; the backend is one web service |
| Secrets | one new repo secret, `SPORTMONKS_API_TOKEN`; the R2 secrets already exist | new service with its own env (token + R2), more Railway config |
| Timing | scheduled runs can start 5 to 20+ min late and are occasionally dropped under load | closer to on time |
| Logs | kept per run, visible in the PR/Actions UI | ephemeral unless a volume is added (the prod-audit snapshot found the same gap) |
| Manual / dry run | `workflow_dispatch` with a `mode` input | needs a one-off command |
| Cost | free for this volume | a second always-configured service |

**Recommendation: GitHub Actions** for daily and deadline runs, and for matchday polls too.

- A 15-minute poll that starts 10 minutes late still catches the confirmed lineup before kickoff,
  because the switch happens ~60 min before.
- B4's first feature works after the fact anyway.

Revisit Railway cron only if the predicted-XI feature needs a guaranteed fresh read at a fixed minute
before the deadline. The job is a plain `python -m` entry point, so moving it is a config change, not a
rewrite.

Secrets Leo adds (his config, not this PR): `SPORTMONKS_API_TOKEN` as a GitHub Actions secret. The
`OWNED_STORE_R2_*` secrets are already present.

## Modes

`python -m licensed_ingestion --pass {daily,matchday,deadline} [--dry-run | --smoke | --publish] [--max-calls N]`
(built in PR 3b; the flags below replaced the earlier `--plan` / `--live` sketch).

- **`--dry-run` (default):** prints the calls a live pass would make and their number (`planned_calls`: 64 for a
  daily pass, 1 for matchday and deadline), then replays a synthetic recorded `Transport` through the whole pass
  into a temp dir that is removed afterwards. It never reads `SPORTMONKS_API_TOKEN` or the remote config, makes no
  network call and publishes nothing. This is what CI runs.
- **`--smoke`:** needs `SPORTMONKS_API_TOKEN`. Reads the provider for real, builds locally, reports counts and
  publishes nothing. The first live smoke (after Leo sets the token and the brain approves) is
  `--pass daily --smoke --max-calls 70`.
- **`--publish`:** a smoke that also publishes the build to the private `football-licensed/` prefix. It needs the
  `FPL_FOOTBALL_REMOTE_*` configuration and is refused without it.
- **`--max-calls`:** every mode takes it. Default and ceiling are daily 120, matchday 10, deadline 10; a larger
  value is refused. The counter wraps the client's `Transport`, counts retries too, and raises before call N+1
  (exit code 3, `FAILED BudgetExceeded`).

The matchday and deadline passes build on the previous published build (they take its crosswalk and carry its cup
tables forward); with no published daily build they fail with `FAILED NoBaseline` rather than guess.
Exit codes: 0 ok (including "skipped, nothing to read"), 1 failed (exception type only), 2 refused, 3 over the cap.

## Backfill (manual, one-off history fill)

`python -m licensed_ingestion --pass backfill [--dry-run | --smoke | --publish] [--since YYYY-MM-DD] [--max-calls N]`

The daily pass only sees the last 7 and the next 14 days, so a store that starts today has one or two matches per club
and B4 cannot show a change against a player's earlier starts. The backfill reads the **finished** PL lineups from the
season's first kickoff (from the free FPL fixture list) to yesterday, in 14-day windows through the same
`licensed_pl_fixtures` route, and appends them to the store.

* **Manual only.** It is a `workflow_dispatch` choice; the schedule names its own passes and never runs it (a test pins it).
* **Cost.** The windows now carry `lineups.details` (R6, player statistics), ~100 KB per fixture, so each window is read in
  pages of 10 fixtures (~1 MB, a quarter of `max_response_bytes`' 4 MiB default) instead of one page of 50. Calls =
  sum over windows of ceil(fixtures / 10), at least one per window, plus at most one `player_stat_types` call. A full
  380-fixture season is ~38 pages + ~1 per window of slack, which is why the hard cap is **60** (`--max-calls` above 60 is
  refused). If a fill ever needs more, split it with `--since` rather than raising the cap.
* **Needs a baseline.** It takes the crosswalk from the previous published build (`FAILED NoBaseline` otherwise) and carries
  the crosswalk and cup tables forward, like a matchday pass.
* **Only completed matches** are kept (`FT`, `AET`, `FT_PEN`, `AWARDED`, `WO`). Their lineup is the XI that was played, so it is
  stored `confirmed = True` even if the provider's flag still reads false after full time. Unfinished or postponed fixtures are
  skipped and counted.
* **Idempotent.** `observed_at` is the morning after the kickoff day (`00:00:00Z`), not the time of the read, so running it again,
  today or next week, yields the same keys and the store's de-duplication on the full key adds nothing. It also means a
  backfilled row can never pass for knowledge from before the match.
* **Does not touch earlier rows.** The daily pass's provisional and confirmed snapshots keep their own `observed_at`, state and
  flag; a reader picks the latest confirmed observation of a match.
* **Logs.** Counts only, like every pass: windows, fixtures read / completed / skipped, rows per table, calls vs cap.

## Where the code goes

- `packages/football-intelligence/football_intelligence/ingestion/licensed/`: `derive.py`, `crosswalk.py` and
  `store.py` (parquet + manifest + `licensed_starter` binding, `LICENSED_V1` family). Network-free.
- `packages/licensed-ingestion/licensed_ingestion/`, the only package that imports both `sportmonks_client` and
  `football_intelligence` (neither imports it; a test pins that):
  - `fetch.py`: composes `SportmonksClient` calls; the only place that names families.
  - `fpl.py`: the free FPL feed and the gates (`matchday`: a kickoff within [-3 h, +30 min]; `deadline`: 3 h and
    30 min before each FPL deadline, each a 20-minute window so a late tick is not a miss).
  - `budget.py`: the counting `Transport`.
  - `run.py`: one pass: reads, crosswalk, derive, immutable build.
  - `recording.py`: the synthetic recorded provider (invented ids and names) that `--dry-run` and the tests replay.
  - `__main__.py`: the modes.
- `.github/workflows/licensed-ingestion.yml`: daily 05:00 UTC, a tick every 15 minutes for deadline + matchday, and
  `workflow_dispatch` with a `mode` input. The **schedule** is disabled unless the repository variable
  `LICENSED_INGEST_ENABLED` is `'true'` (otherwise a scheduled run is skipped and green). Manual runs are not
  gated, so the live smoke can run with the schedule still off; the variable is what turns on unattended publishing.
- Serving (Railway sync and the read API B4 uses) is a later slice. Nothing in B3 exposes data to
  users.

## Build order (each one its own PR)

Note: build-order steps 3 (`fetch.py` + modes + cap) and 4 (the workflow, disabled) landed together in PR 3b.

1. `derive.py` + synthetic fixtures + tests (side rule, confirmed flag, crosswalk counting,
   sidelined de-dup by sideline id, cups → `public_calendar` snapshots marked `partial`).
2. `store.py` + manifest binding + publish via `distribution` (tests on `InMemoryArtifactStore`).
3. `fetch.py` + `__main__` modes + the call cap (tests with a recorded `Transport`, asserting the exact
   call list and that call N+1 raises) + the no-identifiers-in-output test (see Logging).
4. The workflow, disabled.
5. Live smoke: Leo sets the token, the brain approves, `--live` without `--publish`. Before the first
   `--publish`, Leo confirms the bucket's public access is off.

## Open questions and their answers

1. **Cups under Starter:** does `team_fixtures` return FA Cup / Carabao rows on the paid plan?
   **Settled by the live smoke.** The design works either way: no rows → an empty `partial`
   snapshot.
2. **"Per entity" in the rate limit:** per endpoint family or per token? **Settled by the smoke**
   (response headers). The caps assume the stricter reading.
3. **Retention of history:** **keep every snapshot all season** (decided). They're small: ~20
   fixtures × 2 teams × a few observations × 18 rows. It's the history B4's "who replaces whom" reads.
4. **Manual identity queue:** the trial left 17 of 430 unmatched after the automatic pass. **Leo
   decides**; the brain recommends yes. Designed as **optional**: a checked-in table of FPL element ids
   and the registry fields the matcher already uses (no provider ids). When it's absent, the build
   runs, and unmatched players are dropped and counted. No build PR waits on it.


## Player match statistics (R6)

`player_match_stats` (optional table; key element, FPL fixture, `observed_at`) holds, per player and finished match: minutes,
rating, touches, passes, accurate passes, key passes, long balls, through balls, **backward passes**, final-third passes,
shots (total / on target), duels won, tackles, interceptions, recoveries, dribbles. Totals per match: no zones, no minutes
of the action, no progressive or forward-pass counts (the provider has none).

* **Where it comes from.** The last-7-days window of the daily pass and every backfill window use the route
  `licensed_pl_fixtures_stats` (the licensed fixtures include plus `lineups.details`), in pages of 10. The 14-day window
  ahead, the matchday and the deadline passes do not ask for details (a match not played has none). No extra call for the
  stats themselves.
* **Names.** `stat_types` (optional table, type id -> developer name) is read from the provider with one
  `fixtures/{id}?include=lineups.details.type` call, **only** when a finished fixture carries a type id the table does not
  know (which includes an empty table), and at most once per pass. An id still unknown afterwards is left out and counted
  (`stat_types.unknown_after`). `core/types` answers 404 on the trial token, which is why it is not used.
* **Absent = zero** only for a player with minutes (the provider sends non-zero stats only). A player with no minutes has no
  row. A rating is never zero-filled. A re-read that changes nothing adds no row; a correction is kept, dated.
* **Old builds.** Both tables are optional: a build written before R6 validates and the runtime serves them empty.
* **Logs.** Counts only (`stat_types`: known, learned, provider_calls, unknown_after; `rows.player_match_stats`).

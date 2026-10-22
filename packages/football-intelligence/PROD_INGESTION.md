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
matchday 10). A counting wrapper around the client's `Transport` raises before call N+1, so a bug
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

- **`--dry-run` (default):** a recorded-fixture `Transport` replays synthetic payloads. No token, no
  network. It writes the build to a temp dir, prints row counts, the crosswalk rate, the call count it
  *would* have made and the side checks, and never publishes. This is what CI runs.
- **`--plan`:** prints the calls a live run would make and their budget, then exits. No network.
- **`--live`:** needs `SPORTMONKS_API_TOKEN`, the explicit flag and `--max-calls`. It publishes only
  when `--publish` is also given, so the first live smoke (after Leo sets the token and the brain approves) is
  `--live --max-calls 70` without `--publish`: it reads, builds locally, reports, and publishes nothing.

## Where the code goes

- `packages/football-intelligence/football_intelligence/ingestion/licensed/`:
  - `fetch.py`: composes `SportmonksClient` calls; the only place that names families and includes.
  - `derive.py`: pure function from typed client entities to derived tables. No I/O, fully unit-tested.
  - `store.py`: parquet + manifest + `licensed_starter` binding; publishes via `distribution`.
  - `__main__.py`: modes, call cap.
- `.github/workflows/licensed-ingestion.yml`: daily, matchday and deadline schedules, plus `workflow_dispatch`.
  It is added in its own PR, **disabled** (`if: vars.LICENSED_INGESTION_ENABLED == 'true'`) until the live
  smoke passes.
- Serving (Railway sync and the read API B4 uses) is a later slice. Nothing in B3 exposes data to
  users.

## Build order (each one its own PR)

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

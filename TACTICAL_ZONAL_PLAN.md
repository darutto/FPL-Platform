# Execution Plan — Tactical Zonal-Weakness Intelligence (Phase T1–T2 + T4a)

**Audience:** the implementing agent (Fable).
**Branch:** `feat/tactical-zonal-intelligence` (already created off `main`).
**Source of truth for scope:** `TACTICAL_ASSISTANT_ROADMAP.md` (rewritten 2026-07-02). This plan implements **T1 (owned ingest)**, **T2 (zonal engine)**, and **T4a (orchestrator tool reach)**. It deliberately stops before T3 (FotMob buildup-flank) and T4b/c (cards, Track D tie-in) — those are follow-ups.

**Why this exists:** a live PoC (2026-07-02) proved the whole idea against real 2025/26 Understat data — see Appendix A. This plan turns that throwaway proof into an owned, tested, tool-surfaced capability, mirroring two patterns that already exist in this repo: the **Track A owned-store** (`packages/fpl-historical/`) and the **Track D pure-engine + thin-tool split** (`fixture_outlook.py` + `fixture_outlook_tool.py`).

---

## 0. Ground rules (read before writing any code)

1. **Work on `feat/tactical-zonal-intelligence` only.** First action: `git checkout feat/tactical-zonal-intelligence`, then commit this plan file as the first commit so it travels with the branch.
2. **Do not touch the deterministic FPL scoring engines.** This track is additive and orchestrator-tool-only (like Track D FI2). No changes to `captain`, `transfer_advisor`, `comparison`, `differential_picks`, `chip_advisor` in this plan. The Track D tie-in (T4c) is out of scope here.
3. **No buy/sell language anywhere.** The engine reports *opportunity/weakness signals* ("Palace leak in-box down their right, above league average"). Advice framing stays owned by the existing engines. This mirrors the `team_fixture_calendar` / Track D invariant.
4. **Relative, not absolute.** The signal is *deviation from the league baseline per zone*, never raw zone totals (central always dominates raw xGA). This is the single most important modeling constraint — see PoC finding in Appendix A.
5. **Own the data.** Every external pull lands in a local parquet store and is published to R2, exactly like `fpl-historical`. Never scrape live inside a request handler.
6. **Commit per slice** with a clear message. Each slice below is independently shippable and independently testable.
7. **Test conventions gotcha (from prior Track D work):** package tests must load modules directly via `importlib` rather than through `fpl_grounded_assistant/__init__.py` — its `__init__` pulls the dispatcher/harness and a stale `fpl-captain-engine/python` `pytest.ini` path that breaks `import fpl_captain_engine`. Follow the import style already used in `packages/fpl-grounded-assistant/tests/test_fixture_outlook.py`.

---

## Slice T1a — Data-source spike (do this FIRST, timeboxed)

**Goal:** decide the ingest client before building the pipeline around it. The PoC found Understat **moved to gzip AJAX endpoints** (`getLeagueData`, `getMatchData`) and no longer embeds JSON in HTML — so the old `understatapi` package may be broken. `soccerdata` is the preferred maintained library, **but that must be verified**, not assumed.

**Steps:**
1. In a scratch venv, `pip install soccerdata` and attempt to read **2025/26 EPL shot events** (`soccerdata.Understat`). Confirm it returns per-shot `X`, `Y`, `xG`, `situation`, `result`, player, team.
2. **Decision gate:**
   - **If soccerdata works** → adopt it as the ingest client. Preferred: it tracks upstream scraper churn for us.
   - **If soccerdata's Understat reader is broken** (stale on the AJAX change) → build a thin internal client `understat_client.py` using the **proven endpoints from Appendix B**. Do NOT resurrect `understatapi`.
3. Record the decision in a one-paragraph `packages/fpl-tactical/DECISIONS.md` with the date and what you verified.

**Acceptance:** a 10-line script prints a DataFrame/list of ≥10 real 2025/26 shots with coordinates, and `DECISIONS.md` states the chosen client and why.

**Deliverable:** `DECISIONS.md`; no pipeline yet.

---

## Slice T1b — `fpl-tactical` package + owned ingest

**Goal:** pull a season of Understat shots into a local parquet store, idempotently. Mirror `packages/fpl-historical/` structure (don't invent a new layout).

**New package:** `packages/fpl-tactical/`
```
fpl_tactical/
  __init__.py
  paths.py            # mirror fpl-historical/paths.py: env-overridable root, season dirs
  understat_client.py # OR a thin soccerdata wrapper, per T1a decision
  ingest.py           # fetch season shots -> normalized rows
  store.py            # write/read parquet; _tactical_latest.json pointer w/ provenance
  cli.py              # argparse subcommands: ingest, verify
  __main__.py
requirements.txt      # soccerdata OR (requests only) + pandas + pyarrow
CONTRACT.md           # short: schema, endpoints, provenance fields, idempotency rule
tests/
  test_ingest.py
  test_store.py
  test_zone.py        # (added in T2a)
  fixtures/           # a small canned getMatchData/getLeagueData JSON sample
```

**Normalized shot row schema (parquet `understat_shots`):**
| column | type | source |
|---|---|---|
| `season` | str | "2025-2026" (match `fpl-historical` season key style) |
| `match_id` | int | Understat match id |
| `date` | str (ISO) | match date |
| `shooting_team` | str | team that took the shot |
| `conceding_team` | str | opponent (the defense) |
| `player` | str | shooter |
| `is_home_shot` | bool | shot by home side? |
| `minute` | int | |
| `x` | float | Understat X (0–1) |
| `y` | float | Understat Y (0–1) |
| `xg` | float | Understat xG |
| `situation` | str | OpenPlay / FromCorner / SetPiece / Penalty / DirectFreekick |
| `shot_type` | str | shotType |
| `result` | str | Goal / SavedShot / MissedShots / … |

- Store `conceding_team` explicitly so T2's defensive aggregation is a trivial group-by (don't recompute opponent at query time).
- **Idempotency:** re-running ingest for a season replaces that season's parquet atomically (write temp → rename), and updates `_tactical_latest.json` with `{season, ingested_at, source, source_version, n_matches, n_shots}` provenance (mirror `_owned_latest.json`).
- **Env override:** `FPL_TACTICAL_ROOT` (default `packages/fpl-tactical/data/tactical/`), mirroring `FPL_HISTORICAL_ROOT`.

**CLI:**
```
python -m fpl_tactical.cli ingest  --season 2025-2026
python -m fpl_tactical.cli verify  --season 2025-2026   # prints row counts + provenance
```
Exit codes: 0 ok, 1 failed (match `fpl-historical` conventions).

**Acceptance:**
- `ingest --season 2025-2026` writes `understat_shots` parquet with ≥5000 non-penalty shots and a valid pointer file.
- Re-running `ingest` is idempotent (same row count; pointer `ingested_at` updates; no duplication).
- `test_ingest.py` / `test_store.py` run against the **canned fixtures** (no network) and pass. Network is only touched by the real CLI, never by tests.

---

## Slice T1c — R2 publish + weekly refresh

**Goal:** publish the tactical store to R2 and refresh it weekly, reusing the existing R2 sync + GitHub Actions machinery.

**Steps:**
1. **Publish:** reuse `packages/fpl-grounded-assistant/fpl_grounded_assistant/owned_store_sync.py` R2 env conventions (`OWNED_STORE_R2_ENDPOINT/BUCKET/ACCESS_KEY_ID/SECRET_ACCESS_KEY/PREFIX`). Either extend that module with a tactical prefix, or add `fpl_tactical/publish.py` that uploads `understat_shots` parquet + pointer to `r2://<bucket>/<prefix>/tactical/2025-2026/`. Prefer a distinct key prefix so it never collides with the FPL owned store.
2. **Workflow:** add `.github/workflows/tactical-store-refresh.yml`, copied from `.github/workflows/owned-store-refresh.yml`, changed to:
   - cron offset from the FPL one (e.g. `30 6 * * 1`) to avoid overlapping load.
   - steps: install deps → `python -m fpl_tactical.cli ingest --season 2025-2026` → publish to R2 → (optional) Railway redeploy.
   - `workflow_dispatch` for manual runs.

**Acceptance:** `tactical-store-refresh.yml` passes a dry-run (`workflow_dispatch`) or, if secrets aren't wired, a documented manual `python -m fpl_tactical.cli ingest && publish` succeeds locally and the object appears in R2. If R2 secrets are unavailable to you, stop at local parquet + a TODO note in `DECISIONS.md` and flag it for the user — do **not** invent credentials.

---

## Slice T2a — Zonal engine (pure, no registry)

**Goal:** the deterministic engine that turns shots into a **relative** zonal-weakness signal. Pure stdlib+pandas, no tool registry, no LLM — exactly like `fixture_outlook.py`.

**New module:** `packages/fpl-grounded-assistant/fpl_grounded_assistant/zonal_weakness.py`
(Engine lives next to the tool wrapper, mirroring the `fixture_outlook.py` / `fixture_outlook_tool.py` pairing. It reads the tactical parquet via a small reader — inject the store path so tests can point at fixtures.)

**Zone definition (locked, from the PoC — do not re-derive):**
- Depth band from Understat `x`: `in-box` if `x ≥ 0.84`; `edge-of-box` if `0.70 ≤ x < 0.84`; else ignore (long-range noise).
- Lateral band from Understat `y`: ~~`left` if `y < 0.36`; `right` if `y > 0.64`~~ **[CORRECTED 2026-07-09, flank-mirror fix]:** `right` if `y < 0.36`; `left` if `y > 0.64`; else `central`. Understat `y` grows toward the attacker's LEFT — pinned by known-flank players (Saka/Salah/Bowen cluster in the low band; Mitoma in the high band). The original spec line encoded the mirror.
- **Exclude penalties** (`situation == "Penalty"`) from zonal aggregation; report their xGA separately as context.
- **Coordinate caveat (document in the docstring):** Understat `y` orientation is fixed; "left/right" is from the attacking team's perspective — this is *zone-of-finish*, not buildup-flank (that's T3). **[CORRECTED 2026-07-09]:** all copy now speaks ONE attacker/opportunity frame ("ataca por la derecha"); the defender-side flip is gone, and the known-flank regression tests pin the orientation.

**Public functions:**
```python
def compute_team_zone_profiles(shots, *, min_x=0.70) -> dict[team, dict[zone, {shots, xga, goals, games}]]
def compute_league_baseline(profiles) -> dict[zone, float]         # mean xga/game per zone
def get_zonal_weakness(team, *, store) -> {
    "status": "ok" | "not_found" | "missing_context",
    "team": str,
    "zones": [ {"zone": "in-box / right", "xga_per_game": float,
                "league_avg": float, "delta_vs_avg": float, "rank": int} ... ],
    "weakest_zones": [top-2 by delta_vs_avg],
    "verdict": "<Spanish, schedule/opportunity-only one-liner>",
}
def get_zonal_opportunity(opponent, *, position=None, store) -> {
    # opponent weak zones joined to players whose OWN shot profile concentrates there
    "status": ..., "opponent": str,
    "opportunities": [ {"zone", "delta_vs_avg", "players": [player names]} ],
}
```
- `get_zonal_opportunity` player matching (T2c in the roadmap): per player, bucket their **own** shots by zone; a player "operates" in a zone if a meaningful share of their non-penalty xG comes from it. Keep the threshold a named constant; document it.
- Verdict strings: Spanish, opportunity-framed, no buy/sell. E.g. `"Ataca a Crystal Palace por la derecha dentro del área — concede por encima de la media de la liga ahí."` *(re-derived 2026-07-09: corrected handedness + unified attacker frame; the original example used a defender-frame flip of mirrored labels.)*

**Acceptance:** `tests/test_zonal_weakness.py` (mirror `test_fixture_outlook.py` style, importlib load) against **canned shot fixtures** with hand-computed expected deltas:
- baseline math correct; penalties excluded; orientation asserted.
- `not_found` for unknown team; `missing_context` when store empty.
- opportunity matcher returns the right players for a constructed weak zone.
≥15 tests. No network.

---

## Slice T2b — Orchestrator tool (T4a reach)

**Goal:** expose the engine to the LLM orchestrator so any "who should I target against Palace" question reaches it — zero deterministic-engine changes, mirroring `fixture_outlook_tool.py` exactly.

**New module:** `packages/fpl-grounded-assistant/fpl_grounded_assistant/zonal_weakness_tool.py`
- Define `GET_ZONAL_WEAKNESS_SPEC` and `GET_ZONAL_OPPORTUNITY_SPEC` as `ToolSpec`s; register both with `TOOL_REGISTRY.register(...)` and delegate to the engine. Reuse `_resolve_team` from `team_fixture_calendar` for team name/alias resolution (same as the fixture tool).
- Handlers return `status ∈ {ok, not_found, missing_context}`; `missing_context` when the tactical store is absent (graceful — never raise into the orchestrator).

**Wiring (three exact edits, mirror Track D):**
1. `tool_schema_registry.py`: add `GET_ZONAL_WEAKNESS_SCHEMA` + `GET_ZONAL_OPPORTUNITY_SCHEMA` (`ToolSchema`, near `GET_FIXTURE_OUTLOOK_SCHEMA` at line ~607) and include them in the `_ALL_SCHEMAS` tuple (line ~985). Descriptions must say **schedule/opportunity-only, no buy/sell**.
2. `__init__.py`: add `from . import zonal_weakness_tool as zonal_weakness_tool  # T-zonal — triggers TOOL_REGISTRY self-registration` next to the fixture_outlook_tool import (line ~251).
3. Follow the **atomic-tool pattern**: schemas go in `_ALL_SCHEMAS` (orchestrator-callable) but the tools are deliberately **kept OUT** of `_TOOL_TO_INTENT` / `SUPPORTED_INTENTS` / the classifier — they are narrated as text by the orchestrator, not rendered as a dedicated card in this plan (cards = T4b, later). Verify the classifier-coverage contract stays green (there is no `hint ⊆ supported` assertion that these must satisfy — confirm as Track D did).

**Acceptance:**
- `tests/test_zonal_weakness_tool.py`: `run_tool("get_zonal_weakness", {...}, bootstrap)` and `run_tool("get_zonal_opportunity", {...}, bootstrap)` return the expected shapes against a fixture store; `missing_context` when no store. ≥6 tests.
- Update whatever tool-count preflight exists (Track D bumped `run_phase_m3_preflight_tests.py` counts — search for a hard-coded tool count and bump it; grep for the current count).
- Full backend suite: no **new** failures. (Pre-existing unrelated failures noted in Track D memory: router name-extraction ×3, owned_store fixtures-table ×1 — confirm these are the same ones via `git stash` compare, don't fix them here.)

---

## Slice T2c — End-to-end smoke + docs

1. `packages/fpl-tactical/scripts/smoke_zonal.py`: ingest (or load cached) → `get_zonal_weakness("Crystal Palace")` → print verdict + weak zones. Must reproduce the PoC's qualitative result. *(Re-derived 2026-07-09: the PoC note "Palace weak down their right" was built on the mirrored labels. Correct read: Palace concede in the attacker's RIGHT band — "ataca a Palace por la derecha", i.e. Palace's own left side.)*
2. `packages/fpl-tactical/README.md` + `CONTRACT.md`: schema, endpoints, refresh cadence, the relative-baseline rule, the finish-vs-buildup caveat, and the T3 follow-up.
3. Update `TACTICAL_ASSISTANT_ROADMAP.md`: mark T1a–T2b done with commit SHAs.

**Acceptance:** smoke script prints a sane, differentiated ranking from real data; docs committed.

---

## Definition of done (whole plan)

- [ ] `packages/fpl-tactical/` ingests + stores + publishes Understat shots for 2025/26, idempotently, owned in parquet/R2.
- [ ] `zonal_weakness.py` computes relative-to-baseline zonal weakness + player opportunity matching, penalties excluded, orientation tested.
- [ ] `get_zonal_weakness` + `get_zonal_opportunity` are orchestrator-callable tools; no deterministic engine touched; no new test failures.
- [ ] Weekly refresh workflow exists (or a documented manual runbook + flagged blocker if R2 secrets unavailable).
- [ ] No buy/sell language anywhere; all verdicts schedule/opportunity-framed and Spanish.
- [ ] Roadmap updated; PR opened against `main` (do not merge — leave for user review).

**Explicitly OUT of scope (do not start):** T3 FotMob/Sofascore buildup-flank; T4b zonal card / frontend; T4c Track D matchup-modifier tie-in; VAEP/PPDA/pitch-control (offline research backlog); the PuLP solver. Note them in the PR description as the next steps.

---

## Appendix A — What the PoC proved (2026-07-02)

Live pull of all 380 EPL 2025/26 matches from Understat (stdlib only). League avg in-box xGA/game: **left 0.079 · central 1.159 · right 0.081**. Most vulnerable down their right (attacker's left): **Crystal Palace (+0.055), Burnley (+0.047), Newcastle (+0.040)**. Most vulnerable down their left: **Sunderland (+0.045), Aston Villa (+0.043), Burnley (+0.035)**. Conclusion: free Understat shot data is sufficient for zonal weakness; the signal is deviation-from-baseline; central dominance makes absolute totals useless; it's zone-of-finish (buildup-flank needs Tier-2 FotMob). Reference scripts are committed on this branch at `tactical-poc/understat_zonal_poc.py` and `tactical-poc/understat_league_flank.py` — reuse their zone math (delete the `tactical-poc/` folder once T2a lands).

## Appendix B — Proven Understat endpoints (fallback client, if soccerdata is stale)

Understat now serves gzip'd JSON via AJAX (no inline HTML JSON). Verified working 2026-07-02:

- **League list:** `GET https://understat.com/getLeagueData/EPL/2025`
  → JSON `{ "dates": [...], "teams": {...}, "players": [...] }`. `"2025"` == 2025/26. Each `dates[]` entry: `{id, isResult, h:{title,...}, a:{title,...}, ...}`.
- **Match shots:** `GET https://understat.com/getMatchData/{match_id}`
  → JSON `{ "shots": { "h": [...], "a": [...] }, "rosters": {...} }`. Each shot: `{minute, result, X, Y, xG, situation, shotType, player, player_id, h_team, a_team, ...}`.
- **Required headers:** `User-Agent: Mozilla/5.0`, `X-Requested-With: XMLHttpRequest`, `Referer: https://understat.com/`.
- **Response is gzip:** check `Content-Encoding == "gzip"` and `gzip.decompress()` before `json.loads`.
- **Politeness:** ~0.1–0.2s between match requests; a full league pass is ~380 requests (~2–3 min). This is why ingest runs weekly into the owned store, not per query.
- For a team's conceded shots: for each of its matches, take the **opponent's** side of `shots` (`h` if the team is away, `a` if home).

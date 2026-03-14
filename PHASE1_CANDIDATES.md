# Phase 1 Candidate Ranking
**Prepared after:** Phase 0 validation complete (fpl-captain-engine TypeScript pilot in captaincy-showdown)
**Date:** 2026-03-08
**Constraint:** Do not start Phase 1 until approved.

---

## Scoring criteria

Each candidate is scored 1–5 on four axes:

| Axis | Meaning |
|------|---------|
| **Independence** | How free is this from upstream repos (fpl-elo-insights, external APIs, other projects not yet migrated)? High = no external blockers |
| **Ease of testing** | How straightforward is validation? High = deterministic, pure functions, no network/file I/O mocking needed |
| **Risk** | How much damage if the migration introduces a bug or break? High score = low risk |
| **Leverage** | How many future platform features and the grounded chat interface are unblocked by completing this? |

---

## Ranked candidates

### 🥇 Candidate 1 — `fpl-data-core` · `season_registry.py` + `season_registry.yaml` full activation

**What this means:** Write the full test suite for `season_registry.py` and the YAML config (§1.1–1.5 of TEST_PLAN.md), confirm the module is importable from `fpl-data-core` as a package, and add the first passing CI check.

| Axis | Score | Rationale |
|------|-------|-----------|
| Independence | ⭐⭐⭐⭐⭐ | Zero upstream dependency. Pure Python + YAML. No FPL API, no fpl-elo-insights, no external network. |
| Ease of testing | ⭐⭐⭐⭐⭐ | All functions are pure and deterministic (`get_season_id`, `get_gw_date_range`, `get_all_gameweeks`). Test data is the YAML itself — no fixtures needed. |
| Risk | ⭐⭐⭐⭐⭐ | Read-only config module. Cannot affect production data or any live service. Rollback is delete the tests. |
| Leverage | ⭐⭐⭐⭐☆ | Every other platform package (captain engine scoring, CSV loading, API client caching, chat grounding) needs to know "what season/GW are we currently in?" This is the foundational lookup. The grounded chat interface needs it to answer "who should I captain this week?" without hallucinating the gameweek. |

**Total: 19 / 20**

**Why first:** This is the only candidate with no open blockers, no external dependencies, and a complete test plan already written. It establishes the Python package infrastructure (`__init__.py`, `pyproject.toml` or `setup.cfg`, first passing `pytest`) that every subsequent Python package will inherit.

---

### 🥈 Candidate 2 — `fpl-data-core` · `analytics.py` creation (`compute_rolling_xgi_per_90`)

**What this means:** Create `analytics.py`, move `compute_rolling_xgi_per_90()` from `stat_calculator.py` (captaincy-showdown source), write the §1.6 placeholder test into a real test suite, and retire the dormant function from its source project.

| Axis | Score | Rationale |
|------|-------|-----------|
| Independence | ⭐⭐⭐⭐⭐ | Derived from internal `captaincy-showdown`. The function is pure pandas — no fpl-elo-insights dependency. Input is a DataFrame; output is a float per player per GW. |
| Ease of testing | ⭐⭐⭐⭐☆ | Numerical output is deterministic given a fixture DataFrame. Slight complexity in constructing multi-GW rolling window test fixtures, but no mocking needed. |
| Risk | ⭐⭐⭐⭐☆ | New file, no existing callers in the platform. The source function in captaincy-showdown is currently unused by the live app (it was identified as a candidate for retirement from `stat_calculator.py`). Safe to introduce without breaking anything. |
| Leverage | ⭐⭐⭐⭐☆ | `compute_rolling_xgi_per_90` is the key input to the captain scoring formula. Once this lives in `fpl-data-core`, the Python side of the captain engine can consume it directly — unblocking the Python parity test for `fpl-captain-engine`. Also useful for chat queries like "who has the highest xGI trend over the last 5 GWs?" |

**Total: 17 / 20**

**Sequencing note:** Ideally done immediately after Candidate 1, in the same Phase 1 work block, since `analytics.py` will import `season_registry` for GW lookups and the package infrastructure will already be in place.

---

### 🥉 Candidate 3 — `fpl-api-client` · Python FPL bootstrap client

**What this means:** Validate `fpl_client.py` (bootstraps FPL data: players, teams, fixtures, GW status) as a standalone importable module in `fpl-platform/packages/fpl-api-client`. Write smoke tests with HTTP mocking (no live API calls in CI). Confirm it is the canonical version replacing equivalent ad-hoc scripts in `fpl-video-repurposer` and `FPL-team-stats`.

| Axis | Score | Rationale |
|------|-------|-----------|
| Independence | ⭐⭐⭐⭐☆ | No upstream repo dependency. The only external is the public FPL API (`https://fantasy.premierleague.com/api/bootstrap-static/`). Tests use mocked responses, so no live network in CI. |
| Ease of testing | ⭐⭐⭐☆☆ | Requires HTTP mocking (`responses` or `httpretty`) and a sample bootstrap JSON fixture. The bootstrap payload is large (~500KB) so a trimmed fixture is needed. Moderate setup cost. |
| Risk | ⭐⭐⭐⭐☆ | The client is read-only (GET requests only). No writes, no mutations. The FPL API is undocumented and can change shape without notice — this is an accepted external risk, not a migration risk. |
| Leverage | ⭐⭐⭐⭐⭐ | **Highest leverage of any candidate for the grounded chat interface.** Every real-time chat query ("Is Salah playing this week?", "What's Haaland's ownership?", "Who has the best fixture run?") requires fresh bootstrap data. Without this module in the platform, the chat interface must either use stale hardcoded data or re-implement the API client inline. Completing this unblocks `fpl-player-registry` (which needs player IDs from bootstrap) and the CSV loading pipeline. |

**Total: 16 / 20**

**Why not ranked higher:** The HTTP mocking setup is a non-trivial one-time cost, and the FPL API's undocumented nature means the fixture JSON needs to be a real sample capture. This is a two-session piece of work rather than a one-session piece. Candidates 1 and 2 should be done first to establish the Python package infrastructure.

---

### 4️⃣ Candidate 4 — `fpl-data-core` · `schemas.py` upstream SHA pinning (Tier B completion)

**What this means:** Write the §1.4 upstream contract test — a CI check that reads the most recent `playerstats.csv` from `FPL-Elo-Insights/By Gameweek/GW{n}/` and asserts that every column in `CUMULATIVE_COLS` is present in the actual file. Add the `# aligned-with: <sha>` comment to `schemas.py`.

| Axis | Score | Rationale |
|------|-------|-----------|
| Independence | ⭐⭐⭐☆☆ | This test has a direct read dependency on `fpl-elo-insights` CSV outputs being present on the local filesystem. In CI, the CSV path must be resolvable — either through a committed fixture or a symlink to the upstream repo. This is the one candidate with a runtime coupling to the upstream pipeline. |
| Ease of testing | ⭐⭐⭐⭐☆ | The test itself is simple (read a CSV header, assert column set). The complexity is in the CI fixture strategy. |
| Risk | ⭐⭐⭐⭐⭐ | `schemas.py` only contains constants — no logic. The upstream contract test is read-only. Cannot regress anything. |
| Leverage | ⭐⭐⭐☆☆ | Important for long-term stability (prevents silent schema drift between platform and upstream), but does not directly unblock any new feature. The chat interface benefits indirectly — it prevents wrong column reads — but a human review of schema drift would catch the same issue. |

**Total: 15 / 20**

**Prerequisite:** The §1.4 test requires at least one gameweek of upstream CSVs to be present on disk. This is already satisfied by the existing `fpl-elo-insights` data on the local machine, but must be documented as an assumption for any future CI/CD pipeline running in a clean environment.

---

### 5️⃣ Candidate 5 — `fpl-player-registry` · SeasonIdMapper + nickname resolver

**What this means:** Validate `season_id_mapper.py` and the nickname/player-name normalisation logic as a standalone importable package. Write smoke tests confirming that player IDs resolve correctly across seasons.

| Axis | Score | Rationale |
|------|-------|-----------|
| Independence | ⭐⭐⭐☆☆ | The mapper is internally sourced (`captaincy-ml`, `fpl-video-repurposer`), but its test suite needs bootstrap player data to confirm ID mappings — which means a dependency on Candidate 3 (`fpl-api-client`) for any integration test beyond pure unit smoke tests. |
| Ease of testing | ⭐⭐⭐☆☆ | Unit tests on the mapping logic are straightforward. Any test involving real player IDs requires a bootstrap fixture, coupling this to the API client work. |
| Risk | ⭐⭐⭐⭐☆ | Read-only, no writes. Low migration risk. |
| Leverage | ⭐⭐⭐⭐☆ | The grounded chat interface needs player name normalisation badly ("Is 'Haaland' the same as 'E. Haaland'?", "What's player ID 355?"). But this leverage is fully realised only after Candidate 3 supplies the bootstrap data. |

**Total: 14 / 20**

**Sequencing note:** Best done after Candidate 3 (`fpl-api-client`), not before, because the most valuable tests for this package require player ID data from the bootstrap response.

---

## Recommended Phase 1 sequence

```
Phase 1a (no blockers, this session):
  └─ season_registry.py + YAML tests (Candidate 1)
  └─ analytics.py creation (Candidate 2)

Phase 1b (one-time HTTP fixture cost):
  └─ fpl-api-client Python client (Candidate 3)

Phase 1c (depends on 1b for full integration tests):
  └─ schemas.py upstream contract test (Candidate 4)
  └─ fpl-player-registry (Candidate 5)
```

Completing Phase 1a alone would:
- Give the platform its first clean `pytest` green run with zero failures
- Establish the Python package structure all subsequent packages will use
- Provide the season/GW context layer the grounded chat interface depends on
- Move `compute_rolling_xgi_per_90` to its canonical home, enabling Python-side captain engine tests

---

## What is not a Phase 1 candidate

| Item | Reason deferred |
|------|----------------|
| `fpl-charts` (TypeScript) | Low test leverage; charts are pure rendering, tested adequately by visual regression in captaincy-showdown's existing test suite |
| `fpl-captain-engine` Python variant | Requires `analytics.py` (Candidate 2) and `season_registry` (Candidate 1) to be in place first; this is Phase 2 |
| `fpl-pipeline` | Orchestration layer; has no value until the modules it orchestrates are all stable in the platform |
| Captaincy-showdown full build validation | Requires Windows environment; cannot be fully automated from the Linux VM without resolving the node_modules cross-OS issue |



# FPL Platform V1.5 Roadmap

## Purpose

V1.5 is the stabilisation wave between the approved V1 MVP and the V2 beta-tester release.

The V1 gate proved the platform is internally consistent and deterministically grounded.
V1.5 raises the accuracy and usefulness of the advice to a level that extended UAT can
produce meaningful signal — where real FPL players push back on the answers, not on
missing infrastructure.

> V1.5 is done when the advice is correct enough to be argued with, and stable enough
> to be handed to a UI developer.

---

## What V1 Left Open

### Score algorithm gaps

The canonical formula (`form 40 / fixture 30 / xGI/90 20 / minutes 10`) was designed
for outfield attacking players and ported directly from the TypeScript captain engine.
It works well for MID and FWD captaincy comparisons.  It has three structural weaknesses:

| Gap | Impact |
|---|---|
| All positions share the same weights | DEF and GKP captain/comparison scores are misleading: xGI/90 is near-zero for defenders and goalkeepers, but the formula still allocates 20% of the score to it |
| FDR is integer 1-5 with no home/away split | A home FDR-2 and an away FDR-2 are treated identically, which understates home advantage and understates away difficulty |
| Form is a 4-GW rolling average with equal weighting | Recent-GW form spikes or slumps (e.g., returning from injury) are diluted by older weeks |

### Missing advice coverage

| Gap | Current behaviour |
|---|---|
| Free hit advice | Always returns `missing_context` — no blank/double gameweek detection |
| Fixture run follow-up | "What about Haaland?" after a fixture run query is not handled |
| Differential follow-up | "What about Mbeumo?" after a differential response is not handled |
| Squad context | Transfer and chip advice ignores whether the user has budget or chips available |

---

## V1.5 Scope

### Slice overview

| Slice | Title | Impact |
|---|---|---|
| 8a | Position-aware scoring | High — removes the main accuracy complaint from UAT |
| 8b | Home/away fixture factor | Medium — completes the scoring signal picture |
| 8c | DGW/BGW detection and free hit unblock | High — makes chip advice useful for the most-asked chip |
| 8d | Follow-up resolution completeness | Medium — closes the two remaining follow-up gaps |
| 8e | Squad context layer | High — makes transfer and chip advice actionable |
| 8f | Validation Corpus V3 and gate | Required — closes the wave |

---

## Slice Details

---

### 8a — Position-Aware Scoring

**Problem**

`calculate_captain_score(form, fixture_difficulty, xgi_per_90, minutes_risk)` allocates
20% of the score to `xgi_per_90`.  For a goalkeeper this score is structurally zero
all season.  For most defenders it is near-zero.  This suppresses GKP and DEF scores by
10-20 points regardless of actual quality.

**Pre-work findings (live bootstrap-static, GW28 2025-26)**

Live API inspection (105 element keys) confirmed the following fields are available
directly in the bootstrap `elements` array — no per-player API calls needed:

| Field | Notes |
|---|---|
| `defensive_contribution_per_90` | Pre-computed by FPL: `dc / (minutes / 90)` |
| `clean_sheets_per_90` | Pre-computed by FPL |
| `saves_per_90` | Pre-computed by FPL — non-zero only for GKP |
| `goals_conceded_per_90` | Pre-computed by FPL |
| `expected_goals_conceded_per_90` | Pre-computed by FPL |

Distribution by position (players with >450 min):

| Signal | GKP | DEF | MID | FWD |
|---|---|---|---|---|
| `dc_per_90` median | 0.0 | 7.5 | **8.3** | 4.4 |
| `dc_per_90` max | **0.0** | 13.8 | 14.9 | 7.5 |
| `saves_per_90` | 1.6–3.6 | 0.0 | 0.0 | 0.0 |
| `clean_sheets_per_90` median | 0.26 | 0.27 | 0.28 | 0.31 |

**Key conclusions from the data:**
1. `dc_per_90` is NOT a DEF advantage over MID — defensive midfielders (Ugarte, Cook,
   Wieffer) score higher than most DEFs.  It cannot be used as a DEF-specific bonus.
2. `dc_per_90 = 0.0` for ALL GKPs — a clean structural boundary between GKP and outfield.
3. `saves_per_90` is GKP-exclusive (all outfield = 0.0).
4. `clean_sheets_per_90` is uniform across outfield positions (~0.27–0.34 median) —
   useful as a player-level historical signal, not a position differentiator.
5. The `form` component of the canonical formula already partially captures dc bonus
   points through recent total_points averages.

These findings determine the correct position bias signals:
- **GKP**: `saves_per_90` bonus + `clean_sheets_per_90` historical signal + full xGI drag offset
- **DEF**: `clean_sheets_per_90` historical signal + partial xGI drag offset;
  `dc_per_90` exposed in `score_inputs` for transparency but not added as a bonus
  (it would incorrectly disadvantage attacking DEFs vs defensive DEFs)
- **MID**: `0` (canonical formula already calibrated)
- **FWD**: small xGI boost (xGI is the primary return driver)

**Proposal**

Add a `position_bias` signal computed *alongside* the canonical score.  The canonical
formula is not modified.

```
adjusted_captain_score = clamp(captain_score + position_bias, 0, 100)
```

`position_bias` rules:

| Position | Primary signals | Bias |
|---|---|---|
| GKP | `saves_per_90`, `clean_sheets_per_90` | `saves_score × 0.15 + cs_score × 0.10 − xgi_drag × 1.0` |
| DEF | `clean_sheets_per_90` | `cs_score × 0.10 − xgi_drag × 0.5` |
| MID | — | `0` |
| FWD | `xgi_per_90` | `xgi_score × 0.05` |

Where:
- `xgi_drag = xgi_score × 0.20` (the xGI component's full contribution in the canonical formula)
- `saves_score = clamp(saves_per_90 / 4.0 × 100, 0, 100)` (normalised: 4 saves/90 ≈ 100)
- `cs_score = clamp(clean_sheets_per_90 / 0.5 × 100, 0, 100)` (normalised: 0.5 cs/90 ≈ 100)

**Outputs changed**

- `score_inputs` gains: `adjusted_captain_score`, `position_bias`,
  `dc_per_90`, `saves_per_90`, `clean_sheets_per_90` (all from bootstrap element directly)
- All advice modules (`comparison`, `transfer_advisor`, captain ranking, `differential_picks`)
  switch to `adjusted_captain_score` for ranking and thresholds
- `captain_score` (canonical) is preserved and still exposed
- `tier` classification uses `adjusted_captain_score`

**Schema pre-work (completed 2026-03-23)**

`fpl-data-core` schemas updated in both `python/schemas.py` and `fpl_data_core/schemas.py`:
- `CUMULATIVE_COLS` gains: `defensive_contribution`, `clearances_blocks_interceptions`,
  `tackles`, `recoveries`
- `PER_90_COLS` added as a new list covering all FPL pre-computed per-90 fields

**Test surface**

- Unit tests for `position_bias()` per position: GKP bias > 0 with high saves_per_90;
  MID bias = 0; DEF bias > 0 when cs_per_90 is high; FWD bias = small positive
- Regression: existing STANDARD_BOOTSTRAP MID/FWD scores must not change (bias=0 for MID;
  FWD bias is additive only)
- Corpus scenarios: GKP captain query (Raya) — adjusted score higher than canonical;
  DEF captain query (Alexander-Arnold) — adjusted score reflects cs history
- Comparison: "Pickford vs Raya" produces a sensible margin; result auditable via
  `score_inputs.saves_per_90` and `score_inputs.clean_sheets_per_90`

**Validation gate:** new corpus scenarios for GKP and DEF advice show correct bias
direction; all 31 existing scenarios remain PASS.

---

### 8b — Home/Away Fixture Factor

**Problem**

The FDR map assigns one difficulty rating per team per gameweek, but home teams win
roughly 45% of Premier League matches versus 28% away.  A home FDR-3 fixture is
meaningfully easier than an away FDR-3 fixture.  The current schema does not distinguish
them.

**Proposal**

Extend the bootstrap `fixture_difficulty_map` to include `is_home` per fixture.

```python
# current
fixture_difficulty_map: dict[int, int]  # team_id → fdr

# V1.5
fixture_difficulty_map: dict[int, dict]  # team_id → {fdr, is_home}
```

In `_derive_scoring_inputs()`, apply a half-step adjustment:

```
effective_fdr = fdr - 0.5 if is_home else fdr + 0.5
effective_fdr = clamp(effective_fdr, 1, 5)
```

The canonical formula receives `effective_fdr` as `fixture_difficulty`, so no formula
change is needed.  `score_inputs` gains an `is_home: bool` field.

**Outputs changed**

- `score_inputs` gains `is_home`
- `effective_fdr` replaces raw FDR in the formula; raw `fdr` stays visible for auditability
- Renderer for fixture run and comparison can surface `(H)` / `(A)` labels

**Fixture run integration**

`player_fixture_run` already retrieves upcoming fixture data.  In 8b, each
`FixtureEntry` gains `is_home: bool` and the rendered text annotates home/away:

```
GW29: Arsenal (H) — FDR 2  →  GW29: Arsenal (H) — FDR 1.5 effective
```

**Test surface**

- Unit tests for `effective_fdr` clamping at both ends (home FDR-1 stays 1; away FDR-5 stays 5)
- Regression: existing scoring tests must only change by the delta attributable to
  home/away if fixtures in STANDARD_BOOTSTRAP are marked
- New corpus scenario: same player, home vs away variant — confirm score differs
- Parity: CLI, HTTP, session all surface `is_home` in `score_inputs`

---

### 8c — DGW/BGW Detection and Free Hit Unblock

**Problem**

`chip_advisor.py` comment explicitly notes:
> "free_hit: Requires blank or double gameweek detection, which is not yet available"

Every free hit query returns `recommendation="missing_context"`.  This is the most-asked
chip in FPL at the business end of the season.

**Proposal**

Add a `gameweek_type` detection layer in the bootstrap assembly pipeline.

```python
# New field in bootstrap
"current_gameweek_info": {
    "gw": 28,
    "type": "normal" | "double" | "blank",
    "affected_teams": ["ARS", "MCI"],  # teams with extra/missing fixtures
}
```

The detection logic uses the `team_fixtures` data already in the bootstrap (introduced
for `player_fixture_run` in Phase 7h):

- **DGW**: a team plays more than once in the current GW window
- **BGW**: fewer teams than normal have fixtures in the current GW

`chip_advisor._advise_free_hit()` is updated:

```
DGW detected (≥6 teams affected):  conditions_favorable
DGW partial  (3-5 teams):          conditions_marginal
BGW detected:                      conditions_marginal (save for next DGW)
Normal GW:                         conditions_unfavorable
```

`ChipAdviceMeta.signal_label` gains a new value for DGW/BGW context.

**Test surface**

- Unit tests for DGW/BGW classification at boundary conditions (5 vs 6 teams)
- New conversation fixtures: `DGW_BOOTSTRAP` and `BGW_BOOTSTRAP` added to
  `conversation_fixtures.py`
- New corpus scenarios: `chip_advice_fh_dgw`, `chip_advice_fh_bgw`,
  `chip_advice_fh_normal` — confirm recommendation vocabulary per gameweek type
- Regression: TC, WC, BB scenarios unchanged; free hit changes from `missing_context`
  in all three new scenarios

**Validation gate:** 3 new corpus scenarios all PASS; existing 31 remain PASS.

---

### 8d — Follow-Up Resolution Completeness

**Problem**

Two intents added in V1 — `player_fixture_run` (Phase 7h) and `differential_picks`
(Phase 7g) — do not support conversational follow-ups.  A session like:

```
> Haaland fixtures
  [fixture run for Haaland]
> What about Salah?
  [expected: fixture run for Salah]
  [actual: general reference resolution, likely fails or misclassifies]
```

The deferred note in `project_fpl_platform.md` confirms this explicitly.

**Proposal**

**8d-i: Fixture run follow-up**

Mirror the comparison and transfer follow-up pattern:

- `ConversationState` gains `last_fixture_run_player: str | None`
- `resolve_fixture_run_followup()` in `conversation_state.py` detects:
  - "What about {player}?"
  - "How about {player}?"
  - "{player}?" (bare name after a fixture run)
- Rewrites as: `"{player} fixtures"`
- `resolver_source` gains 7th value: `"fixture_run_followup"`
- `ConversationState.last_fixture_run_player` is set on OK fixture run turns,
  cleared on any other OK turn
- `SessionInfoResponse.last_fixture_run_player` added

**8d-ii: Differential follow-up**

Differential picks return a list, not a single player.  Follow-up semantics differ:

- `resolve_differential_followup()` detects "what about {player}?" patterns
- Rewrites as: `"should I captain {player}?"` (captain score for that player)
- This intentionally routes to captain intent, not another differential — asking
  about a specific differential pick is usually asking "how good is this pick?"
- `ConversationState.last_differential_result: bool` — set True on OK differential turns
- `resolver_source` gains 8th value: `"differential_followup"`

**Test surface**

- Unit tests for both follow-up detectors across the standard pattern families
- New session flow examples in `session_examples.py`:
  - `fixture_run_followup` flow: two fixture run queries linked by follow-up
  - `differential_followup` flow: differential pick followed by player inquiry
- New corpus scenarios (#32, #33): one per follow-up type, session surface only
- Resolver source parity: both new sources appear in `ResolverDebug` and
  `SessionInfoResponse.last_resolver_source`

**Validation gate:** 2 new corpus scenarios PASS; all 34 pass.

---

### 8e — Squad Context Layer

**Problem**

Every transfer and chip recommendation ignores whether the user has any money to spend
or chips left to use.  "Transfer in Salah" is useless if the user has £0 in the bank.
"Use your triple captain" is useless if they used it in GW1.

**Proposal**

Add an optional `squad_context` parameter to the primary API surface.

```python
# HTTP POST /ask
{
  "question": "should I sell Saka for Salah?",
  "squad_context": {
    "itb": 1.5,           # in the bank (£m)
    "chips_remaining": ["bench_boost", "free_hit"],  # available chips
    "free_transfers": 2   # free transfers this gameweek
  }
}
```

`squad_context` is optional.  When absent, all existing advice is unchanged.

When present:

- `transfer_advisor`: If `price_delta` exceeds `itb`, the recommendation is overridden
  to `"budget_constraint"` (new vocabulary value).  `TransferMeta` gains
  `budget_constraint: bool`.
- `chip_advisor`: If the requested chip is not in `chips_remaining`, the recommendation
  is overridden to `"chip_unavailable"` (new vocabulary value).  `ChipAdviceMeta` gains
  `chip_unavailable: bool`.
- `transfer_advisor`: If `free_transfers` is 1 and the score delta is `marginal_transfer_in`,
  a `hit_warning: bool` flag is added (taking a hit for a marginal transfer is rarely
  recommended).

**Scope boundary**

- No squad composition (no bench players, no team lineup)
- No net transfer cost (points hit calculation)
- `squad_context` is not persisted in `ConversationState` for V1.5; callers pass it
  per-turn if relevant

**Contract additions**

- `AskRequest` gains `squad_context: dict | None` (optional)
- `fpl_cli.py run()` gains `--itb`, `--chips`, `--free-transfers` flags
- `TransferMeta` gains `budget_constraint: bool` (default False)
- `ChipAdviceMeta` gains `chip_unavailable: bool` (default False)
- `FINAL_RESPONSE_CONTRACT.md` updated

**Test surface**

- Unit tests for budget constraint override at price_delta boundary
- Unit tests for chip_unavailable override for each chip
- Unit tests for hit_warning when marginal delta + free_transfers=1
- New corpus scenarios: `transfer_budget_constraint`, `chip_unavailable_tc`
- Examples: `squad_context` CLI, HTTP, session examples added
- Parity: squad_context flows confirmed consistent across all three surfaces

**Validation gate:** 2 new corpus scenarios PASS; all 36 pass.

---

### 8f — Validation Corpus V3 and Gate

**Purpose**

Integrate all new scenarios from 8a–8e into a cohesive, human-readable validation
corpus that serves as the UAT gate for V1.5.

**New corpus scenarios**

| # | ID | Family | New in slice |
|---|---|---|---|
| 32 | gkp_captain_score | position_scoring | 8a |
| 33 | def_captain_score | position_scoring | 8a |
| 34 | home_away_scoring | fixture_factor | 8b |
| 35 | chip_advice_fh_dgw | dgw_detection | 8c |
| 36 | chip_advice_fh_bgw | dgw_detection | 8c |
| 37 | chip_advice_fh_normal | dgw_detection | 8c |
| 38 | fixture_run_followup | followup | 8d-i |
| 39 | differential_followup | followup | 8d-ii |
| 40 | transfer_budget_constraint | squad_context | 8e |
| 41 | chip_unavailable_tc | squad_context | 8e |

**Scope**

- `ValidationScenario` gains `expect_position_bias: bool | None`,
  `expect_home_away: bool | None`, `expect_dgw_type: str | None`,
  `expect_squad_context_override: bool | None`
- `_check_scenario_result()` validates new expect fields
- `write_markdown_artifact()` renders new columns in the human-readable report
- Full re-run of all 41 scenarios; gate is 41/41 PASS

**Regression standard**

All 31 existing V1 corpus scenarios must remain PASS with no assertion changes
except where scoring values change due to 8a/8b (in which case the fixture values
in STANDARD_BOOTSTRAP must be annotated with home/away to show the delta is expected).

---

## Explicitly Deferred to V2

These are not V1.5 blockers.  They are the natural next wave once V1.5 is approved
and the UI work begins.

| Item | Why deferred |
|---|---|
| Multi-player comparison (3+) | Requires UI — list comparison doesn't render well as text |
| Multi-transfer planning | Needs squad composition as input (deferred from squad context scope) |
| LLM-assisted transfer follow-up | Deterministic-only is sufficient for V1.5; LLM variant adds complexity without UAT value |
| Wildcard squad planner | Out of scope without full squad context |
| Session persistence (multi-worker) | Infrastructure; not a feature; belongs in V2 backend work |
| Authentication / rate limiting | Belongs in V2 backend work |
| Frontend / widget output | V3 design; structured output already exists in FinalResponse |
| Open-ended football reasoning | LLMs must remain subordinate to deterministic backend per core invariant |

---

## Recommended Sequencing

```
8a → 8b → 8c → 8d → 8e → 8f
```

Rationale:

1. `8a` first — position bias is foundational; every subsequent slice that surfaces
   a score number should show the corrected value.
2. `8b` immediately after — home/away feeds into the same scoring path; both 8a and 8b
   touch `_derive_scoring_inputs()`; doing them together reduces merge surface.
3. `8c` — DGW/BGW detection is independent of scoring but depends on bootstrap data
   structure being stable.
4. `8d` — follow-up resolution is purely conversation state; no scoring dependency.
5. `8e` — squad context is an input layer; can safely layer on top of all previous changes.
6. `8f` — gate only after all slices land.

---

## Working Principles (Carried Forward From V1)

1. LLM remains subordinate to deterministic backend.
2. `respond()` never raises; `final_text` always non-empty.
3. Additive contract changes only — no field removal without a deprecation wave.
4. New metadata must be bounded, explicit, and auditable.
5. All three surfaces (CLI, stateless HTTP, session HTTP) must remain contract-consistent.
6. The canonical `captain_score` formula is not modified — only extended.

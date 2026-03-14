# fpl-platform · Claude Code Handoff

**Prepared:** 2026-03-14
**Handing off at:** Phase 3d complete
**Primary package:** `fpl-grounded-assistant`

---

## What This Project Is

A Python platform that wraps FPL (Fantasy Premier League) data and logic
into a grounded assistant.  The assistant accepts a natural-language user
message and returns a structured `FinalResponse` — deterministic routing and
scoring, with an optional LLM presentation layer on top.

The core design principle: **the LLM is subordinate to the deterministic
backend**.  Routing, scoring, outcome classification, and safety fallbacks are
all deterministic.  The LLM only phrases the grounded result; it never alters
backend semantics.

---

## Repository Layout

```
fpl-platform/
├── HANDOFF.md                  ← this file
├── PACKAGE_STATUS.md           ← ground truth for all package status + history
├── packages/
│   ├── fpl-captain-engine/     ← scoring formula (TypeScript + Python)
│   ├── fpl-data-core/          ← season registry, analytics, schemas
│   ├── fpl-api-client/         ← FPL bootstrap + fixtures HTTP client
│   ├── fpl-player-registry/    ← player identity + nickname resolution
│   ├── fpl-query-tools/        ← player lookup composition layer
│   ├── fpl-tool-contract/      ← 5 structured tools (resolve, summary, gw, captain, rank)
│   ├── fpl-tool-runner/        ← ToolSpec/ToolRegistry, in-process dispatch
│   ├── fpl-pipeline/           ← context assembly (bootstrap + fixtures + FDR in one call)
│   └── fpl-grounded-assistant/ ← PRIMARY PACKAGE — full end-to-end stack
└── Activity Tracker/
    └── memory.json             ← phase progress tracker
```

---

## fpl-grounded-assistant Stack (innermost → outermost)

```
respond(user_message, bootstrap, ...)     → FinalResponse    [Phase 3c/3d]
  └── ask_llm_safe(...)                   → (LLMResponse, ReviewResult)  [Phase 3b]
        └── ask_llm(...)                  → LLMResponse       [Phase 3a]
              └── adapt(...)              → AdapterResponse   [Phase 2m]
                    └── dispatch(...)     → DispatchResult    [Phase 2k/2l]
                          └── ask(...)   → dict               [Phase 1h]
                                └── run_tool(name, args, bootstrap)      [Phase 1g]
                                      └── tool_contract layer            [Phase 1f]
```

**Key contract documents:**
- `packages/fpl-grounded-assistant/FINAL_RESPONSE_CONTRACT.md` — stable
  caller-facing surface (`respond()` / `FinalResponse`) — read this first
- `packages/fpl-grounded-assistant/CONTRACT.md` — lower-level adapter
  contract (`adapt()` / `AdapterResponse`)

---

## How to Run All Tests

Every phase has a standalone test runner at the package root.  Run from
`packages/fpl-grounded-assistant/` with:

```bash
cd packages/fpl-grounded-assistant
PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\
../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\
../fpl-api-client:../fpl-pipeline:. python run_phase3d_tests.py
```

Replace `run_phase3d_tests.py` with any test file.  All test files are
self-contained (no pytest required, no network, no LLM calls):

| File | Phase | Count |
|------|-------|-------|
| `run_phase1h_tests.py` | 1h — harness | 47 |
| `run_phase2a_tests.py` | 2a — captain score tool | 78 |
| `run_phase2b_tests.py` | 2b — rank candidates | 112 |
| `run_phase2c_tests.py` | 2c — auto-derivation | 133 |
| `run_phase2d_tests.py` | 2d — fixture difficulty | 132 |
| `run_phase2f_tests.py` | 2f — assembled context | 106 |
| `run_phase2g_tests.py` | 2g — tiers | 160 |
| `run_phase2h_tests.py` | 2h — role signals | 165 |
| `run_phase2i_tests.py` | 2i — renderer | 172 |
| `run_phase2j_tests.py` | 2j — explainer | 184 |
| `run_phase2k_tests.py` | 2k — dispatcher | 132 |
| `run_phase2l_tests.py` | 2l — outcomes | 211 |
| `run_phase2m_tests.py` | 2m — adapter | 118 |
| `run_phase2n_tests.py` | 2n — contract fixtures | 261 |
| `run_phase3a_tests.py` | 3a — LLM layer | 269 |
| `run_phase3b_tests.py` | 3b — LLM review | 355 |
| `run_phase3c_tests.py` | 3c — final response | 328 |
| `run_phase3d_tests.py` | 3d — contract hardening | 248 |

---

## Public API — What to Import

```python
from fpl_grounded_assistant import (
    # Primary entrypoint (Phase 3c)
    respond,
    FinalResponse,
    FinalResponseDebug,
    FINAL_TEXT_POLICY,

    # Adapter layer (Phase 2m)
    adapt,
    AdapterResponse,

    # Dispatcher (Phase 2k/2l)
    dispatch,
    DispatchResult,
    OUTCOME_OK, OUTCOME_NOT_FOUND, OUTCOME_AMBIGUOUS,
    OUTCOME_MISSING_ARGUMENTS, OUTCOME_ERROR, OUTCOME_UNSUPPORTED_INTENT,
    INTENT_CAPTAIN_SCORE, INTENT_RANK_CANDIDATES, INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_SUMMARY, INTENT_PLAYER_RESOLVE, INTENT_UNSUPPORTED,
    SUPPORTED_INTENTS, INTENT_MANIFEST,

    # Contract fixtures (Phase 2n)
    STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP,
    FIXTURE_DEFINITIONS, run_all,

    # Final response fixtures (Phase 3d)
    FINAL_RESPONSE_FIXTURE_DEFINITIONS, run_all_final_response,
    FinalResponseFixture,
)
```

**Simplest working call** (deterministic, no API key needed):
```python
from fpl_grounded_assistant import respond, STANDARD_BOOTSTRAP

r = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
print(r.final_text)   # deterministic captain score answer
print(r.outcome)      # "ok"
print(r.llm_used)     # False (no API key → deterministic fallback)
```

**With LLM** (requires `ANTHROPIC_API_KEY` env var):
```python
r = respond("should I captain Haaland", STANDARD_BOOTSTRAP)
# llm_used=True if API call succeeded and passed review; False if any failure
```

---

## Key Invariants — Never Break These

1. `respond()` never raises — every failure case returns a valid `FinalResponse`
2. `final_text` is always non-empty
3. `supported == (outcome != OUTCOME_UNSUPPORTED_INTENT)` — always
4. `llm_used=True` implies `review_passed=True` — always
5. `not llm_used → final_text == response_text` (debug bundle shows this)
6. The LLM does **not** affect `outcome`, `supported`, `intent`, or
   `dispatch_result.raw_output` — routing and scoring are deterministic
7. The review layer (`llm_review.py`) is the only place violation logic lives
   — do not spread it into other modules
8. `FinalResponse` field shape is a **stable contract** — treat renames/type
   changes as breaking changes and document them with a phase label

---

## Design Decisions to Preserve

### LLM subordination
The LLM is presented the grounded result and asked to rephrase it.  It is not
asked to reason about the answer or make decisions.  `build_user_prompt()`
always includes the outcome, intent, and grounded `response_text`.

### Deterministic backend as truth source
`response_text` (from `adapt()` → `dispatch()` → `ask()`) is always the
safety net.  Any LLM failure — network error, review violation, empty response,
missing API key — falls back to `response_text` unchanged.

### Review layer is deterministic
All 4 violation checks in `llm_review.py` are regex/string operations.  There
is no LLM-based review.  Do not add fuzzy or model-based review without a new
approved phase.

### ok outcomes exempt from overconfidence/numeric checks
When `outcome=ok`, the grounded backend has authoritative data (score, player
name, gameweek number).  Moderate confidence in the LLM presentation is
acceptable.  Only non-ok outcomes (not_found, ambiguous, missing_arguments,
error, unsupported_intent) are reviewed for overconfidence and invented numbers.

---

## Activity Tracker

Progress is tracked in:
```
Activity Tracker/memory.json
```

The fpl-platform track is at `tracks[].id == "fpl-platform"`.
Each phase has an item with `validation_state: "passed"` once tests pass.

Rules for updates are in:
```
Activity Tracker/tracker_rules.md
```

The CLI updater is at:
```
Activity Tracker/update_memory.py
```

**Current metrics (Phase 3d):**
- `total_items`: 18
- `validated_items`: 13
- `in_progress_items`: 0

---

## Deferred Work — Explicitly Out of Scope

These were intentionally deferred in every phase and should be introduced as
new approved slices:

| Capability | Last deferred in |
|------------|-----------------|
| Multi-turn conversation memory | Phase 3d |
| Pronoun resolution ("What about his form?") | Phase 3d |
| Combined intents | Phase 3d |
| UI integration | Phase 3d |
| Streaming responses | Phase 3d |
| Model-based (non-deterministic) review | Phase 3d |
| LLM-based intent classification | Phase 3d |
| Live FPL API calls in test fixtures | All phases |

---

## Suggested Next Phases

These were recorded as "next step" in the phase history.  None are committed —
they require explicit approval and scoping:

**Phase 4a — Live API integration test**
Wire `assemble_captain_context()` (from `fpl-pipeline`) through `respond()`
and verify the full stack with live FPL bootstrap data.  Proves the platform
works end-to-end before any UI work begins.

**Phase 4b — HTTP endpoint**
Thin FastAPI (or similar) wrapper around `respond()`.  The `FinalResponse`
dataclass maps cleanly to a JSON response body.  Keep the business logic
untouched in the grounded-assistant package.

**Phase 4c — Multi-turn state**
Introduce a `ConversationState` object that tracks player context across turns
for pronoun resolution.  Design as a separate module — do not modify
`dispatcher.py` or `adapter.py` in this slice.

**Phase 4d — LLM-based intent classification (optional)**
Replace or augment the deterministic keyword router with an LLM classification
step.  The existing `_OUTCOME_INSTRUCTION` and `INTENT_MANIFEST` provide the
vocabulary.  The deterministic router should remain as a fallback.

---

## Bootstrap Shape Reference

The minimum valid bootstrap for testing:

```python
bootstrap = {
    "elements": [          # list of player dicts
        {
            "id": 1, "first_name": "Erling", "second_name": "Haaland",
            "web_name": "Haaland", "team": 13, "element_type": 4,
            "status": "a", "now_cost": 145, "selected_by_percent": "52.3",
            "form": "8.0", "expected_goal_involvements": "1.70",
            "minutes": 1800, "penalties_order": 1,
            "direct_freekicks_order": None,
            "corners_and_indirect_freekicks_order": None,
        },
        ...
    ],
    "teams": [             # list of team dicts
        {"id": 13, "name": "Manchester City", "short_name": "MCI",
         "code": 43, "strength": 5},
        ...
    ],
    "events": [            # list of gameweek dicts
        {"id": 28, "is_current": True, "is_next": False, "finished": False},
        ...
    ],
    "element_types": [
        {"id": 4, "singular_name_short": "FWD"},
        ...
    ],
    "fixture_difficulty_map": {13: 4, 14: 4, ...},  # team_id → FDR int
}
```

Import the pre-built test bootstrap:
```python
from fpl_grounded_assistant import STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP
```

---

## Files Added This Session (Phases 3a–3d)

```
packages/fpl-grounded-assistant/
├── fpl_grounded_assistant/
│   ├── llm_layer.py              # Phase 3a — LLM integration (ask_llm, build_user_prompt)
│   ├── llm_review.py             # Phase 3b — deterministic violation checks
│   ├── final_response.py         # Phase 3c — FinalResponse, respond()
│   └── final_response_fixtures.py # Phase 3d — FinalResponseFixture, 6 scenarios
├── FINAL_RESPONSE_CONTRACT.md    # Phase 3d — stable caller-facing contract doc
├── run_phase3a_tests.py          # 269/269 PASS
├── run_phase3b_tests.py          # 355/355 PASS
├── run_phase3c_tests.py          # 328/328 PASS
└── run_phase3d_tests.py          # 248/248 PASS
```

---

## Quick Smoke Test

To verify the environment is set up correctly before any new work:

```bash
cd packages/fpl-grounded-assistant
PYTHONPATH=../fpl-tool-runner:../fpl-player-registry:../fpl-captain-engine:\
../fpl-data-core:../fpl-tool-contract:../fpl-query-tools:\
../fpl-api-client:../fpl-pipeline:. python -c "
from fpl_grounded_assistant import respond, STANDARD_BOOTSTRAP, FINAL_RESPONSE_FIXTURE_DEFINITIONS, run_all_final_response, AMBIGUOUS_BOOTSTRAP
r = respond('should I captain Haaland', STANDARD_BOOTSTRAP)
assert r.final_text, 'final_text empty'
assert r.outcome == 'ok', f'expected ok, got {r.outcome}'
results = run_all_final_response(STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP)
assert len(results) == 6, f'expected 6 fixtures, got {len(results)}'
all_pass = all(r[1].outcome == r[0].expected_outcome for r in results)
assert all_pass, 'fixture outcomes mismatch'
print('Smoke test PASS — 6/6 fixtures correct')
"
```



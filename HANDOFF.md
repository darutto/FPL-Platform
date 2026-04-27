# fpl-platform · Claude Code Handoff

**Prepared:** 2026-03-14
**Last updated:** 2026-04-01 (V2 Phase 1f complete)
**Handing off at:** V2 Phase 1f complete — HTTP contract fixtures; backend ready for UI consumption
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
ConversationSession.respond(question, bootstrap, ...)  → FinalResponse  [Phase 4e/4f]
  ├── resolve_reference(question, state, client=...)  → ReferenceResolution  [Phase 4f]
  │     ├── resolve_reference_llm(...)   ← LLM structured JSON extraction (Phase 4f)
  │     └── resolve_pronouns(...)        ← Phase 4e regex fallback
  └── respond(rewritten_question, bootstrap, ...)     → FinalResponse    [Phase 3c/3d]
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
| `run_phase5b_tests.py` | 5b — comparison contract normalization | 61 |
| `run_phase5a_tests.py` | 5a — two-player captain comparison | 98 |
| `run_phase4j_tests.py` | 4j — session examples and docs | 86 |
| `run_phase4i_tests.py` | 4i — session hygiene | 149 |
| `run_phase4h_tests.py` | 4h — HTTP session exposure | 184 |
| `run_phase4g_tests.py` | 4g — resolver auditability | 161 |
| `run_phase4f_tests.py` | 4f — LLM reference resolver | 151 |
| `run_phase4e_tests.py` | 4e — multi-turn state | 120 |
| `run_phase4d_tests.py` | 4d — integration examples | 115 |
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
    ResolverDebug,   # Phase 4g: resolver debug bundle
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

    # Multi-turn state (Phase 4e)
    ConversationSession,
    ConversationState,
    resolve_pronouns,

    # Reference resolver (Phase 4f)
    ReferenceResolution,
    resolve_reference,
    build_resolver_prompt,
    RESOLVER_SYSTEM_PROMPT,
)
```

**Multi-turn usage** (Phase 4e — English pronoun follow-ups, no LLM):
```python
from fpl_grounded_assistant import ConversationSession, STANDARD_BOOTSTRAP

session = ConversationSession()
r1 = session.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
r2 = session.respond("should I captain him?", STANDARD_BOOTSTRAP)  # resolves to Haaland
session.clear()  # reset for next conversation
```

**Multi-turn with LLM resolver** (Phase 4f — Spanish + English follow-ups):
```python
import anthropic
from fpl_grounded_assistant import ConversationSession, STANDARD_BOOTSTRAP

client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY
session = ConversationSession()
r1 = session.respond("should I captain Haaland", STANDARD_BOOTSTRAP)
r2 = session.respond("¿Y como capitán?", STANDARD_BOOTSTRAP,
                     resolver_client=client)  # Spanish ellipsis resolved to Haaland
r3 = session.respond("¿Y él?", STANDARD_BOOTSTRAP,
                     resolver_client=client)  # Spanish pronoun resolved
session.clear()
```

**Multi-turn session runner** (Phase 4g — batch questions with resolver debug):
```python
from fpl_cli import run_session
from fpl_grounded_assistant import STANDARD_BOOTSTRAP

results = run_session(
    ["should I captain Haaland", "should I captain him?"],
    STANDARD_BOOTSTRAP,
    debug=True,
)
# results[1]["rewritten_question"]  # "should I captain Haaland?"
# results[1]["debug"]["resolver"]["resolver_source"]  # "fallback_regex"
# results[1]["debug"]["resolver"]["fallback_reason"]  # "llm_unavailable"
```

**Inspecting a resolution** (Phase 4f):
```python
from fpl_grounded_assistant import resolve_reference, ConversationState

state = ConversationState()
state.last_player_query = "Haaland"
resolution = resolve_reference("¿Y como capitán?", state, client=client)
# ReferenceResolution(
#   resolved_query="Haaland", intent_guess="captain_score",
#   reference_source="ellipsis", confidence=0.85, language="es",
#   rewritten_question="should I captain Haaland"
# )
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

## V2 Backend Status (2026-04-01)

V2 Phase 1 is **complete**. The backend contract is stable and ready for UI consumption.

| Phase | Label | Status |
|-------|-------|--------|
| V2 Phase 1a | Container — Dockerfile, .dockerignore, requirements.txt | Complete |
| V2 Phase 1b | Classifier startup — `_try_init_classifier_from_env()` in lifespan | Complete |
| V2 Phase 1c | `intent_hint` implementation — full stack threading, 69/69 tests | Complete |
| V2 Phase 1d | `intent_hint` doc parity — contract docs + examples, 22/22 tests | Complete |
| V2 Phase 1e | Architecture doc parity — `orchestrator-instructions.md` + `HANDOFF.md`, 44/44 checks | Complete |
| V2 Phase 1f | HTTP contract fixtures — `http_contract_fixtures.json` + verifier, 126/126 pass | Complete |

`http_contract_fixtures.json` is the canonical machine-readable HTTP contract for downstream consumers.
It covers `POST /ask` and `POST /session/{id}/ask` request shapes, response invariants annotated with
`stable` / `conditional` / `debug_only` stability levels, and all `intent_hint` contract invariants in
one self-contained artifact. The backend is ready for UI slash-command consumption.

### `intent_hint` invariants — do not regress

These invariants are stable contract commitments. Backend behavior changes that violate any of them require an explicit approved phase.

1. **Deterministic router wins** — if `route(question)` succeeds, `intent_hint` is completely ignored
2. **Allowlisted only** — valid values: `captain_score`, `rank_candidates`, `compare_players`, `transfer_advice`, `chip_advice`, `player_fixture_run`, `differential_picks`
3. **Safe ignore** — invalid or unrecognised hints are silently ignored; never raise, never block
4. **Pre-classifier** — fires before the LLM classifier fallback, without any LLM call
5. **Provider-neutral** — no Anthropic or provider-specific identity in the public contract
6. **Per-turn in sessions** — hint is not stored in session state; does not affect subsequent turns
7. **`classification_source` audit field** — `"intent_hint"` when hint fires; `None` for deterministic; `"llm_classifier"` for LLM fallback

### Next consumer

The primary downstream consumer of `intent_hint` is the UI slash-command layer (`fpl-ui`). That work is a separate product concern and does not modify the backend.

---

## Deferred Work — Explicitly Out of Scope

These were intentionally deferred in every phase and should be introduced as
new approved slices:

| Capability | Last deferred in |
|------------|-----------------|
| Multi-turn conversation memory (persistence beyond session) | Phase 4e |
| Trailing-clause pronoun handling ("who is better, him or Salah?") | Phase 4f |
| Combined intents beyond " and "-split | Phase 3d |
| UI slash-command integration (consumer of `intent_hint`) | V2 Phase 1f — backend + contract fixtures complete, UI deferred |
| Streaming responses | Phase 3d |
| Model-based (non-deterministic) review | Phase 3d |
| Live FPL API calls in test fixtures | All phases |
| DGW/BGW detection for `free_hit` | Phase 7b |

Note: LLM-based intent classification is **implemented** (Phase 4k — fires on deterministic router miss, confidence-gated, allowlisted to supported intents). `intent_hint` pre-classifier routing bias is also **implemented and documented** (V2 Phase 1c/1d). Neither is deferred.

---

## Suggested Next Phases

These were recorded as "next step" in the phase history.  None are committed —
they require explicit approval and scoping:

**Phase 4a — Live API integration test** *(complete)*
Wired `assemble_captain_context()` through `respond()` with live FPL bootstrap.
82/82 PASS.  Files: `run_phase4a_tests.py`.

**Phase 4b — CLI entrypoint** *(complete)*
`fpl_cli.py`: `run(question, bootstrap, *, debug) → (exit_code, str)` + `main()`.
Exit 0 = supported intent answered; exit 1 = unsupported intent.
119/119 PASS.  Files: `fpl_cli.py`, `run_phase4b_tests.py`.

**Phase 4c — HTTP endpoint** *(complete)*
`fpl_server.py`: FastAPI app with `POST /ask` and `GET /health`.
Request: `{"question": str, "debug": bool}`.  Response: FinalResponse-compatible JSON.
HTTP 200 for all FinalResponse outcomes (inspect `supported`/`outcome` in body).
HTTP 422 for malformed requests.  Bootstrap injected at startup via lifespan.
148/148 PASS.  Files: `fpl_server.py`, `run_phase4c_tests.py`.

**Phase 4d — Integration examples and client fixtures** *(complete)*
`examples/cli_examples.py`: executable CLI examples for all 5 canonical scenarios
(supported_ok, supported_ambiguous, supported_not_found, supported_missing_arguments,
unsupported_intent) using `run()` + fixture bootstraps.  Runnable directly.
`examples/http_examples.py`: executable HTTP examples for the same 5 scenarios plus
edge cases (malformed_request → 422, service_not_ready → 503) using TestClient.
Runnable directly.  Both importable by test runners.
115/115 PASS.  Files: `examples/cli_examples.py`, `examples/http_examples.py`,
`run_phase4d_tests.py`.

**Phase 4e — Multi-turn conversation state** *(complete)*
`conversation_state.py`: `ConversationState` (dataclass), `ConversationSession`
(stateful wrapper around `respond()`), `resolve_pronouns` (pure helper).
State tracks `last_player_query` across turns; cleared on `session.clear()`.
Pronoun follow-ups ("should I captain him?", "tell me about him") resolved via
word-boundary-safe regex substitution before routing.  Stateless `respond()` unchanged.
120/120 PASS.  Files: `fpl_grounded_assistant/conversation_state.py`, `run_phase4e_tests.py`.

**Phase 4f — LLM-assisted reference resolution** *(complete)*
`reference_resolver.py`: `ReferenceResolution` (frozen dataclass), `resolve_reference()`,
`resolve_reference_llm()`, `build_resolver_prompt()`.
LLM extracts structured JSON: `resolved_query`, `intent_guess`, `reference_source`,
`confidence`, `language` — never answers FPL questions.  Falls back to Phase 4e
deterministic pronoun resolution when LLM is unavailable or confidence < 0.5.
`ConversationState.history` added (bounded ≤ 3 turns) for context passing.
`ConversationSession.respond()` accepts `resolver_client` kwarg.
151/151 PASS.  Files: `fpl_grounded_assistant/reference_resolver.py`, `run_phase4f_tests.py`.

**Phase 4g — Resolver auditability and controlled session exposure** *(complete)*
`ReferenceResolution.fallback_reason` added (`"llm_unavailable"` / `"low_confidence"` / `None`).
`ResolverDebug` frozen dataclass added to `final_response.py`; `FinalResponseDebug.resolver`
field added (default `None`).  `ConversationSession.respond()` builds and passes
`_resolver_debug` when `include_debug=True`.  `run_session()` added to `fpl_cli.py`
for multi-turn CLI sessions.  161/161 PASS.
Files: `reference_resolver.py`, `final_response.py`, `conversation_state.py`,
`fpl_grounded_assistant/__init__.py`, `fpl_cli.py`, `run_phase4g_tests.py`.

**Phase 4h — HTTP session exposure** *(complete)*
`fpl_server.py`: three new endpoints for in-memory session lifecycle.
`POST /session` — create session (returns `{"session_id": "<uuid4>"}`).
`POST /session/{session_id}/ask` — multi-turn question within a session; pronoun/reference
follow-ups resolved via `ConversationSession`.  Response: `SessionAskResponse` (extends
`AskResponse` shape with `session_id` and `rewritten_question`).
`DELETE /session/{session_id}` — clear and remove a session.
Sessions are in-memory only; stateless `POST /ask` unchanged.  Resolver metadata
in debug bundle only.  184/184 PASS.  Files: `fpl_server.py`, `run_phase4h_tests.py`.

**Phase 4i — Session hygiene and lifecycle hardening** *(complete)*
`_SessionEntry` dataclass added (`session`, `created_at`, `last_used_at`).
`_SESSION_TTL_SECONDS` (default 1800s) and `_SESSION_MAX_COUNT` (default 100) config.
`_prune_expired_sessions()` — lazy cleanup called on `POST /session`.
Lazy TTL check on `session_ask()` and `get_session()` — expired sessions return 404.
`last_used_at` updated on every ask; `GET /session/{id}` not count as activity.
`GET /session/{session_id}` — new inspection endpoint: `created_at`, `last_used_at`, `turn_count`.
`CreateSessionResponse` extended with `created_at` and `expires_after_seconds`.
149/149 PASS.  Files: `fpl_server.py`, `run_phase4i_tests.py`.

**Phase 4j — Session interaction examples and operational docs** *(complete)*
`examples/session_examples.py`: `SESSION_FLOWS` (full lifecycle, pronoun follow-up),
`SESSION_EDGE_CASES` (not_found, clear_missing, ttl_expiry, cap_reached),
`run_session_flow()`, `run_edge_case()`, `make_session_client()`.
`SESSION_CONTRACT.md`: operational doc covering TTL, max-count, in-memory nature,
single-instance assumption, endpoint reference, and deferred capabilities.
86/86 PASS.  Files: `examples/session_examples.py`, `SESSION_CONTRACT.md`, `run_phase4j_tests.py`.

**Phase 4k — LLM intent classification (optional)**
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

## Files Added (Phases 3a–4e)

```
packages/fpl-grounded-assistant/
├── fpl_grounded_assistant/
│   ├── llm_layer.py              # Phase 3a — LLM integration (ask_llm, build_user_prompt)
│   ├── llm_review.py             # Phase 3b — deterministic violation checks
│   ├── final_response.py         # Phase 3c — FinalResponse, respond()
│   ├── final_response_fixtures.py # Phase 3d — FinalResponseFixture, 6 scenarios
│   ├── conversation_state.py     # Phase 4e/4f — ConversationState (+ history), ConversationSession, resolve_pronouns
│   └── reference_resolver.py     # Phase 4f — ReferenceResolution, resolve_reference, build_resolver_prompt
├── examples/
│   ├── __init__.py               # Phase 4d — makes examples an importable package
│   ├── cli_examples.py           # Phase 4d — CLI examples, 5 scenarios, runnable
│   ├── http_examples.py          # Phase 4d — HTTP examples, 5 scenarios + 2 edge cases, runnable
│   └── session_examples.py       # Phase 4j — session lifecycle flows + edge cases, runnable
├── FINAL_RESPONSE_CONTRACT.md    # Phase 3d — stable caller-facing contract doc
├── SESSION_CONTRACT.md           # Phase 4j — operational doc: TTL, cap, in-memory, single-instance
├── fpl_cli.py                    # Phase 4b — CLI: run() + main(); run_session() added Phase 4g
├── fpl_server.py                 # Phase 4c — HTTP: POST /ask, GET /health; session endpoints Phase 4h; hygiene Phase 4i
├── run_phase3a_tests.py          # 269/269 PASS
├── run_phase3b_tests.py          # 355/355 PASS
├── run_phase3c_tests.py          # 328/328 PASS
├── run_phase3d_tests.py          # 248/248 PASS
├── run_phase4a_tests.py          # 82/82 PASS  (live + offline)
├── run_phase4b_tests.py          # 119/119 PASS
├── run_phase4c_tests.py          # 148/148 PASS
├── run_phase4d_tests.py          # 115/115 PASS
├── run_phase4e_tests.py          # 120/120 PASS
├── run_phase4f_tests.py          # 151/151 PASS
├── run_phase4g_tests.py          # 161/161 PASS
├── run_phase4h_tests.py          # 184/184 PASS
├── run_phase4i_tests.py          # 149/149 PASS
└── run_phase4j_tests.py          # 86/86 PASS
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



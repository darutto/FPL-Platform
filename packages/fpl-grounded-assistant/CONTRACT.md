# fpl-grounded-assistant · Model-Facing Contract

*Phase 2n. Canonical reference for integrating with the grounded assistant adapter.*

---

## Interface Hierarchy

```
adapt()          ← model-facing entrypoint  (Phase 2m)  ← THIS DOCUMENT
  └── dispatch() ← typed dispatcher          (Phase 2k/2l)
        └── ask()       ← grounded harness   (Phase 1h/2f)
              └── run_tool() ← tool runner   (Phase 1g)
                    └── tool_contract layer  (Phase 1f)
```

All routing and execution is **deterministic** — no LLM calls in the
grounded backend. The adapter layer is the designed integration point for a
future LLM tool-use loop.

---

## `adapt()` — Primary Entrypoint

```python
from fpl_grounded_assistant import adapt, AdapterResponse

response: AdapterResponse = adapt(
    user_message,            # str        — raw user question
    bootstrap,               # dict       — FPL bootstrap or assembled context
    *,
    candidate_inputs=None,   # dict|None  — scoring overrides for captain_score
    candidates_list=None,    # list|None  — candidates for rank_candidates
)
```

**Guarantees:**
- Never raises — all error cases return a valid `AdapterResponse`
- Fully deterministic — identical inputs produce identical outputs
- No LLM calls — all routing and execution is rule-based keyword matching
- `response.user_message` is always the exact string passed in
- `response.response_text` is always non-empty

---

## `AdapterResponse` — 4 fields (frozen dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `user_message` | `str` | Original user message, preserved verbatim |
| `dispatch_result` | `DispatchResult` | Full dispatcher output (all 7 fields) |
| `supported` | `bool` | `True` if intent was recognised; `False` only for unsupported scope |
| `response_text` | `str` | Human-readable response; mirrors `dispatch_result.answer_text` |

### `supported` flag semantics

| Value | Meaning | Outcome examples |
|-------|---------|-----------------|
| `True` | Intent was *recognised* — even if execution did not complete | `ok`, `not_found`, `ambiguous`, `missing_arguments`, `error` |
| `False` | Question is *outside the supported scope* | `unsupported_intent` |

> **Note for LLM integration:** `supported=True` does not mean the answer
> is complete. When `supported=True` but `outcome != "ok"`, inspect
> `dispatch_result.outcome` to determine the failure mode and decide
> whether to ask a clarifying question or surface the `response_text`
> directly.

---

## `DispatchResult` — 7 fields (frozen dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `intent` | `str` | One of the `INTENT_*` constants (see table below) |
| `question` | `str` | Original question, preserved verbatim |
| `selected_tool` | `str\|None` | Tool name used; `None` when `intent == INTENT_UNSUPPORTED` |
| `raw_output` | `dict` | Structured tool output from the grounded backend |
| `answer_text` | `str` | Human-readable response string |
| `context_meta` | `dict\|None` | Pipeline metadata when assembled context was passed; `None` for raw bootstrap |
| `outcome` | `str` | One of the `OUTCOME_*` constants (see table below) |

### `raw_output` status codes

| `raw_output["status"]` | Meaning |
|------------------------|---------|
| `"ok"` | Tool executed successfully; response fields are populated |
| `"not_found"` | Player query matched no player in the registry |
| `"ambiguous"` | Player query matched multiple players; `candidates` list included |
| `"error"` | Unexpected failure; `raw_output["code"]` gives detail |
| `"unsupported"` | Intent was not recognised before reaching any tool |

---

## Outcome Vocabulary

| Constant | String value | Meaning | `supported` |
|----------|-------------|---------|-------------|
| `OUTCOME_OK` | `"ok"` | Intent recognised; execution succeeded | `True` |
| `OUTCOME_NOT_FOUND` | `"not_found"` | Intent recognised; player not found in registry | `True` |
| `OUTCOME_AMBIGUOUS` | `"ambiguous"` | Intent recognised; player name matched multiple entries | `True` |
| `OUTCOME_MISSING_ARGUMENTS` | `"missing_arguments"` | Intent recognised; required input not supplied | `True` |
| `OUTCOME_ERROR` | `"error"` | Intent recognised; unexpected backend error | `True` |
| `OUTCOME_UNSUPPORTED_INTENT` | `"unsupported_intent"` | Intent not recognised; outside supported scope | `False` |

### When to surface `response_text` directly vs. follow up

| Outcome | Recommended action |
|---------|-------------------|
| `ok` | Surface `response_text` as final answer |
| `not_found` | Surface `response_text`; optionally prompt user to check spelling |
| `ambiguous` | Surface `response_text`; prompt user to disambiguate |
| `missing_arguments` | Surface `response_text` (already contains guidance); request missing input |
| `error` | Surface `response_text`; log `raw_output` for diagnostics |
| `unsupported_intent` | Surface `response_text` (safe fallback); optionally route elsewhere |

---

## Supported Intents

| Constant | Value | Tool | Needs player query | Needs candidates list |
|----------|-------|------|--------------------|-----------------------|
| `INTENT_CAPTAIN_SCORE` | `"captain_score"` | `get_captain_score` | Yes | No |
| `INTENT_RANK_CANDIDATES` | `"rank_candidates"` | `rank_captain_candidates` | No | Yes |
| `INTENT_CURRENT_GAMEWEEK` | `"current_gameweek"` | `get_current_gameweek` | No | No |
| `INTENT_PLAYER_SUMMARY` | `"player_summary"` | `get_player_summary` | Yes | No |
| `INTENT_PLAYER_RESOLVE` | `"player_resolve"` | `resolve_player` | Yes | No |

`INTENT_MANIFEST` (importable dict) is the single source of truth. Each entry
includes `tool`, `description`, `requires_player_query`,
`requires_candidates_list`, and `example_phrasings`.

### Routing mechanism

Routing is deterministic keyword matching (no fuzzy logic, no LLM):

```
gameweek keywords  →  INTENT_CURRENT_GAMEWEEK
ranking keywords   →  INTENT_RANK_CANDIDATES
captain prefixes   →  INTENT_CAPTAIN_SCORE
summary prefixes   →  INTENT_PLAYER_SUMMARY
resolve prefixes   →  INTENT_PLAYER_RESOLVE
(no match)         →  INTENT_UNSUPPORTED
```

---

## Invariants (Always True)

All of the following hold for every `AdapterResponse` returned by `adapt()`:

1. `response.response_text == response.dispatch_result.answer_text`
2. `response.user_message == response.dispatch_result.question`
3. `response.supported == (response.dispatch_result.outcome != OUTCOME_UNSUPPORTED_INTENT)`
4. `response.dispatch_result.selected_tool is None` iff `response.dispatch_result.intent == INTENT_UNSUPPORTED`
5. `len(response.response_text) > 0` — response_text is never empty
6. `response.dispatch_result.context_meta is None` when a raw bootstrap dict is passed;
   populated when an assembled context dict (from `assemble_captain_context()`) is passed

---

## Bootstrap vs. Assembled Context

`adapt()` (and `dispatch()`) accept either:

```python
# Raw bootstrap — minimal, no context_meta
adapt(message, bootstrap_dict)

# Assembled context — from fpl_pipeline.assemble_captain_context()
# Populates dispatch_result.context_meta
ctx = assemble_captain_context(gameweek=28, bootstrap=bs, fixtures=fx)
adapt(message, ctx)
```

The detection is automatic — no parameter change required.

---

## `candidate_inputs` and `candidates_list` Parameters

```python
# Captain score with explicit scoring overrides
adapt(
    "should I captain Haaland",
    bootstrap,
    candidate_inputs={"fixture_difficulty": 3},  # override auto-derived FDR
)

# Rank candidates — candidates_list is required for rank_candidates intent
adapt(
    "top captains this week",
    bootstrap,
    candidates_list=[{"query": "Haaland"}, {"query": "Salah"}],
)
```

Without `candidates_list`, `rank_candidates` returns `OUTCOME_MISSING_ARGUMENTS`.

---

## Example Scenarios

See `fpl_grounded_assistant.conversation_fixtures` for 9 executable scenarios
covering all outcome types. Run `run_phase2n_tests.py` to validate all
fixture expectations against the live system.

```python
from fpl_grounded_assistant.conversation_fixtures import (
    FIXTURE_DEFINITIONS,
    run_all,
    STANDARD_BOOTSTRAP,
    AMBIGUOUS_BOOTSTRAP,
)

results = run_all(STANDARD_BOOTSTRAP, AMBIGUOUS_BOOTSTRAP)
for fixture, response in results:
    print(fixture.scenario_id, "→", response.dispatch_result.outcome)
```

---

## Out of Scope (Deferred)

| Capability | Status |
|------------|--------|
| LLM-based intent classification | Deferred |
| Multi-turn conversation memory | Deferred |
| Pronoun resolution ("What about his form?") | Deferred |
| Combined intents ("Who is Salah and what gameweek is it?") | Deferred |
| Freeform / generative response text | Deferred |
| UI integration | Deferred |
| Live FPL API calls (fixtures use injected bootstrap) | Out of scope for grounded layer |



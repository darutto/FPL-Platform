# fpl-grounded-assistant · Final Response Contract

*Phase 3d. Canonical reference for the stable caller-facing ``respond()`` /
``FinalResponse`` surface.*

---

## Purpose

This document defines the **stable public contract** for ``respond()``, the
outermost entrypoint of the fpl-grounded-assistant stack.

External callers (UI layers, API handlers, evaluation harnesses) should rely
only on the fields and invariants described here.  Internal fields in
``FinalResponseDebug`` are explicitly **not** part of this contract.

See ``CONTRACT.md`` for the lower-level ``adapt()`` / ``AdapterResponse``
contract (Phase 2m).

---

## Interface Hierarchy

```
respond()                    ← caller-facing entrypoint  (Phase 3c)  ← THIS DOCUMENT
  └── ask_llm_safe()         ← review gate               (Phase 3b)
        └── ask_llm()        ← LLM presentation          (Phase 3a)
              └── adapt()    ← deterministic adapter     (Phase 2m)
                    └── dispatch()    ← dispatcher       (Phase 2k/2l)
                          └── ask()  ← grounded harness  (Phase 1h)
```

All routing and scoring is **deterministic** — no LLM calls affect
``outcome``, ``supported``, ``intent``, or the structured ``raw_output``.
The LLM layer is limited to phrasing presentation of the grounded result;
it never alters backend semantics.

---

## `respond()` — Primary Entrypoint

```python
from fpl_grounded_assistant import respond, FinalResponse

response: FinalResponse = respond(
    user_message,              # str        — raw user question
    bootstrap,                 # dict       — FPL bootstrap or assembled context
    *,
    client=None,               # Anthropic|None  — pre-built API client
    model=DEFAULT_MODEL,       # str        — Anthropic model identifier
    candidate_inputs=None,     # dict|None  — scoring overrides for captain_score
    candidates_list=None,      # list|None  — candidates for rank_candidates
    api_key=None,              # str|None   — explicit API key
    include_debug=False,       # bool       — opt-in debug bundle
)
```

**Guarantees:**
- Never raises — all failure cases return a valid ``FinalResponse``
- ``final_text`` is always non-empty
- ``outcome`` is always one of the six ``OUTCOME_*`` constants
- ``supported`` is always ``(outcome != OUTCOME_UNSUPPORTED_INTENT)``
- ``llm_used=True`` iff an LLM API call was made AND the returned text passed
  the deterministic parity review
- ``debug`` is ``None`` unless ``include_debug=True`` is passed explicitly

---

## `FinalResponse` — Stable Caller-Facing Contract

Eight fields.  Frozen dataclass.

### Stable caller-facing fields

| Field | Type | Stability | Description |
|-------|------|-----------|-------------|
| `final_text` | `str` | **Stable** | The text to surface to the user. Non-empty. Policy: `llm_text` when `llm_used=True`; `response_text` otherwise. |
| `outcome` | `str` | **Stable** | One of the six `OUTCOME_*` constants. Use for routing decisions. |
| `supported` | `bool` | **Stable** | `True` if intent was within supported scope; `False` only for `unsupported_intent`. |
| `intent` | `str` | **Stable** | One of the `INTENT_*` constants. Useful for logging and analytics. |
| `review_passed` | `bool` | **Stable** | Whether the LLM text passed deterministic parity checks. `False` → `final_text` is the deterministic fallback. |
| `llm_used` | `bool` | **Stable** | Whether LLM-generated text appears in `final_text`. `True` iff `llm_called AND review_passed`. |
| `debug` | `FinalResponseDebug\|None` | **Stable shape; debug-only content** | `None` by default. Opt-in with `include_debug=True`. |
| `comparison` | `ComparisonMeta\|None` | **Stable (Phase 5g)** | Populated for `compare_players` OK turns. `None` for all other intents and non-OK outcomes. Provides structured access to `winner`, `margin`, `label`, `reasons` without parsing `final_text`. |

### Field shape stability commitment

The names and types of the seven non-debug fields above are considered a
**stable external contract**.  Any future change to their names, types, or
semantics is treated as a **breaking change** and must be documented
explicitly with a phase label.

---

## `ComparisonMeta` — Structured Comparison Bundle (Phase 5g)

Frozen dataclass. Populated on `FinalResponse.comparison` when `intent == "compare_players"` and `outcome == "ok"`. `None` for all other turns.

| Field | Type | Description |
|-------|------|-------------|
| `winner` | `str\|None` | Winning player display name. `None` when the two players are tied on captain score. |
| `margin` | `float` | Absolute score difference (winner − loser). Zero on a tie. |
| `label` | `str` | Categorical margin: `"narrow"` (< 3.0), `"moderate"` (3.0–9.99), `"clear"` (≥ 10.0). |
| `reasons` | `tuple[str, ...]` | Deterministic advantage phrases (e.g. `"stronger form (9.5 vs 8.0)"`). Empty tuple when no advantage clears the threshold. |

```python
r = respond("compare Haaland and Salah", bootstrap)
if r.comparison:
    print(r.comparison.winner)   # "Salah"
    print(r.comparison.label)    # "moderate"
    print(r.comparison.reasons)  # ("stronger form (9.5 vs 8.0)",)
```

---

## `FinalResponseDebug` — Debug Bundle (Not Part of Contract)

Five fields.  Frozen dataclass.  Only populated when ``include_debug=True``.

| Field | Type | Description |
|-------|------|-------------|
| `llm_text` | `str` | Raw LLM output (or `response_text` when `llm_called=False`). |
| `response_text` | `str` | Deterministic backend text. Equals `final_text` when `llm_used=False`. |
| `violations` | `tuple[str, ...]` | Violation strings from the review layer. Empty when `review_passed=True`. |
| `prompt_used` | `str` | The user-turn prompt sent (or prepared) for the LLM. |
| `model` | `str` | Anthropic model identifier, or `"none"` when deterministic fallback was used. |

**These fields are for diagnostics and regression testing only.**  Callers
should not branch on ``debug`` content in production code.

---

## Final-Text Policy

```
FINAL_TEXT_POLICY = (
    "final_text = review.safe_text: "
    "llm_text when (llm_called AND review_passed), "
    "response_text otherwise"
)
```

Three cases, exactly one always applies:

| Condition | `final_text` | `llm_used` |
|-----------|-------------|-----------|
| LLM called, review passed | `llm_text` | `True` |
| LLM called, review failed | `response_text` | `False` |
| LLM not called (no API key / error) | `response_text` | `False` |

The deterministic backend ``response_text`` is the ultimate recovery path in
all fallback cases, regardless of failure mode.

---

## `llm_used` Semantics

``llm_used=True`` means exactly:

> An Anthropic API call was made **AND** the returned text passed the
> deterministic parity review.

``llm_used=False`` covers all fallback scenarios without distinction:
- No API key set (``ANTHROPIC_API_KEY`` absent and no explicit ``api_key``)
- API error (network failure, rate limit, etc.)
- Review violation (overconfident language, invented numbers, false resolution)
- ``client=None`` and no key

Callers do not need to distinguish between these failure modes — they always
receive a safe, non-empty ``final_text``.

---

## `review_passed` Semantics

``review_passed=True`` means the LLM text (or deterministic fallback) passed
all four deterministic parity checks:

| Check | What it detects |
|-------|----------------|
| Overconfidence on non-ok outcomes | Phrases like "definitely", "guaranteed", "i can confirm" in failure responses |
| Numeric invention | Numbers in `llm_text` absent from `response_text` (non-ok outcomes only) |
| Ambiguous false resolution | Resolution phrases like "the player you're looking for is" in ambiguous responses |
| Empty LLM text | Empty string returned from an actual API call |

The deterministic fallback path always passes (``llm_text == response_text``
when ``llm_called=False`` → numeric check is trivially satisfied).

---

## Outcome Vocabulary

| Constant | Value | `supported` | When to surface `final_text` |
|----------|-------|-------------|------------------------------|
| `OUTCOME_OK` | `"ok"` | `True` | Surface directly as final answer |
| `OUTCOME_NOT_FOUND` | `"not_found"` | `True` | Surface; optionally invite spelling check |
| `OUTCOME_AMBIGUOUS` | `"ambiguous"` | `True` | Surface; prompt user to disambiguate |
| `OUTCOME_MISSING_ARGUMENTS` | `"missing_arguments"` | `True` | Surface (already contains guidance); request missing input |
| `OUTCOME_ERROR` | `"error"` | `True` | Surface; log debug bundle for diagnostics |
| `OUTCOME_UNSUPPORTED_INTENT` | `"unsupported_intent"` | `False` | Surface (safe fallback); optionally route to another system |

---

## Invariants (Always True)

All of the following hold for every ``FinalResponse`` returned by ``respond()``:

1. ``len(response.final_text) > 0`` — ``final_text`` is never empty
2. ``response.supported == (response.outcome != "unsupported_intent")``
3. ``not response.llm_used or response.review_passed`` — ``llm_used=True``
   implies ``review_passed=True``
4. ``response.outcome in {OUTCOME_OK, OUTCOME_NOT_FOUND, OUTCOME_AMBIGUOUS,``
   ``OUTCOME_MISSING_ARGUMENTS, OUTCOME_ERROR, OUTCOME_UNSUPPORTED_INTENT}``
5. When ``include_debug=True``:
   - ``response.debug is not None``
   - ``response.debug.violations == ()`` iff ``response.review_passed``
   - ``not response.llm_used → response.final_text == response.debug.response_text``
6. ``response.debug is None`` when ``include_debug=False`` (default)

---

## Named Scenarios

Six canonical scenarios covering all caller-relevant states.
See ``fpl_grounded_assistant.final_response_fixtures`` for executable versions.

### 1. `supported_ok`
```python
respond("should I captain Haaland", STANDARD_BOOTSTRAP)
# FinalResponse(
#   final_text=<non-empty captain score response>,
#   outcome="ok",
#   supported=True,
#   intent="captain_score",
#   review_passed=True,
#   llm_used=False,   # False in deterministic mode; True when LLM passes review
#   debug=None,
# )
```

### 2. `supported_ambiguous`
```python
respond("who is Doe", AMBIGUOUS_BOOTSTRAP)
# FinalResponse(
#   final_text=<clarification prompt listing both Doe players>,
#   outcome="ambiguous",
#   supported=True,
#   intent="player_resolve",
#   review_passed=True,
#   llm_used=False,
#   debug=None,
# )
```

### 3. `supported_not_found`
```python
respond("should I captain xyznotaplayer999", STANDARD_BOOTSTRAP)
# FinalResponse(
#   final_text=<player not found message>,
#   outcome="not_found",
#   supported=True,
#   intent="captain_score",
#   review_passed=True,
#   llm_used=False,
#   debug=None,
# )
```

### 4. `supported_missing_arguments`
```python
respond("top captains this week", STANDARD_BOOTSTRAP)  # no candidates_list
# FinalResponse(
#   final_text=<missing candidates_list guidance>,
#   outcome="missing_arguments",
#   supported=True,
#   intent="rank_candidates",
#   review_passed=True,
#   llm_used=False,
#   debug=None,
# )
```

### 5. `unsupported_intent`
```python
respond("Is Haaland fit to play?", STANDARD_BOOTSTRAP)
# FinalResponse(
#   final_text=<safe out-of-scope message>,
#   outcome="unsupported_intent",
#   supported=False,
#   intent="unsupported",
#   review_passed=True,
#   llm_used=False,
#   debug=None,
# )
```

### 6. `llm_fallback_to_deterministic`
```python
# No API key set, no explicit client
response = respond("should I captain Salah", STANDARD_BOOTSTRAP,
                   include_debug=True)
# FinalResponse(
#   final_text=<same as debug.response_text>,
#   outcome="ok",
#   supported=True,
#   intent="captain_score",
#   review_passed=True,
#   llm_used=False,                              ← fallback
#   debug=FinalResponseDebug(
#     llm_text=<same as response_text>,          ← fallback sets llm_text=response_text
#     response_text=<deterministic backend text>,
#     violations=(),                             ← no LLM → no violations
#     model="none",                              ← no LLM call
#     ...
#   ),
# )
assert response.final_text == response.debug.response_text  # fallback invariant
```

---

## Bootstrap vs. Assembled Context

``respond()`` accepts either a raw bootstrap dict or a full assembled context
from ``fpl_pipeline.assemble_captain_context()``.  Detection is automatic.

```python
# Raw bootstrap
respond("should I captain Haaland", bootstrap_dict)

# Assembled context — fixture_difficulty_map automatically included
from fpl_pipeline import assemble_captain_context
ctx = assemble_captain_context(gameweek=28, bootstrap=bs, fixtures=fx)
respond("should I captain Haaland", ctx)
```

---

## Stability Commitment

The following are **breaking changes** requiring explicit documentation:
- Renaming or removing any of the six non-debug fields on ``FinalResponse``
- Changing the type of any non-debug field
- Changing the semantics of ``supported``, ``llm_used``, or ``review_passed``
- Adding required parameters to ``respond()``

The following are **non-breaking**:
- Adding new optional parameters to ``respond()`` (keyword-only, with defaults)
- Populating additional fields in ``FinalResponseDebug``
- Adding new ``OUTCOME_*`` constants (callers should handle unknown outcomes
  gracefully by treating them as unsupported)

---

## Out of Scope (Deferred)

| Capability | Status |
|------------|--------|
| Multi-turn conversation memory | Deferred |
| Pronoun resolution | Deferred |
| Combined intents | Deferred |
| UI integration | Deferred |
| Streaming responses | Deferred |
| Model-based (non-deterministic) review | Deferred |
| LLM-based intent classification | Deferred |
| Live FPL API calls (fixtures use injected bootstrap) | Out of scope for grounded layer |



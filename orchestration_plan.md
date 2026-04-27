# FPL Grounded Assistant: LLM-as-Orchestrator Architecture Plan

**Date**: 2026-04-12  
**Problem**: Current rigid intent classification prevents natural conversation. Users can only ask pre-defined question shapes.  
**Solution**: Invert architecture — LLM becomes the orchestrator that calls grounded tools as needed, not a decorator that prettifies predetermined answers.

---

## Diagnosis: Current Pain Point

### Example: "debo usar mi benchboost en la 33?"

**What happens now:**
1. `route()` pattern-matches the question — fails (Spanish + specific gameweek not in templates)
2. `classify_intent_llm()` fires as fallback, rewrites to canonical form: "should I use bench boost this week"
3. `get_chip_advice` tool executes — but it analyzes only the *current* gameweek, not GW33
4. System responds: "I can't give specific advice on when to use chips"

**Why it fails:**
- The LLM classifies intent but never reasons about the data
- The deterministic tool can't handle contextual reasoning (comparing GW33 to current, DGW patterns, squad composition, etc.)
- The system enforces a "question shape → tool → render" pipeline that breaks the instant the user's phrasing doesn't fit a template

### Underlying Architecture Issue

Current flow:
```
user question 
  → route() [pattern match] 
  → dispatcher [intent-gated] 
  → tool [deterministic only] 
  → LLM [presentation only, can't reason]
  → answer
```

**The LLM is in the wrong place.** It's used as:
1. **Intent classifier** — rewrites questions for the router ❌ (doesn't reason)
2. **Presenter** — prettifies deterministic answers ❌ (can't add intelligence)

It's never used as an **orchestrator** that understands the question, reasons about the data, and calls tools when needed.

### Why "CSV-attached LLM" Works Better

Examples you've seen with FPL data in a CSV work because:
- The LLM receives the **raw data as context** (fixture calendar, player stats, DGW flags, etc.)
- The LLM is the **primary reasoner** — it reads the data, understands the question, synthesizes an answer
- Tools are **optional helpers** for computed data (captain scores, comparisons) the LLM can't derive from raw data alone
- The LLM composes the answer in **natural language** without being gated by intent templates

---

## Proposed Solution: LLM-as-Orchestrator

### Architecture Inversion

New flow:
```
user question (any language, any shape)
  → LLM receives:
     • user question
     • system prompt (with data context: bootstrap summary)
     • tool definitions (captain_score, compare_players, chip_advice, etc.)
  → LLM reasons freely
  → LLM decides which tools to call (if any)
  → LLM composes answer
  → answer (natural language, contextual, grounded)
```

### Component Changes

| Component | Current Role | New Role | Status |
|-----------|-------------|----------|--------|
| `route()` / `dispatcher` | Gate that filters allowed questions | Tool definitions & execution layer | Repurposed |
| `intent_classifier.py` | Rewrites questions for router | **Removed** — LLM understands intent natively | Obsolete |
| `llm_layer.py` | Presentation-only wrapper around deterministic result | **Orchestrator** — receives context + tools, reasons, composes answer | Replaced |
| `harness.ask()` / tool runners | Called after routing succeeds | Tool implementations called by orchestrator when needed | Unchanged |
| Bootstrap data | Passed opaquely through layers | **Injected as system context** — LLM sees raw fixture data, squad context, etc. | Elevated |
| Review layer | Validates deterministic output | Still validates for hallucination against grounded data | Unchanged |

### Concrete Workflow: Bench Boost Example

User asks: "debo usar mi benchboost en la 33?"

**What happens with orchestration:**

1. System prompt includes:
   ```
   Current gameweek: 30
   GW 33 is a DGW (double gameweek): teams A, B, C
   Top bench players by form: [player list with ownership, form, fixture]
   Bench boost signal value this week: 0.62 (moderate positive)
   Chip availability: bench_boost (available), triple_captain (used), ...
   ```

2. Tool definitions available:
   ```
   get_chip_advice(chip_name: str) → {recommendation, signal_value, gw}
   get_player_fixture_run(player_name: str) → {fixtures, horizon}
   ```

3. LLM reasons:
   - Understands "benchboost" = bench_boost chip
   - Understands "en la 33" = gameweek 33 (a DGW)
   - Sees from context that GW33 has multiple teams playing twice
   - Calls `get_chip_advice("bench_boost")` to get this week's signal
   - Reasons about DGW advantage vs. current signal
   - Composes answer in Spanish about whether to save it for GW33

4. Answer is natural, contextual, grounded.

---

## Implementation Phases

### Phase 1: Context Builder (Foundation)

**Goal:** Build a function that takes the bootstrap and produces a condensed, LLM-friendly summary.

**Deliverable:** `build_orchestration_context(bootstrap: dict) → str`

Returns a text block like:
```
=== FPL Context Summary ===
Current Gameweek: 30
Next GW Status: No DGW (single gameweek)
GW 33 Status: DOUBLE GAMEWEEK
Teams playing twice in GW33: Arsenal, Chelsea, Tottenham

Top 10 Players by Form (available):
1. Haaland (MCI) | Form: 8.5 | Ownership: 35% | Next 5: A(h) M(a) C(h) ...
...

Bench Boost Signal: 0.62 (moderate)
Triple Captain Signal: 0.45 (wait)
Wildcard Signal: not available (used GW15)
Free Hit Signal: not available (used GW20)

Your Squad Context (if provided):
  Captaincy options: Haaland, Salah, Palmer (top 3)
  Bench strength: 3 premium options
  Transfer budget: £1.2m available
```

**Why this is important:** This is the "CSV equivalent" — the LLM has real data to reason over, not a black box.

**Tests:** Ensure context is:
- Factually correct (matches bootstrap)
- Concise (fits in a system prompt)
- Structured (easy for LLM to parse)
- Contains no hallucinations (only raw bootstrap data + simple derivations)

### Phase 2: Tool Schema Registry (Function Calling Setup)

**Goal:** Convert existing tools into callable schemas the LLM can invoke.

**Deliverable:** Tool definition registry (similar to OpenAI function calling format)

```python
ORCHESTRATION_TOOLS = {
    "get_captain_score": {
        "name": "get_captain_score",
        "description": "Compute captaincy score for a single player",
        "parameters": {
            "type": "object",
            "properties": {
                "player_name": {"type": "string", "description": "Player name or alias"}
            },
            "required": ["player_name"]
        }
    },
    "compare_players": { ... },
    "get_chip_advice": { ... },
    "get_player_summary": { ... },
    "resolve_player": { ... },
    # ... etc
}
```

**Implementation:** Each tool wraps your existing `run_tool()` calls.

**Why this is important:** The LLM sees what tools are available and their signatures. It decides whether to call them.

### Phase 3: Orchestrator Entrypoint

**Goal:** New function that orchestrates the LLM + tool loop.

**Deliverable:** `ask_orchestrated(user_question, bootstrap, classifier_client=None) → OrchestrationResponse`

**Behavior:**
1. Build context summary from bootstrap
2. Assemble system prompt (with context + tool definitions + safety instructions)
3. Send to LLM with `tools` parameter (Anthropic tool_use / Gemini function_calling / OpenAI function_calling)
4. Loop: if LLM wants to call a tool, execute it and return result to LLM
5. When LLM reaches a final answer, return it

**Fallback:** If LLM unavailable or refuses, fall back to deterministic path.

**Response type:** Similar to `LLMResponse` but with:
- `llm_text`: the orchestrated answer
- `tools_called`: which tools the LLM invoked
- `grounded`: boolean (True if answer cites only context + tool results)
- `source`: "orchestrator" or "deterministic_fallback"

**Safety guardrails:**
- System prompt forbids inventing player stats
- Review layer checks answer against bootstrap (same as today)
- LLM instructed to cite specific data or say "I don't have that information"

### Phase 4: Wire into Server

**Goal:** Integrate orchestrator into existing HTTP layer.

**Changes:**
- `/ask` endpoint calls `ask_orchestrated()` instead of `ask_llm()`
- `/session/{id}/ask` calls orchestrator-aware session responder
- Fallback to deterministic path if orchestrator unavailable
- `AskResponse` schema gains `tools_called` field (optional, for transparency)

**Backward compatibility:** Existing contract is preserved; new fields are optional.

---

## Grounding & Safety

### How Grounding Is Preserved

1. **Data context** — Only real bootstrap data is in the system prompt (no hallucination source)
2. **Tool calls** — Computed scores come from deterministic backend, not LLM reasoning
3. **Review layer** — Same violation checks as today; answer must cite context or tool results
4. **Fallback** — If LLM refuses or unavailable, deterministic path still works

### How to Validate

- Unit tests: context builder produces accurate summaries
- Integration tests: orchestrator respects guardrails (doesn't invent stats)
- Regression tests: same questions as today produce similarly grounded answers
- Smoke tests: edge cases (ambiguous players, no tools called, multiple tool chains)

---

## What Stays the Same

- All scoring logic (`fpl-captain-engine`, `fpl-pipeline`)
- All tools and data sources
- The `FinalResponse` contract
- The review layer
- Deterministic path as fallback

---

## Rollout Strategy

1. **Start small** — Phase 1 (context builder) is a pure function, testable without LLM
2. **Build incrementally** — Phase 2 (schemas) + Phase 3 (orchestrator) can coexist with current system
3. **Dual-path** — New endpoint `POST /ask-orchestrated` while `/ask` still works
4. **Validate** — Run both paths on test corpus, compare outputs
5. **Graduate** — If orchestrator performs well, make it the default; keep deterministic as fallback

---

## Open Questions

1. **Which LLM provider?** Orchestrator works with Anthropic (tool_use), Gemini (function_calling), or OpenAI (function_calling). Recommend Claude for reasoning depth.

2. **Tool set scope** — Should all existing tools be callable, or a curated subset? Recommend all, let LLM decide what's needed.

3. **Context size** — How much bootstrap detail in the prompt? Balancing detail (helps reasoning) vs. cost (token budget). Recommend starting lean (top 50 players, key fixtures) and expanding.

4. **Fallback behavior** — When does orchestrator fall back to deterministic? Options: LLM unavailable, LLM timeout, LLM refusal. Recommend: LLM unavailable only (fast-fail on refusal).

5. **Session state** — Should orchestrator maintain multi-turn context (pronoun resolution, follow-ups)? Recommend starting stateless; layer conversation context later.

---

## Expected Outcomes

**User experience:**
- Natural questions in any language → sensible answers
- Contextual reasoning (GW33 DGW bench boost advice, not generic)
- No more "that question is out of scope" walls

**Developer experience:**
- Clearer data flow (context → orchestrator → answer)
- LLM is the reasoning layer, not a decorator
- Tools are optional, not mandatory gates

**System properties:**
- Grounded (answers cite real data or tool results)
- Conversational (natural language, any shape)
- Fallback-safe (deterministic path still works)
- Cost-transparent (tool calls logged, context size bounded)

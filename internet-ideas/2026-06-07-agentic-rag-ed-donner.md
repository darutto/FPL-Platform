---
title: Taking Agentic RAG to the next level
source: https://www.youtube.com/watch?v=UmGLirGbKTk
author: Ed Donner
repo: https://github.com/ed-donner/expert
captured: 2026-06-07
relevant_to: [routing, cost, knowledge, orchestrator, resources, prompts]
status: new
---

## Source in one line
A short walkthrough of an "agentic RAG" assistant (OpenAI Agents SDK + Qdrant
vector store via MCP) where the key move is: answer with plain code when you
can, and only route to the LLM + tools when you can't.

## How it relates to us
Ed's architecture and our `decision_router` converge on the same skeleton:
classify the input *before* any model runs, short-circuit recognizable input
with code, fall through to the LLM only for the rest.

- Ed's `get_instant_answer("Q37")` → dict lookup, no LLM
  ≈ our `@resource` / `/prompt`-dispatch branches in
  [decision_router.py](../packages/fpl-grounded-assistant/fpl_grounded_assistant/decision_router.py)
  and [resource_registry.py](../packages/fpl-grounded-assistant/fpl_grounded_assistant/resource_registry.py).
- Ed's "list the FAQ *questions* in the prompt, fetch the long answer via a
  tool on demand" ≈ our bootstrap-context + tool-use orchestrator (don't stuff
  the dataset into context).

**Key difference:** Ed's project is literally RAG — semantic retrieval over 190
scraped text chunks. Ours, despite the `fpl-grounded-assistant` name, is *not*
RAG: our grounding is **computed** (transfer/chip advisors, fixture runs,
position scoring), not retrieved. There is no semantic-retrieval layer today.

## Ideas

### 1. A cheap deterministic rung before the orchestrator for plain text — priority: high
Our P1.a pivot routes **all** plain text straight to `ask_orchestrated()` (an
LLM call). See the comments at
[harness.py:821-846](../packages/fpl-grounded-assistant/fpl_grounded_assistant/harness.py#L821):
the old step 1 (`route()` first-try) and step 2 (`classifier_rewrite`) were
removed from the plain-text path.

Ed's closing line — *"sometimes LLMs are not the answer, just look it up"* — is a
direct counterpoint. He keeps a zero-cost path for recognizable input. A middle
path we don't currently have: a cheap exact/alias-match rung on plain text that
resolves the top-N common questions deterministically, falling to the
orchestrator only on a miss. The orchestrator still owns genuinely ambiguous
queries.

- **Why it matters:** cost + latency on every common question; we bill Patreon
  users against LLM spend.
- **Caveat:** the orchestrator-primary inversion was deliberate (see auto-memory
  `feedback_llm_orchestration_architecture`). This is a *re-add a fast rung*
  idea, not an *undo the pivot* idea.
- **Folds into:** any roadmap step that touches routing-ladder ordering or
  orchestrator cost/quota work.

### 2. A curated FAQ surface ("questions in prompt, answers via tool") — priority: high
FPL has a large body of stable, factual Q&A: chip mechanics, deadline rules,
price-change timing, "what is xG/xGI", wildcard vs. free hit. Ed's pattern fits
perfectly as a new `@faq` resource or `/faq` prompt: list the *questions*
cheaply, fetch the long answer via a tool only when needed.

- **Why it matters:** Spanish-first, deterministic, zero model cost, great
  onboarding surface. Slots into the existing
  [resource_registry.py](../packages/fpl-grounded-assistant/fpl_grounded_assistant/resource_registry.py)
  / [prompt_registry.py](../packages/fpl-grounded-assistant/fpl_grounded_assistant/prompt_registry.py)
  with no new infrastructure.
- **Lowest-risk, most directly portable idea here.**
- **Folds into:** any resource/prompt-registry expansion step, or V2 onboarding UI.

### 3. A small semantic-retrieval layer for open-ended questions — priority: low/med
Our orchestrator fallback has *tools* but no *knowledge corpus*. For genuinely
open questions ("explain the philosophy behind early wildcards"), it answers
from model priors with nothing grounded to retrieve. Ed's Qdrant layer is the
fix; we have raw material via the historical pipeline.

- **Caveat:** vector RAG introduces non-determinism, against our "grounded"
  invariant. Fence it off to explainer-type questions only — never numeric or
  advice answers.
- **Folds into:** historical-data / knowledge work, well after #1 and #2.

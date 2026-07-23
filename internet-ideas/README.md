# Internet Ideas

A parking lot for ideas harvested from outside sources — videos, articles, other
people's repos, conference talks — that are *tangentially* relevant to this
project but **not** part of the committed roadmap.

The roadmap comes first. This folder exists so a good idea doesn't get lost, and
so we can **organically fold an idea into a roadmap step when that step happens
to touch the same area** — without derailing to chase it now.

## How to use this folder

### When you find an idea
Add one Markdown file per source: `YYYY-MM-DD-short-slug.md`. Copy the
front-matter block from the template below. Keep one *source* per file even if it
yields several ideas — list the ideas inside.

### When you're planning a roadmap step
Before writing a plan, skim this folder (or grep the `relevant_to:` tags — see
below). If the step you're about to build is tangentially relevant to an idea
here, decide whether to **fold it in** (cheap, on-theme), **defer** (note it in
the plan as a follow-up), or **drop** (no longer useful — delete the file).

### The `relevant_to:` tagging convention
Each idea file carries front-matter tags naming the areas of the codebase /
roadmap it touches. This makes the folder greppable during planning:

```
rg "relevant_to:.*routing" internet-ideas/
```

Use stable, coarse tags so they survive roadmap churn. Current vocabulary
(extend as needed, keep it small):

| tag | covers |
|---|---|
| `routing` | decision_router, input_normalizer, ladder ordering, deterministic-vs-LLM |
| `orchestrator` | ask_orchestrated, LLM-primary path, tool-use loop |
| `cost` | LLM token spend, latency, Patreon billing economics |
| `knowledge` | retrieval/RAG, FAQ surfaces, explainer content, vector stores |
| `resources` | resource_registry / `@resource` surface |
| `prompts` | prompt_registry / `/prompt` surface |
| `ui` | V2 Next.js frontend, Stitch redesign |
| `historical` | owned historical data pipeline, backtesting |
| `observability` | telemetry, routing_trace, audit |
| `spanish` | Spanish-first routing, aliases, localization |

## Status values
`new` (just captured) · `triaged` (assessed, priority noted) ·
`folded` (merged into a roadmap step — note which) · `dropped` (rejected).

## Index

| date | source | ideas | relevant_to | status |
|---|---|---|---|---|
| 2026-06-07 | [Ed Donner — Taking Agentic RAG to the next level](2026-06-07-agentic-rag-ed-donner.md) | cheap pre-LLM rung; curated FAQ surface; semantic explainer layer | routing, cost, knowledge, orchestrator | new |

---

## Idea file template

```markdown
---
title: <source title>
source: <url>
author: <who>
captured: YYYY-MM-DD
relevant_to: [routing, cost]   # tags from the vocabulary above
status: new
---

## Source in one line
<what it is>

## Ideas
### 1. <idea name>  — priority: <high|med|low>
<what it is, why it might matter here, the caveat/tradeoff, where it would land
in our code (link files), and what roadmap step it could fold into>
```

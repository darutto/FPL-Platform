# Field Notes

A parking lot for defects and gaps found **by exploring our own running system** —
poking at live data, reading a card that looked wrong, tracing a number back to
its source.

Sibling to [`internet-ideas/`](../internet-ideas/README.md), which parks ideas
harvested from *outside* sources. Same mechanics, opposite direction: that folder
is "someone else's good idea, maybe fold it in someday", this one is "our thing
is doing something we didn't intend, here's the evidence".

The roadmap still comes first. This folder exists so a finding doesn't evaporate
between sessions, and so we can **fold a fix into a roadmap step when that step
happens to touch the same code** — without derailing to chase it now.

## How to use this folder

### When you find something
Add one Markdown file per exploration session: `YYYY-MM-DD-short-slug.md`. One
*session* per file even if it turned up several findings — list them inside,
each with its own severity.

**Every finding must carry reproducible evidence.** A number someone can
re-derive, a file:line, an API response. This folder is not for hunches — a
hunch goes in the session's "open questions" section, clearly separated.

### When you're planning a roadmap step
Skim this folder (or grep `relevant_to:`) before writing a plan. If the step
touches the same area as a finding, decide whether to **fix it in** (cheap,
on-theme), **defer** (note it in the plan as follow-up), or **drop** (no longer
real — delete the file, or strike the finding and say why).

### The `relevant_to:` tagging convention
Coarse, stable tags naming the areas a finding touches. Shares the
`internet-ideas/` vocabulary where it overlaps and extends it where this folder
needs to be more specific about the domain layer:

| tag | covers |
|---|---|
| `scoring` | captain_score, position_score, per-90 derivation, `_derive_scoring_inputs` |
| `chips` | chip_advisor, chip windows, ChipAdviceMeta |
| `fixtures` | FDR maps, fixture_outlook, calendars, DGW/BGW detection |
| `preseason` | anything specific to the between-seasons / pre-GW1 state |
| `gw-resolution` | current-gameweek resolvers, `is_current`/`is_next` handling |
| `contracts` | FinalResponse fields, card payloads, what the UI can actually see |
| `ui` | V2 Next.js frontend rendering rules |
| `data-quality` | upstream FPL API quirks, stale/missing/null fields |
| `packaging` | import paths, package collisions, test wiring |
| `instruments` | the tools we measure *with* — probes, greps, byte counts, CI readings |
| `falsifiability` | whether a reported value can fail; seeding, deletion experiments, the probe gate |
| `tooling` | git/shell/test-harness behaviour that changes what a measurement means |

## Severity

| level | means |
|---|---|
| `high` | produces a confidently wrong answer to a user |
| `med` | degrades or silently narrows an answer |
| `low` | cosmetic, or only reachable in an edge case |

## Status values
`new` (just captured) · `triaged` (assessed, priority noted) ·
`fixed` (note the commit/PR) · `dropped` (not real after all — say why).

## Index

| date | session | findings | relevant_to | status |
|---|---|---|---|---|
| 2026-08-05 | [Preseason gaps — Bench Boost GW1](2026-08-05-preseason-gaps.md) | BB selection bias; `form=0` blind engine; per-90 no minutes floor; GW resolver half-migrated | scoring, chips, preseason, gw-resolution | new |
| 2026-08-06 | [Query-primitive coverage gap](2026-08-06-query-primitives-gap.md) | no price filter; no per-90 metrics; no budget/formation/club-limit concepts; answer-shaped vs query-shaped tools | contracts, scoring, fixtures, orchestrator | new |
| 2026-08-07 | [Primitive discovery close](2026-08-07-primitive-discovery-close.md) | no season table / promotion model / venue filter / offset GW window / block swing / real xP — **plus the 4-category synthesis and scoping warning** | contracts, fixtures, historical, orchestrator | new |
| 2026-08-09 | [Armado 25-26 dogfooding](2026-08-09-user-armado-dogfooding.md) | bootstrap minutes cache staleness; `position_score` vs `captain_score` split, no standalone rating query; compare-wizard free-text discoverability (fixed, PR #104); player-snapshot renderer asymmetry + no shareable card | scoring, contracts, ui, data-quality | new |
| 2026-08-12 | [«mejor jugador del Newcastle» — team dump, no card](2026-08-12-team-snapshot-no-card-wrong-answer.md) | card coverage gated by `_TOOL_TO_INTENT` (13 tools unmapped); «máximo goleador» is top *points* not goals; «mejor forma» degenerate at form=0; GW1 dropped from the fixture run; last-season totals undisclosed; superlative question unanswered | contracts, ui, gw-resolution, data-quality, preseason, orchestrator | new |
| 2026-08-13 | [Three instruments, three false readings](2026-08-13-instruments-failing-silently.md) | aborted probe run read as a verdict (caught by the tool); `grep -c $'\r'` and `file`-through-a-pipe both misreport line endings, in opposite directions; `git check-attr` reads a deleted `.gitattributes` from the index, turning a falsification experiment into a false pass already written into a commit message — **common factor is silence, and the fix each time was a second measurement by a different mechanism** | instruments, falsifiability, tooling | new |

> **Discovery status:** the primitive-discovery pass is **closed** as of
> 2026-08-07 — findings converged into 4 categories. Read the synthesis section
> of the 2026-08-07 note before scoping any of this work; it flags two items
> that are projects disguised as tools.

---

## Note file template

```markdown
---
title: <what you were doing>
found_via: <how it surfaced — "user noticed X", "traced the number behind Y">
captured: YYYY-MM-DD
relevant_to: [scoring, chips]   # tags from the vocabulary above
status: new
---

## What prompted this
<the trigger, in a line or two>

## Findings

### 1. <finding> — severity: <high|med|low>
**What happens:** <observable behaviour>
**Evidence:** <the reproducible number / response / file:line>
**Where:** <file:line>
**Why it happens:** <mechanism>
**Fix direction:** <shape of the fix, not a full plan>

## Open questions
<hunches and unknowns — explicitly NOT findings>
```

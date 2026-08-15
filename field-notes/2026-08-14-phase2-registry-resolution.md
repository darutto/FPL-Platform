---
title: "#72 phase 2 — diagnosing three red suites in the player-resolution path"
found_via: diagnosing the three remaining red package suites before wiring them into CI
captured: 2026-08-14
relevant_to: [contracts, packaging, instruments, tooling, data-quality]
status: new
---

## What prompted this

Phase 2 of #72 required diagnosing three red suites — `fpl-player-registry` (2),
`fpl-query-tools` (1), `fpl-data-core` (2) — before wiring any of them. Fixed in
PRs #130, #131, #132. Two things surfaced that are *not* fixed there and would
otherwise evaporate.

## Findings

### 1. `lstrip("el ")` is a character-set strip, not a prefix strip — severity: med

**What happens:** The Spanish "el X" nickname handling uses `str.lstrip("el ")`,
which removes any leading run of the characters `e`, `l`, and space — not the
literal prefix `"el "`. Any alias or query beginning with those characters is
mangled, including ones with no `"el "` prefix at all.

**Evidence:** measured, not reasoned:

```
'el palmer'  -> 'palmer'    correct, by luck
'el vikingo' -> 'vikingo'   correct, by luck
'el elanga'  -> 'anga'      should be 'elanga'
'el leon'    -> 'on'        should be 'leon'
'el lewis'   -> 'wis'       should be 'lewis'
'ellis'      -> 'is'        no "el " prefix at all
```

The cases that work do so only because the next character happens not to be
`e`, `l`, or space.

**Where:** `packages/fpl-player-registry/fpl_player_registry/registry.py:232`
(alias index construction) and `:323` (`lookup_by_alias`, applied to the user's
query).

**Why it matters here:** the product is Spanish-first and `"el X"` is its
house nickname pattern, so this is the intended path rather than an edge. At
`:323` it is applied to *user input*, so a query like "Ellis" is looked up as
"is". Impact is currently limited because a mangled key usually just misses —
`_by_alias.get(stripped)` returns None — but it silently narrows alias
resolution and would return a **wrong** player if a mangled form collides with
a real alias.

**Fix direction:** `a.removeprefix("el ")` (or a regex anchored on the prefix)
at both sites. Small and self-contained, but it changes alias resolution
behaviour, so it wants its own regression over the table rather than being
folded into a CI-onboarding PR.

### 2. `ab32cc6` broke two pins and introduced one defect, in three packages — severity: low (process)

**What happens:** Three of the five phase-2 failures trace to the same commit,
"Complete Phase 2.5 hardening and readiness contract slices":

| Package | What ab32cc6 did | Result |
|---|---|---|
| fpl-player-registry | added the diacritic-folded index | ambiguous web_names silently resolved to the most-owned candidate (a real defect — PR #130) |
| fpl-data-core | added 4 columns to `CUMULATIVE_COLS` | count pin stale at 26 vs 30 (PR #132) |
| fpl-query-tools | — (inherited via the registry) | contract violation surfaced downstream (PR #131) |

**Evidence:** `git log -S` on each symbol lands on `ab32cc6` for
`defensive_contribution`, `recoveries`, and the folded-index code.

**Why it happened:** a broad multi-slice commit crossing package boundaries,
landing when none of the three packages had a CI job. Every consequence was
invisible for months.

**Fix direction:** nothing to fix retroactively — the three PRs cover it. Worth
recording as the concrete cost case for "a suite nobody runs rots, silently"
(#72): one commit, three packages, five failures, zero signal.

## Open questions

- Are there other `lstrip(` / `rstrip(` calls in the repo being used as
  prefix/suffix strips? Not swept — finding 1 was found incidentally while
  probing alias behaviour, and the sweep is the obvious follow-up.
- `_by_web_name_folded` resolves folded collisions by highest ownership. That
  is documented and deliberate, and #130 deliberately left it alone (it only
  stopped *ambiguous raw* names from reaching it). But "two players whose names
  fold to the same key" is arguably ambiguous too, and nothing currently pins
  which way that should go. Not a finding — no evidence it has produced a wrong
  answer — but it is the next question in this area.

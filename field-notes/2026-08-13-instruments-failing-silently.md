---
title: "Three measuring instruments gave confident false readings in one session — and the failure mode was silence, not unreliability"
found_via: rescuing S5b from a superseded branch; each instrument was caught only because a second measurement by a different mechanism happened to be taken
captured: 2026-08-13
relevant_to: [instruments, falsifiability, tooling]
status: new
---

## What prompted this

A single session's work — recovering `trial_stats.py` from the superseded
`feat/fi8-s5-health-stats` (#88), restoring the missing frozen examples (#127),
and pinning their line endings (#128) — produced **three** instrument failures.
No defect was found in the code under measurement. Every failure was in the
thing doing the measuring.

The thesis is not new. The plan already states it, around line 2554:

> the code being swept has been in better shape than the things doing the
> sweeping, consistently. Three of five high-confidence claims failed on
> instruments.

These three are direct evidence for that line, captured while fresh. **They are
recorded here rather than folded into the plan now** because that passage sits
in the same region #100 will rebase (~2537–2563), and editing it the day before
the trial opens would mean two uncoordinated edits to one paragraph. The
consolidation happens when #100 is rebased after trial day 5–10, deliberately
and in one pass.

## The three instances

### 1. An aborted probe run, read as a verdict — severity `low`

The falsifiability probe aborted at seed 13 of 34 (`242 passed, 162 errors`)
because the sandbox blocks pytest's default temp root. **Caught by the tool
itself**: `score()` maps any run whose summary contains `error` to `INVALID`,
and the probe refused to print a verdict.

This is the one that worked. The instrument defended itself, and the phase
already documents the class on #101. Severity is `low` precisely *because* the
defense existed.

Its residue is the finding filed on #101: in that invalid run, kills were
attributed to `test_falsifiability_probe.py` and `test_trial_discovery.py`
rather than to the declared owner. A genuine `owner-silent=0` and a false one
produced by an invalid run are indistinguishable from the attribution output
alone.

### 2. `grep -c $'\r'` and `file`-through-a-pipe — severity `med`

The question: are the committed example blobs LF or CRLF? It matters because
seven tests compare them byte-for-byte against a fresh run.

Two instruments, two confident answers, opposite directions, **neither
self-reporting**:

| instrument | verdict | reality |
|---|---|---|
| `git cat-file blob <sha> \| file -` | "UTF-8 text" (no CRLF) | right answer, wrong reason — `file` does not report CRLF through a pipe |
| `git cat-file blob <sha> \| grep -c $'\r'` | `21` CR lines of 21 | matches **every line regardless of content** |

The tell was visible and initially missed: the CR count equalled the line count
for *every* file measured — 21/21, 29/29, 39/39, 71/71. A real mix never lands
on exactly 100% eight times running.

What settled it was arithmetic and a different transport:

```
git cat-file -s 2ed9b20                     -> 1022          (object size)
gh api .../git/blobs/2ed9b20 | base64 -d    -> 1022 bytes, 0 CR, ends 0a
git cat-file blob 2ed9b20 | tr -cd '\r' | wc -c  -> 0
tr -cd '\r' < <worktree copy> | wc -c            -> 21   (1043 on disk)
```

Blobs are LF; the Windows **worktree** is CRLF via the `autocrlf` smudge. Both
states coexist, which is why a single reading of either could support either
conclusion.

### 3. `git check-attr` reading a deleted file from the index — severity `med`

While proving that `.gitattributes` and `newline="\n"` must ship together, the
experiment "writer change alone" was run by deleting `.gitattributes` from the
working tree. It reported **7 passed** — apparently proving the pairing
unnecessary.

It was the experiment that was wrong. **Git falls back to the index for
attribute lookup**, so with the file deleted from disk `git check-attr` still
reported `text: set` / `eol: lf`. The attribute never stopped applying.
Disabling it needed `git rm --cached` as well; then the disk returned to CRLF
(1043 bytes against a 1022-byte blob) and the expected **7 failed** appeared.

This is the worst of the three. The false pass had *already been written into a
commit message* as a completed measurement. It was caught only because the
result contradicted a claim made before running it, and the claim was re-run
rather than trusted.

## The common factor

**The failure was not unreliability. It was silence.**

Each wrong reading looked exactly like a clean result. None emitted a warning,
an error, or an anomaly. An unreliable instrument that announces its
uncertainty is manageable; these did not, and in cases 2 and 3 the confident
false reading was on its way into a durable artifact — a PR body and a commit
message — where it would have outlived the session and been read as measured
fact.

**What worked, all three times, was a second measurement by a different
mechanism** — not more care with the same one. Object size instead of a pipe.
The blob API instead of local git. `git rm --cached` instead of `rm`. Re-reading
the same instrument more carefully would have confirmed the error in every case,
because the instrument was internally consistent; it was consistently wrong.

The practical rule this suggests, stated as a proposal and not as a measured
finding: **a claim that will outlive the session needs corroboration by a
second mechanism before it is written down**, and the corroboration should not
share a transport, a tool, or a code path with the first.

## Severity note

The folder's severity table is defined in terms of user-facing answers
(`high` = "produces a confidently wrong answer to a user"). These findings
produce confidently wrong answers to *developers and to the record*, not to
users, so the taxonomy does not fit cleanly. Graded `med`/`low` against a
translated reading — "degrades or silently narrows" a claim — and flagged here
rather than silently forced into a category. Case 3 arguably reaches `high` on
the translated scale: it produced a false statement in a commit message, which
is the record's equivalent of a confidently wrong answer.

## Open questions

- Is there a cheap way to make the "second mechanism" rule mechanical rather
  than remembered? Every mitigation this phase has produced for unfalsifiable
  values was a *rule*, and the measured result is that rules about sweeping
  fail under favourable conditions.
- Case 1's mitigation — suppressing attribution output for `INVALID` runs — is
  filed on #93, unbuilt, under the `580b278` probe freeze. It is a proposal,
  not a decision.

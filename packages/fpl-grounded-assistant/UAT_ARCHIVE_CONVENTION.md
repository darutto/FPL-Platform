# FPL Grounded Assistant - UAT Evidence Archive Convention

This document defines how completed UAT passes should be named, saved, and distinguished
from blank templates and illustrative examples.

---

## File roles at a glance

| File | Role | Copy for your pass? |
|---|---|---|
| `UAT_RUNBOOK.md` | Primary workflow guide | No — reference only |
| `UAT_CHECKLIST.md` | Canonical check IDs and pass/fail criteria | No — reference only |
| `UAT_CAPTURE_SHEET.md` | Blank command-and-capture form | **Yes — copy and fill** |
| `UAT_FINDINGS_TEMPLATE.md` | Blank findings template | **Yes — copy and fill** |
| `UAT_FINDINGS_EXAMPLE.md` | Illustrative completed pass with `[SAMPLE]` values | No — reference only |
| `UAT_ARCHIVE_CONVENTION.md` | This document | No — reference only |
| `UAT_FINDINGS.md` | Running historical findings log | Append only — do not copy |

---

## Naming convention for a completed pass

A completed UAT pass produces two files. Name them with an ISO date and a short label:

```
UAT_CAPTURE_<YYYYMMDD>[_<label>].md
UAT_FINDINGS_<YYYYMMDD>[_<label>].md
```

The `<label>` segment is optional. Use it when more than one pass runs on the same date,
or when you want to distinguish scope (e.g. `_regression` or `_quickcheck`).

**Examples:**

| Scenario | Capture file | Findings file |
|---|---|---|
| Standard full pass on 5 April 2026 | `UAT_CAPTURE_20260405.md` | `UAT_FINDINGS_20260405.md` |
| Second pass on same day | `UAT_CAPTURE_20260405_2.md` | `UAT_FINDINGS_20260405_2.md` |
| Focused regression after a fix | `UAT_CAPTURE_20260407_regression.md` | `UAT_FINDINGS_20260407_regression.md` |

Both files are saved alongside the other UAT documents in `packages/fpl-grounded-assistant/`.

---

## What a complete evidence bundle contains

A completed pass is considered complete when it contains all of the following:

### Completed capture file (`UAT_CAPTURE_<YYYYMMDD>.md`)

- All preflight status boxes checked
- All capture blocks filled with real command output or explicit `N/A` with reason
- All section status checkboxes marked (Pass / Fail / N/A)
- Exit Decision table at the bottom filled in

### Completed findings file (`UAT_FINDINGS_<YYYYMMDD>.md`)

- Session Summary header complete (tester, date, data mode, validation runner result)
- Findings Log table complete (at least one row per issue found; `—` rows for sections with no issues)
- Blockers section complete (active blockers recorded, or explicitly marked none)
- Major Issues section complete (issues recorded, or explicitly marked none)
- V1.5 Structured Checks Summary table complete (all rows marked with status and notes)
- Notes on Style and Trust section populated with at least three observations
- Final Recommendation written — Go / No-Go with rationale

A findings file with any section blank is not a complete evidence record.

---

## How to start a pass

**Step 1 — choose your filenames before you begin.**

Replace `YYYYMMDD` with today's date. Add `_label` only if you need to distinguish this pass
(e.g. `_regression` after a specific fix, `_2` for a second same-day pass). Omit otherwise.

Example for a standard pass on 5 April 2026:
```
UAT_CAPTURE_20260405.md
UAT_FINDINGS_20260405.md
```

Example for a regression-focused pass on the same day:
```
UAT_CAPTURE_20260405_regression.md
UAT_FINDINGS_20260405_regression.md
```

Use these exact names throughout. They must also match the Pass Index row and compact summary
you will add to `UAT_FINDINGS.md` at the end of the pass (see sync-rules in that file).

**Step 2 — create the files.**

```
Copy UAT_CAPTURE_SHEET.md   → UAT_CAPTURE_<YYYYMMDD>[_label].md
Copy UAT_FINDINGS_TEMPLATE.md → UAT_FINDINGS_<YYYYMMDD>[_label].md
```

**Step 3 — mark both files in-progress.**

At the very top of each new file, add one line before the title:

```
<!-- IN PROGRESS — not a completed evidence record -->
```

Remove this line only when the pass is fully complete (exit decision filled, findings written,
historical log updated). A file with this marker is not a completed evidence record even if it
has content in it.

**Step 4 — run the pass.**

3. Open both files side by side with `UAT_RUNBOOK.md` and `UAT_CHECKLIST.md`
4. Work through `UAT_CAPTURE_<YYYYMMDD>.md` section by section
5. Carry significant findings (any non-pass result) into `UAT_FINDINGS_<YYYYMMDD>.md` as you go
6. Complete the exit decision checklist in the capture file last
7. Write the Final Recommendation in the findings file

**Step 5 — close out.**

8. Remove the `<!-- IN PROGRESS -->` markers from both files
9. Update `UAT_FINDINGS.md` (Pass Index row + compact summary above the marker)
10. Verify the four sync values match — see sync-rules table in `UAT_FINDINGS.md`

At any point, reference `UAT_FINDINGS_EXAMPLE.md` to see what a complete pass looks like.

---

## How to update the running historical log

`UAT_FINDINGS.md` is the persistent append-only log of UAT history across all passes.
After completing a pass:

1. Add a row to the **Pass Index** table near the top of `UAT_FINDINGS.md`
2. Insert a **Pass summary section** immediately above the `<!-- END OF REAL PASS SUMMARIES -->` marker in `UAT_FINDINGS.md` — this keeps all real pass summaries in the compact history zone above the appendices
3. Do not duplicate the full capture or findings content — reference the dated files by name

The per-pass summary template lives at the top of `UAT_FINDINGS.md` under "Per-Pass Summary Template".
Copy it, fill in all fields, and remove the placeholder markers before committing.

**Four values must be identical in both the Pass Index row and the compact summary section.** See the sync-rules table immediately below the Pass Index in `UAT_FINDINGS.md` for the exact field-to-column mapping. In brief:
- `Date` column = section heading date = `Date` field in summary table
- `Label` column = `[_label]` suffix in section heading and both filenames (omit in all four places if no label)
- `Recommendation` column = `Recommendation` field in summary table
- `Capture` / `Findings` columns = `Capture file` / `Findings file` fields in summary table

Each summary section should be self-contained in 15–25 lines:
- the header table (date, tester, GW, validation result, recommendation, file references)
- new blockers (or "none")
- new cautions (or "none — [prior caution IDs] unchanged")
- 2–4 key observation bullets

Do not leave any `[placeholder]` text in committed sections.

---

## Distinguishing live evidence from illustrative content

| Signal | What it means |
|---|---|
| File named `UAT_FINDINGS_EXAMPLE.md` | Illustrative only — not a real pass |
| Values marked `[SAMPLE: ...]` inside a file | Placeholder — not real observed output |
| File named `UAT_FINDINGS_TEMPLATE.md` | Blank template — not a pass record |
| File named `UAT_CAPTURE_SHEET.md` (no date) | Blank template — not a pass record |
| Dated file **with** `<!-- IN PROGRESS -->` marker | Pass in progress — **not** a completed evidence record, even if it has content |
| Dated file **without** `<!-- IN PROGRESS -->` marker | Completed evidence record |

A dated filename alone does not determine completion state. The in-progress marker is the authoritative signal: if it is present, the file is not a completed evidence record regardless of how much content it contains. Remove the marker only at closeout (Step 5).

If a dated findings file contains any `[SAMPLE]` markers, it is also incomplete.

---

## Retention policy

Retain all dated capture and findings files in the repository indefinitely.
They form the audit trail for V1.5 stabilization decisions and are useful when comparing
behavior across GWs or after dependency updates.

Do not delete or overwrite completed pass files. If a re-test is needed after a fix,
create a new dated file rather than editing the existing one.

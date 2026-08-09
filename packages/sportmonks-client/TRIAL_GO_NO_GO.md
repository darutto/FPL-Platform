# TRIAL_GO_NO_GO.md — subscription decision rubric

**Agreed before the trial starts.** Created by FI-8 S1. This file satisfies the
§14.1 gate item *"Go/no-go rubric (§14.4) agreed"* and answers the brief's
question Q17.

Reproduced from the implementation plan §14.4. The point of writing it down
before the trial is that the bar cannot move afterwards to fit the result.

| | |
|---|---|
| Decision | **undecided** |
| Decided on | — |
| Decided by | — |
| Recorded in | [TRIAL_STATUS.md](TRIAL_STATUS.md) |

## GO — requires **all six**

A single unmet criterion is not a GO. There is no partial credit and no
"close enough"; if a criterion cannot be measured, it is not met.

| | Criterion | Status | Evidence |
|---|---|---|---|
| **(a)** | ≥95% Premier League player auto-map (post-queue ≥99%) | `not_started` | |
| **(b)** | Confirmed lineups available pre-kickoff with formation + grid for ≥90% of PL fixtures observed | `not_started` | |
| **(c)** | Injuries/suspensions update within 48h of public news for sampled cases | `not_started` | |
| **(d)** | Licensing answers permit raw storage + derived scores + subscriber display | `not_started` | |
| **(e)** | Starter+1 plan covers PL + UCL + FA Cup + EFL Cup at minimum | `not_started` | |
| **(f)** | M1–M3 produce sensible evidence on opening weekend (spot-check ≥20 players) | `not_started` | |

Where each is measured:

- **(a)** `trial_mapping.py` — objectives 18, 19. Also the §14.1 identity gate.
  Fuzzy matching, speculative aliases, and unsafe fall-through tiers are
  prohibited; a rate reached by loosening the matcher does not count.
- **(b)** `trial_lineups.py` — objectives 6–10. Note this requires **both**
  formation *and* grid; a formation string alone does not satisfy (b).
- **(c)** `trial_injuries.py` — objective 11, plus freshness timestamps.
- **(d)** [TRIAL_LICENSING_CHECKLIST.md](TRIAL_LICENSING_CHECKLIST.md) Q3–Q7.
  An unanswered question is not a yes.
- **(e)** [TRIAL_LICENSING_CHECKLIST.md](TRIAL_LICENSING_CHECKLIST.md) Q9, Q10.
- **(f)** FI-9 three-module demo on real opening-weekend data.

## NO-GO / defer — **any one** of these

| | Condition | Triggered | Evidence |
|---|---|---|---|
| 1 | Grid data absent or undocumented — M2 collapses to `detailed_position` only, re-evaluate value | no | |
| 2 | Licensing blocks derived display | no | |
| 3 | Mapping <90% auto | no | |

**Before any `unavailable` is read as evidence for a NO-GO, check the exit code.**
An endpoint family reported `unavailable` means *the provider did not answer for
that family*. It does **not** mean the endpoint is missing from our plan — and
those two readings lead to opposite decisions. A run that ended in a credential
failure exits **3** and reports nothing about coverage at all; only a run that
exited **0** or **1** carries a coverage claim worth reading.

This is not hypothetical. S3 shipped with a defect that made a rejected token
report as per-family unavailability: `SportmonksAuthenticationError` subclasses
`SportmonksError`, so the sweep's broad catch swallowed it, and a 401 on every
family would have produced *"15 families unavailable"* with exit 1. That report
is not a failure signal — it is a **plausible NO-GO**, and it would have
recommended against buying the product on trial day 1 from a credential typo.
The taxonomy is fixed and pinned (standing DoD item 13), and the check stays
here because the cost of this class of error is a wrong *decision*, not a wrong
test.

**Condition 1 is the one to watch.** Every grid fixture checked into this package
is documentation-derived and carries `"status": "unverified_against_live"` in its
`_fixture` block (see `sportmonks_client/assumptions.py`); the semantics are not
documented, which is why licensing question 13 exists. `trial_lineups.py` is
built to *report the shape it finds* rather than assert an expected one,
precisely so this condition is detected rather than papered over.

Note the gap between (a) and NO-GO 3: **90–95% auto-mapping is neither a GO nor a
NO-GO.** It is a defer — the queue burn-down has to close it before the identity
gate passes.

## Partial fallback

Per §14.4: **if only lineups are weak**, a lineups-only cheaper source may be
reconsidered rather than abandoning the track.

This applies when the failure is narrow — lineups/grid weak while identity,
fixtures, injuries, stats, and licensing are all fine. It does not apply when
licensing blocks derived display (nothing is salvageable) or when mapping is
below 90% (a different source does not fix identity).

**The decision is recorded in [TRIAL_STATUS.md](TRIAL_STATUS.md)**, not in a
commit message or a chat log.

*No fallback decision recorded.*

## Decision record

| Date | Decision | Rationale | Criteria unmet |
|---|---|---|---|
| | | | |

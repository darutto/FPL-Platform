# i124 — evaluator rejections: measurement and proposal (2026-10-03)

Measurement only. Nothing in the evaluator or the retry path changed here.
Decision on the proposal goes to Leo (via the review session).

## What was measured

| Source | Turns | Notes |
|---|---|---|
| Prod audit `audit-2026-10-02.ndjson` | 10 orchestrated | real traffic (`C:\Users\thera\fpl-audit\`); the 2026-09-23 file with the two original cases is still pending |
| Local, `origin/main` @ 3faafa3 | 48 sent, 45 evaluated | prod orchestrator config: openai / gpt-5.6-luna, evaluator ON, live bootstrap, no team; corpus = the 10 canonical i37 questions + the 6 distinct prod questions of 2026-10-02, R=3; cap 48 turns / 0.40 USD, spent 0.18 USD |

Scripts: `scripts/measure_i124_evaluator_rejections.py` (HTTP with debug,
joined to the server's own audit lines by question), and
`scripts/analyze_i124_evaluator_rejections.py` (reads both the measurement
JSONL and raw audit NDJSON). Data: `artifacts/i124-evaluator-rejections-local-2026-10-03.jsonl`.

## Numbers

| | Prod 10-02 | Local R=3 |
|---|---|---|
| Rejected by the evaluator | **3/10 (30%)** | **23/45 (51%)** |
| …with a grounded primary (every primary call `ok`) | 3/3 | 12/23 |
| …of those, feedback only asks to cite/show data (read by hand) | 3/3 | ~10/12 (the other two: an unsupported Isak injury claim, an unsupported home/away split) |
| Retry re-ran a primary tool | 3/3 | 22/23 |
| Retry lost an argument | 0/3 | 1/23 (wildcard) |
| Tokens, approved turn (mean) | 46,320 | 55,187 |
| Tokens, rejected turn (mean) | 76,383 | 76,276 |
| USD, approved turn (mean) | 0.0018 | 0.0014 |
| USD, rejected turn (mean) | 0.0070 | 0.0064 |
| Retry + evaluator share of a rejected turn's tokens | 35% | 34% |

Rejections by question (local, of 3): Haaland vs Salah 3, Chelsea zone
exploiters 3, Palmer vs Saka 3, Free Hit 6/7/8 3, Tottenham zones 2, wildcard 2,
bench boost 2, captain 1, top scorers 1, Liverpool defence 1, Fulham transfer 1,
Fulham free hit 1; Arsenal calendar, cheap defenders, Fulham (2nd wording) 0.

## Root cause (read in the code, not inferred)

`evaluator.py::_build_evaluator_user_message` gives the evaluator only
`tool(args) → status` per call — **never the tool's data** — while its system
prompt says *"Be strict on GROUNDED: every factual claim cites a tool
result"*. It cannot check a single number, so a correct, grounded answer is
judged "not grounded" and the feedback asks to cite. One local feedback says
it outright: *"el resultado visible solo indica «ok» y no respalda la ventana
GW2–GW19…"*. The retry then does what the feedback asks — calls the same tool
again — and pays a second ~25K-token round.

Two side effects worth knowing:

* On non-ok turns the feedback can fight product decisions: for the ambiguous
  "Palmer", the evaluator asked to compare *"en lugar de pedir una aclaración"* —
  the opposite of the i60 disambiguation chips.
* **Cost caveat.** The retry's ~25K input tokens are billed in the audit as
  uncached: `_apply_evaluator` records `retry_input` but no retry
  `cache_read`, while the primary shows 24.6K of 25.3K cached. Tokens are real;
  the USD of rejected turns is an upper bound if the provider caches the retry
  prefix. (Separate, small instrumentation card if wanted.)

## Options, with what each costs and buys (local numbers)

Baseline now: **65,966 tokens / 0.0039 USD per evaluated turn**, 51% retried.

| | Change | Tokens/turn | USD/turn | What it fixes | Risk |
|---|---|---|---|---|---|
| A | Verdict-only: `FPL_ORCH_EVAL_VERDICT_ONLY=1` (exists; env flag, no code) | ≈53,000 (−20%) | ≈0.0014 (−65%, upper bound) | every wasted retry; primary always served, verdict still audited | loses the retries that do help (unsupported claims ~2/12 grounded; non-ok turns) |
| B | Plan's option: a cite-only rejection re-synthesises with the SAME tool result (no tool re-call, original args kept) | saves ≈1 of the retry's 2 calls (≈−12K on a rejected turn, ≈−9% overall) | ≈−30% | the re-call and the lost-args bug | still rejects grounded answers at the same rate; "cite-only" needs a reliable signal (keyword rules over-match: mine labelled 23/23) |
| C | Give the evaluator the same (truncated) tool payload the model saw, so GROUNDED is judged against data | + payload on every turn (unmeasured; payloads are capped at 10 items) | unknown until measured | the false rejections themselves (root cause) | more evaluator tokens on every turn; needs a measured before/after |

**Recommendation:** decide between A and C by measurement, not B.
B keeps the root cause and adds a fragile "cite-only" classifier. C is the
real fix but its cost is unknown; A is free, reversible today, and is what
C must beat. Proposed next step (no prod change): one offline replay — record
primary answers + tool payloads for this same corpus, judge each twice (as
today / with payload), report rejection rate and evaluator tokens for both.
Cap ≈0.10 USD.

## Gates for whichever option is chosen

Cost per turn with a retry before/after on the prod audit; 0 regression on
the i108 E3 chip gate and on i107; the 2026-09-23 prod lines (two original
cases) added to this table when the file arrives.

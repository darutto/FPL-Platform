# i124 — offline replay: the evaluator with and without the tool data (2026-10-03)

Follow-up to `2026-10-03-i124-evaluator-rejections.md` (option C vs A).
Authorised cap 0.10 USD; spent **0.030 USD**. Nothing served changed: the
replay swaps the evaluator's *user message builder* inside
`scripts/replay_i124_evaluator_payload.py` only.

## Method

16 corpus questions (the i124 corpus) → one primary each through the real
`ask_orchestrated` (openai / gpt-5.6-luna, live bootstrap, no team), with
`evaluate_response` captured in-process so the exact evaluator input is
recorded and no retry runs. Each primary is then judged by the real evaluator
(gpt-5.6-luna, production client) **twice as served today** (`tool(args) →
status`) and **twice with the payload the model saw** (`_truncate_tool_output`:
lists capped at 10, hidden fields dropped). Same system prompt, same model.
Data: `artifacts/i124-evaluator-replay-2026-10-03.jsonl`.

## A finding that changes every number: ~25–50% of verdicts are not verdicts

`evaluator.py` calls luna with **`max_output_tokens=256`** (lines 177/214/251).
Luna is a reasoning model; the reasoning eats the budget, the JSON comes back
cut mid-string, `_parse_verdict` returns None, and `evaluate_response` returns
**`_FAIL_OPEN` — approved=True, grounded/complete/safe=None**. That is what the
"approved, grounded None" lines in the prod audit are.

| | approved | rejected | **fail-open** |
|---|---|---|---|
| Prod audit 2026-10-02 (10) | 2 | 3 | **5** |
| Local measurement (45) | 12 | 23 | **10** |
| Replay, today's message (32 judgments) | 11 | 13 | **8** |
| Replay, with payload (32 judgments) | 17 | 8 | **7** |

So in prod the evaluator "approved" half of the turns without judging them,
and the true rejection rate among real verdicts is 3/5 in prod, 23/35 locally.
This is independent of A vs C and is a one-line fix to measure (raise the
evaluator's output budget for reasoning models), separate card proposed.

## Rejection rate with vs without the data (parsed verdicts only)

| | rejected / parsed | evaluator tokens per judgment (mean) | user message (chars) |
|---|---|---|---|
| Today (`tool → status`) | **13/24 (54%)** | 787 | 749 |
| With payload | **8/25 (32%)** | 1,755 | 3,456 |

Cost of seeing the data: +968 tokens per judgment ≈ **+0.0002 USD per turn**
at luna input rates — against ≈0.005 USD for each retry it avoids.

Turns rejected today and approved with the payload (both judgments): Chelsea
zone exploiters (#5), Palmer vs Saka (#10, the ambiguity turn); Arsenal
calendar (#3) and Tottenham zones (#9) flip from split to 2/2 approved.

## What the evaluator still rejects with the data — read by hand

Six primaries (8 judgments). "Real" = the user would be better served without
the primary as written.

| # | Question | Real error? | What |
|---|---|---|---|
| 2 | Haaland o Salah | **yes** | `compare_players` returned `not_found` for "Salah"; the primary gives up. A retry with the full name could answer. (Also a resolver finding: plain "Salah" not found by compare_players — separate card.) Rejected in both arms. |
| 8 | Liverpool defensivamente | **yes — caught only with the data** | The primary contradicts itself / the tool: "2 goles en 2 partidos en casa" vs "ha concedido en dos de sus tres partidos como local". Today's evaluator approved it 2/2. |
| 14 | Free Hit 6/7/8 | **yes (minor)** | States GW7 and GW8 are "normal" but the tool evaluated GW6 only. |
| 11 | Wildcard | no | Objects to general advice ("cambios de titularidad") not backed by data. |
| 13 | Fulham Free Hit | no | Asks to "say which GW is best"; the primary already says none is. |
| 15 | Bench Boost | no (policy) | SAFE rule "minutes + status for every recommended player", for names that come from the chip tool, which carries neither. |

**Value option A would give up:** the retries for #2, #8, #14 — 3 of 16
primaries (19%) had a real defect the evaluator-with-data flags; one of them
(#8) is invisible to the evaluator as served today.

## Reading for the decision (A vs C)

* **A (verdict-only)** is the cheapest (no retry ever) but serves #2/#8/#14
  as written. With today's blind evaluator most of what A drops is noise; with
  the data, what remains is mostly real.
* **C (evaluator sees the payload)** cuts rejections 54% → 32% for
  ≈+0.0002 USD/turn, keeps the real catches and adds one today misses (#8).
  It still rejects 3 non-errors (#11, #13, #15); #15 is the SAFE minutes/status
  rule, a policy question rather than an evaluator defect.
* **Either way**, the 256-token fail-open is a prerequisite: without it ~25–50%
  of turns are approved unjudged under both A and C.

Small sample: 16 primaries, 2 judgments per arm. The direction is clear; the
exact rates are not.

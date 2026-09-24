# i108 E3 — chip answer general → particular: the gate, three rounds

**Model:** `openai/gpt-5.6-luna` (script pin = prod) · **Ids:** the 14 chip ids
`cvg-01/02/03/04/05/09/10/11/12, ad-03/04/05/07/10`, R=3 · **Bootstrap:**
`field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json` (GW1 current,
`team_fixtures` present) · **Team:** 68643 (live picks) · **Corpus:**
`tool_routing_corpus.py` blob `8461da1dcb142e7497dc9e8d82b698702194bfd9`, untouched ·
**Grader:** `scripts/grade_i108_chip_two_parts.py`, deterministic; phrases imported
from `fpl_grounded_assistant/chip_two_part.py` · **Cap:** $1.00, **spent $0.366**
(7 arms × 42 calls, 0 exceptions, 0 unpriced).

## Decision rule (declared before measuring, agreed in review)

- **Denominator:** rows whose trace ran `get_chip_advice`, status ok, for a
  squad-fit chip (BB/WC/FH) with a defined particular outcome.
- **Counted apart, never as failures:** triple captain (`cvg-09`, `ad-04`; no
  particular part yet, an open question for Leo) and rows with no chip call
  (`ad-05` and friends; a routing gap).
- **Pass** = all three of:
  - part 1: the verdict label for `recommendation` is in the opening, and a
    favoured team or player is named before the particular phrase;
  - part 2: the exact particular phrase is present;
  - order: the verdict comes before the particular phrase.
- **Target:** ≥ 95% of the denominator in both arms.
- **Extra conditions:** `transaction_hits` 0 on the chip answers, and 0
  forbidden openings.

**Grader change, declared.** After the first 13 rows of round 1 and before any
result was known, "opening" changed from *first paragraph* to *leading
markdown heading(s) + first paragraph*. The model opened with
`## Wildcard — GW1` followed by `**Jornada a medias.**`. Both counts are reported.

## Results

| round | what changed | A (team 68643) | B (no team) | A strict / B strict |
|---|---|---|---|---|
| C (ref) | `main` without E3, team 68643, same grader | 0/31 (not a fair "before": main doesn't know the phrases) | — | 0/31 |
| 1 | prompt rule CHIP_COMPOSITION, model writes both parts | **23/33 = 70%** | **28/33 = 85%** | 16/33 · 17/33 |
| 2 | copy: «te faltan {n} **jugadores** del grupo…» (the model's own form); rule: verbatim, particular required | **29/33 = 88%** | **28/32 = 88%** | 18/33 · 16/32 |
| 3 | Leo's option (b): header (verdict + favoured group) and particular sentence composed deterministically; model writes the body | **33/33 = 100%** | **31/31 = 100%** | 33/33 · 31/31 |
| 3b | + squad fields hidden from the model's payload (A only) | **33/33 = 100%**, 0 transaction hits | — | 33/33 |

- **Why round 1 failed:** 8 of the 10 A misses were near-misses of the
  particular phrase: an inserted word ("te faltan **4 jugadores** del grupo…")
  or a paraphrase. The B misses were real: ad-07 (FH) had no invitation 3/3,
  ad-10 paraphrased it ("no puedo confirmar… tu plantilla no está enlazada"),
  and cvg-10 had no label.
- **Why round 2 failed:** part 2 in A reached 33/33, but part 1 failed. In
  cvg-01 ("evalúa mi equipo **y** … el bench boost") and cvg-02 ("Analizá mi
  plantilla primero") the model follows the user's order and opens with the
  squad. There were also label paraphrases ("sí, bench boost favorable").
  **Leo decided: always general → particular, also in cvg-01/02.**
- **Why round 3b exists:** round 3 met the gate but had 1/33 transaction hits.
  In the body the model cited the enum literal ("el ajuste aparece como
  **"needs transfers"**"). Fix: `squad_fit` / `squad_source` /
  `linked_squad_error` are dropped from the `get_chip_advice` payload sent to
  the LLM (`orchestrator._MODEL_HIDDEN_FIELDS`, in `_truncate_tool_output`).
  The real output, the trace and the audit keep them. With that, 0 hits.

### Counted apart

| arm | triple captain | no chip call |
|---|---|---|
| C | 6 | 5 |
| 1 A | 6 | 3 |
| 1 B | 6 | 3 |
| 2 A | 6 | 3 |
| 2 B | 6 | 4 |
| 3 A | 6 | 3 |
| 3 B | 6 | 5 |
| 3b A | 6 | 3 |

- Transaction words outside the denominator: 2–3 per arm, all in `ad-05`
  ("¿hago un **transfer** o guardo el chip?"), which echoes the user's own word
  and never calls the chip tool.

## Findings

1. **E2 + E3 remove the extra `get_my_squad` call.** In C, the model called
   `get_my_squad` in 21/42 calls (all `squad`), 42 calls for $0.062. With E3
   the tool already carries the squad: 2/42 in round 1 A, 5/42 in round 3b A,
   for $0.040–0.048.
2. **Routing gap, same family as ad-05** (not fixed in E3): with no team,
   "Analizá mi plantilla primero" (cvg-02, 1 of 3 in round 3 B) routes to
   `get_my_squad` instead of the chip tool. Its `no_team_connected` message
   then opens the answer: «No puedo evaluar tu plantilla porque no hay ningún
   equipo conectado».
3. **Measured outcomes are only BB `needs_transfers` and WC/FH
   `not_applicable`.** In this GW1/GW2 bootstrap the wildcard 5-GW run and
   free hit have an empty favoured group. `set` and `fetch_failed` are covered
   by offline tests, not by this measurement.

## Artifacts

`field-notes/artifacts/i108-e3-gate-2026-09-24-{A-e3-team-68643, B-e3-no-team,
C-main-team-68643, r2-A-e3-team-68643, r2-B-e3-no-team, r3-A-e3-team-68643,
r3-B-e3-no-team, r3b-A-e3-team-68643-hidden}.jsonl`

Every row carries `answer_text_full` and `chip_trace`, the chip output read
off `tool_calls_trace`. Re-grade any of them with:

```
python packages/fpl-grounded-assistant/scripts/grade_i108_chip_two_parts.py <jsonl>
```

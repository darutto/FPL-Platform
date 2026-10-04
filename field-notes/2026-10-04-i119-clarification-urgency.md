# i119 — the clarification answer: urgency, not transfer vocabulary

**Decision (Leo, option C, 2026-10-04):**
- When the user asks about transfers, neutral words are fine: «transfer», «¿qué jugador
  venderías?», «comprarías».
- The rule blocks only urgency or danger: «vende ya», «hay que sacarlo», «peligro».
- The E3 chip grader (`transaction_hits`, `_ALLOWED_WORDS`) is unchanged, except for the
  *venir* exclusion below.

## What changed

- **`opportunity_framing._ALLOWED_WORDS`** gains the forms of *venir* decided in review:
  vendr(ía|ías|íamos|ían|á|ás|án|é). The i111 E3 run had reported «el beneficio
  principal vendría de Ndiaye» as a transaction. Every form of *vender* is still a hit.
  Re-grading the i111 E3 team arm: **39/39, 0 tx** (was 1 tx).
- **`opportunity_framing.urgency_hits`:** a closed list of urgency and danger patterns.
  - urgente;
  - peligro, except the football idiom «generar/crear peligro»;
  - a transaction verb pushed to "now": «vende ya», «véndelo cuanto antes», «sácalo ya»;
  - obligation: «hay que sacarlo», «tienes que venderlo»;
  - English: sell/buy now, get rid, must sell.
- **`scripts/grade_i119_clarification_urgency.py`:** the gate over the served texts
  (default `ad-05`). Raw `transaction_hits` are reported only as information.
- **Tests:**
  - `test_i119_clarification_urgency.py`: «vende ya» fails, «¿qué jugador venderías?»
    passes, and so does a real ad-05 clarification.
  - `test_i119_framing_venir.py`.
  - **Mutation:** removing each pattern, or the idiom exemption, makes at least one test
    fail (6/6).

## Gate — ad-05, R=3, luna, frozen bootstrap

Stop rule: one run per arm, cap $0.10. It passes if no arm has a row with urgency.

| arm | urgency (rows) | tx informational |
|---|---|---|
| no team | **0/3** | 3/3 |
| team 68643 | **0/3** | 3/3 |
| re-grading the 12 ad-05 answers from i111/i112 E3 | **0/12** | 11/12 |

- All ad-05 answers are graded, clarifications (`no_tool`) and the rest alike. That is
  stricter than grading clarifications only.
- With the decided rule, the prompt needs no change. The old count (`transaction_hits`)
  would fail on almost every row, nearly all of them on «transfer», which is the user's
  own word.

**Spend:** $0.0085.

## Artifacts

`field-notes/artifacts/i119-ad05-{no-team,team-68643}.jsonl`. Re-grade with
`scripts/grade_i119_clarification_urgency.py`.

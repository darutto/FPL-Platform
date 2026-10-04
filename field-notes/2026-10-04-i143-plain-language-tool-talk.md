# i143 — no machine talk in the body, and chip names in English

**Seen 2026-10-04 in prod:**
- «no baso la decisión en afirmar que no la hay, porque la salida de recomendación no
  muestra una alerta explícita…»
- «esta salida no incluye explícitamente su estado médico»
- «el triple capitán es defendible»

This is the i123 family (PLAIN_LANGUAGE).

## Change

- **Prompt** (`_SYSTEM_PROMPT`, inherited by the loop prompt): two rules after
  PLAIN_LANGUAGE.
  - **NO_TOOL_TALK:** never talk about where the facts came from (no «la herramienta»,
    «la salida», «el sistema», «el resultado», «los datos disponibles/recibidos»,
    «campo»). State the fact itself. Say what isn't known ONCE, in one plain sentence,
    without justifying it. Don't guess beyond the data, including no speculating about
    doubles or blanks.
  - **CHIP_NAMES:** Wildcard, Free Hit, Bench Boost, Triple Captain. Never comodín,
    ficha libre, golpe de suerte, impulso de banca, banco extra or triple capitán.
- **Grader** (`scripts/grade_i123_internal_names.py`): new `tool_talk()` and
  `spanish_chip_names()`, reported apart. `leaks()` keeps its i123 contract.
  - Anchored so football prose stays clean: «salida de balón», «salida en largo», «el
    resultado del partido», «en su campo».
  - On 504 earlier answers (i111/i112/i132 E3 runs and i142): tool talk in 61, Spanish
    chip names in 90. Every hit I read was genuine.
  - **Declared:** three patterns were added after reading the before arm, all stricter:
    «con los datos disponibles», «no aparece un campo», «golpe de suerte».
    `--summary` recomputes every count from the stored texts with the current
    detector, so the JSONL and the summary always come from one detector.

## Gate — the 14 E3 chip ids × R=3, luna, evaluator ON, no team, bootstrap assembled like the server

Stop rule: one run per arm, cap $0.15. Pass if served tool talk is 0, served Spanish
chip names are 0, and rejections are ≤ the before arm's.

| arm | served tool talk | primary tool talk | Spanish chip names | i123 internal names | rejected | USD/turn |
|---|---|---|---|---|---|---|
| before (main bf9b63b) | 3/42 | 5/42 | 3/42 | 0/42 | 19/42 | 0.00133 |
| after | **0/42** | 0/42 | **0/42** | 0/42 | **18/42** | 0.00142 |

**Where it came from (first step of the card):** in the before arm, 2 of the 3 served
cases were already in the model's first draft. 1 appeared only in the retry after a
rejection. So the source is mostly the primary, not the retry. The prompt removes it in
both.

**Cost:** +7% per turn, from the longer prompt. **Spend:** $0.116 (0.056 before + 0.060
after).

## Artifacts

`field-notes/artifacts/i143-chip-language-{before,after}.jsonl`. Each row keeps
`primary_text` and `final_text`. Summary:
`scripts/measure_i143_chip_language.py --summary …`.

# i139 — English texts that reach cards: what was changed and what remains

## Changed (Spanish at the origin)

| where | before | now |
|---|---|---|
| `comparison._explain_comparison` (ComparisonCard `reasons`) | stronger form / easier fixture (FDR 2H vs 4A) / higher xGI output / better minutes security / set-piece advantage (pen vs fk2) | mejor forma / partido más fácil (FDR 2L vs 4V) / más xGI por 90 / minutos más asegurados / ventaja a balón parado (penales vs 2.º en tiros libres) |
| `comparison._build_recommendation` (served text on the deterministic path; it splices in the reasons) | «X edges Y — clear margin (…). Advantages: …» | «X supera a Y — diferencia clara (…). Ventajas: …»; margins use the card's own words (ajustada / moderada / clara) |
| `_apply_squad_overrides` budget block (it replaced the whole answer) | «Budget constraint: bringing in X costs +£…m but you have £…m in the bank.» | «No te alcanza el presupuesto: X cuesta +£…m más y tienes £…m en el banco.», then «Para planificar, este es el análisis del cambio:» and the turn's answer |

**Consumers of `reasons` checked before changing:**
- ComparisonCard: renders them as they come, at most 3.
- `ComparisonMeta`: passes them through.
- `_build_recommendation`: translated with them.
- The LLM: reads them in the tool output.
- No grader reads them.
- orch4b/orch4e: only pass their own reasons through.
- `FINAL_RESPONSE_CONTRACT.md` and the UAT notes: documentation examples in English, not updated.

The set-piece helper is shared with transfer: `locale="es"` for comparison, and English
by default for transfer, so transfer reasons don't end up half-translated.

## Remaining in English and reaching cards (not changed; for decision)

1. **Transfer reasons** (`transfer_advisor.py:305-328` and the «Advantages:» clause at
   :376), shown as they come on TransferCard. Same phrases as comparison.
2. **Chip `signal_label`** (`final_response.py` ~1729-1760), shown as it comes on
   ChipCard: «captain score», «top captain score», «current gameweek», «average FDR
   (top 10)», «double gameweek teams», «blank gameweek teams», «mixed gameweek (double
   teams)», «normal gameweek».
3. **`difficulty_label`** (easy / moderate / hard), shown as it comes on
   TransferSuggestionCard. The catalogue's own rule says to translate it
   (fácil / moderado / difícil).

## Gate

- `tests/test_i139_spanish_card_texts.py` (14 tests): every reason, venue L/V, set-piece
  in both locales, recommendation and margins, budget (lead plus answer kept,
  affordable transfer unchanged).
- Full package: 3035 passed, 1 skipped.
- CI orch runners: green.
- Legacy asserts on «Budget constraint» updated (8e1, 8e2, g1, orch4d, orch4e). g1 E3 now
  asserts that the answer is kept below, per the decision.

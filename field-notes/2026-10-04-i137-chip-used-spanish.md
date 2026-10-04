# i137 — chip already played: Spanish, when it was used, and when it comes back

**Seen 2026-10-04 in prod:** team 68643. FPL `entry/68643/history` confirms bench boost
in GW2, triple captain in GW3 and wildcard in GW5. `_apply_squad_overrides` replaced
the whole answer with «Chip unavailable: triple_captain is not in your chips
remaining.».

## Change

- **Text:**
  - With both gameweeks known: «Ya usaste el Triple Capitán en la GW3. Vuelves a tenerlo
    desde la GW20.»
  - Then «Para planificar, esta es la lectura de la jornada:» and the turn's answer
    unchanged: the i108/i112 composition plus the model's body.
- **Use gameweek:** from `squad_context.chips_used`, a new field. The UI projects FPL's
  `history.chips` in backend names (`normalizeSquadContext`).
- **Return gameweek:** from `bootstrap["chips"]`, FPL's windows: the next start after the
  window the chip was used in. The server passes its turn bootstrap to `to_ask_response`
  as data; nothing is fetched.
- **When a value is missing:**
  - Use gameweek unknown (an old UI, or malformed data): «Ya usaste el Triple Capitán,
    así que ahora no lo tienes disponible.» with no number.
  - Windows missing or malformed, or the chip used in the last window: the use sentence
    without the return.
- **Names:** the chip card's labels (`ChipCard.tsx` `CHIP_LABELS`), pinned by a test,
  with the article and pronoun for each («la Ficha Libre … tenerla»).

## Gate

- **pytest `test_i137_chip_used_spanish.py`** (20 tests): chip used in the first half,
  used without a gameweek, and available (unchanged); the text served by
  `to_ask_response`; label parity with the TSX.
- **Mutation per guard:** 13/13 caught.
- **Suites:**
  - full package: 3021 passed, 1 skipped;
  - CI orch runners 4a/b/c/d/e/f/i: green;
  - UI: tsc 0, jest 628/628.
- **Legacy runners:**
  - asserts on the English literal updated: orch4d A15, orch4e F10, g1 F2, 8e1;
  - 8e1 still exits 1 on an AttributeError that main has too.

## Other English literals in the same block (`_apply_squad_overrides`), not changed

- `budget_constraint`: «Budget constraint: bringing in {player} costs +£{x}m but you have
  £{y}m in the bank.» replaces the whole answer, the same way the chip literal did.

## Related, outside this card

- `fpl-ui/lib/squad-context.ts` `FPL_CHIP_MAX_USES` counts 3xc / bboost / freehit as
  **once per season**, but 2026-27 has two windows per chip.
  - From GW20 on, `chips_remaining` will keep saying they are used up.
  - The first-half wildcard (68643 used it in GW5) still shows as available.
  - The availability decision (`chips_remaining`) comes from there; i137 only changes
    the text.

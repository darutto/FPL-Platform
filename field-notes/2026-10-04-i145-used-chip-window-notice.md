# i145 — a used chip's window notice speaks of the next window

**Follow-up to i144.** In the i144 runs (Wildcard played in GW5, asked in GW6) the
bodies still reasoned «quedan 14 jornadas…», which is the tool's `window_notice` for
the window already spent. Two mixed windows: «para cuando regrese, la ventana actual
sigue abierta hasta la GW19».

## Change (`chip_advisor`)

When `chip_availability.status == "used"` the window fields describe the **next**
window (FPL's own, from `chip_availability.chip_windows`):
- `window_status: "spent"` (new enum value, declared);
- `active_window` = the next window, or `None`;
- `gameweeks_remaining: None`;
- `window_notice`: «This chip's next window: GW20-GW38.», or «There is no later window
  for this chip this season.»

Available and unknown chips are unchanged. Nothing outside `chip_advisor` reads these
fields (checked: UI, `final_response`).

## Gate

**Tests:** `tests/test_i145_used_chip_window_notice.py`, 5 tests.
- Used with a next window, and used in the last window.
- **Controls:** available and unknown keep their active window and «N gameweek(s)
  remain».
- The enum is declared.

**Mutation per guard:** 5/5 caught. Full package 3116 passed locally.

**Live, Leo's case** (68643, `ask_v2` → `to_ask_response`, openai / gpt-5.6-luna, R=5;
before = main efce384, with i143 and i144). Detectors added to
`measure_i144_used_chip.py`; `--summary` recomputes them from the served text.

| arm | spent window remaining | windows mixed | «pronto en la ventana» | keep-it advice | squad sentence | lead | USD/turn |
|---|---|---|---|---|---|---|---|
| before | 1/5 | 0/5 | 3/5 | 1/5 | 0/5 | 5/5 | 0.00151 |
| after | **0/5** | **0/5** | 0/5 | 0/5 | 0/5 | 5/5 | 0.00100 |

- Re-grading i144's stored runs with the same detectors: before 5/5 remaining, after
  5/5 remaining and **2/5 mixed**. That is the problem this card fixes.
- The fresh before arm already shows less of it (1/5, 0 mixed), likely thanks to i143's
  NO_TOOL_TALK ("don't guess beyond the data"). After, it is 0 on both.
- The after bodies speak of the next window: «planificar su próximo uso dentro de la
  ventana GW20–GW38», «Su próxima ventana será de GW20 a GW38».

**Residue, declared:** 3/5 after bodies still say the GW6 timing is «demasiado pronto /
fase temprana» for the Wildcard. That comes from the wildcard's own `advice_text` («It
is early in the active wildcard window»), not from `window_notice`. My detector
(«pronto dentro de la ventana») doesn't catch that wording. Possible follow-up: when the
chip is `used`, also drop the wildcard's early-in-window timing phrase.

**Spend:** $0.0126.

## Artifacts

`field-notes/artifacts/i145-used-chip-{before,after}.jsonl`.

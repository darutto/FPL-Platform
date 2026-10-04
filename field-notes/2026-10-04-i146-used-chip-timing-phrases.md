# i146 — a used chip's advice drops the spent window's timing phrases

**Follow-up to i145.** With the Wildcard played in GW5 and the question in GW6, 4/5
bodies still said GW6 was «demasiado pronto / una fase temprana». That came from the
wildcard's own `advice_text` («It is early in the active wildcard window … later in
this window»), not from the window notice that i145 fixed.

## Change (`chip_advisor`)

When `chip_availability.status == "used"`, `advice_text` loses the timing / keep-it
sentences about the evaluated (spent) window, for all four chips:
- **Wildcard:** the whole phrase (early / late / viable window), passed as the internal
  `timing_phrases`.
- **Triple Captain:** «a stronger option may appear in a later gameweek», «It may be
  worth saving the triple captain chip».
- **Free Hit:** «…, but saving it for an upcoming double gameweek is often the stronger
  play», «Consider saving it for a better opportunity», «…but a larger double gameweek
  would be a stronger opportunity».
- **Bench Boost:** has no timing phrases.

Each phrase is defined once as a constant, used both to build it and to strip it.
**Available and unknown chips get byte-for-byte the same text**: the full suite and
i108's phrase tests pass unchanged.

**Not changed, declared:** "play it now" lines («Conditions support using…», «use it to
field the best XI…»). They aren't timing, and i144's availability sentence already
tells the model not to advise playing a used chip.

## Gate

**Tests:** `tests/test_i146_used_chip_timing_phrases.py`, 11 tests.
- Available keeps its timing phrase (control); used drops every one and keeps the
  conditions label.
- Free Hit in a blank and in a small double gameweek, built with `team_fixtures`.
- The internal key never reaches the output.

**Mutation:** 6/7 caught.
- The survivor is `pop` → `get` of the internal key: equivalent, since the output is
  built from named keys and never spreads `result`. Kept as hygiene.
- A first run showed the Free Hit list untested; the blank/double tests were added and
  now catch it.

**Detector, declared:**
- The early-timing detector in `measure_i144_used_chip.py` was widened to the real
  wording: any «pronto» / «tempran(o/a)», plus «inicio / principio de la ventana».
  i145's version («pronto dentro de la ventana») missed «demasiado pronto» and «fase
  temprana».
- While writing it, a heredoc turned `\b` into a backspace character and the detector
  silently matched nothing (0/5 on i145's after arm). I caught it because I knew that
  arm contained «fase temprana». The fix now has a self-check on known phrases, and the
  file has no control characters.
- With the fixed detector, i145's stored runs give 4/5 in both arms, the same as
  review's regex.

**Live, Leo's case** (68643, `ask_v2` → `to_ask_response`, openai / gpt-5.6-luna, R=5;
before = main 31470ee with i145):

| arm | «pronto / temprana» | keep-it advice | spent window remaining | mixed | lead | USD/turn |
|---|---|---|---|---|---|---|
| before | 5/5 | 2/5 | 0/5 | 0/5 | 5/5 | 0.00145 |
| after | **0/5** | **0/5** | 0/5 | 0/5 | 5/5 | 0.00096 |

The after bodies: «No puedes usar el Wildcard esta jornada: ya lo utilizaste en la GW5.
Volverá a estar disponible desde la GW20.», «Para su próxima ventana, el mejor tramo
detectado ahora es el de Fulham…».

**Observation, not fixed:** some bodies plan the return around Fulham's «próximas cinco
jornadas». That run is GW6–10, because the favoured group is computed from the current
GW, not from GW20. It's a separate question if the read should plan for the next
window.

**Spend:** $0.012.

## Artifacts

`field-notes/artifacts/i146-used-chip-{before,after}.jsonl`.

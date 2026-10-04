# i142 — the Triple Captain candidate carries its season minutes and status

**Seen 2026-10-04 in prod:** the model said of Groß «no tengo datos suficientes para
certificar su disponibilidad», although the card shows his minutes. i132 had put
`minutes_played_season` / `status` on bench boost's `favoured_players` only.

## Change (`chip_advisor`)

- TC `signals` carry `top_minutes_played_season` and `top_status`, plus
  `evaluated_minutes_played_season` / `evaluated_status` when the user names a
  candidate. Same bootstrap element and the same mapping as i132 (`_safe_int(minutes)`,
  `_map_status`).
- They are also present on the `missing_context` path for an unresolved name, which
  still names the top option.
- The output schema declares them.
- The model and the evaluator see them: `_truncate_tool_output` keeps them, and the
  evaluator's TOOL DATA carries them (tested).

## Gate — «¿Uso el Triple Captain esta jornada?», R=6 per arm, luna, evaluator ON, bootstrap assembled like the server

Before = `origin/main` 58cf768, after = this branch. One run per arm, cap $0.20.

| arm | hedge on availability | rejected | rejected asking for minutes/status | USD/turn |
|---|---|---|---|---|
| before | 1/6 | 4/6 | 3/6 (4/6 by reading) | 0.00163 |
| after | **0/6** | 3/6 | **0/6** | 0.00131 |

- **Before:** the evaluator demanded «verifica explícitamente sus minutos de la
  temporada y su estado» because it couldn't see them. One retry hedged: «no aparece
  un campo separado de estado… así que no añado ninguna afirmación sobre su
  disponibilidad».
- **After:** the 3 rejections are about **other things**, outside this card:
  - the body says the TC «está disponible» while the tool says the chip's availability
    is unknown (no team linked);
  - speculating about a double gameweek that the tool doesn't back up.
- **Detector change, declared:** after the first run I added the pattern «afirmación
  sobre su disponibilidad», because the before arm's hedge wasn't caught. That makes
  the detector stricter, not looser. Both arms were re-graded with the same detector.
- **Observed, not fixed (i143):** two "after" bodies use machine language («la
  herramienta no aporta una novedad médica», «el sistema no puede confirmar si
  conservas el chip»).

**Spend:** $0.0177 (before 0.0098 + after 0.0079).

## Tests

`tests/test_i142_tc_candidate_minutes_status.py`, 7 tests:
- top and named candidate checked against `find_players`' own mapping;
- missing minutes → 0 / Unknown;
- unresolved name;
- schema;
- model view;
- the evaluator message carries them.

Full package: 3075 + 7 locally.

## Artifacts

`field-notes/artifacts/i142-tc-{before,after}.jsonl`. Re-grade with
`scripts/measure_i142_tc_availability.py --regrade …`.

# i132 (b) — bench boost's favoured players carry season minutes and status

**Decision (Leo, 2026-10-03):** option (b). The chip tool adds minutes and status to
`favoured_players`, so the evaluator's SAFE rule ("no player recommendations missing
minutes_played_season + status check") can be met. Before this change it rejected
Bench Boost answers that named the favoured group, and the retry could not fix it.

**Change:** `chip_advisor._score_outfield_players` reads `minutes_played_season`
(`element.minutes`) and `status` off each bootstrap element. It uses the same
`_safe_int` / `_map_status` that `find_players` and `get_my_squad` use.
`_bench_boost_favoured` copies both into every `favoured_players` row, and the
output schema declares them. Nothing else reads the new keys: triple captain reads
only `captain_score` / `web_name` / `tier` from the same scored rows. The fields are
not in `_MODEL_HIDDEN_FIELDS`, so the model and the evaluator both see them (i124 C:
the evaluator gets the model's view).

**Model / config:** `openai/gpt-5.6-luna` for the orchestrator and evaluator, a local
server with the prod orchestrator config, live bootstrap, no team.
**Spend:** $0.696 of a declared $1.00 cap. 0 exceptions, 0 non-200.

## Results

### The one question the change touches: bench boost, R=8 per arm (same moment, both servers)

| | before (main) | after |
|---|---|---|
| SAFE = false | **5/8** | **0/8** |
| rejected | 6/8 | 2/8 (both SAFE = true: «no confirma doble jornada», «los equipos mejor situados») |
| retries | 6/8 | 2/8 |
| tokens / turn (mean) | 71,831 | 59,121 |
| USD / turn (mean) | 0.00535 | 0.00278 |

### i124 set, 16 questions × R=3 (`measure_i124_evaluator_rejections.py`)

| | before | after |
|---|---|---|
| SAFE = false | 2 (both bench boost) | 1 («jugadores de Fulham», `get_transfer_suggestion`, not a chip tool) |
| bench boost rows rejected | 2/3, both SAFE | 1/3, SAFE = true |
| rejected, all questions | 11/45 (24%) | 17/45 (38%) |
| USD / turn | 0.00255 | 0.00339 |

The overall rate went up on questions whose tool output the diff does not touch:
captain 0→2, Haaland vs Salah 1→3 (`compare_players` Salah not_found, i129),
Liverpool 0→1, wildcard 0→1, free hit 6/7/8 1→1, Fulham free hit 2→3.
None of these calls `get_chip_advice` for bench boost, which is the only output
that changed. I read that as run-to-run variance in this set (the #355 run of the
same set gave 51%). It is not an effect of the change. To make the touched question
readable I measured it alone at R=8 (table above).

**Keep in mind what produced the drop.** The served answers rarely cite the minutes
(2/8 after, 0/8 before). The SAFE rejections go away because the evaluator can now
see minutes and status for the named players in TOOL DATA. The model is not citing
them more.

The fourth SAFE rejection in the #355 set, «defensas baratos», does not use the chip
tool and is out of scope for this card. It did not appear in either arm today.

### i108 E3 gate (14 chip ids × R=3, frozen bootstrap 2026-08-18), on the rebased base `02c2443`

| arm | before (main) | after |
|---|---|---|
| team 68643 | 33/33, 0 tx hits, 0 forbidden | 33/33, 0 tx hits, 0 forbidden |
| no team | 29/32 | 30/33 |

No regression. **Every** no-team miss, in both arms and in the earlier run on `3c44610`
(29/33 → 30/33), is the i111 defect: `get_my_squad` → `no_team_connected` →
`get_chip_advice` ok. The turn outcome becomes `tool_result_error`, and
`orchestrator._compose_chip_answer` composes only on `ok`, so neither the header nor
the particular sentence is added. Fixed separately under i111.

## Artifacts

`field-notes/artifacts/i132-{before,after}-r3-2026-10-03.jsonl`,
`i132-bb-r8-{before,after}.jsonl`,
`i132-e3-{before,after}-{team-68643,no-team}.jsonl` (base 3c44610),
`i132-e3-rebased-{before,after}-{team-68643,no-team}.jsonl` (base 02c2443).
Bench boost reps: `scripts/measure_i132_bench_boost_reps.py`.

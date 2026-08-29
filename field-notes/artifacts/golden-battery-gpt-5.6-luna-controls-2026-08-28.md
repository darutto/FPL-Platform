# Golden battery — gpt-5.6-luna

Diffable: two models compare by reading two of these tables, with no re-run.

| field | value |
|---|---|
| model | `gpt-5.6-luna` |
| provider | `openai` |
| tier | `controls` |
| reps | 3 |
| max_tokens | 1024 |
| temperature | None (unset) |
| bootstrap | `agentic-loop-bootstrap-2026-08-18.json` |
| bootstrap sha256 | `4cbb9fa18a5852c73a54fbe24a03b34e0c33ae5b3c549171cbcb02568d8b2aae` |
| distinct cases | 70 |
| calls | 210 |
| spend USD | 1.0092 |
| run at | 2026-08-29T01:15:19+00:00 |

| axis | kind | result | threshold | verdict | reference |
|---|---|---|---|---|---|
| routing | target | 129/141 pass (91%) | >= 80% | PASS | #171 / i38: the corpus is labelled with acceptable sets, not a single key; luna's rate is the row this run records. |
| metric_resolution | target | 30/30 pass (100%) | >= 95% | PASS | i18/i19 after PR #181: unknown_metric on 1 of 26 calls (96%). |
| invented_metric_relay | target | 14/15 pass (93%) | >= 100% | **FAIL** | i15 live, 2026-08-26: 0/10 fell through to a gameweek tool. |
| order_direction | target | 9/9 pass (100%) | >= 100% | PASS | i42/i44 after PR #181: order='asc' applied on every call. |
| ownership_no_possessive | target | 6/6 pass (100%) | >= 80% | PASS | i41 after PR #186: sb-02 5/5 and sb-13 5/5. |
| overfire_guards | guard | 0/33 fires (0%) | <= 0% | PASS | i41: 0 fires of get_my_squad in 45 negative calls. |
| synthesis_present | target | 199/210 pass (95%) | >= 100% | **FAIL** | i46, opened 2026-08-28: 3 of 9 calls in an unrelated probe returned synthesis_turn=False. |

**REJECT — guards held, but target(s) below threshold: invented_metric_relay, synthesis_present.**

> Guards outrank targets: a breached guard fails the model even when every target passes.
